import ast
import json
import math
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
DEFAULT_MODEL_ID = os.getenv("DEFAULT_MODEL_ID", "zhipu-glm-4.7-flash")

MODEL_OPTIONS = [
    {
        "id": "zhipu-glm-4.7-flash",
        "label": "智谱 GLM-4.7-Flash",
        "provider": "zhipu",
        "model": "glm-4.7-flash",
        "base_url": os.getenv("ZHIPU_BASE_URL") or os.getenv("ZAI_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4",
        "api_key_envs": ["ZAI_API_KEY", "ZHIPU_API_KEY"],
        "thinking": "disabled",
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
        "description": "低成本、低延迟，推荐作为 DeepSeek 默认选项。",
    },
    {
        "id": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "api_key_envs": ["DEEPSEEK_API_KEY"],
        "thinking": "disabled",
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
        "description": "开启思考模式，适合更难的问题；会更慢、更贵。",
    },
]
MODEL_OPTIONS_BY_ID = {option["id"]: option for option in MODEL_OPTIONS}

ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"

AGENT_SYSTEM_PROMPT = """你是一个轻量级手写 Agent。你只能输出 JSON，不要输出任何其他文字。

## 可用工具
1. current_time - 获取当前时间
2. calculator - 计算数学表达式

## 输出格式（严格遵守）
你的每次回复必须且只能是下面两种 JSON 之一，不允许输出其他任何内容：

调用工具时输出：
{"action":"tool","tool":"工具名","args":{...}}

给出最终答案时输出：
{"action":"final","answer":"你的中文回答"}

## 示例

用户：现在几点？
你：{"action":"tool","tool":"current_time","args":{"timezone":"Asia/Shanghai"}}

用户：帮我算 12 * 7
你：{"action":"tool","tool":"calculator","args":{"expression":"12 * 7"}}

用户：你好
你：{"action":"final","answer":"你好！有什么可以帮你的吗？"}

## 要求
- 输出必须是合法 JSON，不要加 markdown 代码块、不要加解释文字。
- 优先用中文回答。
- 不要编造工具结果，必须调用工具获取。
- 收到工具结果后，用 final 格式回复用户。
"""


class ToolError(Exception):
    pass


def safe_calculate(expression):
    allowed_binops = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a**b,
    }
    allowed_unary = {
        ast.UAdd: lambda a: +a,
        ast.USub: lambda a: -a,
    }
    allowed_names = {
        "pi": math.pi,
        "e": math.e,
        "tau": math.tau,
    }

    def eval_node(node):
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in allowed_names:
            return allowed_names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binops:
            return allowed_binops[type(node.op)](eval_node(node.left), eval_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary:
            return allowed_unary[type(node.op)](eval_node(node.operand))
        raise ToolError("表达式包含不支持的内容")

    try:
        tree = ast.parse(expression, mode="eval")
        return eval_node(tree)
    except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise ToolError(str(exc)) from exc


def run_tool(tool_name, args):
    if tool_name == "current_time":
        timezone = args.get("timezone", "Asia/Shanghai") if isinstance(args, dict) else "Asia/Shanghai"
        return {
            "timezone": timezone,
            "timestamp": int(time.time()),
            "local_time": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()),
        }
    if tool_name == "calculator":
        if not isinstance(args, dict) or "expression" not in args:
            raise ToolError("calculator 需要 expression 参数")
        return {"expression": args["expression"], "result": safe_calculate(str(args["expression"]))}
    raise ToolError(f"未知工具：{tool_name}")


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
            }
        )
    return options


def llm_chat(messages, model_config, temperature=0.2):
    api_key = first_env_value(model_config["api_key_envs"])
    if not api_key:
        envs = " 或 ".join(model_config["api_key_envs"])
        raise RuntimeError(f"请先设置 {envs} 环境变量")

    url = model_config["base_url"].rstrip("/") + "/chat/completions"
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
            return data["choices"][0]["message"]["content"]
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


KNOWN_TOOLS = {"current_time", "calculator"}


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


def run_agent(user_messages, model_id=None):
    model_config = get_model_config(model_id)
    messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    messages.extend(user_messages[-12:])
    steps = []

    for _ in range(4):
        raw = llm_chat(messages, model_config)
        decision = parse_agent_json(raw)

        if decision.get("action") == "tool":
            tool_name = decision.get("tool")
            args = decision.get("args") or {}
            try:
                result = run_tool(tool_name, args)
                steps.append({"type": "tool", "tool": tool_name, "args": args, "result": result})
            except ToolError as exc:
                result = {"error": str(exc)}
                steps.append({"type": "tool_error", "tool": tool_name, "args": args, "result": result})

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

        answer = decision.get("answer") or raw
        return {"answer": answer, "steps": steps}

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
    return {"answer": decision.get("answer") or fallback, "steps": steps}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/models":
            self.send_json(200, {"models": public_model_options(), "default": get_model_config()["id"]})
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
        if self.path != "/api/chat":
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

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Agent server running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
