import json
import logging
import shlex
import subprocess
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context

import config
from claude_stream import to_sse_frames
from ssh_runner import (
    is_valid_repo_name, is_valid_project_id, run_remote_claude,
    run_remote_command, select_kobito_project,
)
from telemetry import traced_claude_run

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
            "Slackの#p-kobitoと、Macの受付ログで直近エラーと対処方法を確認してください。",
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
                "--type", "action_required", "--dedupe-key", "kobito-health",
                "--title", "kobito実行基盤の確認が必要です",
                "--body", f"原因: {summary}\n影響: 今回のkobito作業は開始または完了できませんでした。\n"
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
    if not config.EXECUTION_ENABLED or not config.CLAUDE_ENABLED:
        return {"error": "Claude execution is disabled"}, 503
    body = request.get_json(force=True, silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    resume_session_id = body.get("resume_session_id") or None
    repo = (body.get("repo") or "").strip() or None
    source = (body.get("source") or "").strip() or None
    project_id = body.get("project_id")
    execution_mode = body.get("execution_mode")

    if not prompt:
        return {"error": "prompt is required"}, 400

    if project_id is not None and (
        not isinstance(project_id, str) or not is_valid_project_id(project_id)
    ):
        return {"error": "invalid project ID"}, 400
    if source == "kobito-slack" or execution_mode == "conversation":
        # Slack conversations run directly on the Mac since FEZ-281.
        return {"error": "Slack conversations are no longer served by the gateway"}, 400
    if execution_mode not in (None, "work"):
        return {"error": "invalid execution mode"}, 400

    if _is_kobito_run(prompt, source) and config.KOBITO_PROJECT_DISPATCH_ENABLED and not project_id:
        try:
            code, output = select_kobito_project()
            if code:
                raise ValueError("project selection failed")
            selected = json.loads(output)
            if selected is None:
                return Response(
                    'event: result\ndata: {"type":"result","result":"No enabled project work"}\n\n',
                    mimetype="text/event-stream",
                )
            project_id, repo = selected["id"], selected["repo"]
            if not is_valid_project_id(project_id) or not is_valid_repo_name(repo):
                raise ValueError("invalid selected project")
            execution_mode = "work"
        except (ValueError, TypeError, KeyError, OSError, subprocess.TimeoutExpired):
            return {"error": "project selection unavailable; no work started"}, 503

    if project_id and not repo:
        return {"error": "project-scoped execution requires repo"}, 400

    if repo and not is_valid_repo_name(repo):
        return {"error": "invalid repo name"}, 400

    def generate():
        tracker = _KobitoRunTracker() if _is_kobito_run(prompt, source) else None
        failed = False
        failure_message = None
        if tracker:
            tracker.start()
        with traced_claude_run(source, repo) as span:
            try:
                if project_id:
                    raw_lines = run_remote_claude(
                        prompt, resume_session_id, repo,
                        project_id=project_id, execution_mode=execution_mode,
                    )
                else:
                    raw_lines = run_remote_claude(prompt, resume_session_id, repo)
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
                span.set_attribute("error", failed)
                if tracker:
                    tracker.finish(
                        "failed" if failed else "completed",
                        failure_message or "gatewayまたはSSHエラーで終了"
                        if failed else "Claude Codeセッションが終了",
                    )

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
