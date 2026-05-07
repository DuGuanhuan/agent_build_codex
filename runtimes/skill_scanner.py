from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_SKILL_BODY_CHARS = int(os.getenv("SKILL_CATALOG_BODY_CHARS", "4000"))


@dataclass(frozen=True)
class SkillSearchRoot:
    runtime: str
    root: Path
    scope: str
    source: str
    standard: str = "agent-skills"


def discover_claude_code_skills(workspace: Path) -> list[dict[str, Any]]:
    roots: list[SkillSearchRoot] = []
    for base in _workspace_chain(workspace):
        roots.append(
            SkillSearchRoot(
                runtime="claude-code",
                root=base / ".claude" / "skills",
                scope="project",
                source="claude-code-project",
            )
        )
    roots.append(
        SkillSearchRoot(
            runtime="claude-code",
            root=Path.home() / ".claude" / "skills",
            scope="user",
            source="claude-code-personal",
        )
    )
    roots.extend(_extra_roots("CLAUDE_CODE_SKILL_DIRS", "claude-code", "configured", "claude-code-configured"))
    return scan_skill_roots(roots)


def discover_opencode_skills(workspace: Path) -> list[dict[str, Any]]:
    roots: list[SkillSearchRoot] = []
    for base in _workspace_chain(workspace):
        roots.extend(
            [
                SkillSearchRoot("opencode", base / ".opencode" / "skills", "project", "opencode-project"),
                SkillSearchRoot("opencode", base / ".claude" / "skills", "project", "opencode-claude-compatible"),
                SkillSearchRoot("opencode", base / ".agents" / "skills", "project", "opencode-agent-compatible"),
            ]
        )
    roots.extend(
        [
            SkillSearchRoot(
                "opencode",
                Path.home() / ".config" / "opencode" / "skills",
                "user",
                "opencode-global",
            ),
            SkillSearchRoot("opencode", Path.home() / ".claude" / "skills", "user", "opencode-claude-compatible"),
            SkillSearchRoot("opencode", Path.home() / ".agents" / "skills", "user", "opencode-agent-compatible"),
        ]
    )
    roots.extend(_extra_roots("OPENCODE_SKILL_DIRS", "opencode", "configured", "opencode-configured"))
    return scan_skill_roots(roots)


def discover_codex_skills(workspace: Path) -> list[dict[str, Any]]:
    roots: list[SkillSearchRoot] = []
    for base in _workspace_chain(workspace):
        roots.append(SkillSearchRoot("codex", base / ".agents" / "skills", "project", "codex-repo"))
    roots.extend(
        [
            SkillSearchRoot("codex", Path.home() / ".agents" / "skills", "user", "codex-user"),
            SkillSearchRoot("codex", Path("/etc/codex/skills"), "admin", "codex-admin"),
            SkillSearchRoot("codex", Path.home() / ".codex" / "skills", "user", "codex-local"),
        ]
    )
    roots.extend(_extra_roots("CODEX_SKILL_DIRS", "codex", "configured", "codex-configured"))
    return scan_skill_roots(roots)


def scan_skill_roots(roots: list[SkillSearchRoot]) -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()

    for root in roots:
        if not root.root.exists() or not root.root.is_dir():
            continue
        try:
            skill_files = sorted(root.root.glob("*/SKILL.md"))
        except OSError:
            continue
        for skill_file in skill_files:
            resolved = _safe_resolve(skill_file)
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            parsed = parse_skill_file(skill_file, root)
            if parsed:
                skills.append(parsed)

    return skills


def parse_skill_file(skill_file: Path, root: SkillSearchRoot) -> dict[str, Any] | None:
    try:
        content = skill_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = skill_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    meta, body = parse_frontmatter(content)
    name = str(meta.get("name") or skill_file.parent.name).strip()
    if not name:
        return None
    description = str(meta.get("description") or _first_paragraph(body) or "").strip()
    body_excerpt = body.strip()[:MAX_SKILL_BODY_CHARS]
    truncated = len(body.strip()) > MAX_SKILL_BODY_CHARS

    return {
        "name": name,
        "description": description,
        "type": "native",
        "paths": _list_value(meta.get("paths")),
        "trigger_words": _list_value(meta.get("tags")),
        "instructions": body_excerpt,
        "runtime": root.runtime,
        "source": "filesystem_scan",
        "source_detail": root.source,
        "scope": root.scope,
        "standard": root.standard,
        "path": str(skill_file),
        "skill_dir": str(skill_file.parent),
        "frontmatter": meta,
        "editable": False,
        "native": True,
        "content_truncated": truncated,
    }


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    normalized = content.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return {}, normalized

    end = normalized.find("\n---\n", 4)
    if end < 0:
        return {}, normalized

    raw_frontmatter = normalized[4:end]
    body = normalized[end + len("\n---\n") :]
    return _parse_yaml_lite(raw_frontmatter), body


def _parse_yaml_lite(content: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None

    for raw_line in content.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        if stripped.startswith("- ") and current_key:
            current = data.setdefault(current_key, [])
            if isinstance(current, list):
                current.append(_parse_scalar(stripped[2:].strip()))
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip().strip("'\"")
        value = value.strip()
        current_key = key
        if not value:
            data[key] = []
            continue
        data[key] = _parse_scalar(value)

    return data


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    return value.strip("'\"")


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _first_paragraph(body: str) -> str:
    lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if lines:
                break
            continue
        if line.startswith("#"):
            continue
        lines.append(line)
    return " ".join(lines)


def _workspace_chain(workspace: Path) -> list[Path]:
    start = Path(workspace).resolve()
    root = _git_root(start)
    chain: list[Path] = []
    current = start
    while True:
        chain.append(current)
        if current == root or current.parent == current:
            break
        current = current.parent
    return chain


def _git_root(start: Path) -> Path:
    current = start
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return start
        current = current.parent


def _extra_roots(env_name: str, runtime: str, scope: str, source: str) -> list[SkillSearchRoot]:
    value = os.getenv(env_name, "")
    if not value:
        return []
    return [
        SkillSearchRoot(runtime=runtime, root=Path(path).expanduser(), scope=scope, source=source)
        for path in value.split(os.pathsep)
        if path.strip()
    ]


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()
