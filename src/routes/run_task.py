import json
import logging
import shlex
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context

import config
from claude_stream import to_sse_frames
from ssh_runner import is_valid_repo_name, run_remote_claude, run_remote_command

run_task_blueprint = Blueprint("run_task_blueprint", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


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
    def __init__(self):
        self.run_id = None
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        code, output = _board_command("run", "start", "--source", "kobito", "--trigger", "cloud-scheduler")
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
            self.heartbeat("claude_running", "Claude Codeセッションを実行中")

    def heartbeat(self, phase, summary):
        if not self.run_id:
            return
        code, _ = _board_command(
            "run", "heartbeat", "--source", "kobito", "--run-id", self.run_id,
            "--phase", phase, "--summary", summary,
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
            "--outcome", outcome, "--summary", summary,
        )
        if code:
            logger.warning("could not record kobito run finish: exit=%s", code)
        if outcome == "failed":
            _board_command(
                "add", "--direction", "agent-to-user", "--from", "kobito",
                "--type", "action_required", "--dedupe-key", "kobito-gateway",
                "--title", "kobito実行基盤の確認が必要です",
                "--body", "gatewayまたはSSHエラーで実行が終了しました。Macの起動、Tailscale、SSH接続を確認してください。次回の定期実行で自動再試行します。",
            )
        else:
            _board_command(
                "resolve", "--direction", "agent-to-user",
                "--dedupe-key", "kobito-gateway",
            )


@run_task_blueprint.route("/run", methods=["POST"])
def run_task():
    if not config.EXECUTION_ENABLED or not config.CLAUDE_ENABLED:
        return {"error": "Claude execution is disabled"}, 503
    body = request.get_json(force=True, silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    resume_session_id = body.get("resume_session_id") or None
    repo = (body.get("repo") or "").strip() or None
    source = (body.get("source") or "").strip() or None

    if not prompt:
        return {"error": "prompt is required"}, 400

    if repo and not is_valid_repo_name(repo):
        return {"error": "invalid repo name"}, 400

    def generate():
        tracker = _KobitoRunTracker() if _is_kobito_run(prompt, source) else None
        failed = False
        if tracker:
            tracker.start()
        try:
            raw_lines = run_remote_claude(prompt, resume_session_id, repo)
            for line in raw_lines:
                if '"type":"gateway_error"' in line.replace(" ", ""):
                    failed = True
                yield from to_sse_frames([line])
        except Exception:
            failed = True
            raise
        finally:
            if tracker:
                tracker.finish(
                    "failed" if failed else "completed",
                    "gatewayまたはSSHエラーで終了" if failed else "Claude Codeセッションが終了",
                )

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
