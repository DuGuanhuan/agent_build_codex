import ast
import os
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
from skills.manager import SkillManager

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = ROOT

skill_manager = SkillManager(skills_dir=str(WORKSPACE_ROOT / "skills"))


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
    def is_safe_shell_command(command: str) -> bool:
        """
        判断 shell 命令是否为安全的“只读/观察”类命令。
        对标主流产品，这些命令不需要人工确认。
        """
        if not command:
            return False
        
        # 允许的观察类基础命令
        SAFE_OBSERVATION_COMMANDS = [
            "ls", "pwd", "date", "whoami", "id", "hostname",
            "uname", "df", "du", "free", "uptime",
            "git status", "git log", "git diff", "git branch", "git remote",
            "cat", "head", "tail", "grep", "find", "which", "whereis",
            "file", "stat", "lsblk", "lscpu"
        ]
        
        cmd_trim = command.strip().lower()
        
        # 排除包含重定向、管道写操作等危险符合的命令
        # 注意：这里只是第一层过滤，执行阶段还有更严格的黑名单
        DANGEROUS_SYMBOLS = [">", ">>", "|", ";", "&", "`", "$("]
        if any(sym in cmd_trim for sym in DANGEROUS_SYMBOLS):
            # 如果有管道或分号，除非整条命令都被显式允许（如常用的 grep），否则认为不安全
            # 为了简单起见，目前包含这些符号的一律要求确认
            return False

        # 检查是否以允许的命令开头
        for safe_cmd in SAFE_OBSERVATION_COMMANDS:
            if cmd_trim.startswith(safe_cmd):
                # 检查后面是否紧跟空格或结尾，防止 lss, catty 等命令绕过
                if len(cmd_trim) == len(safe_cmd) or cmd_trim[len(safe_cmd)] == " ":
                    return True
        
        return False

    @staticmethod
    def needs_confirmation(permission: str, tool_name: str = None, args: dict = None) -> bool:
        """
        判断调用是否需要人工确认。
        增加了对工具名称和参数的动态判断逻辑。
        """
        # 如果是 shell 工具，动态判断命令是否安全
        if tool_name == "shell_exec" and args and "command" in args:
            if ToolPermission.is_safe_shell_command(str(args["command"])):
                return False
            return True
            
        # 默认基于权限等级判断
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


def _handle_web_search(args: dict) -> dict:
    """使用 Tavily API 进行联网搜索"""
    query = args.get("query")
    if not query:
        raise ToolError("web_search 需要 query 参数")

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ToolError("未配置 TAVILY_API_KEY 环境变量，无法使用联网搜索。")

    try:
        data = json.dumps({
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": 5
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            results = []
            for item in res_data.get("results", []):
                results.append({
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "content": item.get("content")
                })
            return {"query": query, "results": results}
    except Exception as exc:
        raise ToolError(f"搜索失败: {exc}")


def _handle_skill_create(args: dict) -> dict:
    """创建或更新一个专家技能"""
    name = args.get("name")
    description = args.get("description", "")
    type_ = args.get("type", "hook")
    path_patterns = args.get("paths", [])
    trigger_words = args.get("trigger_words", [])
    instructions = args.get("instructions", "")

    if not name or not instructions:
        raise ToolError("skill_create 需要 name 和 instructions 参数")
    
    meta = {
        "description": description,
        "type": type_,
        "paths": path_patterns,
        "trigger_words": trigger_words
    }

    skill = skill_manager.save_skill(name, meta, instructions)
    if not skill:
        raise ToolError("创建技能失败")
    
    return {
        "status": "success",
        "message": f"技能 '{name}' 已成功创建并加载。",
        "skill": {
            "name": skill.name,
            "type": skill.type,
            "dir": skill.skill_dir
        }
    }


def _handle_skill_delete(args: dict) -> dict:
    """删除指定的专家技能"""
    name = args.get("name")
    if not name:
        raise ToolError("skill_delete 需要 name 参数")
    
    if skill_manager.delete_skill(name):
        return {"status": "success", "message": f"技能 '{name}' 已删除。"}
    else:
        raise ToolError(f"未找到技能: {name}")


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
        # 对 URL 进行编码以支持中文
        parsed = urllib.parse.urlsplit(url)
        encoded_path = urllib.parse.quote(parsed.path)
        encoded_query = urllib.parse.quote(parsed.query, safe="=&")
        url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, encoded_path, encoded_query, parsed.fragment))

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


def _handle_shell_exec(args: dict) -> dict:
    """Execute a shell command within the workspace.

    Security design inspired by Claude Code's BashTool:
    - Working directory locked to WORKSPACE_ROOT (no cd escape)
    - Dangerous command patterns are blocked outright
    - Output is capped to prevent memory exhaustion
    - Timeout prevents runaway processes
    - Requires SHELL permission (human-in-the-loop approval)
    """
    if not isinstance(args, dict) or "command" not in args:
        raise ToolError("shell_exec 需要 command 参数")

    command = str(args["command"]).strip()
    if not command:
        raise ToolError("command 不能为空")

    description = str(args.get("description", "")).strip()
    timeout_ms = _coerce_int(args.get("timeout", 30000), 30000, 1000, 120000)
    timeout_sec = timeout_ms / 1000

    # ── Security: block dangerous command patterns ──────────────────────
    # Inspired by Claude Code's bashSecurity.ts deny-list approach.
    # We block commands that could cause irreversible system-level damage.
    BLOCKED_COMMANDS = [
        # System destruction
        "rm -rf /", "rm -rf /*", "mkfs", "dd if=",
        # Privilege escalation
        "sudo", "su -", "doas", "pkexec",
        # System config mutation
        "shutdown", "reboot", "poweroff", "halt",
        "systemctl stop", "systemctl disable",
        # Network exfiltration (outbound data)
        "nc -l", "ncat -l",
        # Disk / partition
        "fdisk", "parted", "mount", "umount",
        # Dangerous shell invocations
        "eval ", "exec ",
    ]

    command_lower = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if command_lower.startswith(blocked) or f" {blocked}" in command_lower:
            raise ToolError(f"安全策略：该命令包含被禁止的操作 ({blocked.strip()})")

    # Block piping to destructive targets
    BLOCKED_PIPE_TARGETS = [
        "| sh", "| bash", "| zsh",
        "| sudo", "> /etc/", "> /dev/sd",
        "> ~/.ssh/", "> ~/.bashrc", "> ~/.profile",
    ]
    for pattern in BLOCKED_PIPE_TARGETS:
        if pattern in command_lower:
            raise ToolError(f"安全策略：该命令包含被禁止的输出目标 ({pattern.strip()})")

    # ── Execute ────────────────────────────────────────────────────────
    MAX_OUTPUT_BYTES = 100 * 1024  # 100 KB cap (Claude Code uses 30K chars)

    start_time = time.time()
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            timeout=timeout_sec,
            env={**__import__("os").environ, "PAGER": "cat", "GIT_PAGER": "cat"},
        )
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start_time, 2)
        return {
            "command": command,
            "description": description or command,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"命令超时（{timeout_sec}s）",
            "timed_out": True,
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:
        raise ToolError(f"命令执行失败: {exc}")

    elapsed = round(time.time() - start_time, 2)

    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    stdout_truncated = False
    stderr_truncated = False

    if len(stdout) > MAX_OUTPUT_BYTES:
        stdout = stdout[:MAX_OUTPUT_BYTES] + f"\n\n... [输出已截断，共 {len(result.stdout)} 字节]"
        stdout_truncated = True

    if len(stderr) > MAX_OUTPUT_BYTES:
        stderr = stderr[:MAX_OUTPUT_BYTES] + f"\n\n... [错误输出已截断，共 {len(result.stderr)} 字节]"
        stderr_truncated = True

    return {
        "command": command,
        "description": description or command,
        "exit_code": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "timed_out": False,
        "elapsed_seconds": elapsed,
    }


def _handle_invoke_skill(args: dict) -> dict:
    """按名称调用一个 Invocable 技能"""
    skill_name = args.get("skill_name")
    if not skill_name:
        raise ToolError("invoke_skill 需要 skill_name 参数")
    
    skill = skill_manager.get_skill(skill_name)
    if not skill:
        raise ToolError(f"未找到技能: {skill_name}")
    
    if skill.type != "invocable":
        raise ToolError(f"技能 '{skill_name}' 不是一个可调用的功能技能 (当前类型: {skill.type})")
    
    # 渲染指令
    instructions = skill_manager.render_skill_instructions(skill)
    
    return {
        "status": "success",
        "skill": skill_name,
        "instructions": instructions
    }


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
    "web_search": Tool(
        name="web_search",
        description="联网搜索关键词，返回相关的网页标题、链接和内容摘要。推荐在需要获取实时信息或背景知识时使用。",
        permission=ToolPermission.NETWORK_READ,
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
            },
        },
        handler=_handle_web_search,
    ),
    "shell_exec": Tool(
        name="shell_exec",
        description=(
            "在工作区内执行 shell 命令。工作目录锁定在项目根目录。"
            "适用于运行构建脚本、测试、git 操作、安装依赖、查看系统状态等。"
            "危险命令（如 sudo、rm -rf /、eval）会被安全策略拦截。"
            "输出超过 100KB 会被截断。默认超时 30 秒，最大 120 秒。"
        ),
        permission=ToolPermission.SHELL,
        parameters={
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "要执行的 shell 命令。支持管道、重定向等 shell 语法。"
                        "示例：ls -la、git status、python3 -c 'print(1+1)'、npm run build"
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "对命令的简短中文描述，说明这条命令做了什么。"
                        "示例：'查看当前目录文件列表'、'运行单元测试'"
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "default": 30000,
                    "description": "超时时间（毫秒），范围 1000-120000，默认 30000",
                },
            },
        },
        handler=_handle_shell_exec,
    ),
    "invoke_skill": Tool(
        name="invoke_skill",
        description=(
            "按名称调用一个特定的专家技能。当你发现任务属于某个专业领域（如 Git、PDF、安全等）时，"
            "可以使用此工具获取专家的详细指令和工作流程。"
        ),
        permission=ToolPermission.SAFE_READ,
        parameters={
            "type": "object",
            "required": ["skill_name"],
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "要调用的技能名称，如 'git-committer'",
                }
            },
        },
        handler=_handle_invoke_skill,
    ),
    "skill_create": Tool(
        name="skill_create",
        description="创建或更新一个专家技能。你可以将复杂的工作流、专业知识或特定场景的指令沉淀为持久化技能。技能保存在 skills/ 目录下。",
        permission=ToolPermission.WRITE_FILE,
        parameters={
            "type": "object",
            "required": ["name", "instructions"],
            "properties": {
                "name": {
                    "type": "string",
                    "description": "技能唯一标识名，建议用英文小写加连字符，如 'react-expert'",
                },
                "description": {
                    "type": "string",
                    "description": "技能的简短描述，说明它能解决什么问题。",
                },
                "type": {
                    "type": "string",
                    "enum": ["hook", "invocable"],
                    "default": "hook",
                    "description": "技能类型：'hook' 为基于路径自动激活，'invocable' 为需要手动通过 invoke_skill 调用。",
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "仅 type='hook' 时有效。触发该技能的文件路径模式（glob），如 ['*.js', 'docs/*']。",
                },
                "instructions": {
                    "type": "string",
                    "description": "详细的专家级系统指令。可以使用 Markdown 格式，支持 !`cmd` 嵌入式安全观察命令。",
                },
            },
        },
        handler=_handle_skill_create,
    ),
    "skill_delete": Tool(
        name="skill_delete",
        description="删除一个不再需要的专家技能。",
        permission=ToolPermission.WRITE_FILE,
        parameters={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要删除的技能名称",
                },
            },
        },
        handler=_handle_skill_delete,
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
