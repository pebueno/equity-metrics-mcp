"""Tool-call auditing.

Every MCP tool call writes exactly one audit record, in a `finally` path, so a
failure is as visible as a success. The record is written through its own
session: a rolled-back data session must never take the audit trail with it,
and an audit failure must never turn a good answer into an error.
"""

import datetime as dt
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from equity_metrics.db.models import McpToolCall

logger = logging.getLogger("equity_metrics.mcp.audit")

# Argument values are bounded so one oversized input cannot bloat the audit table.
MAX_VALUE_LENGTH = 200
MAX_SEQUENCE_ITEMS = 20

# Keys whose values must never reach storage, matched as substrings.
REDACTED_KEY_PARTS = ("key", "token", "secret", "password", "authorization", "prompt", "question")
REDACTED = "[redacted]"

OUTCOME_SUCCESS = "success"
OUTCOME_ERROR = "error"
OUTCOME_FAILURE = "failure"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


@contextmanager
def correlation_scope(correlation_id: str) -> Iterator[str]:
    """Bind a correlation ID so every tool call inside the block shares it.

    The AI gateway uses this to tie one investor question to the tool calls it
    triggered; a standalone MCP client simply gets a fresh ID per call.
    """
    token = _correlation_id.set(correlation_id)
    try:
        yield correlation_id
    finally:
        _correlation_id.reset(token)


def current_correlation_id() -> str:
    """Return the bound correlation ID, or a fresh one for an unscoped call."""
    return _correlation_id.get() or uuid.uuid4().hex


@contextmanager
def audit_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    session_factory: Callable[[], Session],
) -> Iterator["AuditRecord"]:
    """Time a tool call and persist its audit record however the call ends."""
    record = AuditRecord(
        correlation_id=current_correlation_id(),
        tool_name=tool_name,
        sanitized_arguments=sanitize_arguments(arguments),
    )
    started = time.perf_counter()
    try:
        yield record
    except BaseException as exc:
        record.outcome = OUTCOME_FAILURE
        record.error_code = type(exc).__name__
        raise
    finally:
        record.duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        _persist(record, session_factory)


class AuditRecord:
    """Mutable audit state for one in-flight tool call."""

    def __init__(
        self, *, correlation_id: str, tool_name: str, sanitized_arguments: dict[str, Any]
    ) -> None:
        self.correlation_id = correlation_id
        self.tool_name = tool_name
        self.sanitized_arguments = sanitized_arguments
        self.outcome = OUTCOME_SUCCESS
        self.error_code: str | None = None
        self.duration_ms = 0

    def mark_error(self, error_code: str) -> None:
        """Record a recoverable domain error returned to the caller."""
        self.outcome = OUTCOME_ERROR
        self.error_code = error_code


def sanitize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Bound and redact tool arguments before they are stored."""
    sanitized: dict[str, Any] = {}
    for key, value in arguments.items():
        if value is None:
            continue
        if any(part in key.lower() for part in REDACTED_KEY_PARTS):
            sanitized[key] = REDACTED
            continue
        sanitized[key] = _sanitize_value(value)
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_VALUE_LENGTH]
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, list | tuple):
        return [_sanitize_value(item) for item in value[:MAX_SEQUENCE_ITEMS]]
    if isinstance(value, dict):
        return sanitize_arguments(value)
    return str(value)[:MAX_VALUE_LENGTH]


def _persist(record: AuditRecord, session_factory: Callable[[], Session]) -> None:
    """Write the audit record, logging rather than raising if storage fails."""
    try:
        with session_factory() as session:
            session.add(
                McpToolCall(
                    correlation_id=record.correlation_id,
                    tool_name=record.tool_name,
                    sanitized_arguments=record.sanitized_arguments,
                    outcome=record.outcome,
                    error_code=record.error_code,
                    duration_ms=record.duration_ms,
                    created_at=dt.datetime.now(dt.UTC),
                )
            )
            session.commit()
    except Exception:  # pragma: no cover - storage failure must not mask the result
        logger.exception(
            "failed to persist audit record for tool %s (correlation %s)",
            record.tool_name,
            record.correlation_id,
        )
