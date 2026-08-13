import json


def to_sse_frames(raw_lines):
    """Converts `claude --output-format stream-json` NDJSON lines into
    Server-Sent Events frames for the browser.

    Lines that aren't valid JSON (stray SSH/shell noise) are forwarded as
    a generic "log" event rather than dropped, so nothing goes silently
    missing during debugging.
    """
    for line in raw_lines:
        if not line.strip():
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            yield _frame("log", {"line": line})
            continue

        event_type = event.get("type", "unknown")
        yield _frame(event_type, event)


def _frame(event_name: str, data: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"
