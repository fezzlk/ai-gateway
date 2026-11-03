import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture(autouse=True)
def default_kobito_agent(monkeypatch):
    # kobito runs ask the Mac which agent to use; tests never reach a real Mac.
    from routes import run_task
    monkeypatch.setattr(run_task, "select_kobito_agent", lambda: {"agent": "claude"})
