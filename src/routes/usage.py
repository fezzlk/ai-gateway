import json

from flask import Blueprint, jsonify, request

from ssh_runner import run_remote_command

usage_blueprint = Blueprint("usage_blueprint", __name__)


@usage_blueprint.route("/api/usage", methods=["GET"])
def usage():
    try:
        hours = min(24 * 30, max(1, int(request.args.get("hours", 168))))
    except ValueError:
        return jsonify(error="hours must be an integer"), 400
    command = f"python3 ~/repos/human-agent-board/board.py usage dashboard --hours {hours}"
    returncode, output = run_remote_command(command, timeout=60)
    if returncode != 0:
        return jsonify(error="usage unavailable", details=output.strip()[:1000]), 502
    try:
        return jsonify(json.loads(output))
    except json.JSONDecodeError:
        return jsonify(error="invalid usage response"), 502
