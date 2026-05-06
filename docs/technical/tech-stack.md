# 手搓 Agent 技术栈文档

## 1. 文档目的

本文记录当前项目实际采用的技术栈和后续引入新技术的边界，避免功能扩展后前端、后端、Agent 编排、工具系统、技能系统和部署方式各自分叉。

核心原则：

- 优先稳定主链路，再引入复杂基础设施。
- 新依赖必须解决当前明确问题。
- Agent 核心机制尽量保持可读和可调试。
- 技术升级要有触发条件，不为“工程感”提前重构。

## 2. 当前已采用技术栈

| 层级 | 当前技术 | 状态 | 说明 |
| --- | --- | --- | --- |
| 后端语言 | Python 3 | 已采用 | Agent 主循环、模型调用、工具执行、技能管理。 |
| 后端 HTTP 服务 | Python 标准库 `http.server` | 已采用 | JSON API、SSE、旧版静态文件服务。 |
| LLM 接入协议 | OpenAI-compatible Chat Completions | 已采用 | 智谱、DeepSeek、万擎、小米 MiMo 共用。 |
| 流式输出 | Server-Sent Events + provider `stream: true` | 已采用 | 工具决策后，最终回答逐 token 输出。 |
| Agent 协议 | 自定义 JSON 决策协议 | 已采用 | 模型输出 `tool` 或 `final` JSON，由后端执行工具循环。 |
| 工具系统 | 自研 `tools/registry.py` | 已采用 | 工具 schema、权限、handler、安全策略集中注册。 |
| 技能系统 | 自研 `skills/manager.py` | 已采用 | `hook` 自动注入与 `invocable` 主动调用。 |
| 前端框架 | Next.js 16 App Router | 已采用 | React UI 和 API Route 代理。 |
| 前端语言 | TypeScript | 已采用 | 消息、模型、工具、技能类型。 |
| UI 框架 | React 19 | 已采用 | 聊天、模型选择、工具步骤、技能管理。 |
| 样式 | Tailwind CSS 4 | 已采用 | 响应式布局和组件样式。 |
| 图标 | `lucide-react` | 已采用 | 聊天、工具、模型、导航按钮图标。 |
| Markdown 渲染 | `react-markdown` + `remark-gfm` + `rehype-sanitize` | 已采用 | 安全渲染模型回答。 |
| 状态存储 | `localStorage` | 已采用 | 会话、活跃会话、选中模型、摘要、会话级信任工具。 |
| 测试 | Python `unittest`、ESLint、Next build | 已采用 | 后端核心单测，前端静态检查和生产构建。 |
| 部署 | Docker Compose + Caddy | 已采用 | 后端、前端、HTTPS 反向代理三容器。 |
| 旧版前端 | 原生 HTML/CSS/JS | 保留 | 位于 `public/`，仅作轻量参考。 |
| 配置 | 环境变量 | 已采用 | API Key、默认模型、provider base URL、端口、域名。 |

## 3. 当前依赖基线

前端以 `frontend/package.json` 为准：

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
| `clsx` | `^2.1.1` |
| `tailwind-merge` | `^3.5.0` |

后端当前保持标准库优先。`skills/manager.py` 中有 `yaml` 可选导入，但当前实际解析使用 `_parse_yaml_lite`，没有强依赖 PyYAML。

## 4. 环境变量

基础变量：

```bash
HOST=127.0.0.1
PORT=8000
DEFAULT_MODEL_ID=zhipu-glm-4.7-flash
LLM_MAX_TOKENS=2048
AGENT_BACKEND_URL=http://127.0.0.1:8000
```

Provider key：

```bash
ZAI_API_KEY=...
ZHIPU_API_KEY=...
DEEPSEEK_API_KEY=...
WQ_API_KEY=...
MIMO_API_KEY=...
TAVILY_API_KEY=...
```

Provider 配置：

```bash
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
DEEPSEEK_BASE_URL=https://api.deepseek.com
WQ_BASE_URL=http://wanqing.internal/api/gateway/v1/endpoints
WQ_MODEL=ep-cvhcjv-1776239525862887187
WQ_CONTEXT_WINDOW_TOKENS=128000
WQ_MAX_OUTPUT_TOKENS=2048
MIMO_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1
MIMO_CONTEXT_WINDOW_TOKENS=128000
```

部署变量：

```bash
APP_DOMAIN=agent.example.com
```

安全要求：

- API Key 不进入前端 bundle。
- API Key 不写入 `localStorage`。
- `.env.production` 不提交到仓库。
- 前端只消费模型 `available` 状态，不读取 key。

## 5. 推荐继续沿用的技术

### 前端

继续使用：

- Next.js App Router
- React
- TypeScript
- Tailwind CSS
- `lucide-react`
- `react-markdown` + `remark-gfm` + `rehype-sanitize`

暂不引入：

- Redux、Zustand、Jotai 等全局状态库。
- 大型 UI 组件库。
- GraphQL。
- 前端数据库。

引入条件：

| 技术 | 触发条件 | 建议 |
| --- | --- | --- |
| Zustand | 会话、设置、技能、trace 多页面共享导致 props 传递明显混乱。 | P2 后评估。 |
| shadcn/ui | 对话框、菜单、Tabs、表单校验等交互明显增多。 | 按需复制组件，不整体重写 UI。 |
| Playwright | 需要自动验证“选模型 -> 发消息 -> 工具审批 -> 流式输出”。 | P2 引入。 |

### 后端

继续使用：

- Python 标准库 HTTP 服务。
- `urllib.request` 调用 provider。
- 单进程 Agent Runner。
- 环境变量配置。
- `unittest` 作为当前测试基线。

暂缓引入：

- FastAPI。
- Celery/RQ。
- LangChain/LangGraph。
- SQLAlchemy。
- Redis。

引入条件：

| 技术 | 触发条件 | 建议 |
| --- | --- | --- |
| FastAPI + Uvicorn | 路由、SSE、文件上传、鉴权、中间件和请求校验复杂度明显上升。 | P2 后迁移更合适。 |
| `httpx` | 需要 async、连接池、更稳的流式读取和细粒度 timeout。 | provider 调用复杂后引入。 |
| Pydantic | API schema、工具 schema、模型配置校验开始复杂。 | 可独立于 FastAPI 引入。 |
| SQLite | 需要服务端保存会话、trace、配置、技能版本。 | P2 优先本地单文件。 |
| PyYAML | 技能 YAML 需要嵌套结构、类型校验和更好的报错。 | 修正技能系统时优先评估。 |

### Agent 编排

继续使用：

- 自研 Agent Runner。
- 自定义 JSON 决策协议。
- OpenAI-compatible chat completions。

暂不引入：

- LangChain。
- LangGraph。
- AutoGen。
- CrewAI。

重新评估条件：

- 需要可恢复 DAG、计划模式、人类审批节点和长期运行任务。
- 多 Agent 协作成为核心能力。
- 自研 runner 的状态管理超过当前维护能力。

若未来引入，优先考虑 LangGraph，因为它更适合状态图、审批节点和可恢复执行。

## 6. 数据存储策略

| 阶段 | 存储 | 用途 |
| --- | --- | --- |
| 当前 | `localStorage` | 会话历史、摘要、选中模型、会话级信任工具。 |
| P2 | SQLite | 服务端会话、trace、配置、工具运行记录、技能版本。 |
| P3 | SQLite + 可选向量存储 | 知识库、文档索引、长期记忆。 |

短期不使用 Postgres、MongoDB、Redis 或云数据库。当前没有账号体系，服务端存储的第一步应尽量轻。

## 7. 测试与质量

当前最低验证：

```bash
python3 -m unittest discover -s tests
cd frontend && npm run lint && npm run build
```

或：

```bash
make check
```

当前测试覆盖以 `unittest` 为准，不是 pytest。后续如果需要参数化、fixture、临时目录管理和更清晰的断言，可以再迁移到 pytest。

暂不强推：

- Black。
- Ruff。
- mypy。
- Jest/Vitest。
- Storybook。

原因：当前更需要保护 Agent 主链路和工具安全边界；格式化和组件测试可在模块拆分后再统一。

## 8. 不推荐的技术路径

短期不建议：

- 一开始就把后端迁到微服务架构。
- 为了 Agent 能力直接套 LangChain/LangGraph。
- 为本地会话直接上 Postgres 或云数据库。
- 为当前单向流式输出直接上 WebSocket。
- 为模型选择器和工具卡片引入大型 UI 组件库。
- 同时维护旧版原生前端和 Next.js 前端的功能等价。
- 把工具读写范围直接放开到宿主机全盘。

## 9. 技术栈决策记录

| 决策 | 当前结论 | 复盘条件 |
| --- | --- | --- |
| 后端框架 | 继续 Python 标准库。 | 鉴权、上传、复杂 SSE、请求校验明显增多。 |
| Agent 框架 | 继续自研 Runner。 | 计划模式和可恢复任务成为主线。 |
| 数据库 | 当前不引入，浏览器本地保存会话。 | 需要跨设备、trace 查询或配置持久化。 |
| 实时通信 | 使用 SSE，不使用 WebSocket。 | 工具执行过程需要高频双向交互。 |
| 状态管理 | React 本地状态。 | 技能、设置、trace 多页面状态开始交叉。 |
| 测试 | 当前 `unittest` + lint/build。 | 后端测试复杂到需要 pytest fixture。 |
| 技能 YAML | 当前轻量解析。 | 需要嵌套 activation、校验和错误提示。 |

## 10. 结论

当前最合适的路线是继续保持“手搓 Agent”的透明度：

- 前端继续 Next.js + React + TypeScript + Tailwind。
- 后端继续 Python 标准库，先把工具、技能、上下文和测试补稳。
- Agent 编排继续自研 JSON 协议。
- 流式继续用 SSE。
- 会话先在浏览器，服务端持久化优先 SQLite。
- 只有复杂度真实出现时，再引入 FastAPI、Pydantic、httpx、Zustand、Playwright、SQLite、PyYAML 等工具。
