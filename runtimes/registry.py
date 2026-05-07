from __future__ import annotations

from runtimes.base import AgentRuntime


DEFAULT_RUNTIME_ID = "handmade"
_runtime_options: list[AgentRuntime] = []
_runtimes_by_id: dict[str, AgentRuntime] = {}


def configure_runtimes(runtimes: list[AgentRuntime], default_runtime_id: str = DEFAULT_RUNTIME_ID) -> None:
    global DEFAULT_RUNTIME_ID, _runtime_options, _runtimes_by_id
    DEFAULT_RUNTIME_ID = default_runtime_id
    _runtime_options = runtimes
    _runtimes_by_id = {runtime.id: runtime for runtime in runtimes}


def get_runtime(runtime_id: str | None = None) -> AgentRuntime:
    requested_id = runtime_id or DEFAULT_RUNTIME_ID
    runtime = _runtimes_by_id.get(requested_id)
    if not runtime:
        allowed = ", ".join(runtime.id for runtime in _runtime_options)
        raise ValueError(f"未知 Agent Runtime：{requested_id}。可用 Runtime：{allowed}")
    return runtime


def public_runtime_options() -> dict:
    default_runtime = get_runtime()
    return {
        "runtimes": [runtime.public_info(default_runtime.id) for runtime in _runtime_options],
        "default": default_runtime.id,
    }


def public_runtime_catalog() -> dict:
    default_runtime = get_runtime()
    return {
        "runtimes": [
            {
                **runtime.public_info(default_runtime.id),
                "tools": runtime.tool_catalog(),
                "skills": runtime.skill_catalog(),
            }
            for runtime in _runtime_options
        ],
        "default": default_runtime.id,
    }
