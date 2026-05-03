import ast
import html
import ipaddress
import json
import math
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = ROOT


class ToolPermission:
    SAFE_READ = "safe_read"
    SAFE_COMPUTE = "safe_compute"
    READ_USER_FILE = "read_user_file"
    NETWORK_READ = "network_read"
    REPO_READ = "repo_read"
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    SHELL = "shell"

    @staticmethod
    def needs_confirmation(permission: str) -> bool:
        return permission in (ToolPermission.WRITE_FILE, ToolPermission.EDIT_FILE, ToolPermission.SHELL)


class ToolError(Exception):
    pass


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        permission: str,
        parameters: dict,
        handler: Callable[[dict], Any],
    ):
        self.name = name
        self.description = description
        self.permission = permission
        self.parameters = parameters
        self.handler = handler

    def execute(self, args: dict) -> Any:
        return self.handler(args)

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission,
            "parameters": self.parameters,
        }


def _coerce_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, number))


def _workspace_relative_path(path_value: Any) -> tuple[Path, str]:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ToolError("path 必须是非空字符串")
    if Path(path_value).is_absolute():
        raise ToolError("path 必须是工作区内的相对路径")

    full_path = (WORKSPACE_ROOT / path_value).resolve()
    workspace_root = WORKSPACE_ROOT.resolve()
    if workspace_root != full_path and workspace_root not in full_path.parents:
        raise ToolError("路径必须在工作区内")

    return full_path, full_path.relative_to(workspace_root).as_posix()


def _validate_public_http_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("url 必须以 http:// 或 https:// 开头")
    if not parsed.hostname:
        raise ToolError("url 缺少 hostname")

    hostname = parsed.hostname.lower()
    blocked_hosts = {"localhost", "0.0.0.0"}
    if hostname in blocked_hosts or hostname.endswith((".local", ".internal")):
        raise ToolError("web_fetch 只允许读取公开网页，不允许访问本地或内网 hostname")

    try:
        ip_address = ipaddress.ip_address(hostname)
    except ValueError:
        return url

    if ip_address.is_private or ip_address.is_loopback or ip_address.is_link_local or ip_address.is_reserved:
        raise ToolError("web_fetch 只允许读取公开网页，不允许访问本地或内网 IP")

    return url


def _safe_calculate(expression: str) -> float:
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


def _handle_current_time(args: dict) -> dict:
    timezone = args.get("timezone", "Asia/Shanghai") if isinstance(args, dict) else "Asia/Shanghai"
    return {
        "timezone": timezone,
        "timestamp": int(time.time()),
        "local_time": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()),
    }


def _handle_calculator(args: dict) -> dict:
    if not isinstance(args, dict) or "expression" not in args:
        raise ToolError("calculator 需要 expression 参数")
    expression = str(args["expression"])
    result = _safe_calculate(expression)
    return {"expression": expression, "result": result}


def _handle_file_read(args: dict) -> dict:
    if not isinstance(args, dict) or "path" not in args:
        raise ToolError("file_read 需要 path 参数")

    full_path, relative_path = _workspace_relative_path(args["path"])

    if not full_path.exists():
        raise ToolError(f"文件不存在: {relative_path}")

    if not full_path.is_file():
        raise ToolError(f"不是文件: {relative_path}")

    max_size = 1024 * 1024
    file_size = full_path.stat().st_size
    if file_size > max_size:
        raise ToolError(f"文件太大，最大支持 1MB，当前 {file_size} 字节")

    offset = _coerce_int(args.get("offset", 1), 1, 1, 1000000)
    limit = _coerce_int(args.get("limit", 2000), 2000, 1, 100000)

    try:
        content = full_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        total_lines = len(lines)
        
        start_idx = max(0, offset - 1)
        end_idx = min(total_lines, start_idx + limit)
        
        target_lines = lines[start_idx:end_idx]
        
        # Add line numbers (cat -n style)
        numbered_lines = []
        for i, line in enumerate(target_lines):
            line_num = start_idx + i + 1
            numbered_lines.append(f"{line_num:6}\t{line}")
            
        final_content = "\n".join(numbered_lines)
        
        truncated = end_idx < total_lines

        return {
            "path": relative_path,
            "content": final_content,
            "size_bytes": file_size,
            "total_lines": total_lines,
            "read_start_line": start_idx + 1,
            "read_end_line": end_idx,
            "truncated": truncated,
        }
    except UnicodeDecodeError:
        raise ToolError("无法读取文件，可能是二进制文件")
    except Exception as exc:
        raise ToolError(f"读取失败: {exc}")


def _handle_file_write(args: dict) -> dict:
    if not isinstance(args, dict) or "path" not in args or "content" not in args:
        raise ToolError("file_write 需要 path 和 content 参数")

    full_path, relative_path = _workspace_relative_path(args["path"])
    content = str(args["content"])
    
    is_create = not full_path.exists()
    
    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return {
            "action": "create" if is_create else "update",
            "path": relative_path,
            "size_bytes": len(content.encode("utf-8"))
        }
    except Exception as exc:
        raise ToolError(f"写入失败: {exc}")


def _handle_file_edit(args: dict) -> dict:
    if not isinstance(args, dict) or "path" not in args or "old_string" not in args or "new_string" not in args:
        raise ToolError("file_edit 需要 path, old_string 和 new_string 参数")

    full_path, relative_path = _workspace_relative_path(args["path"])
    
    if not full_path.exists():
        raise ToolError(f"文件不存在: {relative_path}。如果是新文件，请使用 file_write。")

    old_string = str(args["old_string"])
    new_string = str(args["new_string"])
    replace_all = bool(args.get("replace_all", False))
    
    if old_string == new_string:
        raise ToolError("修改无效：old_string 和 new_string 完全相同。")
        
    try:
        content = full_path.read_text(encoding="utf-8")
        
        if old_string not in content:
            raise ToolError("在文件中找不到 old_string。请确保使用 file_read 读取最新内容，且未包含行号前缀。")
            
        occurrences = content.count(old_string)
        if occurrences > 1 and not replace_all:
            raise ToolError(f"找到 {occurrences} 个匹配项，但 replace_all 为 false。请提供更多上下文以唯一标识修改位置，或者设置 replace_all=true。")
            
        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            
        full_path.write_text(new_content, encoding="utf-8")
        
        return {
            "path": relative_path,
            "replaced_occurrences": occurrences if replace_all else 1,
            "message": "文件编辑成功"
        }
    except UnicodeDecodeError:
        raise ToolError("无法编辑，可能是二进制文件")
    except Exception as exc:
        raise ToolError(f"编辑失败: {exc}")


def _handle_repo_search(args: dict) -> dict:
    if not isinstance(args, dict) or "query" not in args:
        raise ToolError("repo_search 需要 query 参数")

    query = args.get("query", "")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("query 不能为空")

    max_results = _coerce_int(args.get("max_results", 20), 20, 1, 100)

    extensions = args.get("extensions", [])
    if isinstance(extensions, str):
        extensions = [extensions]
    if not isinstance(extensions, list):
        extensions = []

    try:
        cmd = [
            "rg",
            "--json",
            "--line-number",
            "--max-count",
            str(max_results),
            "--glob",
            "!frontend/node_modules/**",
            "--glob",
            "!frontend/.next/**",
            "--glob",
            "!.git/**",
        ]
        if extensions:
            ext_args = [f"--type={ext}" for ext in extensions if ext]
            cmd.extend(ext_args)
        cmd.extend(["--", query, str(WORKSPACE_ROOT)])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode > 1:
            raise ToolError(result.stderr.strip() or "搜索失败")

        workspace_root = WORKSPACE_ROOT.resolve()
        matches = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if entry.get("type") == "match":
                    data = entry.get("data", {})
                    lines = data.get("lines", {})
                    text = lines.get("text", "")
                    path_info = data.get("path", {})
                    path_str = path_info.get("text", "")
                    line_num = data.get("line_number", 0)
                    try:
                        path_text = Path(path_str).resolve().relative_to(workspace_root).as_posix()
                    except ValueError:
                        path_text = path_str
                    matches.append({"path": path_text, "line": line_num, "content": text.rstrip()[:300]})
                    if len(matches) >= max_results:
                        break
            except (json.JSONDecodeError, KeyError):
                continue

        return {"query": query, "matches": matches, "count": len(matches)}
    except FileNotFoundError:
        raise ToolError("rg 命令不可用，请安装 ripgrep: brew install ripgrep")
    except subprocess.TimeoutExpired:
        raise ToolError("搜索超时，请尝试更精确的查询")
    except Exception as exc:
        raise ToolError(f"搜索失败: {exc}")


def _handle_web_fetch(args: dict) -> dict:
    if not isinstance(args, dict) or "url" not in args:
        raise ToolError("web_fetch 需要 url 参数")

    url = args.get("url", "")
    if not isinstance(url, str) or not url.strip():
        raise ToolError("url 不能为空")

    url = _validate_public_http_url(url)

    max_size = 512 * 1024
    max_chars = _coerce_int(args.get("max_chars", 4000), 4000, 500, 12000)
    timeout = 15

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Agent/1.0)",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                raise ToolError(f"不支持的内容类型: {content_type}")

            content = response.read(max_size).decode("utf-8", errors="replace")

            title_match = re.search(r"<title[^>]*>([^<]+)</title>", content, re.IGNORECASE)
            title = title_match.group(1) if title_match else ""

            clean_content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.IGNORECASE | re.DOTALL)
            clean_content = re.sub(r"<style[^>]*>.*?</style>", "", clean_content, flags=re.IGNORECASE | re.DOTALL)
            clean_content = re.sub(r"<[^>]+>", "", clean_content)
            clean_content = html.unescape(re.sub(r"\s+", " ", clean_content)).strip()

            truncated = False
            if len(clean_content) > max_chars:
                clean_content = clean_content[:max_chars] + "..."
                truncated = True

            return {
                "url": url,
                "title": html.unescape(title.strip()),
                "content_type": content_type,
                "content": clean_content,
                "length": len(clean_content),
                "truncated": truncated,
            }
    except ToolError:
        raise
    except urllib.error.URLError as exc:
        raise ToolError(f"请求失败: {exc.reason}")
    except Exception as exc:
        raise ToolError(f"获取失败: {exc}")


TOOLS = {
    "current_time": Tool(
        name="current_time",
        description="获取当前本地时间",
        permission=ToolPermission.SAFE_READ,
        parameters={
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "default": "Asia/Shanghai",
                    "description": "时区，如 Asia/Shanghai、America/New_York",
                }
            },
        },
        handler=_handle_current_time,
    ),
    "calculator": Tool(
        name="calculator",
        description="安全计算数学表达式，支持四则运算、幂运算、取模和常量(pi/e/tau)",
        permission=ToolPermission.SAFE_COMPUTE,
        parameters={
            "type": "object",
            "required": ["expression"],
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，如 12 * 7、2**10、100 % 3",
                }
            },
        },
        handler=_handle_calculator,
    ),
    "file_read": Tool(
        name="file_read",
        description="读取指定文件的内容（带有行号前缀）。支持通过 offset 和 limit 按行读取部分内容，推荐不传参数以读取全文件。读取后内容前会附加行号以辅助修改定位。",
        permission=ToolPermission.READ_USER_FILE,
        parameters={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对于工作区的文件路径，如 docs/README.md",
                },
                "offset": {
                    "type": "integer",
                    "description": "从哪一行开始读取（1-indexed）。如果不传则默认从第 1 行开始。",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多读取的行数。如果不传则默认读取 2000 行。",
                },
            },
        },
        handler=_handle_file_read,
    ),
    "file_write": Tool(
        name="file_write",
        description="创建新文件或完全覆盖现有文件内容。",
        permission=ToolPermission.WRITE_FILE,
        parameters={
            "type": "object",
            "required": ["path", "content"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对于工作区的目标文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的完整文件内容",
                },
            },
        },
        handler=_handle_file_write,
    ),
    "file_edit": Tool(
        name="file_edit",
        description="基于精确字符串匹配就地修改现有文件的内容。请确保精确匹配文件中的缩进/空格，并不要包含由 file_read 返回的行号前缀。",
        permission=ToolPermission.EDIT_FILE,
        parameters={
            "type": "object",
            "required": ["path", "old_string", "new_string"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要修改的目标文件路径",
                },
                "old_string": {
                    "type": "string",
                    "description": "要被替换的原始精确字符串。必须在文件中唯一存在。",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新字符串。",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "如果设为 true，则替换所有匹配的 old_string。否则若有多个匹配将报错。",
                    "default": False
                },
            },
        },
        handler=_handle_file_edit,
    ),
    "repo_search": Tool(
        name="repo_search",
        description="在代码仓库中搜索文件内容和文件名",
        permission=ToolPermission.REPO_READ,
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或正则表达式",
                },
                "max_results": {
                    "type": "integer",
                    "default": 20,
                    "description": "最大返回结果数",
                },
                "extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "限定文件类型，如 ['py', 'js']",
                },
            },
        },
        handler=_handle_repo_search,
    ),
    "web_fetch": Tool(
        name="web_fetch",
        description="获取网页内容，支持读取公开网页的文本信息",
        permission=ToolPermission.NETWORK_READ,
        parameters={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "目标网页 URL，必须以 http:// 或 https:// 开头",
                },
                "max_chars": {
                    "type": "integer",
                    "default": 4000,
                    "description": "最大返回字符数，范围 500 到 12000",
                },
            },
        },
        handler=_handle_web_fetch,
    ),
}


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name)


def get_all_tools() -> Dict[str, Tool]:
    return TOOLS


def get_tools_schema() -> List[dict]:
    return [tool.to_schema() for tool in TOOLS.values()]


def execute_tool(name: str, args: dict) -> Any:
    tool = get_tool(name)
    if not tool:
        raise ToolError(f"未知工具：{name}")
    return tool.execute(args)


def get_safe_tools() -> List[str]:
    return [name for name, tool in TOOLS.items() if not ToolPermission.needs_confirmation(tool.permission)]


def get_tools_by_permission(permission: str) -> List[str]:
    return [name for name, tool in TOOLS.items() if tool.permission == permission]
