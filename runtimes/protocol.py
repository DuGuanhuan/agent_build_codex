from __future__ import annotations

import time
import uuid
from typing import Any, Callable


RUNTIME_EVENT_PROTOCOL = "runtime-event.v1"
RUNTIME_ARTIFACT_PROTOCOL = "runtime-artifact.v1"
RUNTIME_TURN_PROTOCOL = "runtime-turn.v1"

RuntimeEventSink = Callable[[str, dict[str, Any]], None]

RUNTIME_EVENT_NAMES = {
    "message_start",
    "text_delta",
    "tool_start",
    "tool_result",
    "tool_error",
    "artifact_updated",
    "session_diff",
    "session_todo",
    "session_status",
    "message_done",
    "error",
}

ARTIFACT_TYPES = {
    "tool_call",
    "command_output",
    "file_diff",
    "todo",
    "permission",
    "diagnostic",
    "trace",
    "file",
    "link",
}


class RuntimeEventStream:
    def __init__(
        self,
        *,
        runtime_id: str,
        trace_id: str | None = None,
        turn_id: str | None = None,
    ):
        self.runtime_id = runtime_id
        self.trace_id = trace_id
        self.turn_id = turn_id
        self._sequence = 0

    def sink(self, event_sink: RuntimeEventSink | None) -> RuntimeEventSink | None:
        if not event_sink:
            return None

        def wrapped(event: str, payload: dict[str, Any]) -> None:
            normalized_event, normalized_payload = self.normalize(event, payload)
            event_sink(normalized_event, normalized_payload)

        return wrapped

    def normalize(self, event: str, payload: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        self._sequence += 1
        return normalize_runtime_event(
            event,
            payload or {},
            runtime_id=self.runtime_id,
            trace_id=self.trace_id,
            turn_id=self.turn_id,
            sequence=self._sequence,
        )


def normalize_runtime_event(
    event: str,
    payload: dict[str, Any],
    *,
    runtime_id: str | None = None,
    trace_id: str | None = None,
    turn_id: str | None = None,
    sequence: int | None = None,
) -> tuple[str, dict[str, Any]]:
    normalized_event = "tool_start" if event == "tool_awaiting_approval" else event
    normalized = dict(payload)

    normalized["protocol_version"] = RUNTIME_EVENT_PROTOCOL
    normalized["event"] = normalized_event
    normalized.setdefault("event_id", f"evt_{uuid.uuid4().hex[:12]}")
    if sequence is not None:
        normalized["sequence"] = sequence
    normalized.setdefault("created_at", time.time())

    runtime = _first_str(normalized.get("runtime"), runtime_id)
    if runtime:
        normalized["runtime"] = runtime

    trace = _first_str(normalized.get("trace_id"), trace_id)
    if trace:
        normalized["trace_id"] = trace

    turn = _first_str(normalized.get("turn_id"), turn_id)
    if turn:
        normalized["turn_id"] = turn

    if normalized_event in {"tool_start", "tool_result", "tool_error"}:
        step = normalize_tool_step(normalized, runtime_id=runtime, trace_id=trace)
        normalized.update(step)
        normalized["step_id"] = step["id"]

    if normalized_event in {"artifact_updated", "session_diff", "session_todo"}:
        artifact = normalized.get("artifact")
        if isinstance(artifact, dict):
            normalized["artifact"] = normalize_runtime_artifact(artifact, runtime_id=runtime)

    if normalized_event == "message_done":
        steps = normalized.get("steps")
        if isinstance(steps, list):
            normalized["steps"] = [
                normalize_tool_step(step, runtime_id=runtime, trace_id=trace)
                for step in steps
                if isinstance(step, dict)
            ]
        artifacts = normalized.get("artifacts")
        if isinstance(artifacts, list):
            normalized["artifacts"] = [
                normalize_runtime_artifact(artifact, runtime_id=runtime)
                for artifact in artifacts
                if isinstance(artifact, dict)
            ]

    if normalized_event == "error":
        message = normalized.get("message") or normalized.get("error") or "Runtime error"
        normalized["message"] = str(message)

    return normalized_event, normalized


def normalize_tool_step(
    step: dict[str, Any],
    *,
    runtime_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    step_id = _first_str(step.get("id"), step.get("step_id")) or f"tool_{uuid.uuid4().hex[:8]}"
    status = _first_str(step.get("status")) or "running"
    tool_type = _first_str(step.get("type")) or ("tool_error" if status == "error" else "tool")
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    normalized = {
        "id": step_id,
        "type": tool_type,
        "status": status,
        "tool": _first_str(step.get("tool")) or "runtime_tool",
        "args": args,
        "result": step.get("result"),
        "error": None if step.get("error") is None else str(step.get("error")),
        "permission": None if step.get("permission") is None else str(step.get("permission")),
        "started_at": step.get("started_at"),
        "ended_at": step.get("ended_at"),
        "duration_ms": step.get("duration_ms"),
    }
    runtime = _first_str(step.get("runtime"), runtime_id)
    if runtime:
        normalized["runtime"] = runtime
    trace = _first_str(step.get("trace_id"), trace_id)
    if trace:
        normalized["trace_id"] = trace
    return normalized


def normalize_runtime_artifact(
    artifact: dict[str, Any],
    *,
    runtime_id: str | None = None,
) -> dict[str, Any]:
    artifact_id = _first_str(artifact.get("id")) or f"artifact_{uuid.uuid4().hex[:12]}"
    artifact_type = _first_str(artifact.get("type")) or "diagnostic"
    status = _first_str(artifact.get("status")) or "ready"
    normalized = dict(artifact)
    normalized.update(
        {
            "protocol_version": RUNTIME_ARTIFACT_PROTOCOL,
            "id": artifact_id,
            "type": artifact_type,
            "status": status,
            "title": _first_str(artifact.get("title")) or _title_for_artifact_type(artifact_type),
            "data": artifact.get("data"),
        }
    )
    runtime = _first_str(artifact.get("runtime"), runtime_id)
    if runtime:
        normalized["runtime"] = runtime
    normalized.setdefault("updated_at", time.time())
    return normalized


def normalize_turn(turn: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(turn)
    normalized["protocol_version"] = RUNTIME_TURN_PROTOCOL
    normalized.setdefault("turn_id", f"turn_{uuid.uuid4().hex[:12]}")
    normalized.setdefault("session_id", "")
    normalized.setdefault("runtime_id", "")
    normalized.setdefault("model_id", "")
    normalized.setdefault("status", "running")
    normalized.setdefault("side_effect_level", "none")
    normalized.setdefault("file_changes", [])
    normalized.setdefault("artifacts", [])
    normalized.setdefault("event_count", 0)
    normalized.setdefault("assistant_message_id", "")
    normalized.setdefault("trace_id", "")
    normalized.setdefault("error", "")
    normalized.setdefault("created_at", time.time())
    normalized.setdefault("completed_at", None)
    normalized.setdefault("rolled_back_at", None)
    normalized.setdefault("retry_of_turn_id", None)
    return normalized


def _first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _title_for_artifact_type(artifact_type: str) -> str:
    titles = {
        "file_diff": "File Diff",
        "todo": "Todo / Plan",
        "diagnostic": "Diagnostic",
        "trace": "Trace",
        "permission": "Permission",
        "command_output": "Command Output",
        "tool_call": "Tool Call",
    }
    return titles.get(artifact_type, artifact_type.replace("_", " ").title())
