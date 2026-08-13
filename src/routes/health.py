from flask import Blueprint, jsonify

health_blueprint = Blueprint("health_blueprint", __name__)


@health_blueprint.route("/health")
def health():
    return jsonify(status="ok")
