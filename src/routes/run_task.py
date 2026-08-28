import json
import logging
import shlex
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context

import config
from claude_stream import to_sse_frames
from ssh_runner import (
    is_valid_repo_name,
    run_remote_claude,
    run_remote_codex,
    run_remote_command,
)

run_task_blueprint = Blueprint("run_task_blueprint", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)

_VALID_AGENTS = ("claude", "codex")


def _executor_for(agent):
    """Looks up the executor function for a resolved `agent` by name *at
    call time* rather than a module-level dict literal -- a dict built once
    at import time would freeze in the original run_remote_claude /
    run_remote_codex objects, so tests (and any future runtime patching)
    that monkeypatch those module attributes directly (the existing style
    in this test suite) would silently keep calling the un-patched
    function. Building the mapping fresh here re-reads the current module
    attributes every call.
    """
    return {"claude": run_remote_claude, "codex": run_remote_codex}[agent]


def _agent_enabled(agent):
    return {"claude": config.CLAUDE_ENABLED, "codex": config.CODEX_ENABLED}.get(agent, False)


def _resolve_agent(requested_agent):
    """Resolves which agent executes a /api/run request, per the priority
    order in the ai-gateway agent boundary decision record: the request's
    explicit `agent` value, then the system default (config.DEFAULT_AGENT).

    The decision record also names a middle tier -- "kobito's task-type
    config" -- between those two, but no such config source exists in this
    repo yet, so that tier is skipped here (see config.DEFAULT_AGENT's
    docstring; this is a deferred follow-up, not an oversight).

    Returns (agent, error) where `error` is None iff `agent` is one of
    "claude"/"codex" and its executor is enabled. Callers must not execute
    anything when `error` is set.
    """
    agent = (requested_agent or config.DEFAULT_AGENT or "").strip().lower()
    if agent not in _VALID_AGENTS:
        return agent, f"invalid agent: {agent!r} (expected 'claude' or 'codex')"
    if not _agent_enabled(agent):
        return agent, f"{agent} execution is disabled"
    return agent, None


def _is_kobito_run(prompt, source):
    return source == "kobito" or "kobito/OPERATING.md" in prompt


def _board_command(*parts):
    command = " ".join(shlex.quote(str(part)) for part in parts)
    return run_remote_command(f"python3 {config.HUMAN_AGENT_BOARD_CLI} {command}", timeout=15)


@run_task_blueprint.route("/kobito-health", methods=["POST"])
def kobito_health():
    code, output = _board_command(
        "run", "list", "--source", "kobito", "--json",
        "--stale-after", "900", "--missing-after", "14400",
    )
    if code:
        return jsonify(health="unreachable", error="human-agent-board could not be reached"), 503
    try:
        health = json.loads(output)
    except json.JSONDecodeError:
        return jsonify(health="unreachable", error="invalid human-agent-board response"), 503

    state = health.get("health")
    if state in ("stale", "missing", "degraded"):
        _board_command(
            "add", "--direction", "agent-to-user", "--from", "kobito",
            "--type", "action_required", "--dedupe-key", "kobito-health",
            "--title", "kobitoの稼働確認が必要です",
            "--body",
            f"稼働状態は{state}、最終確認は{health.get('last_seen_at') or 'なし'}、"
            f"連続失敗は{health.get('consecutive_failures', 0)}回です。"
            "LINEのkobito状況で直近エラーと対処方法を確認してください。",
        )
    elif state in ("healthy", "running"):
        _board_command(
            "resolve", "--direction", "agent-to-user", "--dedupe-key", "kobito-health"
        )
    return jsonify(health)


class _KobitoRunTracker:
    """Tracks one kobito execution against human-agent-board.

    board.py's `run start/heartbeat/finish` CLI has no dedicated field for
    which agent (claude/codex) ran the task -- only free-text `--trigger`
    (start) and `--summary` (heartbeat/finish), confirmed by reading
    ~/repos/human-agent-board/board.py's argparse setup. Rather than invent
    a structured field there (out of scope -- that repo isn't touched by
    this change), the agent is folded into those existing free-text fields
    as a `[agent] ` prefix, since `summary` is exactly what LINE/Board
    render for a run (see line_webhook.py's _run_health_bubble()). The
    failure notification body also gets its own explicit "エージェント:"
    line for unambiguous identification there too.
    """

    def __init__(self, agent):
        self.agent = agent
        self.run_id = None
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        code, output = _board_command(
            "run", "start", "--source", "kobito",
            "--trigger", f"cloud-scheduler:{self.agent}",
        )
        if code:
            logger.warning("could not record kobito run start: exit=%s", code)
            return
        try:
            self.run_id = json.loads(output)["run_id"]
        except (json.JSONDecodeError, KeyError):
            logger.warning("could not parse kobito run start response")
            return
        self.thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.thread.start()

    def _heartbeat_loop(self):
        while not self.stop_event.wait(config.KOBITO_HEARTBEAT_SECONDS):
            self.heartbeat(f"{self.agent}_running", f"{self.agent}セッションを実行中")

    def heartbeat(self, phase, summary):
        if not self.run_id:
            return
        code, _ = _board_command(
            "run", "heartbeat", "--source", "kobito", "--run-id", self.run_id,
            "--phase", phase, "--summary", f"[{self.agent}] {summary}",
        )
        if code:
            logger.warning("could not record kobito heartbeat: exit=%s", code)

    def finish(self, outcome, summary):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)
        if not self.run_id:
            return
        code, _ = _board_command(
            "run", "finish", "--source", "kobito", "--run-id", self.run_id,
            "--outcome", outcome, "--summary", f"[{self.agent}] {summary}",
        )
        if code:
            logger.warning("could not record kobito run finish: exit=%s", code)
        if outcome == "failed":
            _board_command(
                "add", "--direction", "agent-to-user", "--from", "kobito",
                "--type", "action_required", "--dedupe-key", "kobito-health",
                "--title", "kobito実行基盤の確認が必要です",
                "--body", f"エージェント: {self.agent}\n原因: {summary}\n"
                "影響: 今回のkobito作業は開始または完了できませんでした。\n"
                "対処: Macの起動、Tailscale、SSH接続、接続preflightの順に確認してください。\n"
                "再試行: 次の3時間ごとの定期実行で自動再試行します。",
            )
        else:
            _board_command(
                "resolve", "--direction", "agent-to-user",
                "--dedupe-key", "kobito-health",
            )


@run_task_blueprint.route("/run", methods=["POST"])
def run_task():
    if not config.EXECUTION_ENABLED:
        return {"error": "execution is disabled"}, 503
    body = request.get_json(force=True, silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    resume_session_id = body.get("resume_session_id") or None
    repo = (body.get("repo") or "").strip() or None
    source = (body.get("source") or "").strip() or None
    requested_agent = (body.get("agent") or "").strip().lower() or None

    if not prompt:
        return {"error": "prompt is required"}, 400

    if repo and not is_valid_repo_name(repo):
        return {"error": "invalid repo name"}, 400

    # Agent is resolved and locked in for the whole run before anything is
    # executed or recorded -- no SSH call and no board run tracking happens
    # if it can't be resolved to an enabled agent. There is no fallback to
    # a different agent within this run if the chosen one fails later.
    agent, agent_error = _resolve_agent(requested_agent)
    if agent_error:
        return {"error": agent_error}, 400

    def generate():
        tracker = _KobitoRunTracker(agent) if _is_kobito_run(prompt, source) else None
        failed = False
        failure_message = None
        if tracker:
            tracker.start()
        try:
            raw_lines = _executor_for(agent)(prompt, resume_session_id, repo)
            for line in raw_lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {}
                if event.get("type") == "gateway_error":
                    failed = True
                    failure_message = event.get("message") or "gateway error"
                yield from to_sse_frames([line])
        except Exception as error:
            failed = True
            failure_message = f"{type(error).__name__}: {error}"
            raise
        finally:
            if tracker:
                tracker.finish(
                    "failed" if failed else "completed",
                    failure_message or "gatewayまたはSSHエラーで終了"
                    if failed else "セッションが終了",
                )

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
