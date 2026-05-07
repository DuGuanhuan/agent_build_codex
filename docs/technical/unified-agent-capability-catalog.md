# 统一 Agent Skill / Tool 管理实现说明

## 1. 背景

项目已经支持三类 Agent Runtime：

| Runtime | 说明 |
| --- | --- |
| `handmade` | 项目内置手搓 Agent，工具和技能都由本项目 registry 管理。 |
| `opencode` | 通过 OpenCode serve adapter 接入的原生 coding agent。 |
| `claude-code` | 通过 Claude Code headless CLI adapter 接入的原生 coding agent。 |

此前“技能与工具管理”页面只展示 `handmade` 的工具和技能，导致两个问题：

1. 用户切换到 OpenCode / Claude Code 后，看不到当前底层 Agent 到底具备哪些工具能力。
2. 前端容易继续围绕手搓 Agent 的 schema 生长特殊逻辑，后续接入 OpenClaw、Gemini CLI、Codex CLI 时会继续分叉。

因此本轮引入一层统一 capability catalog，让所有 runtime 都能用同一种结构对外声明自己的工具和技能。

## 2. 设计目标

| 目标 | 说明 |
| --- | --- |
| 统一展示 | 前端按 runtime 展示 Handmade、OpenCode、Claude Code 的 tools / skills。 |
| 保持兼容 | `/api/tools` 和 `/api/skills` 保留原有 `tools` / `skills` 字段，旧调用方不需要立刻改。 |
| 不混淆所有权 | Handmade 技能可编辑；OpenCode / Claude Code 原生能力只读展示。 |
| 可扩展 | 新 runtime 只要实现 `tool_catalog()` / `skill_catalog()`，前端即可自动显示。 |
| 不影响执行链路 | catalog 只描述能力，不改变 runtime 调用、工具执行、权限审批和流式输出逻辑。 |

## 3. 后端实现

### 3.1 Runtime 基类扩展

`runtimes/base.py` 中的 `AgentRuntime` 新增两个可选方法：

```python
def tool_catalog(self) -> list[dict[str, Any]]:
    return []

def skill_catalog(self) -> list[dict[str, Any]]:
    return []
```

默认返回空数组，避免老 runtime 被迫实现。

### 3.2 Handmade Runtime

`runtimes/handmade.py` 通过构造函数接收两个 catalog provider：

```python
HandmadeRuntime(
    run_agent,
    get_model_config,
    public_tool_options,
    public_skill_options,
)
```

它把项目内原有 `tools.registry.get_tools_schema()` 和 `skill_manager.skills` 转成统一结构，并补充来源字段：

```json
{
  "runtime": "handmade",
  "source": "workbuddy-registry",
  "editable": false,
  "native": false
}
```

技能则标记为：

```json
{
  "runtime": "handmade",
  "source": "workbuddy-skills",
  "editable": true,
  "native": false
}
```

这表示 Handmade 工具只读展示，Handmade 技能可通过本项目页面编辑。

### 3.3 OpenCode Runtime

`runtimes/opencode_serve.py` 静态声明 OpenCode 原生 tool 能力：

| Tool | 说明 |
| --- | --- |
| `bash` | 执行 shell 命令。 |
| `read` | 读取文件。 |
| `edit` | 编辑或写入文件。 |
| `grep` | 搜索文件内容。 |
| `glob` | 按模式匹配路径。 |
| `webfetch` | 读取公开网页。 |
| `websearch` | 联网搜索。 |
| `task` | 启动 OpenCode 子 Agent / 子任务。 |
| `skill` | 调用 OpenCode 原生 skill 机制。 |

OpenCode skill catalog 由 `runtimes/skill_scanner.py` 扫描真实 `SKILL.md` 文件生成。当前扫描目录：

| 作用域 | 目录 |
| --- | --- |
| project | `<workspace>/.opencode/skills/*/SKILL.md` |
| project compatible | `<workspace>/.claude/skills/*/SKILL.md` |
| project compatible | `<workspace>/.agents/skills/*/SKILL.md` |
| user | `~/.config/opencode/skills/*/SKILL.md` |
| user compatible | `~/.claude/skills/*/SKILL.md` |
| user compatible | `~/.agents/skills/*/SKILL.md` |
| configured | `OPENCODE_SKILL_DIRS` 环境变量指定的目录 |

扫描结果统一标记为：

```json
{
  "runtime": "opencode",
  "source": "filesystem_scan",
  "source_detail": "opencode-global",
  "scope": "user",
  "standard": "agent-skills",
  "path": "/Users/airr/.config/opencode/skills/foo/SKILL.md",
  "editable": false,
  "native": true
}
```

### 3.4 Claude Code Runtime

`runtimes/claude_code.py` 静态声明 Claude Code 原生 tool 能力：

| Tool | 说明 |
| --- | --- |
| `Bash` | 执行 shell 命令。 |
| `Read` | 读取文件。 |
| `Write` | 创建或覆盖文件。 |
| `Edit` | 编辑文件。 |
| `MultiEdit` | 批量编辑同一文件。 |
| `Glob` | 文件路径匹配。 |
| `Grep` | 仓库内容搜索。 |
| `WebFetch` | 读取公开网页。 |
| `WebSearch` | 联网搜索。 |
| `Task` | 启动 Claude Code 子 Agent。 |
| `AskUserQuestion` | 暂停并向用户提出结构化问题。 |
| `TodoWrite` | 维护 Claude Code 原生 todo / plan。 |

Claude Code skill catalog 由 `runtimes/skill_scanner.py` 扫描真实 `SKILL.md` 文件生成。当前扫描目录：

| 作用域 | 目录 |
| --- | --- |
| project | `<workspace>/.claude/skills/*/SKILL.md` |
| user | `~/.claude/skills/*/SKILL.md` |
| configured | `CLAUDE_CODE_SKILL_DIRS` 环境变量指定的目录 |

扫描结果统一标记为：

```json
{
  "runtime": "claude-code",
  "source": "filesystem_scan",
  "source_detail": "claude-code-personal",
  "scope": "user",
  "standard": "agent-skills",
  "path": "/Users/airr/.claude/skills/foo/SKILL.md",
  "editable": false,
  "native": true
}
```

### 3.5 Runtime Registry 聚合

`runtimes/registry.py` 新增：

```python
def public_runtime_catalog() -> dict:
    default_runtime = get_runtime()
    return {
        "runtimes": [
            {
                **runtime.public_info(default_runtime.id),
                "tools": runtime.tool_catalog(),
                "skills": runtime.skill_catalog(),
            }
            for runtime in _runtime_options
        ],
        "default": default_runtime.id,
    }
```

它把 runtime 元信息、capabilities、tools、skills 放到同一个结构中。

### 3.6 HTTP API 输出

`server.py` 中 `/api/tools` 输出：

```json
{
  "tools": [
    {
      "name": "file_read",
      "description": "...",
      "permission": "read_user_file",
      "parameters": {},
      "runtime": "handmade",
      "source": "workbuddy-registry",
      "editable": false,
      "native": false
    }
  ],
  "runtimes": [
    {
      "id": "handmade",
      "label": "手搓 Agent",
      "available": true,
      "capabilities": {},
      "tools": [],
      "skills": []
    }
  ],
  "default": "handmade"
}
```

`/api/skills` 输出形态相同，只是顶层 flattened 字段为 `skills`。

兼容策略：

- 顶层 `tools` / `skills` 继续保留，方便已有前端逻辑直接消费。
- 新增 `runtimes`，用于前端做 runtime 过滤、计数和分组展示。
- `runtimes[].tools` 和 `runtimes[].skills` 是每个 runtime 自己声明的原生列表。

## 4. 前端实现

### 4.1 类型定义

`frontend/src/lib/types.ts` 扩展：

```ts
export type ToolOption = {
  name: string;
  description: string;
  permission: string;
  parameters: {...};
  runtime?: string;
  source?: string;
  editable?: boolean;
  native?: boolean;
};
```

```ts
export type SkillOption = {
  name: string;
  description: string;
  type: "hook" | "invocable" | "native" | string;
  paths: string[];
  trigger_words: string[];
  instructions: string;
  runtime?: string;
  source?: string;
  editable?: boolean;
  native?: boolean;
};
```

新增：

```ts
export type RuntimeCatalogOption = RuntimeOption & {
  tools?: ToolOption[];
  skills?: SkillOption[];
};
```

### 4.2 页面行为

`frontend/src/components/skill-manager-view.tsx` 当前行为：

1. 并发请求 `/api/skills` 和 `/api/tools`。
2. 保存 flattened `skills`、`tools` 和 runtime catalog。
3. 顶部展示 runtime filter：
   - 全部 Agent
   - 手搓 Agent
   - OpenCode
   - Claude Code
4. 技能页：
   - Handmade 技能可新建、编辑、删除。
   - OpenCode / Claude Code 技能只读展示。
5. 工具页：
   - 按 runtime 展示所有工具。
   - 显示 `permission`、`source`、必填参数和 native 标识。

核心判断：

```ts
function isEditableSkill(skill: SkillOption | null) {
  return Boolean(skill && skill.runtime === "handmade" && skill.editable !== false && !skill.native);
}
```

这样可以防止用户在 WorkBuddy 页面误编辑 OpenCode / Claude Code 的原生配置。

## 5. 当前边界

### 5.1 Catalog 是描述层，不是执行层

本实现只是统一展示各 runtime 的工具和技能目录，不改变实际调用逻辑：

- Handmade 工具仍由 `tools/registry.py` 执行。
- OpenCode 工具仍由 OpenCode serve 原生执行。
- Claude Code 工具仍由 Claude Code CLI 原生执行。

### 5.2 Tool 与 Skill 的真实来源不同

OpenCode / Claude Code 的 tool catalog 目前仍由 adapter 静态声明，后续应升级为 runtime 原生 introspection。

OpenCode / Claude Code 的 skill catalog 已改为文件扫描，来源是真实存在的 `SKILL.md`。scanner 只读取 frontmatter 和正文摘要，不执行 `SKILL.md` 里的动态命令，也不读取 skill 目录下的 scripts/references/assets。

### 5.3 原生技能只读

OpenCode / Claude Code 的技能、slash command、subagent、project memory 通常由它们自己的配置文件和运行时管理。本项目目前只做可视化，不直接编辑这些外部系统配置。

## 6. 验证方式

后端单测覆盖：

```bash
python3 -m unittest discover -s tests
```

新增测试会确认：

- catalog 中包含 `handmade`、`opencode`、`claude-code`。
- tools 中包含 Handmade `file_read`、OpenCode `bash`、Claude Code `AskUserQuestion`。
- skill scanner 能读取 `SKILL.md` frontmatter，并按 Claude/OpenCode 官方和兼容目录发现项目技能。

前端验证：

```bash
cd frontend
npm run lint
npm run build
```

接口手动检查：

```bash
curl -s http://127.0.0.1:8000/api/tools
curl -s http://127.0.0.1:8000/api/skills
```

期望看到顶层 `runtimes`，且 flattened `tools` / `skills` 中的条目带有 `runtime` 字段。

## 7. 后续可改进方向

### 7.1 动态 introspection

当前 OpenCode / Claude Code 的 tool catalog 是静态声明。后续可以升级为：

| Runtime | 可能方案 |
| --- | --- |
| OpenCode | 从 OpenCode serve API 或 CLI 读取真实 tools、agents、MCP、commands。 |
| Claude Code | 从 CLI/settings/MCP/agents 信息组合真实 tools。 |
| OpenClaw / Gemini CLI / Codex CLI | 为每个 adapter 实现自己的 `tool_catalog()` introspection。 |

这会让页面从“能力说明”变成真正的“运行时能力观测面板”。

### 7.2 统一 Capability Schema v1

建议后续把 tool / skill catalog 从自由 dict 固化成后端 dataclass 或 pydantic-like schema：

```text
RuntimeCapability
  id
  runtime
  kind: tool | skill | command | subagent | mcp
  name
  description
  source
  permission
  editable
  native
  input_schema
  config_path
  docs_url
  status
```

这样可支持更细的能力类型：MCP server、slash command、subagent、hook、memory、permission rule。

### 7.3 原生配置编辑

当前只读是更安全的阶段。后续可以按 runtime 分别支持编辑：

| 能力 | 后续可能实现 |
| --- | --- |
| Handmade Skill | 当前已支持编辑。 |
| OpenCode Skill / Agent | 读取并编辑 OpenCode 配置文件，保存前展示 diff。 |
| Claude Code Subagent | 读取并编辑 Claude Code subagent markdown 配置。 |
| Claude Code Project Memory | 编辑 `CLAUDE.md` / `AGENTS.md`，并走文件 diff 和确认。 |

这部分需要非常明确的文件所有权和回滚机制，否则容易破坏外部 runtime 的原生配置。

### 7.4 权限管理统一化

现在 catalog 只是展示 `permission` 字符串，真正权限仍在各 runtime 内部。后续可以做一层统一权限视图：

- read / write / shell / network / subagent / user_input
- 是否需要确认
- 是否允许跨工作区
- 是否允许联网
- 是否允许长期记忆写入
- 当前会话是否已信任

这样用户可以在一个页面理解“当前选中的 Agent 到底能做什么”。

### 7.5 能力健康检查

Runtime 可用性现在只显示 `available` 和 `unavailable_reason`。后续可以增加健康检查：

- CLI 是否存在。
- serve 进程是否可用。
- provider API key 是否可用。
- 模型是否支持当前 runtime。
- 原生工具是否能实际执行。
- workspace 权限是否正常。

对应前端可以展示“能力可用 / 配置缺失 / 运行中异常”。

### 7.6 与 Runtime Protocol v1 打通

当前 runtime protocol 已统一文本流、工具事件、artifact、turn。下一步可以让 capability catalog 和 runtime event/artifact 协议完全对齐：

- `tool_start.tool` 可以关联到 catalog 中的 tool id。
- `artifact.type=todo` 可以关联到 runtime 的 todo capability。
- `AskUserQuestion` 可以作为 `kind=user_input` 的 capability 展示。
- subagent 调用可以作为 `kind=subagent` 的 capability 展示，并在 workbench 中展开子任务轨迹。

这样前端 workbench、工具页、技能页就会成为同一套协议的不同视图，而不是彼此独立的 UI。

## 8. 推荐迭代顺序

1. 固化 `Capability Schema v1`，避免继续用松散 dict。
2. 为 OpenCode 增加 tool 动态 introspection，优先读取 tools / agents / MCP。
3. 为 Claude Code 增加 tool 动态 introspection，展示真实启用 tools / MCP / agents。
4. 增加 capability health check，区分“声明存在”和“实际可用”。
5. 支持只读 diff 预览后编辑外部 runtime 配置。
6. 将 capability 与 RuntimeEvent / RuntimeArtifact / Turn 关联，形成完整 workbench 体验。
