import os
try:
    import yaml
except ImportError:
    yaml = None
import fnmatch
import logging
import re
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict

logger = logging.getLogger('agent.skills')

# 尝试导入 shell_exec
try:
    from tools.registry import execute_tool, ToolPermission
except ImportError:
    execute_tool = None
    ToolPermission = None

@dataclass
class Skill:
    name: str
    description: str
    type: str  # "hook" or "invocable"
    path_patterns: List[str] = field(default_factory=list)
    trigger_words: List[str] = field(default_factory=list)
    instructions: str = ""
    skill_dir: str = ""

class SkillManager:
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, Skill] = {}
        self.load_skills()

    def _parse_yaml_lite(self, content: str) -> dict:
        """简单的 YAML 解析逻辑，处理基础的键值对和列表"""
        data = {}
        lines = content.split('\n')
        current_key = None
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if ':' in line and not line.startswith('-'):
                key, value = line.split(':', 1)
                key = key.strip().strip('"\'')
                value = value.strip().strip('"\'')
                if value:
                    data[key] = value
                else:
                    data[key] = []
                current_key = key
            elif line.startswith('- ') and current_key:
                val = line[2:].strip().strip('"\'')
                if isinstance(data[current_key], list):
                    data[current_key].append(val)
        return data

    def load_skills(self):
        if not self.skills_dir.exists():
            return

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            
            yaml_path = skill_dir / "skill.yaml"
            md_path = skill_dir / "instructions.md"
            
            if yaml_path.exists() and md_path.exists():
                try:
                    with open(yaml_path, 'r', encoding='utf-8') as f:
                        meta = self._parse_yaml_lite(f.read())
                    
                    with open(md_path, 'r', encoding='utf-8') as f:
                        instructions = f.read()
                    
                    skill = Skill(
                        name=meta.get("name", skill_dir.name),
                        description=meta.get("description", ""),
                        type=meta.get("type", "hook"),
                        path_patterns=meta.get("paths", []), # 注意：YAML 里可能是 paths
                        trigger_words=meta.get("trigger_words", []),
                        instructions=instructions,
                        skill_dir=str(skill_dir)
                    )
                    # 兼容 yaml-lite 解析出的不同 key
                    if not skill.path_patterns and "activation" in meta:
                        # 如果有嵌套结构，这里需要更强的解析，目前暂用平铺逻辑
                        pass

                    self.skills[skill.name] = skill
                except (OSError, IOError) as e:
                    logger.error(f"Failed to read skill files for {skill_dir.name}: {e}")
                except Exception as e:
                    logger.exception(f"Failed to load skill {skill_dir.name}: {e}")

    def get_active_hooks(self, context_paths: List[str]) -> List[Skill]:
        active_hooks = []
        for skill in self.skills.values():
            if skill.type != "hook":
                continue
            
            # 路径匹配
            matched = False
            for path in context_paths:
                for pattern in skill.path_patterns:
                    if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(os.path.basename(path), pattern):
                        matched = True
                        break
                if matched:
                    break
            
            if matched:
                active_hooks.append(skill)
        
        return active_hooks

    def _execute_embedded_command(self, command: str) -> str:
        """执行嵌入式命令，仅允许安全观察类命令"""
        if not execute_tool or not ToolPermission:
            return f"[Error: Tool system not available for command: {command}]"
        
        # 安全检查：仅允许只读观察类命令注入 Prompt
        if not ToolPermission.is_safe_shell_command(command):
            return f"[Blocked: Command '{command}' is not marked as safe for prompt injection]"
        
        try:
            # 直接调用 shell_exec 工具处理器
            result = execute_tool("shell_exec", {"command": command})
            if isinstance(result, dict):
                return result.get("stdout", "") + result.get("stderr", "")
            return str(result)
        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f"Failed to execute embedded command '{command}': {e}")
            return f"[Error executing '{command}': {e}]"

    def render_skill_instructions(self, skill: Skill) -> str:
        """解析指令中的嵌入式命令 !`cmd`"""
        content = skill.instructions
        
        # 寻找 !`cmd` 模式
        pattern = r'!`([^`]+)`'
        
        def replace_cmd(match):
            cmd = match.group(1)
            return self._execute_embedded_command(cmd)
        
        return re.sub(pattern, replace_cmd, content)

    def get_skill_instructions_blob(self, context_paths: List[str]) -> str:
        active_hooks = self.get_active_hooks(context_paths)
        if not active_hooks:
            return ""
        
        blob = "\n\n=== ACTIVE SKILLS INSTRUCTIONS ===\n"
        for skill in active_hooks:
            blob += f"\n--- Skill: {skill.name} ---\n"
            # 渲染指令（处理嵌入式命令）
            rendered_instructions = self.render_skill_instructions(skill)
            blob += rendered_instructions
        blob += "\n==================================\n"
        return blob

    def get_invocable_skills_summary(self) -> str:
        """获取所有可主动调用的技能列表及其描述"""
        summary = ""
        for skill in self.skills.values():
            if skill.type == "invocable":
                summary += f"- {skill.name}: {skill.description}\n"
        return summary

    def get_skill(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def save_skill(self, name: str, meta: dict, instructions: str):
        """保存或更新技能到磁盘"""
        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        yaml_path = skill_dir / "skill.yaml"
        md_path = skill_dir / "instructions.md"
        
        # 写入 YAML (简单拼接)
        yaml_content = f'name: "{name}"\n'
        for k, v in meta.items():
            if k == "name": continue
            if isinstance(v, list):
                yaml_content += f'{k}:\n'
                for item in v:
                    yaml_content += f'  - "{item}"\n'
            else:
                yaml_content += f'{k}: "{v}"\n'
        
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
            
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(instructions)
            
        # 重新加载
        self.load_skills()
        return self.skills.get(name)

    def delete_skill(self, name: str):
        """删除技能目录"""
        import shutil
        skill_dir = self.skills_dir / name
        if skill_dir.exists() and skill_dir.is_dir():
            shutil.rmtree(skill_dir)
            if name in self.skills:
                del self.skills[name]
            return True
        return False
