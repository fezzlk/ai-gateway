import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

from flask import Flask, redirect
from werkzeug.middleware.proxy_fix import ProxyFix

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

_STATIC_DIR = Path(__file__).parent / "static"

app = Flask(__name__, static_folder=str(_STATIC_DIR), static_url_path="")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SESSION_SECRET") or None
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

from auth import api_auth  # noqa: E402
from routes.health import health_blueprint  # noqa: E402
from routes.line_webhook import line_webhook_blueprint  # noqa: E402
from routes.run_task import run_task_blueprint  # noqa: E402
from routes.usage import usage_blueprint  # noqa: E402

app.register_blueprint(api_auth)
app.register_blueprint(health_blueprint)
app.register_blueprint(run_task_blueprint)
app.register_blueprint(line_webhook_blueprint)
app.register_blueprint(usage_blueprint)


@app.route("/")
def index():
    # The human-facing chat UI (server-side conversation history, Firestore
    # backing) was removed by FEZ-143: ai-gateway is now a pure automation
    # dispatch gateway for kobito, and humans use Claude's/Codex's own
    # official chat clients instead (see the ai-gateway agent boundary
    # decision record). /usage.html (the AI usage dashboard) is the only
    # remaining human-facing page, so "/" redirects there instead of 404ing.
    return redirect("/usage.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
