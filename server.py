import ast
import json
import math
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL",
    "https://wanqing-api.corp.kuaishou.com/api/gateway/v1/endpoints",
)
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("WQ_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "ep-r8b5g8-1772540899002785977")

ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"

AGENT_SYSTEM_PROMPT = """你是一个轻量级手写 Agent。
你可以直接回答，也可以按下面 JSON 协议调用工具。

可用工具：
1. current_time: 获取当前时间。参数：{"timezone": "Asia/Shanghai"}
2. calculator: 计算安全的数学表达式。参数：{"expression": "2 * (3 + 4)"}

当你需要调用工具时，只输出一个 JSON 对象，不要输出其他文字：
{"action":"tool","tool":"calculator","args":{"expression":"12 * 7"}}

当你已经可以给用户最终答案时，只输出：
{"action":"final","answer":"你的回答"}

要求：
- 优先用中文回答。
- 不要编造工具结果。
- 如果不需要工具，直接 final。
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


def llm_chat(messages, temperature=0.2):
    if not LLM_API_KEY:
        raise RuntimeError("请先设置 LLM_API_KEY 或 WQ_API_KEY 环境变量")

    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM 请求失败：{exc.reason}") from exc

    return data["choices"][0]["message"]["content"]


def parse_agent_json(content):
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"action": "final", "answer": content}


def run_agent(user_messages):
    messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    messages.extend(user_messages[-12:])
    steps = []

    for _ in range(4):
        raw = llm_chat(messages)
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
        ]
    )
    decision = parse_agent_json(fallback)
    return {"answer": decision.get("answer") or fallback, "steps": steps}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
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
            if not isinstance(messages, list):
                raise ValueError("messages 必须是数组")
            result = run_agent(messages)
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
