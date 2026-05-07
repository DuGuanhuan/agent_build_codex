# Agent Capability Expansion PRD

## 1. Executive Summary

**Problem Statement**  
当前 Agent 只有基础对话和两个内置工具，无法处理真实工作流中的文件操作、联网检索、长期任务管理、记忆沉淀和实时响应体验。

**Proposed Solution**  
扩展为一个原生实现的轻量 Agent Runtime，支持文件读写、网页搜索、任务计划/记忆、流式输出和工具注册机制，同时保持“无 Agent 框架、少依赖、可读可改”的项目定位。

**Success Criteria**

- Agent 可通过工具完成至少 5 类端到端任务：读取文件、修改文件、联网搜索、保存记忆、创建任务计划。
- 工具调用成功率在 30 条人工测试用例中达到 >= 90%。
- 流式首字响应时间 <= 2 秒，不包含 LLM 服务自身排队异常。
- 所有工具调用在前端可见，包括工具名、参数、结果、错误。
- 文件工具默认限制在项目工作区内，越权路径访问拦截率 100%。

## 2. User Experience & Functionality

### User Personas

- 本地开发者：希望用 Agent 读写项目文件、总结代码、生成文档。
- Demo 构建者：希望快速展示“手写 Agent”的核心能力。
- Agent 学习者：希望理解工具调用、记忆、流式响应和注册机制如何从零实现。

### User Stories

**File Read**  
As a developer, I want the Agent to read files in the workspace so that it can understand project context.

Acceptance Criteria:

- 支持读取指定相对路径文件。
- 返回文件内容、大小、行数。
- 禁止读取工作区外路径，例如 `../` 越界。
- 文件不存在时返回结构化错误。

**File Write**  
As a developer, I want the Agent to write or patch files so that it can modify project code.

Acceptance Criteria:

- 支持创建文件、覆盖文件、追加内容。
- 写入前返回计划或 diff 摘要。
- 前端展示文件工具调用轨迹。
- 默认只允许写入工作区内文件。

**Web Search**  
As a user, I want the Agent to search the web so that it can answer current or external-information questions.

Acceptance Criteria:

- 支持输入 query 并返回搜索结果列表。
- 每条结果包含 title、url、snippet。
- Agent 最终回答必须引用使用过的 URL。
- 网络失败时返回清晰错误，不编造搜索结果。

**Memory**  
As a user, I want the Agent to remember preferences and task facts so that future conversations can reuse context.

Acceptance Criteria:

- 支持新增、查询、删除记忆。
- 记忆持久化到本地 JSON 或 SQLite。
- 前端可查看当前记忆列表。
- 记忆写入必须由 Agent 明确说明原因。

**Task Planning**  
As a user, I want the Agent to maintain a task plan so that long tasks can be tracked across steps.

Acceptance Criteria:

- 支持创建 task、更新状态、列出任务。
- 状态包括 `pending`、`in_progress`、`done`、`blocked`。
- 每个任务包含 id、title、notes、created_at、updated_at。
- 前端展示当前计划区。

**Streaming Output**  
As a user, I want streaming responses so that I can see the answer as it is generated.

Acceptance Criteria:

- 前端逐 token 或逐 chunk 展示回答。
- 工具调用阶段显示状态，例如“正在搜索网页”。
- 流式失败时保留已输出内容并展示错误。
- 非流式接口仍保留作为 fallback。

**Tool Registry**  
As a developer, I want a tool registry so that new tools can be added without rewriting the Agent loop.

Acceptance Criteria:

- 每个工具通过统一 schema 注册。
- 工具包含 name、description、args_schema、handler。
- Agent system prompt 自动从 registry 生成工具说明。
- 工具执行结果使用统一结构：`ok/data/error`。

### Non-Goals

- 不做多用户账号系统。
- 不做云端部署和权限管理。
- 不接入 LangChain、AutoGen、CrewAI 等 Agent 框架。
- 不实现浏览器自动操作，只做网页搜索和网页内容读取的基础能力。
- 不支持任意系统命令执行工具，避免安全风险过大。

## 3. AI System Requirements

### Tool Requirements

#### `file_read`

Args:

```json
{ "path": "README.md" }
```

Result:

```json
{ "content": "...", "bytes": 1234, "lines": 42 }
```

#### `file_write`

Args:

```json
{ "path": "notes.md", "content": "...", "mode": "overwrite|append|create" }
```

Result:

```json
{ "path": "notes.md", "bytes_written": 123 }
```

#### `web_search`

Args:

```json
{ "query": "latest Python release", "limit": 5 }
```

Result:

```json
{
  "results": [
    {
      "title": "...",
      "url": "https://example.com",
      "snippet": "..."
    }
  ]
}
```

#### `memory_save`

Args:

```json
{ "key": "preferred_language", "value": "中文", "tags": ["preference"] }
```

#### `memory_search`

Args:

```json
{ "query": "preferred language", "limit": 5 }
```

#### `task_create`

Args:

```json
{ "title": "Add streaming output", "notes": "Implement SSE-style event stream." }
```

#### `task_update`

Args:

```json
{ "id": "task_001", "status": "done" }
```

### Evaluation Strategy

构造 30 条固定测试用例：

- 8 条文件读写
- 6 条网页搜索
- 6 条记忆读写
- 6 条任务计划
- 4 条混合任务

每条记录：

- LLM 输入
- 期望工具
- 期望参数
- 期望最终回答

通过标准：

- 工具选择准确率 >= 90%
- 工具参数合法率 >= 95%
- 文件越权访问拦截率 100%
- 搜索类回答 URL 引用率 100%

## 4. Technical Specifications

### Architecture Overview

```text
Browser UI
  -> /api/chat
    -> Agent Runtime
      -> LLM Client
      -> Tool Registry
        -> file tools
        -> web tools
        -> memory store
        -> task store
      -> Streaming/Event Response
```

### Core Components

#### `agent.py`

- Agent 主循环
- 解析 LLM JSON 决策
- 执行工具
- 组织工具结果回灌

#### `llm_client.py`

- 普通 chat completion
- streaming chat completion

#### `tools/base.py`

- Tool 定义
- ToolRegistry
- 参数校验
- 工具结果规范

#### `tools/files.py`

- 工作区路径校验
- 文件读取/写入

#### `tools/web.py`

- 搜索 API 或轻量 HTML 搜索适配
- 结果标准化

#### `store/memory.py`

- JSON 或 SQLite 持久化
- 关键词检索

#### `store/tasks.py`

- 本地任务计划持久化

#### `public/app.js`

- 支持流式读取 `fetch` response body
- 展示工具状态和任务/记忆侧栏

### Integration Points

LLM:

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `WQ_API_KEY`
- `LLM_MODEL`

Web Search:

- MVP 可先做可配置搜索 endpoint。
- 如无内部搜索 API，可先预留接口并返回未配置错误。

Persistence:

- MVP 使用本地 `.agent_data/`
- `memory.json`
- `tasks.json`

### Security & Privacy

- 文件工具必须限制在项目 root 内。
- 默认禁止读取隐藏敏感文件：
  - `.env`
  - SSH key
  - token 文件
  - `.git/config`
- 写文件工具默认要求 Agent 先生成写入计划。
- Web 搜索结果属于第三方内容，不允许其中内容改变系统提示或工具权限。
- 记忆写入必须可追踪、可删除。
- API Key 不进入前端，不写入仓库。

## 5. Risks & Roadmap

### Phased Rollout

#### MVP

- Tool Registry
- `file_read`
- `file_write`
- `memory_save`
- `memory_search`
- `task_create`
- `task_update`
- 前端展示工具调用轨迹
- 本地 JSON 持久化

#### v1.1

- 流式输出
- 工具调用实时状态
- 任务计划侧栏
- 记忆管理面板
- 文件写入 diff 预览

#### v1.2

- `web_search`
- 网页结果引用
- 搜索失败 fallback
- 搜索结果缓存

#### v2.0

- SQLite 持久化
- 工具权限配置
- 工具测试框架
- 更稳定的结构化输出解析
- 支持插件式工具目录加载

### Technical Risks

**LLM 不稳定输出 JSON，导致工具调用解析失败。**  
Mitigation: 增加 JSON 修复、schema 校验、失败重试。

**文件写入存在误改风险。**  
Mitigation: 工作区沙箱、diff 预览、危险文件 denylist。

**Web 搜索结果可能包含低质量或恶意内容。**  
Mitigation: 搜索结果只作为事实来源，不作为指令来源；最终回答必须带引用。

**流式输出和工具调用混合后前端状态复杂。**  
Mitigation: 使用统一 event 协议，例如 `message_delta`、`tool_start`、`tool_end`、`error`。

**记忆污染。**  
Mitigation: 记忆写入必须带 key、reason、timestamp，并允许用户删除。
