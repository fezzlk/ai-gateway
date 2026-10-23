"""Minimal OpenTelemetry GenAI-semantic-conventions PoC (FEZ-115).

Traces are exported to stdout via ConsoleSpanExporter only -- nothing
leaves the process. This validates whether a single Claude execution can
be correlated by agent name, operation, duration, and error outcome
without recording prompt text or credentials.
"""
import time
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

_provider = TracerProvider(resource=Resource.create({"service.name": "ai-gateway"}))
_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(_provider)

_tracer = trace.get_tracer("ai-gateway.claude_run")


def add_span_processor(processor):
    """Lets tests attach an extra exporter (e.g. in-memory) for assertions."""
    _provider.add_span_processor(processor)


@contextmanager
def traced_claude_run(source, repo):
    """Wraps one `run_remote_claude` execution in a span.

    Deliberately excludes prompt text: only routing metadata (source,
    repo) plus duration/error outcome are recorded as attributes.
    """
    with _tracer.start_as_current_span("gen_ai.invoke_agent") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", "claude-code")
        span.set_attribute("ai_gateway.source", source or "unknown")
        span.set_attribute("ai_gateway.repo", repo or "unknown")
        span.set_attribute("error", False)
        started = time.monotonic()
        try:
            yield span
        except Exception:
            span.set_attribute("error", True)
            raise
        finally:
            span.set_attribute("duration_ms", int((time.monotonic() - started) * 1000))
