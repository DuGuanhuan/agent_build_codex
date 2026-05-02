# 手搓 Agent 技术栈文档

## 1. 文档目的

随着项目从轻量 demo 演进为可扩展的个人 Agent 基座，技术栈需要提前定边界：哪些继续沿用，哪些可以引入，哪些暂时不要碰。本文用于约束后续开发选型，避免功能增长后出现前后端框架、状态管理、数据存储、Agent 编排和测试工具各自分叉。

核心原则：

- 先稳定主链路，再引入复杂基础设施。
- 优先使用当前已有技术栈，保持学习和调试成本低。
- 新依赖必须解决明确问题，而不是为了“看起来更工程化”。
- 所有关键选型都要有升级触发条件，避免过早重构。

## 2. 当前已采用技术栈

| 层级 | 当前技术 | 状态 | 说明 |
| --- | --- | --- | --- |
| 后端语言 | Python 3 | 已采用 | 用于 Agent 主循环、模型调用、工具执行。 |
| 后端 HTTP 服务 | Python 标准库 `http.server` | 已采用 | 当前足够支撑本地 demo、JSON API 和静态文件服务。 |
| LLM 接入协议 | OpenAI-compatible Chat Completions | 已采用 | 统一接入智谱、DeepSeek、万擎等 provider。 |
| Agent 协议 | 自定义 JSON 决策协议 | 已采用 | 模型输出 `tool` 或 `final` JSON，由后端执行工具循环。 |
| 前端框架 | Next.js 16 App Router | 已采用 | 负责 React UI 和 API Route 代理。 |
| 前端语言 | TypeScript | 已采用 | 约束消息、模型、工具步骤等核心类型。 |
| UI 框架 | React 19 | 已采用 | 构建聊天界面、模型选择器、工具步骤面板。 |
| 样式 | Tailwind CSS 4 | 已采用 | 当前 UI 快速实现和响应式布局。 |
| 图标 | `lucide-react` | 已采用 | 用于工具、发送、模型等按钮图标。 |
| Markdown 渲染 | `react-markdown` + `remark-gfm` + `rehype-sanitize` | 已采用 | 安全渲染模型回答。 |
| 旧版前端 | 原生 HTML/CSS/JS | 保留 | 作为轻量参考实现，不作为主迭代方向。 |
| 配置 | 环境变量 | 已采用 | 管理 API Key、默认模型、provider base URL、端口。 |

## 3. 推荐目标技术栈

### 3.1 前端

继续使用：

- Next.js App Router
- React
- TypeScript
- Tailwind CSS
- `lucide-react`
- `react-markdown` + `remark-gfm` + `rehype-sanitize`

短期不引入：

- 全局状态库，如 Redux、Zustand、Jotai。
- 大型 UI 组件库。
- GraphQL。
- 前端数据库。

引入条件：

| 技术 | 触发条件 | 建议 |
| --- | --- | --- |
| Zustand | 会话、设置、运行中任务、工具 approval 等状态跨多个页面/组件共享，props 传递明显变乱。 | P1/P2 后再评估。 |
| shadcn/ui | 表单、对话框、菜单、侧栏、Tabs 等组件明显增多，自己维护交互细节成本上升。 | 只按需复制组件，不整体重写 UI。 |
| Playwright | 需要自动验证完整用户路径，如选择模型、发送消息、查看工具步骤、停止生成。 | P2 引入端到端测试。 |

前端状态策略：

- P0：继续用组件内 `useState/useEffect`。
- P1：会话历史先用 `localStorage` + 自定义 hooks。
- P2：如果状态跨页面复杂，再引入轻量 store。

### 3.2 后端

当前继续使用：

- Python 标准库 HTTP 服务。
- `urllib.request` 调用 OpenAI-compatible provider。
- 单进程 Agent Runner。
- 环境变量配置。

短期建议补充：

- `pytest`：后端核心单测。
- Python `dataclasses`：拆分后端模块后，用于模型、工具和 step 的内部结构。

暂缓引入：

- FastAPI。
- Celery/RQ 等任务队列。
- LangChain/LangGraph 等 Agent 框架。
- SQLAlchemy。
- Redis。

升级条件：

| 技术 | 触发条件 | 建议 |
| --- | --- | --- |
| FastAPI + Uvicorn | SSE、文件上传、请求校验、OpenAPI 文档、并发取消和中间件复杂度明显上升。 | P2 之后迁移更合适。 |
| `httpx` | provider 调用需要 async、stream、连接池、细粒度 timeout。 | 实现真实 provider 流式时引入。 |
| Pydantic | API 请求/响应、工具 schema、模型配置结构开始复杂且需要强校验。 | FastAPI 前后均可独立引入。 |
| SQLite | 会话历史、trace、配置需要服务端持久化。 | P2/P3 引入，优先本地单文件。 |
| Redis | 需要跨进程任务状态、缓存、队列或多人使用。 | 云端/团队版再考虑。 |

后端模块化目标：

```text
server.py
agent/
  runner.py
  protocol.py
  context.py
models/
  registry.py
  providers.py
tools/
  registry.py
  builtin.py
tests/
```

迁移节奏：

- P0 先加测试，不急着拆文件。
- P1 做流式和停止生成时，可先抽出 `agent/protocol.py` 和 `tools/registry.py`。
- P2 新增文件/网页/仓库工具时，再正式拆分工具目录。

### 3.3 Agent 编排

继续使用：

- 自定义 Agent Runner。
- 自定义 JSON 决策协议。
- OpenAI-compatible chat completions。

暂不引入：

- LangChain。
- LangGraph。
- AutoGen。
- CrewAI。

原因：

- 当前产品目标是学习和掌控 Agent 核心链路。
- 工具调用、模型路由、上下文管理还处于可手写阶段。
- 引入框架会隐藏关键机制，增加 debug 成本。

重新评估条件：

- 需要复杂 DAG、可恢复任务、人类审批节点和长期运行任务。
- 多 Agent 协作成为核心能力。
- 自研 runner 的状态管理和恢复逻辑明显超过维护能力。

若未来引入，优先考虑：

- LangGraph：适合状态图、计划模式、审批节点和可恢复执行。

### 3.4 数据存储

阶段策略：

| 阶段 | 存储 | 用途 |
| --- | --- | --- |
| P0 | 浏览器内存 | 当前聊天消息。 |
| P1 | `localStorage` | 会话历史、当前选中模型、轻量用户偏好。 |
| P2 | SQLite | 服务端会话、trace、配置、工具运行记录。 |
| P3 | SQLite + 可选向量存储 | 知识库、文档索引、长期记忆。 |

短期不使用：

- Postgres。
- MongoDB。
- Redis。
- 云数据库。

引入 SQLite 的触发条件：

- 需要跨刷新、跨浏览器或服务端统一保存会话。
- trace 和工具调用记录需要查询。
- 配置页面需要持久化 provider、模型可见性、默认模型。

### 3.5 流式与实时通信

推荐：

- P1 使用 Server-Sent Events。
- 前端通过 `fetch` + `ReadableStream` 读取流式响应。
- 后端提供 `/api/chat/stream`，保持 `/api/chat` 非流式 fallback。

暂不使用：

- WebSocket。
- Socket.IO。

原因：

- 当前主要是服务端单向推送 token、工具步骤和完成事件。
- SSE 复杂度低，足够支撑聊天流式输出。

WebSocket 引入条件：

- 需要真正双向实时控制。
- 工具执行过程中频繁交互确认。
- 多任务并发、任务订阅、跨设备状态同步成为核心需求。

### 3.6 测试工具

推荐测试栈：

| 层级 | 工具 | 引入阶段 | 覆盖内容 |
| --- | --- | --- | --- |
| 后端单测 | `pytest` | P0 | calculator、JSON 解析、模型配置、工具执行、Agent Runner。 |
| 前端静态检查 | ESLint + TypeScript | 已有 | 类型、React/Next.js 规则、基础代码质量。 |
| 前端构建 | `next build` | 已有 | 生产构建和类型集成问题。 |
| E2E | Playwright | P2 | 模型选择、发送消息、工具步骤、停止生成。 |

短期不引入：

- Jest/Vitest 组件测试。
- Storybook。
- 视觉回归测试。

引入条件：

- 组件数量增多，交互状态复杂。
- UI 回归成本明显高于手工验证。

### 3.7 质量与格式化

当前：

- 前端已有 ESLint。
- 后端暂无统一 lint/format。

建议：

- 前端继续使用 `npm run lint` 和 `npm run build` 作为最低验收。
- 后端 P0 先引入 `pytest`。
- 后端模块拆分后，再考虑 `ruff` 做 lint 和 format。

暂不强推：

- Prettier。
- Black。
- mypy。

原因：

- 当前代码量小，先把测试保护补起来收益更高。
- 后续文件拆分后再统一格式工具，迁移成本更低。

## 4. 依赖引入规则

新增依赖前必须回答：

- 它解决哪个当前明确问题？
- 是否能用现有标准库或已有依赖解决？
- 是否影响本地启动复杂度？
- 是否会把核心 Agent 逻辑藏进框架？
- 是否有清晰的替代和退出路径？

默认允许：

- 小型、稳定、职责单一的工具库。
- 测试和开发工具。
- 安全相关依赖，如 sanitizer、schema validator。

默认谨慎：

- Agent 大框架。
- 大型 UI 组件库。
- 数据库 ORM。
- 分布式任务队列。
- 需要额外本地服务的依赖。

## 5. 环境与配置

继续使用环境变量作为基础配置方式：

```bash
ZAI_API_KEY="..."
ZHIPU_API_KEY="..."
DEEPSEEK_API_KEY="..."
WQ_API_KEY="..."
DEFAULT_MODEL_ID="zhipu-glm-4.7-flash"
PORT=8000
AGENT_BACKEND_URL="http://127.0.0.1:8000"
```

后续配置演进：

| 阶段 | 方式 | 用途 |
| --- | --- | --- |
| P0 | 环境变量 | API Key、端口、默认模型。 |
| P1 | 环境变量 + 前端本地偏好 | 选中模型、会话历史。 |
| P2 | SQLite 配置表 | provider、base URL、默认模型、可见模型。 |
| P3 | 加密存储 | API Key、安全配置、多用户场景。 |

安全要求：

- API Key 不进入前端 bundle。
- API Key 不写入 localStorage。
- 后端错误不返回完整认证头。
- 配置页面出现前，API Key 继续只从环境变量读取。

## 6. 推荐版本基线

当前前端版本以 `frontend/package.json` 为准：

| 依赖 | 当前版本 |
| --- | --- |
| Next.js | `16.2.4` |
| React | `19.2.4` |
| React DOM | `19.2.4` |
| TypeScript | `^5` |
| Tailwind CSS | `^4` |
| ESLint | `^9` |
| `lucide-react` | `^1.14.0` |
| `react-markdown` | `^10.1.0` |
| `remark-gfm` | `^4.0.1` |
| `rehype-sanitize` | `^6.0.0` |

后端版本基线：

- Python 3.11+ 优先。
- 当前保持标准库优先。
- 后续新增依赖先写入文档，再更新安装说明。

## 7. 不推荐的技术路径

短期不建议：

- 一开始就把后端迁到完整微服务架构。
- 为了 Agent 能力直接套 LangChain/LangGraph。
- 为会话历史直接上 Postgres 或云数据库。
- 为简单流式输出直接上 WebSocket。
- 为模型列表和工具步骤引入大型 UI 组件库。
- 同时维护原生前端和 Next.js 前端的完整功能等价。

原因：

- 当前核心风险不是“基础设施不够高级”，而是 Agent 主链路、工具系统、模型路由和用户体验还需要打磨。
- 过早引入重型技术会让调试路径变长，也会削弱这个项目作为学习型 Agent 基座的价值。

## 8. 技术栈决策记录

| 决策 | 当前结论 | 复盘时间 |
| --- | --- | --- |
| 后端框架 | 继续 Python 标准库，暂不迁 FastAPI。 | P1 流式输出完成后复盘。 |
| Agent 框架 | 继续自研 Runner，暂不引入 LangChain/LangGraph。 | P2 计划模式启动前复盘。 |
| 数据库 | P1 前不引入数据库，会话先放本地。 | 会话历史 MVP 完成后复盘。 |
| 实时通信 | P1 使用 SSE，不使用 WebSocket。 | 工具 approval 做到交互式时复盘。 |
| 状态管理 | 继续 React 本地状态，暂不引入 Zustand。 | 会话侧栏和配置页增加后复盘。 |
| 测试 | P0 优先引入 pytest，前端保留 lint/build。 | 后端单测覆盖主链路后复盘。 |

## 9. 结论

建议现在就固定技术栈文档，但不要把技术栈定死。当前阶段最合理的路线是：

- 前端继续 Next.js + React + TypeScript + Tailwind。
- 后端继续 Python 标准库，先补测试和模块边界。
- Agent 编排继续自研，保留 JSON 决策协议。
- 流式输出优先用 SSE。
- 会话历史先用 localStorage，服务端持久化再用 SQLite。
- 只有当复杂度真实出现时，再引入 FastAPI、Pydantic、httpx、Zustand、Playwright、SQLite 等工具。

这套策略能让项目继续保持“手搓 Agent”的透明度，同时为后续变大留出清晰升级路径。
