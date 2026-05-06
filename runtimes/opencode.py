from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from runtimes.base import AgentRuntime, EventSink, RuntimeRequest, RuntimeResult


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    parts = [
        "你是通过 OpenCode runtime 运行的 coding agent。",
        "请优先用中文回答。除非用户明确要求修改代码，否则先做分析和建议。",
        "以下是当前会话上下文：",
    ]
    for message in messages[-24:]:
        role = message.get("role")
        content = message.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            label = "用户" if role == "user" else "助手"
            parts.append(f"\n{label}：\n{content}")
    return "\n".join(parts)


def _extract_text_from_json_event(data: Any) -> str:
    if not isinstance(data, dict):
        return ""

    for key in ("delta", "text", "content", "message"):
        value = data.get(key)
        if isinstance(value, str):
            return value

    part = data.get("part")
    if isinstance(part, dict):
        for key in ("text", "content"):
            value = part.get(key)
            if isinstance(value, str):
                return value

    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    texts.append(item["text"])
            return "".join(texts)

    return ""


def _safe_text(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...输出已截断"


class OpenCodeRuntime(AgentRuntime):
    id = "opencode"
    label = "OpenCode"
    description = "通过 OpenCode CLI 运行的外部 coding agent runtime。"
    capabilities = {
        "text": True,
        "stream": True,
        "toolEvents": False,
        "toolApproval": False,
        "fileRead": True,
        "fileWrite": True,
        "shell": True,
        "webFetch": True,
        "webSearch": True,
        "subAgent": True,
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
        self.timeout_ms = _env_int("OPENCODE_TIMEOUT_MS", 120000)

    def _binary_path(self) -> str | None:
        return shutil.which(self.binary)

    def available(self) -> bool:
        return bool(self._binary_path())

    def unavailable_reason(self) -> str:
        if not self._binary_path():
            return f"未找到 OpenCode CLI：{self.binary}"
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

    def _supports_skip_permissions_flag(self) -> bool:
        binary = self._binary_path()
        if not binary:
            return False
        try:
            output = subprocess.check_output([binary, "run", "--help"], text=True, stderr=subprocess.STDOUT, timeout=5)
        except Exception:
            return False
        return "--dangerously-skip-permissions" in output

    def _model_arg(self, model_id: str | None) -> str | None:
        configured = os.getenv("OPENCODE_MODEL")
        if configured:
            return configured

        model_map = {
            "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
            "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
            "deepseek-v4-pro-thinking": "deepseek/deepseek-reasoner",
        }
        if model_id in model_map:
            return model_map[model_id]
        if model_id:
            allowed = ", ".join(self.supported_model_ids)
            raise RuntimeError(f"OpenCode runtime 暂不支持模型 {model_id}。请切换到：{allowed}")
        return None

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault(
            "OPENCODE_PERMISSION",
            json.dumps(
                {
                    "*": "allow",
                    "bash": "allow",
                    "read": "allow",
                    "edit": "allow",
                    "glob": "allow",
                    "grep": "allow",
                    "webfetch": "allow",
                    "websearch": "allow",
                    "task": "allow",
                    "skill": "allow",
                    "external_directory": "allow",
                }
            ),
        )
        return env

    def run(self, request: RuntimeRequest, event_sink: EventSink | None = None) -> RuntimeResult:
        binary = self._binary_path()
        if not binary:
            raise RuntimeError(self.unavailable_reason())
        if not self.workspace.exists() or not self.workspace.is_dir():
            raise RuntimeError(f"OpenCode workspace 不存在：{self.workspace}")

        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        model_arg = self._model_arg(request.model_id)
        prompt = _messages_to_prompt(request.messages)

        if event_sink:
            event_sink(
                "message_start",
                {"id": f"assistant-{trace_id}", "model": model_arg or request.model_id, "runtime": self.id, "trace_id": trace_id},
            )

        command = [binary, "run", "--format", "json"]
        if self._supports_skip_permissions_flag():
            command.append("--dangerously-skip-permissions")
        if model_arg:
            command.extend(["--model", model_arg])
        command.append(prompt)

        started = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=str(self.workspace),
            env=self._env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        answer_parts: list[str] = []
        stderr_parts: list[str] = []
        streams = [stream for stream in (process.stdout, process.stderr) if stream]

        try:
            while streams:
                if (time.monotonic() - started) * 1000 > self.timeout_ms:
                    process.kill()
                    raise RuntimeError("OpenCode 执行超时")

                readable, _, _ = select.select(streams, [], [], 0.2)
                if not readable and process.poll() is not None:
                    readable = list(streams)

                for stream in readable:
                    line = stream.readline()
                    if line == "":
                        streams.remove(stream)
                        continue
                    if stream is process.stderr:
                        stderr_parts.append(line)
                        continue

                    text = self._line_to_text(line)
                    if not text:
                        continue
                    answer_parts.append(text)
                    if event_sink:
                        event_sink("text_delta", {"delta": text})

            return_code = process.wait(timeout=1)
        finally:
            if process.poll() is None:
                process.kill()

        answer = "".join(answer_parts).strip()
        stderr_text = _safe_text("".join(stderr_parts).strip())
        if return_code != 0:
            raise RuntimeError(stderr_text or f"OpenCode 执行失败，退出码 {return_code}")
        if not answer and stderr_text:
            answer = stderr_text

        if event_sink:
            event_sink(
                "message_done",
                {
                    "answer": answer,
                    "steps": [],
                    "model": model_arg or request.model_id,
                    "runtime": self.id,
                    "trace_id": trace_id,
                },
            )

        return RuntimeResult(answer=answer, steps=[], trace_id=trace_id, model=model_arg or request.model_id, runtime=self.id)

    def _line_to_text(self, line: str) -> str:
        stripped = line.strip()
        if not stripped:
            return ""
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return line
        if isinstance(data, dict) and data.get("type") == "error":
            error = data.get("error")
            if isinstance(error, dict):
                error_data = error.get("data")
                if isinstance(error_data, dict) and isinstance(error_data.get("message"), str):
                    raise RuntimeError(f"OpenCode 调用失败：{error_data['message']}")
                if isinstance(error.get("message"), str):
                    raise RuntimeError(f"OpenCode 调用失败：{error['message']}")
            raise RuntimeError("OpenCode 调用失败")
        return _extract_text_from_json_event(data)
