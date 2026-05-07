from __future__ import annotations

from typing import Any, Callable

from runtimes.base import AgentRuntime, EventSink, RuntimeRequest, RuntimeResult


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
    ):
        self._run_agent = run_agent
        self._get_model_config = get_model_config

    def run(self, request: RuntimeRequest, event_sink: EventSink | None = None) -> RuntimeResult:
        result = self._run_agent(
            request.messages,
            request.model_id,
            event_sink=event_sink,
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
