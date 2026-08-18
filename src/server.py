import logging
import os
import sys
from pathlib import Path

from flask import Flask

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

_STATIC_DIR = Path(__file__).parent / "static"

app = Flask(__name__, static_folder=str(_STATIC_DIR), static_url_path="")

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
    return app.send_static_file("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
