# Agent Skill 落地实现技术方案报告

> 当前状态说明：本文最初是技能系统方案调研。代码已经落地了 MVP 版本，实际实现以 `skills/manager.py`、`tools/registry.py` 和 `server.py` 为准。当前已支持 `hook` / `invocable`、`skills/` 目录扫描、`invoke_skill`、`skill_create`、`skill_delete`、前端技能管理页和 `` !`cmd` `` 安全观察命令。当前 YAML 解析器是轻量实现，只可靠支持扁平字段；本文早期示例里的 `activation_rules`、`allowed_tools`、嵌套 activation 结构属于后续可演进方向，不是当前可直接使用的 schema。

## 1. 概述与定义

在 AI Agent 领域，“技能（Skill）”是赋予 Agent 特定领域专业能力的核心机制。它不同于基础的“工具（Tool）”，工具解决的是“连接（Connectivity）”和“动作（Action）”的问题（如读文件、发请求），而技能解决的是“认知（Cognitive）”和“流程（Process）”的问题（如如何进行代码评审、如何编写 PR 描述）。

### 核心区分
*   **工具 (Tools)**: 基础设施层。解决“能做什么”。（例：`shell_exec`, `file_write`）
*   **技能 (Skills)**: 认知/策略层。解决“怎么做”。（例：`CodeReviewSkill`, `BugFixSkill`）

---

## 2. 业界主流产品调研

### 2.1 Anthropic MCP (Model Context Protocol) — 连接标准化
MCP 是 Anthropic 推出的开放协议，旨在标准化 Agent 与外部数据/工具的连接。
*   **核心逻辑**: 通过 JSON-RPC 2.0 暴露 Tools, Resources 和 Prompts。
*   **价值**: 实现了技能的“可插拔”。Agent 可以动态连接到一个“天气 MCP Server”或“GitHub MCP Server”来瞬间获得新能力。

### 2.2 Claude Code — 声明式双轨技能机制 (深度解析)
通过对 Claude Code 源码 (`src/skills`, `src/tools/SkillTool`) 的深度分析，其技能机制采用了“自动感知”与“主动调用”的双轨并行模式：

*   **自动感知激活 (Passive/Contextual Activation)**:
    *   **触发源**: 埋点于 `FileReadTool`, `FileWriteTool` 等基础工具。当 Agent 执行读写操作时，系统自动匹配路径。
    *   **逻辑**: 命中后将技能指令注入下轮对话的 System Prompt。LLM 无需感知，直接获得该领域的“经验”注入。
*   **主动调用激活 (Active/Tool-based Activation)**:
    *   **触发源**: LLM 通过 `SkillTool` 主动发起调用。
    *   **逻辑**: LLM 拥有一个“技能清单”，根据用户意图（如“生成提交信息”）调用对应技能。系统随后将指令展开并注入。这适用于有明确目的的功能性任务。

### 2.3 OpenAI GPTs — 指令 + Actions
*   **Actions**: 通过 OpenAPI 规范（JSON/YAML）将外部 API 包装成技能。
*   **Knowledge**: 通过 RAG 注入领域文档。

---

## 3. “手搓 Agent” 技能架构设计方案

基于本项目（Python 后端 + Next.js 前端）的架构，建议采用**声明式技能系统**，并参考 Claude Code 的优点。

### 3.1 技能 definition 规范 (`Skill Definition`)
技能以文件夹形式组织在 `skills/` 目录下：
```text
skills/
  ├── code-reviewer/
  │   ├── skill.yaml     # 元数据
  │   └── instructions.md # 核心指令（支持变量和嵌入式命令）
  └── git-expert/
      ├── skill.yaml
      └── instructions.md
```

#### 当前可用的 `skill.yaml` 示例：
```yaml
name: "code-reviewer"
description: "分析代码变更并提供重构建议"
type: "hook"
paths:
  - "*.ts"
  - "*.py"
trigger_words:
  - "review"
  - "check"
```

当前轻量解析器暂不支持嵌套 `activation_rules`，也不会读取 `allowed_tools` 做权限隔离。

#### `instructions.md` 示例：
```markdown
你现在是一名资深架构师。请遵循以下准则进行评审：
1. 检查代码是否符合项目的 lint 规范。
2. 当前系统的 Git 状态如下：
   !`git status --short`  # 动态注入上下文
3. 重点关注性能开销。
```

### 3.2 核心技术组件

#### 1. 技能管理器 (`Skill Manager`)
*   **注册表**: 缓存所有技能元数据（名称、描述、激活规则、类型）。
*   **类型区分**: `Hook` 类（自动激活） vs `Invocable` 类（主动调用）。

#### 2. 上下文注入引擎 (`Context Augmentation Engine`)
*   **Pre-flight 检查**: 在 `run_agent` 准备消息阶段，扫描当前上下文路径，自动合并匹配的 `Hook` 技能指令。
*   **指令渲染**: 执行指令中的嵌入式 Shell 命令 (`` !`cmd` ``)，并处理变量替换。

#### 3. 技能工具 (`SkillTool`)
*   **工具暴露**: 作为一个标准 Tool 注册到 `registry.py`。
*   **动态描述**: 工具的描述由所有 `Invocable` 技能的简介组合而成，供 LLM 进行意图匹配。

---

## 4. 落地路线图 (Roadmap)

### 第一阶段：静态指令技能 (MVP)
*   实现 `skills/` 目录扫描。（已实现）
*   支持简单的 `instructions.md` 注入到 System Prompt。（已实现，基于路径 hook）
*   在前端提供技能管理入口。（已实现，可创建、编辑、删除技能）

### 第二阶段：动态上下文注入
*   实现嵌入式命令执行（`` !`cmd` ``）。（已实现，仅允许安全观察类命令）
*   支持元数据中的 `paths` 规则，实现根据操作文件自动切换技能。（已实现，当前主要基于文件路径匹配）
*   支持嵌套 YAML schema、校验和更好的错误提示。（未实现）

### 第三阶段：MCP 兼容与外部扩展
*   增加 `mcp_client`，支持连接外部 MCP 服务器作为技能来源。
*   支持技能的“热插拔”和在线下载。

---

## 5. 结论

通过引入“声明式技能”机制，我们可以将 Agent 从一个“通用的聊天机器人”转变为一个“拥有多个专业领域的专家团”。这不仅能提升回复的专业度，还能通过 `paths` 匹配大幅减少 Token 浪费，让 Agent 的思考更聚焦。

---
*报告人: Antigravity*
*日期: 2026-05-04*
