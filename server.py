import json
import os
import time
import uuid
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tools.registry import (
    TOOLS,
    get_tool,
    get_tools_schema,
    execute_tool,
    ToolError,
    ToolPermission,
)

from tools.registry import _safe_calculate as safe_calculate


def run_tool(tool_name, args):
    return execute_tool(tool_name, args)


LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
DEFAULT_MODEL_ID = os.getenv("DEFAULT_MODEL_ID", "zhipu-glm-4.7-flash")
DEFAULT_CONTEXT_WINDOW_TOKENS = int(os.getenv("DEFAULT_CONTEXT_WINDOW_TOKENS", "128000"))


def env_int(name, default):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


MODEL_OPTIONS = [
    {
        "id": "zhipu-glm-4.7-flash",
        "label": "智谱 GLM-4.7-Flash",
        "provider": "zhipu",
        "model": "glm-4.7-flash",
        "base_url": os.getenv("ZHIPU_BASE_URL") or os.getenv("ZAI_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4",
        "api_key_envs": ["ZAI_API_KEY", "ZHIPU_API_KEY"],
        "thinking": "disabled",
        "context_window_tokens": env_int("ZHIPU_CONTEXT_WINDOW_TOKENS", 200000),
        "max_output_tokens": 128000,
        "description": "免费/快速，适合日常聊天和这个轻量 Agent demo。",
    },
    {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "api_key_envs": ["DEEPSEEK_API_KEY"],
        "thinking": "disabled",
        "context_window_tokens": env_int("DEEPSEEK_CONTEXT_WINDOW_TOKENS", 1000000),
        "max_output_tokens": 384000,
        "description": "低成本、低延迟，推荐作为 DeepSeek 默认选项。",
    },
    {
        "id": "wanqing-kimi-k2.5",
        "label": "万擎 Kimi K2.5",
        "provider": "wanqing",
        "model": os.getenv("WQ_MODEL", "ep-cvhcjv-1776239525862887187"),
        "base_url": os.getenv("WQ_BASE_URL")
        or os.getenv("WANQING_BASE_URL")
        or "http://wanqing.internal/api/gateway/v1/endpoints",
        "api_key_envs": ["WQ_API_KEY"],
        "context_window_tokens": env_int("WQ_CONTEXT_WINDOW_TOKENS", DEFAULT_CONTEXT_WINDOW_TOKENS),
        "max_output_tokens": env_int("WQ_MAX_OUTPUT_TOKENS", LLM_MAX_TOKENS),
        "description": "公司内部万擎部署的 Kimi K2.5 推理接入点。",
    },
    {
        "id": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "api_key_envs": ["DEEPSEEK_API_KEY"],
        "thinking": "disabled",
        "context_window_tokens": env_int("DEEPSEEK_CONTEXT_WINDOW_TOKENS", 1000000),
        "max_output_tokens": 384000,
        "description": "质量更高，适合复杂一点的问答和 Agent 规划。",
    },
    {
        "id": "deepseek-v4-pro-thinking",
        "label": "DeepSeek V4 Pro Thinking",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "api_key_envs": ["DEEPSEEK_API_KEY"],
        "thinking": "enabled",
        "reasoning_effort": "high",
        "context_window_tokens": env_int("DEEPSEEK_CONTEXT_WINDOW_TOKENS", 1000000),
        "max_output_tokens": 384000,
        "description": "开启思考模式，适合更难的问题；会更慢、更贵。",
    },
]
MODEL_OPTIONS_BY_ID = {option["id"]: option for option in MODEL_OPTIONS}

ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"


def build_agent_system_prompt() -> str:
    tools_schema = get_tools_schema()
    tools_list = []
    for tool in tools_schema:
        params = tool["parameters"].get("properties", {})
        params_desc = []
        for pname, pinfo in params.items():
            required = tool["parameters"].get("required", [])
            required_mark = "必填" if pname in required else "可选"
            default = f'，默认: {pinfo["default"]}' if "default" in pinfo else ""
            params_desc.append(f"  - {pname}: {pinfo.get('description', '')} ({required_mark}{default})")
        tools_list.append(f"- {tool['name']}: {tool['description']}\n" + "\n".join(params_desc))

    tools_section = "\n".join(tools_list)

    return f"""你是一个轻量级手写 Agent。你只能输出 JSON，不要输出任何其他文字。

## 可用工具
{tools_section}

## 输出格式（严格遵守）
你的每次回复必须且只能是下面两种 JSON 之一，不允许输出其他任何内容：

调用工具时输出：
{{"action":"tool","tool":"工具名","args":{{...}}}}

给出最终答案时输出：
{{"action":"final","answer":"你的中文回答"}}

## 示例

用户：现在几点？
你：{{"action":"tool","tool":"current_time","args":{{"timezone":"Asia/Shanghai"}}}}

用户：帮我算 12 * 7
你：{{"action":"tool","tool":"calculator","args":{{"expression":"12 * 7"}}}}

用户：你好
你：{{"action":"final","answer":"你好！有什么可以帮你的吗？"}}

## 要求
- 输出必须是合法 JSON，不要加 markdown 代码块、不要加解释文字。
- 优先用中文回答。
- 不要编造工具结果，必须调用工具获取。
- 收到工具结果后，用 final 格式回复用户。
"""

FINAL_ANSWER_SYSTEM_PROMPT = """你是一个轻量级手写 Agent。请直接回答用户的问题。

## 要求
- 优先用中文回答。
- 不要输出 JSON。
- 不要提到内部协议、草稿答案或工具调用格式。
- 如果有工具结果，必须基于工具结果回答。
"""

SUMMARY_SYSTEM_PROMPT = """你负责维护一个会话摘要，用于长对话的后续上下文压缩。

## 要求
- 用中文输出。
- 保留用户目标、重要事实、偏好、关键决策、待办、已完成事项、约束条件。
- 如果有旧摘要，请合并旧摘要和新增消息，不要丢失仍然重要的信息。
- 不要输出 JSON，不要写寒暄。
- 控制在 800 字以内，结构清晰。
"""


def first_env_value(names):
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def get_model_config(model_id=None):
    requested_id = model_id or DEFAULT_MODEL_ID
    config = MODEL_OPTIONS_BY_ID.get(requested_id)
    if not config:
        allowed = ", ".join(option["id"] for option in MODEL_OPTIONS)
        raise ValueError(f"未知模型：{requested_id}。可用模型：{allowed}")
    return config


def public_model_options():
    default_id = get_model_config()["id"]
    options = []
    for option in MODEL_OPTIONS:
        context_window_tokens = option.get("context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS)
        reserved_output_tokens = get_reserved_output_tokens(option)
        options.append(
            {
                "id": option["id"],
                "label": option["label"],
                "provider": option["provider"],
                "model": option["model"],
                "thinking": option.get("thinking", "disabled"),
                "description": option["description"],
                "available": bool(first_env_value(option["api_key_envs"])),
                "default": option["id"] == default_id,
                "context_window_tokens": context_window_tokens,
                "reserved_output_tokens": reserved_output_tokens,
                "available_input_tokens": max(1, context_window_tokens - reserved_output_tokens),
            }
        )
    return options


def public_tool_options():
    return get_tools_schema()


def get_reserved_output_tokens(model_config):
    return min(LLM_MAX_TOKENS, int(model_config.get("max_output_tokens", LLM_MAX_TOKENS)))


def build_llm_payload(messages, model_config, temperature=0.2, stream=False):
    payload = {
        "model": model_config["model"],
        "messages": messages,
        "max_tokens": LLM_MAX_TOKENS,
    }
    thinking = model_config.get("thinking")
    if thinking:
        payload["thinking"] = {"type": thinking}
    if model_config.get("reasoning_effort"):
        payload["reasoning_effort"] = model_config["reasoning_effort"]
    if thinking != "enabled":
        payload["temperature"] = temperature
    if stream:
        payload["stream"] = True
    return payload


def llm_chat(messages, model_config, temperature=0.2):
    api_key = first_env_value(model_config["api_key_envs"])
    if not api_key:
        envs = " 或 ".join(model_config["api_key_envs"])
        raise RuntimeError(f"请先设置 {envs} 环境变量")

    url = model_config["base_url"].rstrip("/") + "/chat/completions"
    payload = build_llm_payload(messages, model_config, temperature=temperature)
    request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=request_data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            message = data["choices"][0]["message"]
            return message.get("content", "")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"LLM HTTP {exc.code}: {body}")
            if exc.code in (429, 500, 502, 503):
                time.sleep(2 * (attempt + 1))
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM 请求失败：{exc.reason}") from exc

    raise last_error


def llm_chat_stream(messages, model_config, on_delta, temperature=0.2):
    api_key = first_env_value(model_config["api_key_envs"])
    if not api_key:
        envs = " 或 ".join(model_config["api_key_envs"])
        raise RuntimeError(f"请先设置 {envs} 环境变量")

    url = model_config["base_url"].rstrip("/") + "/chat/completions"
    payload = build_llm_payload(messages, model_config, temperature=temperature, stream=True)
    request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    answer_parts = []
    last_error = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=request_data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith(":") or not line.startswith("data:"):
                        continue

                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        return "".join(answer_parts)

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        answer_parts.append(content)
                        on_delta(content)
            return "".join(answer_parts)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"LLM HTTP {exc.code}: {body}")
            if exc.code in (429, 500, 502, 503):
                time.sleep(2 * (attempt + 1))
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM 请求失败：{exc.reason}") from exc

    raise last_error


KNOWN_TOOLS = set(TOOLS.keys())


def now_ms():
    return int(time.time() * 1000)


def make_trace_id():
    return f"trace_{uuid.uuid4().hex[:12]}"


def make_step_id(index):
    return f"step-{index}"


def emit_agent_event(event_sink, event, payload):
    if event_sink:
        event_sink(event, payload)


def parse_agent_json(content):
    text = content.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    # Try standard JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: detect tool name on first line + optional JSON args
    first_line = text.split("\n", 1)[0].strip().rstrip(":")
    if first_line in KNOWN_TOOLS:
        rest = text.split("\n", 1)[1].strip() if "\n" in text else "{}"
        try:
            args = json.loads(rest)
        except json.JSONDecodeError:
            args = {}
        return {"action": "tool", "tool": first_line, "args": args}
    return {"action": "final", "answer": content}


def execute_tool_step(step_index, tool_name, args):
    started_at = now_ms()
    tool = get_tool(tool_name)
    step = {
        "id": make_step_id(step_index),
        "type": "tool",
        "status": "running",
        "tool": tool_name,
        "args": args,
        "result": None,
        "error": None,
        "permission": tool.permission if tool else None,
        "started_at": started_at,
        "ended_at": None,
        "duration_ms": None,
    }

    try:
        result = execute_tool(tool_name, args)
        step["status"] = "success"
        step["result"] = result
        return step, result
    except ToolError as exc:
        error_message = str(exc)
        result = {"error": error_message}
        step["type"] = "tool_error"
        step["status"] = "error"
        step["result"] = result
        step["error"] = error_message
        return step, result
    finally:
        ended_at = now_ms()
        step["ended_at"] = ended_at
        step["duration_ms"] = max(0, ended_at - started_at)


SUMMARY_CONTEXT_PREFIX = "以下是此前会话摘要，用于延续上下文："


def clean_chat_messages(user_messages, max_messages=None):
    clean_messages = []
    for message in user_messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            clean_messages.append({"role": role, "content": content})

    if max_messages is None:
        return clean_messages

    if len(clean_messages) <= max_messages:
        return clean_messages

    first_message = clean_messages[0]
    if first_message["role"] == "user" and first_message["content"].startswith(SUMMARY_CONTEXT_PREFIX):
        return [first_message] + clean_messages[-(max_messages - 1) :]

    return clean_messages[-max_messages:]


def clean_summary_messages(user_messages):
    clean_messages = []
    for message in user_messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            clean_messages.append({"role": role, "content": content})
    return clean_messages


def estimate_text_tokens(text):
    if not text:
        return 0

    cjk_chars = 0
    other_chars = 0
    for char in str(text):
        code = ord(char)
        if (
            0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0x3040 <= code <= 0x30FF
            or 0xAC00 <= code <= 0xD7AF
        ):
            cjk_chars += 1
        else:
            other_chars += 1

    return max(1, int(cjk_chars * 0.6 + other_chars * 0.25 + 0.999))


def estimate_messages_tokens(messages):
    tokens = 3
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role not in ("system", "user", "assistant") or not isinstance(content, str):
            continue
        tokens += 4
        tokens += estimate_text_tokens(role)
        tokens += estimate_text_tokens(content)
    return tokens


def build_agent_input_messages(user_messages):
    messages = [{"role": "system", "content": build_agent_system_prompt()}]
    messages.extend(clean_chat_messages(user_messages))
    return messages


def estimate_context_usage(user_messages, model_id=None):
    model_config = get_model_config(model_id)
    context_window_tokens = int(model_config.get("context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS))
    reserved_output_tokens = get_reserved_output_tokens(model_config)
    available_input_tokens = max(1, context_window_tokens - reserved_output_tokens)
    input_tokens = estimate_messages_tokens(build_agent_input_messages(user_messages))
    ratio = min(1, input_tokens / available_input_tokens)
    return {
        "model": model_config["id"],
        "estimator": "approximate",
        "input_tokens": input_tokens,
        "context_window_tokens": context_window_tokens,
        "reserved_output_tokens": reserved_output_tokens,
        "available_input_tokens": available_input_tokens,
        "ratio": ratio,
    }


def build_summary_messages(messages, previous_summary=""):
    context_parts = []
    if previous_summary:
        context_parts.append("旧摘要：")
        context_parts.append(str(previous_summary))
    context_parts.append("需要纳入摘要的新增消息：")
    context_parts.append(json.dumps(clean_summary_messages(messages), ensure_ascii=False))
    context_parts.append("请输出更新后的会话摘要。")

    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(context_parts)},
    ]


def summarize_conversation(messages, model_id=None, previous_summary=""):
    model_config = get_model_config(model_id)
    summary_messages = build_summary_messages(messages, previous_summary)
    summary = llm_chat(summary_messages, model_config, temperature=0.1).strip()
    return {"summary": summary, "model": model_config["id"]}


def build_final_answer_messages(user_messages, steps, draft_answer):
    messages = [{"role": "system", "content": FINAL_ANSWER_SYSTEM_PROMPT}]
    messages.extend(clean_chat_messages(user_messages))

    context_parts = []
    if steps:
        context_parts.append("工具调用结果：")
        context_parts.append(json.dumps(steps, ensure_ascii=False))
    if draft_answer:
        context_parts.append("内部草稿答案：")
        context_parts.append(str(draft_answer))
    context_parts.append("请基于以上对话和工具结果，直接输出面向用户的最终回答。")

    messages.append({"role": "user", "content": "\n".join(context_parts)})
    return messages


def stream_final_answer(user_messages, steps, draft_answer, model_config, event_sink):
    if not event_sink:
        return draft_answer

    final_messages = build_final_answer_messages(user_messages, steps, draft_answer)

    def on_delta(delta):
        emit_agent_event(event_sink, "text_delta", {"delta": delta})

    streamed_answer = llm_chat_stream(final_messages, model_config, on_delta)
    return streamed_answer or draft_answer


def run_agent(user_messages, model_id=None, event_sink=None):
    model_config = get_model_config(model_id)
    trace_id = make_trace_id()
    actual_model_id = model_config["id"]
    emit_agent_event(
        event_sink,
        "message_start",
        {"id": f"assistant-{trace_id}", "model": actual_model_id, "trace_id": trace_id},
    )

    messages = build_agent_input_messages(user_messages)
    steps = []
    
    # Handle frontend tool approval/rejection injection
    pre_approved_tool = None
    pre_rejected_tool = None
    
    if len(messages) >= 2 and messages[-1].get("role") == "user":
        last_content = messages[-1].get("content", "")
        if isinstance(last_content, str) and last_content.strip().startswith('{"__system_action"'):
            try:
                system_action = json.loads(last_content)
                action_type = system_action.get("__system_action")
                if action_type == "approve_tool":
                    # pop the system action
                    messages.pop()
                    # The previous message should be the assistant's tool call
                    last_assistant_msg = messages[-1].get("content", "")
                    decision = parse_agent_json(last_assistant_msg)
                    if decision.get("action") == "tool":
                        decision["__is_approved"] = True
                        pre_approved_tool = decision
                elif action_type == "reject_tool":
                    messages.pop()
                    last_assistant_msg = messages[-1].get("content", "")
                    decision = parse_agent_json(last_assistant_msg)
                    if decision.get("action") == "tool":
                        pre_rejected_tool = decision
                        reject_reason = system_action.get("reason", "无")
            except json.JSONDecodeError:
                pass

    for _ in range(4):
        if pre_approved_tool:
            decision = pre_approved_tool
            raw = messages[-1].get("content", "") # keeping the raw tool call
            pre_approved_tool = None
        elif pre_rejected_tool:
            decision = pre_rejected_tool
            raw = messages[-1].get("content", "")
            pre_rejected_tool = None
            
            tool_name = decision.get("tool")
            args = decision.get("args") or {}
            step_index = len(steps) + 1
            step_id = make_step_id(step_index)
            tool = get_tool(tool_name)
            
            # Inject rejection
            error_message = f"用户拒绝执行该工具。理由：{reject_reason}"
            emit_agent_event(
                event_sink,
                "tool_start",
                {
                    "step_id": step_id,
                    "id": step_id,
                    "type": "tool",
                    "status": "error",
                    "tool": tool_name,
                    "args": args,
                    "permission": tool.permission if tool else None,
                },
            )
            step = {
                "id": step_id,
                "type": "tool_error",
                "status": "error",
                "tool": tool_name,
                "args": args,
                "permission": tool.permission if tool else None,
                "started_at": now_ms(),
                "ended_at": now_ms(),
                "duration_ms": 0,
                "error": error_message,
                "result": {"error": error_message}
            }
            steps.append(step)
            emit_agent_event(event_sink, "tool_error", {"step_id": step_id, **step})
            messages.append(
                {
                    "role": "user",
                    "content": "工具返回结果：\n"
                    + json.dumps({"error": error_message}, ensure_ascii=False)
                    + "\n请基于工具结果继续，输出 final JSON 或新的 tool JSON。",
                }
            )
            continue
        else:
            raw = llm_chat(messages, model_config)
            decision = parse_agent_json(raw)

        if decision.get("action") == "tool":
            tool_name = decision.get("tool")
            args = decision.get("args") or {}
            step_index = len(steps) + 1
            step_id = make_step_id(step_index)
            tool = get_tool(tool_name)
            
            is_approved = decision.get("__is_approved", False)
            if tool and ToolPermission.needs_confirmation(tool.permission) and not is_approved:
                step = {
                    "id": step_id,
                    "type": "tool",
                    "status": "awaiting_approval",
                    "tool": tool_name,
                    "args": args,
                    "permission": tool.permission,
                    "started_at": now_ms(),
                }
                steps.append(step)
                
                emit_agent_event(
                    event_sink,
                    "tool_awaiting_approval",
                    {"step_id": step_id, **step},
                )
                emit_agent_event(
                    event_sink,
                    "message_done",
                    {"answer": raw, "steps": steps, "model": actual_model_id, "trace_id": trace_id},
                )
                return {"answer": raw, "steps": steps, "trace_id": trace_id}

            emit_agent_event(
                event_sink,
                "tool_start",
                {
                    "step_id": step_id,
                    "id": step_id,
                    "type": "tool",
                    "status": "running",
                    "tool": tool_name,
                    "args": args,
                    "permission": tool.permission if tool else None,
                },
            )
            step, result = execute_tool_step(step_index, tool_name, args)
            steps.append(step)
            emit_agent_event(
                event_sink,
                "tool_error" if step["status"] == "error" else "tool_result",
                {"step_id": step["id"], **step},
            )

            if not is_approved:
                messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": "工具返回结果："
                    + json.dumps(result, ensure_ascii=False)
                    + "\n请基于工具结果继续，输出 final JSON。",
                }
            )
            continue

        draft_answer = decision.get("answer") or raw
        answer = stream_final_answer(user_messages, steps, draft_answer, model_config, event_sink)
        emit_agent_event(
            event_sink,
            "message_done",
            {"answer": answer, "steps": steps, "model": actual_model_id, "trace_id": trace_id},
        )
        return {"answer": answer, "steps": steps, "trace_id": trace_id}

    fallback = llm_chat(
        messages
        + [
            {
                "role": "user",
                "content": "请停止调用工具，直接给出当前最好的最终答案。",
            }
        ],
        model_config,
    )
    decision = parse_agent_json(fallback)
    draft_answer = decision.get("answer") or fallback
    answer = stream_final_answer(user_messages, steps, draft_answer, model_config, event_sink)
    emit_agent_event(
        event_sink,
        "message_done",
        {"answer": answer, "steps": steps, "model": actual_model_id, "trace_id": trace_id},
    )
    return {"answer": answer, "steps": steps, "trace_id": trace_id}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/models":
            self.send_json(200, {"models": public_model_options(), "default": get_model_config()["id"]})
            return

        if path == "/api/tools":
            self.send_json(200, {"tools": public_tool_options()})
            return

        if path == "/":
            path = "/index.html"
        file_path = (PUBLIC_DIR / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(PUBLIC_DIR.resolve())) or not file_path.exists():
            self.send_error(404)
            return

        content_type = "text/plain; charset=utf-8"
        if file_path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/chat/stream":
            self.handle_chat_stream()
            return

        if path == "/api/summarize":
            self.handle_summarize()
            return

        if path == "/api/context/estimate":
            self.handle_context_estimate()
            return

        if path != "/api/chat":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = body.get("messages", [])
            model_id = body.get("model")
            if not isinstance(messages, list):
                raise ValueError("messages 必须是数组")
            result = run_agent(messages, model_id)
            result["model"] = get_model_config(model_id)["id"]
            self.send_json(200, result)
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def handle_summarize(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = body.get("messages", [])
            model_id = body.get("model")
            previous_summary = body.get("summary", "")
            if not isinstance(messages, list):
                raise ValueError("messages 必须是数组")
            if not isinstance(previous_summary, str):
                raise ValueError("summary 必须是字符串")
            self.send_json(200, summarize_conversation(messages, model_id, previous_summary))
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def handle_context_estimate(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = body.get("messages", [])
            model_id = body.get("model")
            if not isinstance(messages, list):
                raise ValueError("messages 必须是数组")
            self.send_json(200, estimate_context_usage(messages, model_id))
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def handle_chat_stream(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = body.get("messages", [])
            model_id = body.get("model")
            if not isinstance(messages, list):
                raise ValueError("messages 必须是数组")
            model_config = get_model_config(model_id)
        except Exception as exc:
            self.send_response(400)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.write_sse("error", {"message": str(exc)})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def event_sink(event, payload):
            self.write_sse(event, payload)

        try:
            result = run_agent(messages, model_config["id"], event_sink=event_sink)
            result["model"] = model_config["id"]
            self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                self.write_sse("error", {"message": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                return

    def write_sse(self, event, payload):
        data = json.dumps(payload, ensure_ascii=False)
        frame = f"event: {event}\ndata: {data}\n\n".encode("utf-8")
        self.wfile.write(frame)
        self.wfile.flush()

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Agent server running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
