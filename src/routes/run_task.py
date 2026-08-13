from flask import Blueprint, Response, request, stream_with_context

from claude_stream import to_sse_frames
from ssh_runner import run_remote_claude

run_task_blueprint = Blueprint("run_task_blueprint", __name__, url_prefix="/api")


@run_task_blueprint.route("/run", methods=["POST"])
def run_task():
    body = request.get_json(force=True, silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    resume_session_id = body.get("resume_session_id") or None

    if not prompt:
        return {"error": "prompt is required"}, 400

    def generate():
        raw_lines = run_remote_claude(prompt, resume_session_id)
        yield from to_sse_frames(raw_lines)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
