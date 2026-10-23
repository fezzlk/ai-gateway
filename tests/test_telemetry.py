import json
import sys
from pathlib import Path

from flask import Flask
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import telemetry  # noqa: E402
from routes import run_task  # noqa: E402


def _attach_recorder():
    exporter = InMemorySpanExporter()
    telemetry.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def test_traced_claude_run_records_success_without_prompt():
    exporter = _attach_recorder()

    with telemetry.traced_claude_run("kobito", "kobito") as span:
        span.set_attribute("error", False)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    attrs = spans[0].attributes
    assert attrs["gen_ai.operation.name"] == "invoke_agent"
    assert attrs["gen_ai.agent.name"] == "claude-code"
    assert attrs["ai_gateway.source"] == "kobito"
    assert attrs["ai_gateway.repo"] == "kobito"
    assert attrs["error"] is False
    assert attrs["duration_ms"] >= 0
    assert not any("prompt" in key for key in attrs)


def test_traced_claude_run_records_exception_as_error():
    exporter = _attach_recorder()

    try:
        with telemetry.traced_claude_run("kobito", None):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    spans = exporter.get_finished_spans()
    assert spans[-1].attributes["error"] is True
    assert spans[-1].attributes["ai_gateway.repo"] == "unknown"


def test_run_task_emits_span_marked_failed_on_gateway_error(monkeypatch):
    exporter = _attach_recorder()

    app = Flask(__name__)
    app.register_blueprint(run_task.run_task_blueprint)
    monkeypatch.setattr(
        run_task, "run_remote_claude",
        lambda *args, **kwargs: iter(
            [json.dumps({"type": "gateway_error", "message": "ssh failed"})]
        ),
    )

    response = app.test_client().post(
        "/api/run",
        json={"source": "test", "prompt": "hello", "repo": "kobito"},
    )
    response.get_data()

    spans = exporter.get_finished_spans()
    matching = [s for s in spans if s.attributes.get("ai_gateway.source") == "test"]
    assert matching
    assert matching[-1].attributes["error"] is True
