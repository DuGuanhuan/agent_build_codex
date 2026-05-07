from __future__ import annotations

from typing import Any, Callable

from runtimes.base import AgentRuntime, EventSink, RuntimeRequest, RuntimeResult
from runtimes.protocol import RuntimeEventStream


class HandmadeRuntime(AgentRuntime):
    id = "handmade"
    label = "手搓 Agent"
    description = "当前项目内置的轻量手写 Agent，支持模型切换、工具调用、审批和会话摘要。"
    capabilities = {
        "text": True,
        "stream": True,
        "toolEvents": True,
        "toolApproval": True,
        "fileRead": True,
        "fileWrite": True,
        "shell": True,
        "workspaceOnly": True,
    }

    def __init__(
        self,
        run_agent: Callable[..., dict[str, Any]],
        get_model_config: Callable[[str | None], dict[str, Any]],
        get_tool_catalog: Callable[[], list[dict[str, Any]]] | None = None,
        get_skill_catalog: Callable[[], list[dict[str, Any]]] | None = None,
    ):
        self._run_agent = run_agent
        self._get_model_config = get_model_config
        self._get_tool_catalog = get_tool_catalog
        self._get_skill_catalog = get_skill_catalog

    def run(self, request: RuntimeRequest, event_sink: EventSink | None = None) -> RuntimeResult:
        protocol_events = RuntimeEventStream(runtime_id=self.id, turn_id=request.turn_id)
        result = self._run_agent(
            request.messages,
            request.model_id,
            event_sink=protocol_events.sink(event_sink),
            trusted_tools=request.trusted_tools or [],
            runtime_id=self.id,
            turn_id=getattr(request, "turn_id", None),
        )
        model_id = self._get_model_config(request.model_id)["id"]
        return RuntimeResult(
            answer=result.get("answer", ""),
            steps=result.get("steps", []),
            trace_id=result.get("trace_id"),
            model=model_id,
            runtime=self.id,
        )

    def tool_catalog(self) -> list[dict[str, Any]]:
        if not self._get_tool_catalog:
            return []
        return [
            {
                **tool,
                "runtime": self.id,
                "source": "workbuddy-registry",
                "editable": False,
                "native": False,
            }
            for tool in self._get_tool_catalog()
        ]

    def skill_catalog(self) -> list[dict[str, Any]]:
        if not self._get_skill_catalog:
            return []
        return [
            {
                **skill,
                "runtime": self.id,
                "source": "workbuddy-skills",
                "editable": True,
                "native": False,
            }
            for skill in self._get_skill_catalog()
        ]
