from __future__ import annotations

import atexit
import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from runtimes.base import AgentRuntime, EventSink, RuntimeRequest, RuntimeResult
from runtimes.protocol import RuntimeEventStream, normalize_runtime_artifact
from runtimes.skill_scanner import discover_opencode_skills


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return message["content"].strip()
    return ""


def _short_title(text: str) -> str:
    return text.strip().replace("\n", " ")[:40] or "OpenCode Session"


def _permission_rules() -> list[dict[str, str]]:
    permissions = [
        "*",
        "bash",
        "read",
        "edit",
        "glob",
        "grep",
        "webfetch",
        "websearch",
        "task",
        "skill",
        "external_directory",
    ]
    return [{"permission": permission, "pattern": "*", "action": "allow"} for permission in permissions]


def _native_tool(name: str, description: str, permission: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "permission": permission,
        "parameters": {"type": "object", "properties": {}, "required": []},
        "runtime": "opencode",
        "source": "opencode-native",
        "editable": False,
        "native": True,
    }


class OpenCodeServeRuntime(AgentRuntime):
    id = "opencode"
    label = "OpenCode"
    description = "通过 OpenCode serve 运行的原生 coding agent runtime。"
    capabilities = {
        "text": True,
        "stream": True,
        "toolEvents": True,
        "toolApproval": True,
        "fileRead": True,
        "fileWrite": True,
        "shell": True,
        "webFetch": True,
        "webSearch": True,
        "subAgent": True,
        "diff": True,
        "todo": True,
        "nativeSession": True,
        "abort": True,
        "resume": True,
        "workspaceOnly": False,
    }
    supported_model_ids = [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-v4-pro-thinking",
    ]

    def __init__(self, workspace: Path):
        self.workspace = Path(os.getenv("OPENCODE_WORKSPACE", str(workspace))).resolve()
        self.binary = os.getenv("OPENCODE_BIN", "opencode")
        self.host = os.getenv("OPENCODE_SERVER_HOST", "127.0.0.1")
        self.port = int(os.getenv("OPENCODE_SERVER_PORT", "4096"))
        self.server_url = (os.getenv("OPENCODE_SERVER_URL") or f"http://{self.host}:{self.port}").rstrip("/")
        self.start_server = _env_bool("OPENCODE_START_SERVER", True)
        self.request_timeout = _env_int("OPENCODE_REQUEST_TIMEOUT_MS", 30_000) / 1000
        self.event_timeout = _env_int("OPENCODE_EVENT_TIMEOUT_MS", 120_000) / 1000
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._session_map: dict[str, str] = {}
        self._session_store_path = Path(
            os.getenv("RUNTIME_SESSION_STORE_PATH", str(self.workspace / ".workbuddy" / "runtime-sessions.json"))
        )
        self._load_session_map()
        atexit.register(self.stop)

    def _binary_path(self) -> str | None:
        return shutil.which(self.binary)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        password = os.getenv("OPENCODE_SERVER_PASSWORD")
        if password:
            username = os.getenv("OPENCODE_SERVER_USERNAME", "opencode")
            token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = self.server_url + path
        if query:
            url += "?" + urllib.parse.urlencode({key: value for key, value in query.items() if value is not None})
        return url

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("OPENCODE_PERMISSION", json.dumps({rule["permission"]: "allow" for rule in _permission_rules()}))
        return env

    def _session_key(self, local_session_id: str) -> str:
        return f"{self.id}:{self.workspace}:{local_session_id}"

    def _load_session_map(self) -> None:
        try:
            data = json.loads(self._session_store_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if not key.startswith(f"{self.id}:{self.workspace}:") or not isinstance(value, str):
                continue
            local_session_id = key.rsplit(":", 1)[-1]
            self._session_map[local_session_id] = value

    def _save_session_map(self) -> None:
        try:
            existing = json.loads(self._session_store_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        for local_session_id, runtime_session_id in self._session_map.items():
            existing[self._session_key(local_session_id)] = runtime_session_id
        try:
            self._session_store_path.parent.mkdir(parents=True, exist_ok=True)
            self._session_store_path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url(path, query),
            data=data,
            headers=self._headers(),
            method=method,
        )
        with urllib.request.urlopen(request, timeout=timeout or self.request_timeout) as response:
            body = response.read().decode("utf-8")
        if not body.strip():
            return None
        return json.loads(body)

    def _health(self) -> dict[str, Any] | None:
        try:
            data = self._request_json("GET", "/global/health", timeout=2)
        except Exception:
            return None
        return data if isinstance(data, dict) and data.get("healthy") is True else None

    def _ensure_server(self) -> bool:
        if self._health():
            return True
        if os.getenv("OPENCODE_SERVER_URL") or not self.start_server:
            return False

        binary = self._binary_path()
        if not binary:
            return False

        with self._lock:
            if self._health():
                return True
            if self._process and self._process.poll() is None:
                return self._wait_until_healthy()

            self._process = subprocess.Popen(
                [binary, "serve", "--hostname", self.host, "--port", str(self.port)],
                cwd=str(self.workspace),
                env=self._env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return self._wait_until_healthy()

    def _wait_until_healthy(self) -> bool:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._health():
                return True
            time.sleep(0.2)
        return False

    def available(self) -> bool:
        return self._ensure_server()

    def unavailable_reason(self) -> str:
        if self._health():
            return ""
        if not self._binary_path():
            return f"未找到 OpenCode CLI：{self.binary}"
        return f"OpenCode server 不可用：{self.server_url}"

    def version(self) -> str | None:
        health = self._health()
        if health and isinstance(health.get("version"), str):
            return health["version"]
        binary = self._binary_path()
        if not binary:
            return None
        try:
            output = subprocess.check_output([binary, "--version"], text=True, stderr=subprocess.STDOUT, timeout=5)
            return output.strip() or None
        except Exception:
            return None

    def tool_catalog(self) -> list[dict[str, Any]]:
        return [
            _native_tool("bash", "执行 shell 命令，能力和权限由 OpenCode 原生 runtime 控制", "shell"),
            _native_tool("read", "读取文件内容", "read_user_file"),
            _native_tool("edit", "编辑或写入文件", "edit_file"),
            _native_tool("grep", "在仓库内搜索文件内容", "repo_read"),
            _native_tool("glob", "按模式匹配文件路径", "repo_read"),
            _native_tool("webfetch", "读取公开网页内容", "network_read"),
            _native_tool("websearch", "联网搜索", "network_read"),
            _native_tool("task", "启动 OpenCode 子 Agent / 子任务", "subagent"),
            _native_tool("skill", "调用 OpenCode 原生 skill 机制", "native_skill"),
        ]

    def skill_catalog(self) -> list[dict[str, Any]]:
        return discover_opencode_skills(self.workspace)

    def stop(self) -> None:
        process = self._process
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    def _model(self, model_id: str | None) -> dict[str, str]:
        configured = os.getenv("OPENCODE_MODEL")
        if configured and "/" in configured:
            provider_id, model_id_value = configured.split("/", 1)
            return {"providerID": provider_id, "modelID": model_id_value}

        model_map = {
            "deepseek-v4-flash": ("deepseek", "deepseek-v4-flash"),
            "deepseek-v4-pro": ("deepseek", "deepseek-v4-pro"),
            "deepseek-v4-pro-thinking": ("deepseek", "deepseek-reasoner"),
        }
        if model_id in model_map:
            provider_id, model_id_value = model_map[model_id]
            return {"providerID": provider_id, "modelID": model_id_value}
        if model_id:
            allowed = ", ".join(self.supported_model_ids)
            raise RuntimeError(f"OpenCode runtime 暂不支持模型 {model_id}。请切换到：{allowed}")
        provider_id, model_id_value = model_map["deepseek-v4-pro"]
        return {"providerID": provider_id, "modelID": model_id_value}

    def _model_label(self, model: dict[str, str]) -> str:
        return f"{model['providerID']}/{model['modelID']}"

    def _session_for(self, local_session_id: str, title: str) -> str:
        with self._lock:
            existing = self._session_map.get(local_session_id)
            if existing:
                return existing
            created = self._request_json(
                "POST",
                "/session",
                {"title": title, "permission": _permission_rules()},
                query={"directory": str(self.workspace)},
            )
            if not isinstance(created, dict) or not isinstance(created.get("id"), str):
                raise RuntimeError("OpenCode session 创建失败")
            self._session_map[local_session_id] = created["id"]
            self._save_session_map()
            return created["id"]

    def _external_session_id(self, local_session_id: str) -> str | None:
        with self._lock:
            return self._session_map.get(local_session_id)

    def session_ref(self, session_id: str) -> dict[str, Any] | None:
        runtime_session_id = self._external_session_id(session_id)
        if not runtime_session_id:
            return None
        return {
            "local_session_id": session_id,
            "runtime_session_id": runtime_session_id,
            "workspace": str(self.workspace),
        }

    def _send_prompt(self, session_id: str, prompt: str, model: dict[str, str]) -> None:
        self._request_json(
            "POST",
            f"/session/{urllib.parse.quote(session_id)}/prompt_async",
            {
                "model": model,
                "parts": [{"type": "text", "text": prompt}],
            },
            query={"directory": str(self.workspace)},
        )

    def _abort(self, session_id: str) -> None:
        try:
            self._request_json(
                "POST",
                f"/session/{urllib.parse.quote(session_id)}/abort",
                query={"directory": str(self.workspace)},
                timeout=5,
            )
        except Exception:
            pass

    def abort(self, session_id: str) -> bool:
        runtime_session_id = self._external_session_id(session_id)
        if not runtime_session_id:
            return False
        self._abort(runtime_session_id)
        return True

    def _session_diff(self, runtime_session_id: str) -> Any:
        return self._request_json(
            "GET",
            f"/session/{urllib.parse.quote(runtime_session_id)}/diff",
            query={"directory": str(self.workspace)},
        )

    def _session_todo(self, runtime_session_id: str) -> Any:
        return self._request_json(
            "GET",
            f"/session/{urllib.parse.quote(runtime_session_id)}/todo",
            query={"directory": str(self.workspace)},
        )

    def artifacts(self, session_id: str) -> list[dict[str, Any]]:
        runtime_session_id = self._external_session_id(session_id)
        if not runtime_session_id:
            return []

        artifacts: list[dict[str, Any]] = []
        try:
            diff = self._session_diff(runtime_session_id)
            if _has_artifact_payload(diff):
                artifacts.append(
                    normalize_runtime_artifact(
                        {
                            "id": f"{self.id}:{session_id}:diff",
                            "type": "file_diff",
                            "runtime": self.id,
                            "title": "Workspace Diff",
                            "status": "ready",
                            "data": diff,
                        },
                        runtime_id=self.id,
                    )
                )
        except Exception as exc:
            artifacts.append(_diagnostic_artifact(self.id, session_id, "Diff 加载失败", exc))

        try:
            todo = self._session_todo(runtime_session_id)
            if _has_artifact_payload(todo):
                artifacts.append(
                    normalize_runtime_artifact(
                        {
                            "id": f"{self.id}:{session_id}:todo",
                            "type": "todo",
                            "runtime": self.id,
                            "title": "Todo / Plan",
                            "status": "ready",
                            "data": todo,
                        },
                        runtime_id=self.id,
                    )
                )
        except Exception as exc:
            artifacts.append(_diagnostic_artifact(self.id, session_id, "Todo 加载失败", exc))

        return artifacts

    def run(self, request: RuntimeRequest, event_sink: EventSink | None = None) -> RuntimeResult:
        if not self._ensure_server():
            raise RuntimeError(self.unavailable_reason())
        if not self.workspace.exists() or not self.workspace.is_dir():
            raise RuntimeError(f"OpenCode workspace 不存在：{self.workspace}")

        prompt = _latest_user_text(request.messages)
        if not prompt:
            raise RuntimeError("OpenCode runtime 没有收到有效用户消息")

        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        model = self._model(request.model_id)
        model_label = self._model_label(model)
        local_session_id = request.session_id or trace_id
        opencode_session_id = self._session_for(local_session_id, _short_title(prompt))
        protocol_events = RuntimeEventStream(runtime_id=self.id, trace_id=trace_id, turn_id=request.turn_id)
        event_sink = protocol_events.sink(event_sink)

        if event_sink:
            event_sink(
                "message_start",
                {
                    "id": f"assistant-{trace_id}",
                    "model": model_label,
                    "runtime": self.id,
                    "trace_id": trace_id,
                    "session_ref": self.session_ref(local_session_id),
                },
            )
            event_sink(
                "session_status",
                {
                    "runtime": self.id,
                    "status": "busy",
                    "local_session_id": local_session_id,
                    "runtime_session_id": opencode_session_id,
                },
            )

        state = _OpenCodeEventState(
            runtime_id=self.id,
            trace_id=trace_id,
            model_label=model_label,
            session_id=opencode_session_id,
            workspace=self.workspace,
            event_sink=event_sink,
        )

        try:
            with self._open_event_stream() as response:
                self._send_prompt(opencode_session_id, prompt, model)
                self._consume_events(response, state)
        except (BrokenPipeError, ConnectionResetError):
            self._abort(opencode_session_id)
            raise
        except Exception:
            self._abort(opencode_session_id)
            raise

        artifacts = _merge_artifacts(
            state.artifacts,
            self.artifacts(local_session_id),
            _file_diff_artifacts_from_touched_paths(self.id, local_session_id, self.workspace, state.touched_paths),
        )
        if event_sink:
            for artifact in artifacts:
                event_sink("artifact_updated", {"artifact": artifact})
                if artifact["type"] == "file_diff":
                    event_sink("session_diff", {"artifact": artifact, "session_ref": self.session_ref(local_session_id)})
                elif artifact["type"] == "todo":
                    event_sink("session_todo", {"artifact": artifact, "session_ref": self.session_ref(local_session_id)})
            event_sink(
                "session_status",
                {
                    "runtime": self.id,
                    "status": "idle",
                    "local_session_id": local_session_id,
                    "runtime_session_id": opencode_session_id,
                },
            )
            event_sink(
                "message_done",
                {
                    "answer": state.answer,
                    "steps": state.steps,
                    "artifacts": artifacts,
                    "model": model_label,
                    "runtime": self.id,
                    "trace_id": trace_id,
                    "session_ref": self.session_ref(local_session_id),
                },
            )

        return RuntimeResult(
            answer=state.answer,
            steps=state.steps,
            trace_id=trace_id,
            model=model_label,
            runtime=self.id,
            artifacts=artifacts,
        )

    def _open_event_stream(self):
        request = urllib.request.Request(
            self._url("/event", {"directory": str(self.workspace)}),
            headers={key: value for key, value in self._headers().items() if key != "Content-Type"},
            method="GET",
        )
        return urllib.request.urlopen(request, timeout=self.event_timeout)

    def _consume_events(self, response, state: "_OpenCodeEventState") -> None:
        data_lines: list[str] = []
        deadline = time.monotonic() + self.event_timeout
        while time.monotonic() < deadline:
            raw_line = response.readline()
            if raw_line == b"":
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if data_lines:
                    self._handle_sse_data("\n".join(data_lines), state)
                    data_lines = []
                    if state.done:
                        return
                continue
            if line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        raise RuntimeError("OpenCode event stream 等待响应超时")

    def _handle_sse_data(self, data: str, state: "_OpenCodeEventState") -> None:
        if not data or data == "[DONE]":
            return
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        if event.get("type") == "error":
            raise RuntimeError(_event_error_message(event))

        properties = event.get("properties")
        if not isinstance(properties, dict):
            return

        event_session_id = _event_session_id(properties)
        if event_session_id and event_session_id != state.session_id:
            return

        if event.get("type") == "session.idle":
            state.done = True
            return

        if event.get("type") == "session.status":
            status = properties.get("status")
            if isinstance(status, dict) and status.get("type") == "idle":
                state.done = True
            return

        if event.get("type") == "session.diff":
            state.handle_session_diff(properties.get("diff"))
            return

        if event.get("type") == "todo.updated":
            state.handle_todo_updated(properties.get("todos"))
            return

        if event.get("type") != "message.part.updated":
            return

        part = properties.get("part")
        if not isinstance(part, dict) or part.get("sessionID") != state.session_id:
            return

        part_type = part.get("type")
        if part_type == "text":
            delta = properties.get("delta")
            if isinstance(delta, str) and delta:
                state.answer_parts.append(delta)
                if state.event_sink:
                    state.event_sink("text_delta", {"delta": delta})
            return

        if part_type == "tool":
            state.handle_tool_part(part)


class _OpenCodeEventState:
    def __init__(
        self,
        runtime_id: str,
        trace_id: str,
        model_label: str,
        session_id: str,
        workspace: Path,
        event_sink: EventSink | None,
    ):
        self.runtime_id = runtime_id
        self.trace_id = trace_id
        self.model_label = model_label
        self.session_id = session_id
        self.workspace = workspace
        self.event_sink = event_sink
        self.answer_parts: list[str] = []
        self.steps_by_id: dict[str, dict[str, Any]] = {}
        self.artifacts_by_id: dict[str, dict[str, Any]] = {}
        self.touched_paths: set[str] = set()
        self.done = False

    @property
    def answer(self) -> str:
        return "".join(self.answer_parts)

    @property
    def steps(self) -> list[dict[str, Any]]:
        return list(self.steps_by_id.values())

    @property
    def artifacts(self) -> list[dict[str, Any]]:
        return list(self.artifacts_by_id.values())

    def _upsert_artifact(self, artifact: dict[str, Any], event_name: str) -> None:
        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, str):
            return
        self.artifacts_by_id[artifact_id] = artifact
        if self.event_sink:
            self.event_sink("artifact_updated", {"artifact": artifact})
            self.event_sink(event_name, {"artifact": artifact})

    def handle_session_diff(self, diff: Any) -> None:
        if not _has_artifact_payload(diff):
            return
        self._upsert_artifact(
            normalize_runtime_artifact(
                {
                    "id": f"{self.runtime_id}:{self.session_id}:diff",
                    "type": "file_diff",
                    "runtime": self.runtime_id,
                    "title": "Workspace Diff",
                    "status": "ready",
                    "data": diff,
                },
                runtime_id=self.runtime_id,
            ),
            "session_diff",
        )

    def handle_todo_updated(self, todos: Any) -> None:
        if not _has_artifact_payload(todos):
            return
        self._upsert_artifact(
            normalize_runtime_artifact(
                {
                    "id": f"{self.runtime_id}:{self.session_id}:todo",
                    "type": "todo",
                    "runtime": self.runtime_id,
                    "title": "Todo / Plan",
                    "status": "ready",
                    "data": todos,
                },
                runtime_id=self.runtime_id,
            ),
            "session_todo",
        )

    def handle_tool_part(self, part: dict[str, Any]) -> None:
        step_id = str(part.get("callID") or part.get("id") or f"tool-{len(self.steps_by_id) + 1}")
        tool_name = str(part.get("tool") or "opencode_tool")
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        status = state.get("status")
        args = state.get("input") if isinstance(state.get("input"), dict) else {}
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        time_info = state.get("time") if isinstance(state.get("time"), dict) else {}
        self.touched_paths.update(_extract_touched_paths(tool_name, args))

        step = self.steps_by_id.get(step_id)
        first_seen = step is None
        if step is None:
            step = {
                "id": step_id,
                "type": "tool",
                "status": "running",
                "tool": tool_name,
                "args": args,
                "result": None,
                "error": None,
                "permission": "opencode-native",
                "started_at": time_info.get("start"),
                "ended_at": None,
                "duration_ms": None,
            }
            self.steps_by_id[step_id] = step

        step["args"] = args or step.get("args") or {}
        if time_info.get("start"):
            step["started_at"] = time_info["start"]

        if status in ("pending", "running"):
            step["status"] = "running"
            if self.event_sink and first_seen:
                self.event_sink("tool_start", {"step_id": step_id, **step})
            return

        if status == "completed":
            output = state.get("output")
            result = dict(metadata)
            if output is not None:
                result.setdefault("output", output)
            step.update(
                {
                    "status": "success",
                    "result": result,
                    "ended_at": time_info.get("end"),
                }
            )
            step["duration_ms"] = _duration_ms(step.get("started_at"), step.get("ended_at"))
            if self.event_sink:
                self.event_sink("tool_result", {"step_id": step_id, **step})
            return

        if status == "error":
            error = str(state.get("error") or metadata.get("error") or "OpenCode 工具调用失败")
            step.update(
                {
                    "type": "tool_error",
                    "status": "error",
                    "error": error,
                    "result": {"error": error, **metadata},
                    "ended_at": time_info.get("end"),
                }
            )
            step["duration_ms"] = _duration_ms(step.get("started_at"), step.get("ended_at"))
            if self.event_sink:
                self.event_sink("tool_error", {"step_id": step_id, **step})


def _duration_ms(started_at: Any, ended_at: Any) -> int | None:
    if isinstance(started_at, (int, float)) and isinstance(ended_at, (int, float)):
        return max(0, int(ended_at - started_at))
    return None


def _has_artifact_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    if isinstance(value, dict):
        return any(_has_artifact_payload(item) for item in value.values())
    return True


def _merge_artifacts(*artifact_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for artifacts in artifact_groups:
        for artifact in artifacts:
            artifact = normalize_runtime_artifact(artifact, runtime_id=artifact.get("runtime"))
            artifact_id = artifact.get("id")
            if isinstance(artifact_id, str):
                merged[artifact_id] = artifact
    return list(merged.values())


def _extract_touched_paths(tool_name: str, args: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    path_keys = {"file", "path", "filepath", "file_path", "target", "filename", "destination"}
    for key, value in args.items():
        if key.lower() in path_keys and isinstance(value, str):
            paths.add(value)

    command = args.get("command")
    if tool_name == "bash" and isinstance(command, str):
        paths.update(_extract_paths_from_shell_command(command))
    return paths


def _extract_paths_from_shell_command(command: str) -> set[str]:
    paths: set[str] = set()
    for match in re.finditer(r"(?:^|\s)(?:>|>>)\s*([\"']?)([^\s\"';&|]+)\1", command):
        paths.add(match.group(2))
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = []
    if parts:
        if parts[0] == "touch":
            paths.update(part for part in parts[1:] if not part.startswith("-"))
        elif parts[0] in {"mv", "cp"} and len(parts) >= 3:
            paths.add(parts[-1])
    return paths


def _file_diff_artifacts_from_touched_paths(
    runtime_id: str,
    session_id: str,
    workspace: Path,
    touched_paths: set[str],
) -> list[dict[str, Any]]:
    if not touched_paths:
        return []

    diffs: list[dict[str, Any]] = []
    for raw_path in sorted(touched_paths):
        resolved = _resolve_workspace_path(workspace, raw_path)
        if not resolved or not resolved.exists() or not resolved.is_file():
            continue
        rel_path = resolved.relative_to(workspace).as_posix()
        git_status = _git_status_for_path(workspace, rel_path)
        if not git_status:
            continue

        before = ""
        status = "added"
        if not git_status.startswith("??"):
            before = _git_head_content(workspace, rel_path)
            status = "modified"
        after = _read_text_preview(resolved)
        if before == after:
            continue
        diffs.append(
            {
                "file": rel_path,
                "before": before,
                "after": after,
                "additions": _line_count(after),
                "deletions": _line_count(before),
                "status": status,
            }
        )

    if not diffs:
        return []
    return [
        normalize_runtime_artifact(
            {
                "id": f"{runtime_id}:{session_id}:diff:touched-files",
                "type": "file_diff",
                "runtime": runtime_id,
                "title": "Touched File Diff",
                "status": "ready",
                "data": diffs,
            },
            runtime_id=runtime_id,
        )
    ]


def _resolve_workspace_path(workspace: Path, raw_path: str) -> Path | None:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = workspace / path
    try:
        resolved = path.resolve()
        resolved.relative_to(workspace)
        return resolved
    except Exception:
        return None


def _git_status_for_path(workspace: Path, rel_path: str) -> str:
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain", "--", rel_path],
            cwd=str(workspace),
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        return ""
    return output.strip()


def _git_head_content(workspace: Path, rel_path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=str(workspace),
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        return ""


def _read_text_preview(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")[:200_000]
    except UnicodeDecodeError:
        return "[binary file]"
    except Exception:
        return ""


def _line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _diagnostic_artifact(runtime_id: str, session_id: str, title: str, exc: Exception) -> dict[str, Any]:
    safe_title = title.replace(" ", "-").lower()
    return {
        **normalize_runtime_artifact(
            {
                "id": f"{runtime_id}:{session_id}:diagnostic:{safe_title}",
                "type": "diagnostic",
                "runtime": runtime_id,
                "title": title,
                "status": "error",
                "data": {"message": str(exc)},
            },
            runtime_id=runtime_id,
        )
    }


def _event_session_id(properties: dict[str, Any]) -> str | None:
    for key in ("sessionID", "sessionId", "session_id"):
        value = properties.get(key)
        if isinstance(value, str):
            return value
    for key in ("part", "info"):
        value = properties.get(key)
        if isinstance(value, dict) and isinstance(value.get("sessionID"), str):
            return value["sessionID"]
    return None


def _event_error_message(event: dict[str, Any]) -> str:
    error = event.get("error") or event.get("properties")
    if isinstance(error, dict):
        data = error.get("data")
        if isinstance(data, dict) and isinstance(data.get("message"), str):
            return f"OpenCode 调用失败：{data['message']}"
        if isinstance(error.get("message"), str):
            return f"OpenCode 调用失败：{error['message']}"
    return "OpenCode 调用失败"
