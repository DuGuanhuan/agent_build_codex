from __future__ import annotations

import atexit
import json
import logging
import os
import select
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger('agent.runtimes.claude_code')

from runtimes.base import AgentRuntime, EventSink, RuntimeRequest, RuntimeResult
from runtimes.opencode_serve import _file_diff_artifacts_from_touched_paths, _merge_artifacts


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


def _frontend_action(content: str) -> dict[str, Any] | None:
    if not content.startswith('{"__system_action"'):
        return None
    try:
        action = json.loads(content)
    except json.JSONDecodeError:
        return None
    return action if isinstance(action, dict) else None


def _prompt_for_claude_stream(content: str) -> str:
    action = _frontend_action(content)
    if not action or action.get("__system_action") != "answer_user_question":
        return content

    lines = ["用户已回答 Claude Code 的 AskUserQuestion，请基于该回答继续当前任务。"]
    header = action.get("header")
    question = action.get("question")
    label = action.get("label")
    description = action.get("description")
    if isinstance(header, str) and header:
        lines.append(f"问题分组：{header}")
    if isinstance(question, str) and question:
        lines.append(f"问题：{question}")
    if isinstance(label, str) and label:
        lines.append(f"用户选择：{label}")
    if isinstance(description, str) and description:
        lines.append(f"选择说明：{description}")
    answer = action.get("answer")
    if isinstance(answer, str) and answer:
        lines.append(f"用户答复：{answer}")
    return "\n".join(lines)


def _is_answer_user_question_action(content: str) -> bool:
    action = _frontend_action(content)
    return bool(action and action.get("__system_action") == "answer_user_question")


def _anthropic_base_url_from_openai_base(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[: -len("/v1")] + "/anthropic"
    return normalized.rstrip("/") + "/anthropic"


class ClaudeCodeRuntime(AgentRuntime):
    id = "claude-code"
    label = "Claude Code"
    description = "通过 Claude Code headless CLI 运行的原生 coding agent runtime。"
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
        "nativeSession": True,
        "abort": True,
        "resume": True,
        "workspaceOnly": False,
    }
    supported_model_ids = ["deepseek-v4-flash", "deepseek-v4-pro", "mimo-v2.5", "mimo-v2.5-pro"]

    def __init__(self, workspace: Path):
        self.workspace = Path(os.getenv("CLAUDE_CODE_WORKSPACE", str(workspace))).resolve()
        self.binary = os.getenv("CLAUDE_CODE_BIN", "claude")
        self.permission_mode = os.getenv("CLAUDE_CODE_PERMISSION_MODE", "bypassPermissions")
        self.bare = _env_bool("CLAUDE_CODE_BARE", False)
        self._lock = threading.Lock()
        self._running: dict[str, subprocess.Popen[str]] = {}
        self._running_keys: dict[str, str] = {}
        self._session_locks: dict[str, threading.Lock] = {}
        self._touched_paths_by_session: dict[str, set[str]] = {}
        self._session_map: dict[str, str] = {}
        self._session_store_path = Path(
            os.getenv("RUNTIME_SESSION_STORE_PATH", str(self.workspace / ".workbuddy" / "runtime-sessions.json"))
        )
        self._load_session_map()
        atexit.register(self.stop)

    def _binary_path(self) -> str | None:
        return shutil.which(self.binary)

    def available(self) -> bool:
        return bool(self._binary_path())

    def unavailable_reason(self) -> str:
        if not self._binary_path():
            return f"未找到 Claude Code CLI：{self.binary}"
        return ""

    def version(self) -> str | None:
        binary = self._binary_path()
        if not binary:
            return None
        try:
            output = subprocess.check_output([binary, "--version"], text=True, stderr=subprocess.STDOUT, timeout=5)
            return output.strip() or None
        except Exception:
            return None

    def stop(self) -> None:
        """终止所有运行中的子进程"""
        with self._lock:
            processes = list(self._running.values())
            self._running.clear()
            self._running_keys.clear()
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"Process {process.pid} did not terminate gracefully, killing")
                    process.kill()
                    process.wait(timeout=5)

    def abort(self, session_id: str) -> bool:
        """中止特定会话的进程"""
        with self._lock:
            process = self._running.pop(session_id, None)
            self._running_keys.pop(session_id, None)
        if not process or process.poll() is not None:
            return False
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning(f"Process {process.pid} for session {session_id} did not terminate, killing")
            process.kill()
            process.wait(timeout=5)
        return True

    def _session_key(self, local_session_id: str) -> str:
        return f"{self.id}:{self.workspace}:{local_session_id}"

    def _load_session_map(self) -> None:
        try:
            data = json.loads(self._session_store_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        prefix = f"{self.id}:{self.workspace}:"
        for key, value in data.items():
            if key.startswith(prefix) and isinstance(value, str):
                self._session_map[key.removeprefix(prefix)] = value

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

    def _external_session_id(self, local_session_id: str) -> str | None:
        with self._lock:
            return self._session_map.get(local_session_id)

    def _set_external_session_id(self, local_session_id: str, runtime_session_id: str) -> None:
        with self._lock:
            self._session_map[local_session_id] = runtime_session_id
        self._save_session_map()

    def session_ref(self, session_id: str) -> dict[str, Any] | None:
        runtime_session_id = self._external_session_id(session_id)
        if not runtime_session_id:
            return None
        return {
            "local_session_id": session_id,
            "runtime_session_id": runtime_session_id,
            "workspace": str(self.workspace),
        }

    def artifacts(self, session_id: str) -> list[dict[str, Any]]:
        touched_paths = self._touched_paths_by_session.get(session_id, set())
        return _file_diff_artifacts_from_touched_paths(self.id, session_id, self.workspace, touched_paths)

    def _model(self, model_id: str | None) -> dict[str, str]:
        configured = os.getenv("CLAUDE_CODE_MODEL")
        if configured:
            return {"model": configured, "provider": os.getenv("CLAUDE_CODE_PROVIDER", "deepseek")}
        model_map = {
            "deepseek-v4-pro": {"model": "deepseek-v4-pro[1m]", "provider": "deepseek"},
            "deepseek-v4-flash": {"model": "deepseek-v4-flash", "provider": "deepseek"},
            "mimo-v2.5-pro": {"model": "mimo-v2.5-pro", "provider": "xiaomi"},
            "mimo-v2.5": {"model": "mimo-v2.5", "provider": "xiaomi"},
        }
        if model_id in model_map:
            return model_map[model_id]
        if model_id:
            allowed = ", ".join(self.supported_model_ids)
            raise RuntimeError(f"Claude Code runtime 暂不支持模型 {model_id}。请切换到：{allowed}")
        return model_map["deepseek-v4-pro"]

    def _command(self, model_config: dict[str, str], external_session_id: str | None) -> list[str]:
        binary = self._binary_path()
        if not binary:
            raise RuntimeError(self.unavailable_reason())
        model = model_config["model"]
        command = [
            binary,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode",
            self.permission_mode,
            "--model",
            model,
        ]
        if model_config["provider"] in ("deepseek", "xiaomi"):
            command.extend(["--setting-sources", "project,local"])
        if self.bare:
            command.append("--bare")
        if external_session_id:
            command.extend(["--resume", external_session_id])
        return command

    def _process_env(self, model_config: dict[str, str]) -> dict[str, str]:
        env = os.environ.copy()
        provider = model_config["provider"]
        if provider == "deepseek":
            token = env.get("DEEPSEEK_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN")
            if not token:
                raise RuntimeError("请先设置 DEEPSEEK_API_KEY，Claude Code 才能通过 DeepSeek Anthropic API 运行")
            base_url = env.get("DEEPSEEK_ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
            opus_model = env.get("CLAUDE_CODE_DEEPSEEK_OPUS_MODEL", "deepseek-v4-pro[1m]")
            sonnet_model = env.get("CLAUDE_CODE_DEEPSEEK_SONNET_MODEL", "deepseek-v4-pro[1m]")
            haiku_model = env.get("CLAUDE_CODE_DEEPSEEK_HAIKU_MODEL", "deepseek-v4-flash")
            subagent_model = env.get("CLAUDE_CODE_DEEPSEEK_SUBAGENT_MODEL", "deepseek-v4-flash")
        elif provider == "xiaomi":
            token = env.get("MIMO_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN")
            if not token:
                raise RuntimeError("请先设置 MIMO_API_KEY，Claude Code 才能通过小米 MiMo Anthropic API 运行")
            base_url = env.get("MIMO_ANTHROPIC_BASE_URL") or _anthropic_base_url_from_openai_base(
                env.get("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
            )
            opus_model = env.get("CLAUDE_CODE_MIMO_OPUS_MODEL", "mimo-v2.5-pro")
            sonnet_model = env.get("CLAUDE_CODE_MIMO_SONNET_MODEL", model_config["model"])
            haiku_model = env.get("CLAUDE_CODE_MIMO_HAIKU_MODEL", "mimo-v2.5")
            subagent_model = env.get("CLAUDE_CODE_MIMO_SUBAGENT_MODEL", "mimo-v2.5")
        else:
            return env
        env["ANTHROPIC_BASE_URL"] = base_url.rstrip("/")
        env["ANTHROPIC_AUTH_TOKEN"] = token
        env["ANTHROPIC_API_KEY"] = token
        env["ANTHROPIC_MODEL"] = model_config["model"]
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = opus_model
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = sonnet_model
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku_model
        env["CLAUDE_CODE_SUBAGENT_MODEL"] = subagent_model
        env.setdefault("CLAUDE_CODE_EFFORT_LEVEL", "max")
        env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
        env.setdefault("CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK", "1")
        env.setdefault("API_TIMEOUT_MS", "600000")
        return env

    def _start_process(self, command: list[str], env: dict[str, str]) -> subprocess.Popen[str]:
        return subprocess.Popen(
            command,
            cwd=str(self.workspace),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def _process_key(self, model_config: dict[str, str]) -> str:
        return json.dumps(
            {
                "model": model_config["model"],
                "provider": model_config["provider"],
                "permission_mode": self.permission_mode,
                "bare": self.bare,
            },
            sort_keys=True,
        )

    def _run_lock(self, local_session_id: str) -> threading.Lock:
        with self._lock:
            lock = self._session_locks.get(local_session_id)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[local_session_id] = lock
            return lock

    def _process_for_session(
        self,
        local_session_id: str,
        model_config: dict[str, str],
        external_session_id: str | None,
    ) -> subprocess.Popen[str]:
        process_key = self._process_key(model_config)
        with self._lock:
            process = self._running.get(local_session_id)
            if (
                process
                and process.poll() is None
                and self._running_keys.get(local_session_id) == process_key
            ):
                return process
            if process and process.poll() is None:
                process.terminate()

            command = self._command(model_config, external_session_id)
            process = self._start_process(command, self._process_env(model_config))
            self._running[local_session_id] = process
            self._running_keys[local_session_id] = process_key
            return process

    def _drop_process(self, local_session_id: str, process: subprocess.Popen[str] | None = None) -> None:
        with self._lock:
            current = self._running.get(local_session_id)
            if process is None or current is process:
                self._running.pop(local_session_id, None)
                self._running_keys.pop(local_session_id, None)

    def _send_stream_user_message(self, process: subprocess.Popen[str], prompt: str) -> None:
        if process.stdin is None:
            raise RuntimeError("Claude Code stdin 不可用，无法继续当前原生进程")
        payload = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": _prompt_for_claude_stream(prompt)}],
            },
        }
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def _drain_pending_stdout(self, process: subprocess.Popen[str], max_seconds: float = 0.3) -> None:
        stdout = process.stdout
        if stdout is None or not self._stdout_supports_select(stdout):
            return
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline and process.poll() is None:
            ready, _, _ = select.select([stdout], [], [], 0)
            if not ready:
                return
            if not stdout.readline():
                return

    def run(self, request: RuntimeRequest, event_sink: EventSink | None = None) -> RuntimeResult:
        if not self.available():
            raise RuntimeError(self.unavailable_reason())
        if not self.workspace.exists() or not self.workspace.is_dir():
            raise RuntimeError(f"Claude Code workspace 不存在：{self.workspace}")

        prompt = _latest_user_text(request.messages)
        if not prompt:
            raise RuntimeError("Claude Code runtime 没有收到有效用户消息")

        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        local_session_id = request.session_id or trace_id
        external_session_id = self._external_session_id(local_session_id)
        model_config = self._model(request.model_id)
        model = model_config["model"]

        run_lock = self._run_lock(local_session_id)
        with run_lock:
            if event_sink:
                event_sink(
                    "message_start",
                    {
                        "id": f"assistant-{trace_id}",
                        "model": model,
                        "runtime": self.id,
                        "trace_id": trace_id,
                        "session_ref": self.session_ref(local_session_id),
                    },
                )

            state = _ClaudeCodeEventState(self.id, trace_id, model, local_session_id, self.workspace, event_sink)
            process = self._process_for_session(local_session_id, model_config, external_session_id)
            if _is_answer_user_question_action(prompt):
                self._drain_pending_stdout(process)
            self._send_stream_user_message(process, prompt)
            self._consume_json_lines(process, state)
            returncode = process.poll()

            if state.external_session_id:
                self._set_external_session_id(local_session_id, state.external_session_id)

            if state.fatal_error and process.poll() is None:
                process.terminate()
                try:
                    returncode = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    returncode = process.poll()

            if returncode is not None:
                self._drop_process(local_session_id, process)

            if returncode not in (None, 0):
                raise RuntimeError(state.error_message(returncode))

            with self._lock:
                self._touched_paths_by_session.setdefault(local_session_id, set()).update(state.touched_paths)
            artifacts = _merge_artifacts(
                state.artifacts,
                self.artifacts(local_session_id),
            )

            if event_sink:
                for artifact in artifacts:
                    event_sink("artifact_updated", {"artifact": artifact})
                    if artifact["type"] == "file_diff":
                        event_sink("session_diff", {"artifact": artifact, "session_ref": self.session_ref(local_session_id)})
                event_sink(
                    "session_status",
                    {
                        "runtime": self.id,
                        "status": "idle",
                        "local_session_id": local_session_id,
                        "runtime_session_id": state.external_session_id,
                    },
                )
                event_sink(
                    "message_done",
                    {
                        "answer": state.answer,
                        "steps": state.steps,
                        "artifacts": artifacts,
                        "model": state.model,
                        "runtime": self.id,
                        "trace_id": trace_id,
                        "session_ref": self.session_ref(local_session_id),
                    },
                )

            return RuntimeResult(
                answer=state.answer,
                steps=state.steps,
                trace_id=trace_id,
                model=state.model,
                runtime=self.id,
                artifacts=artifacts,
            )

    def _consume_json_lines(self, process: subprocess.Popen[str], state: "_ClaudeCodeEventState") -> None:
        if process.stdout is None:
            return
        if not self._stdout_supports_select(process.stdout):
            for raw_line in process.stdout:
                if self._handle_stdout_line(raw_line, process, state):
                    return
            return

        while True:
            if state.should_return:
                return
            if process.poll() is not None:
                return
            ready, _, _ = select.select([process.stdout], [], [], 0.2)
            if not ready:
                continue
            raw_line = process.stdout.readline()
            if not raw_line:
                if process.poll() is not None:
                    return
                continue
            if self._handle_stdout_line(raw_line, process, state):
                return

    def _stdout_supports_select(self, stdout: Any) -> bool:
        fileno = getattr(stdout, "fileno", None)
        if not callable(fileno):
            return False
        try:
            fileno()
            return True
        except Exception:
            return False

    def _handle_stdout_line(
        self,
        raw_line: str,
        process: subprocess.Popen[str],
        state: "_ClaudeCodeEventState",
    ) -> bool:
        line = raw_line.strip()
        if not line:
            return False
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            state.raw_errors.append(line)
            return False
        if isinstance(event, dict):
            state.handle_event(event)
            if state.fatal_error and process.poll() is None:
                process.terminate()
                return True
        return state.should_return


class _ClaudeCodeEventState:
    def __init__(
        self,
        runtime_id: str,
        trace_id: str,
        model: str,
        local_session_id: str,
        workspace: Path,
        event_sink: EventSink | None,
    ):
        self.runtime_id = runtime_id
        self.trace_id = trace_id
        self.model = model
        self.local_session_id = local_session_id
        self.workspace = workspace
        self.event_sink = event_sink
        self.external_session_id: str | None = None
        self.answer_parts: list[str] = []
        self.last_assistant_text = ""
        self.steps_by_id: dict[str, dict[str, Any]] = {}
        self.stream_tool_by_index: dict[int, str] = {}
        self.stream_tool_json_by_id: dict[str, str] = {}
        self.artifacts_by_id: dict[str, dict[str, Any]] = {}
        self.touched_paths: set[str] = set()
        self.raw_errors: list[str] = []
        self.api_errors: list[str] = []
        self.fatal_error = False
        self.done = False
        self.awaiting_user_question_step_id: str | None = None

    @property
    def answer(self) -> str:
        return "".join(self.answer_parts)

    @property
    def steps(self) -> list[dict[str, Any]]:
        return list(self.steps_by_id.values())

    @property
    def artifacts(self) -> list[dict[str, Any]]:
        return list(self.artifacts_by_id.values())

    @property
    def should_return(self) -> bool:
        return self.done or self.awaiting_user_question_step_id is not None

    def handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "system":
            self._handle_system_event(event)
            return
        if event_type == "stream_event":
            self._handle_stream_event(event.get("event"))
            return
        if event_type == "assistant":
            self._handle_assistant_message(event.get("message"))
            return
        if event_type == "user":
            self._handle_user_message(event.get("message"))
            return
        if event_type == "result":
            result = event.get("result")
            if isinstance(result, str) and result and not self.answer:
                self._emit_full_text(result)
            self.done = True
            return
        if event_type == "error":
            self.api_errors.append(_stringify(event.get("error") or event))
            return
        delta = event.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("text"), str):
            self._emit_delta(delta["text"])

    def _handle_stream_event(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        if event_type == "content_block_start":
            index = event.get("index")
            content_block = event.get("content_block")
            if isinstance(index, int) and isinstance(content_block, dict) and content_block.get("type") == "tool_use":
                step_id = self._tool_start(content_block)
                self.stream_tool_by_index[index] = step_id
                self.stream_tool_json_by_id[step_id] = ""
            return
        if event_type == "content_block_delta":
            delta = event.get("delta")
            if not isinstance(delta, dict):
                return
            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                self._emit_delta(delta["text"])
                return
            if delta.get("type") == "input_json_delta":
                index = event.get("index")
                partial_json = delta.get("partial_json")
                if isinstance(index, int) and isinstance(partial_json, str):
                    self._append_tool_json_delta(index, partial_json)
                return
        if event_type == "content_block_stop":
            index = event.get("index")
            if isinstance(index, int):
                step_id = self.stream_tool_by_index.pop(index, None)
                if step_id:
                    self._finalize_tool_args(step_id, final=True)
            return

    def _handle_system_event(self, event: dict[str, Any]) -> None:
        subtype = event.get("subtype")
        if subtype == "init":
            session_id = event.get("session_id")
            if isinstance(session_id, str):
                self.external_session_id = session_id
            model = event.get("model")
            if isinstance(model, str):
                self.model = model
            if self.event_sink:
                self.event_sink(
                    "session_status",
                    {
                        "runtime": self.runtime_id,
                        "status": "busy",
                        "local_session_id": self.local_session_id,
                        "runtime_session_id": self.external_session_id,
                    },
                )
            return
        if subtype == "api_retry":
            status = event.get("error_status")
            error = event.get("error")
            message = f"Claude Code API retry"
            if status:
                message += f" HTTP {status}"
            if error:
                message += f": {error}"
            self.api_errors.append(message)
            if status in (401, 403):
                self.fatal_error = True

    def _handle_assistant_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        content = message.get("content")
        self._handle_content_items(content)
        text = _content_text(content)
        if text:
            self._emit_full_text(text)

    def _handle_user_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        self._handle_content_items(message.get("content"))

    def _handle_content_items(self, content: Any) -> None:
        if not isinstance(content, list):
            return
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "tool_use":
                self._tool_start(item)
            elif item_type == "tool_result":
                self._tool_result(item)

    def _emit_full_text(self, text: str) -> None:
        if text == self.last_assistant_text:
            return
        if text.startswith(self.last_assistant_text):
            delta = text[len(self.last_assistant_text) :]
        else:
            delta = text
        self.last_assistant_text = text
        self._emit_delta(delta)

    def _emit_delta(self, delta: str) -> None:
        if not delta:
            return
        self.answer_parts.append(delta)
        self.last_assistant_text = self.answer
        if self.event_sink:
            self.event_sink("text_delta", {"delta": delta})

    def _tool_start(self, item: dict[str, Any]) -> str:
        step_id = str(item.get("id") or f"tool-{len(self.steps_by_id) + 1}")
        tool_name = str(item.get("name") or "claude_tool")
        args = item.get("input") if isinstance(item.get("input"), dict) else {}
        self.touched_paths.update(_extract_touched_paths(tool_name, args))
        if step_id in self.steps_by_id:
            step = self.steps_by_id[step_id]
            if args:
                step["args"] = args
                self._maybe_pause_for_user_question(step_id)
                if self.event_sink:
                    self.event_sink("tool_start", {"step_id": step_id, **step})
            return step_id
        step = {
            "id": step_id,
            "type": "tool",
            "status": "running",
            "tool": tool_name,
            "args": args,
            "result": None,
            "error": None,
            "permission": "claude-code-native",
            "started_at": None,
            "ended_at": None,
            "duration_ms": None,
        }
        self.steps_by_id[step_id] = step
        self._maybe_pause_for_user_question(step_id)
        if self.event_sink:
            self.event_sink("tool_start", {"step_id": step_id, **step})
        return step_id

    def _append_tool_json_delta(self, index: int, partial_json: str) -> None:
        step_id = self.stream_tool_by_index.get(index)
        if not step_id:
            return
        self.stream_tool_json_by_id[step_id] = self.stream_tool_json_by_id.get(step_id, "") + partial_json
        self._finalize_tool_args(step_id, emit=True)

    def _finalize_tool_args(self, step_id: str, emit: bool = False, final: bool = False) -> None:
        step = self.steps_by_id.get(step_id)
        raw_json = self.stream_tool_json_by_id.get(step_id)
        if not step or not raw_json:
            return
        try:
            args = json.loads(raw_json)
        except json.JSONDecodeError:
            return
        if not isinstance(args, dict):
            return
        step["args"] = args
        self.touched_paths.update(_extract_touched_paths(str(step.get("tool") or ""), args))
        paused = final and self._maybe_pause_for_user_question(step_id)
        if (emit or paused) and self.event_sink:
            self.event_sink("tool_start", {"step_id": step_id, **step})

    def _maybe_pause_for_user_question(self, step_id: str) -> bool:
        step = self.steps_by_id.get(step_id)
        if not step or str(step.get("tool") or "").lower() != "askuserquestion":
            return False
        args = step.get("args")
        if not isinstance(args, dict) or not args.get("questions"):
            return False
        step.update({"status": "awaiting_approval", "permission": "user-input"})
        self.awaiting_user_question_step_id = step_id
        return True

    def _tool_result(self, item: dict[str, Any]) -> None:
        step_id = str(item.get("tool_use_id") or item.get("id") or f"tool-{len(self.steps_by_id) + 1}")
        step = self.steps_by_id.get(step_id)
        if not step:
            step = {
                "id": step_id,
                "type": "tool",
                "status": "running",
                "tool": "claude_tool",
                "args": {},
                "result": None,
                "error": None,
                "permission": "claude-code-native",
                "started_at": None,
                "ended_at": None,
                "duration_ms": None,
            }
            self.steps_by_id[step_id] = step
        result = {"content": item.get("content")}
        if item.get("is_error"):
            error = _content_text(item.get("content")) or _stringify(item.get("content") or "Claude Code 工具调用失败")
            step.update({"type": "tool_error", "status": "error", "result": result, "error": error})
            if self.event_sink:
                self.event_sink("tool_error", {"step_id": step_id, **step})
            return
        step.update({"status": "success", "result": result, "error": None})
        if self.event_sink:
            self.event_sink("tool_result", {"step_id": step_id, **step})

    def error_message(self, returncode: int) -> str:
        details = self.api_errors[-1:] or self.raw_errors[-3:]
        suffix = f"：{details[0]}" if details else ""
        return f"Claude Code 调用失败，进程退出码 {returncode}{suffix}"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _extract_touched_paths(tool_name: str, args: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    path_keys = {"file", "path", "filepath", "file_path", "target", "filename", "destination"}
    for key, value in args.items():
        if key.lower() in path_keys and isinstance(value, str):
            paths.add(value)
    command = args.get("command")
    if tool_name.lower() == "bash" and isinstance(command, str):
        try:
            import shlex

            parts = shlex.split(command)
        except ValueError:
            parts = []
        if parts:
            if parts[0] == "touch":
                paths.update(part for part in parts[1:] if not part.startswith("-"))
            elif parts[0] in {"mv", "cp"} and len(parts) >= 3:
                paths.add(parts[-1])
    return paths
