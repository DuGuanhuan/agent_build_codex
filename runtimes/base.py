from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


EventSink = Callable[[str, dict[str, Any]], None]


@dataclass
class RuntimeRequest:
    messages: list[dict[str, Any]]
    model_id: str | None = None
    trusted_tools: list[str] | None = None
    session_id: str | None = None
    turn_id: str | None = None


@dataclass
class RuntimeResult:
    answer: str
    steps: list[dict[str, Any]]
    trace_id: str | None = None
    model: str | None = None
    runtime: str | None = None
    artifacts: list[dict[str, Any]] | None = None


class AgentRuntime:
    id = ""
    label = ""
    description = ""
    capabilities: dict[str, Any] = {}
    supported_model_ids: list[str] = []

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def version(self) -> str | None:
        return None

    def public_info(self, default_runtime_id: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "available": self.available(),
            "default": self.id == default_runtime_id,
            "version": self.version(),
            "unavailable_reason": self.unavailable_reason(),
            "capabilities": self.capabilities,
            "supported_model_ids": self.supported_model_ids,
        }

    def run(self, request: RuntimeRequest, event_sink: EventSink | None = None) -> RuntimeResult:
        raise NotImplementedError

    def abort(self, session_id: str) -> bool:
        return False

    def artifacts(self, session_id: str) -> list[dict[str, Any]]:
        return []

    def session_ref(self, session_id: str) -> dict[str, Any] | None:
        return None
