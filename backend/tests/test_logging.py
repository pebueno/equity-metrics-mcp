"""Structured log output."""

import json
import logging

from equity_metrics.logging import JsonFormatter


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="equity_metrics.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="imported %d rows",
        args=(2000,),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_renders_one_json_object_per_record() -> None:
    payload = json.loads(JsonFormatter().format(_record()))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "equity_metrics.test"
    assert payload["message"] == "imported 2000 rows"
    assert payload["timestamp"].endswith("+00:00")


def test_forwards_caller_supplied_context() -> None:
    payload = json.loads(JsonFormatter().format(_record(correlation_id="req-1", duration_ms=12)))

    assert payload["correlation_id"] == "req-1"
    assert payload["duration_ms"] == 12
