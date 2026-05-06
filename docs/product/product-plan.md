# 手搓 Agent 产品规划

## 1. 产品定位

当前项目是一个轻量级手写 LLM Agent 原型。目标不是直接做完整平台，而是把 Agent 的关键链路做成可学习、可演示、可继续扩展的个人 Agent 基座：

- 用户可以在聊天界面里选择模型并持续对话。
- Agent 可以用 JSON 决策协议调用本地工具。
- 前端可以展示流式回答、工具执行过程、审批步骤和上下文占用。
- 后端保持简单透明，方便继续扩展模型、工具、技能、上下文和部署能力。

## 2. 当前已实现功能

### 2.1 后端 Agent 能力

- `server.py` 使用 Python 标准库 `ThreadingHTTPServer` 提供 JSON API、SSE API 和旧版静态前端服务。
- LLM 调用统一走 OpenAI-compatible `/chat/completions`。
- 支持 provider 原生 `stream: true`，最终回答通过 SSE `text_delta` 逐 token 输出。
- Agent 决策阶段使用内部 JSON 协议：`{"action":"tool"}` 或 `{"action":"final"}`。
- Agent 工具循环最多执行 10 轮；工具结果会回填给模型继续决策。
- 模型输出解析支持标准 JSON、Markdown code fence、夹杂说明文字的 JSON，以及工具名首行 fallback。
- 每次请求生成 `trace_id`，工具步骤包含状态、参数、结果、错误、权限、耗时。
- LLM 对 429、500、502、503 做有限重试。
- 支持滚动摘要和基于模型上下文窗口的 token 占用估算。

### 2.2 模型能力

`MODEL_OPTIONS` 当前内置：

| 模型 ID | Provider | 默认模型名 | 说明 |
| --- | --- | --- | --- |
| `zhipu-glm-4.7-flash` | 智谱 | `glm-4.7-flash` | 默认模型，日常轻量任务。 |
| `deepseek-v4-flash` | DeepSeek | `deepseek-v4-flash` | 低成本、低延迟。 |
| `deepseek-v4-pro` | DeepSeek | `deepseek-v4-pro` | 质量更高。 |
| `deepseek-v4-pro-thinking` | DeepSeek | `deepseek-v4-pro` | 开启 `thinking` 与 `reasoning_effort=high`。 |
| `wanqing-kimi-k2.5` | 万擎 | `WQ_MODEL` 或默认接入点 ID | 公司内网 Kimi K2.5 接入点。 |
| `mimo-v2.5-pro` | 小米 MiMo | `mimo-v2.5-pro` | 小米 MiMo Pro 模型。 |
| `mimo-v2.5` | 小米 MiMo | `mimo-v2.5` | 小米 MiMo 快速模型。 |

模型可用性由 API Key 环境变量决定；`GET /api/models` 只返回 `available`，不返回 key。默认模型可通过 `DEFAULT_MODEL_ID` 覆盖。

### 2.3 已实现工具

工具统一注册在 `tools/registry.py`：

| 工具 | 权限 | 能力 |
| --- | --- | --- |
| `current_time` | `safe_read` | 获取当前本地时间。 |
| `calculator` | `safe_compute` | AST 白名单数学计算，支持 `pi/e/tau`。 |
| `file_read` | `read_user_file` | 读取工作区内相对路径文本文件，最大 1MB，默认从第 1 行读取 2000 行，可指定 `offset/limit`。 |
| `file_write` | `write_file` | 创建或覆盖工作区内文本文件，需要确认。 |
| `file_edit` | `edit_file` | 精确字符串替换编辑工作区内文本文件，需要确认。 |
| `repo_search` | `repo_read` | 使用 `rg --json` 搜索仓库内容。 |
| `web_fetch` | `network_read` | 读取公开网页文本，禁止本地/内网地址。 |
| `web_search` | `network_read` | 使用 Tavily 搜索，需要 `TAVILY_API_KEY`。 |
| `shell_exec` | `shell` | 在工作区内执行 shell 命令，输出上限 100KB，默认 30s、最大 120s。 |
| `invoke_skill` | `safe_read` | 主动调用 invocable 技能并返回技能指令。 |
| `skill_create` | `write_file` | 创建或更新技能。 |
| `skill_delete` | `write_file` | 删除技能。 |

### 2.4 工具权限与审批

- `safe_read`、`safe_compute`、`read_user_file`、`repo_read`、`network_read` 当前默认可自动执行。
- `write_file`、`edit_file`、`shell` 默认需要前端确认。
- `shell_exec` 有动态分类：`ls`、`pwd`、`cat`、`grep`、`find`、`git status/log/diff` 等观察类命令可自动执行。
- `sudo`、`rm -rf /`、`mkfs`、`systemctl stop`、管道到 shell 等危险模式会在后端被拦截，即使前端批准也不会执行。
- 前端工具卡片支持“继续执行”“拒绝”“在本会话中始终信任此工具”。会话信任保存在当前浏览器会话对象中。

### 2.5 技能系统

- `skills/manager.py` 扫描 `skills/<name>/skill.yaml` 和 `skills/<name>/instructions.md`。
- 支持 `hook` 技能：当用户消息或工具步骤中出现匹配路径时，技能指令自动注入 system prompt。
- 支持 `invocable` 技能：Agent 可通过 `invoke_skill` 主动获取技能指令。
- 支持在 `instructions.md` 中使用 `` !`cmd` `` 嵌入观察类命令；只有安全命令会执行并注入结果。
- 前端有“技能与工具管理”页面，可查看工具清单、新建/编辑/删除技能。
- 当前 YAML 解析器是轻量实现，只可靠支持扁平字段：`name`、`description`、`type`、`paths`、`trigger_words`。嵌套 `activation.paths` 这种结构目前不会被完整解析。

### 2.6 API 能力

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/models` | `GET` | 返回模型列表、默认模型、可用性、上下文窗口和预留输出 token。 |
| `/api/tools` | `GET` | 返回工具 schema。 |
| `/api/skills` | `GET` | 返回已加载技能。 |
| `/api/skills` | `POST` | 创建或更新技能。 |
| `/api/skills/:name` | `DELETE` | 删除技能。 |
| `/api/chat` | `POST` | 非流式兼容接口。 |
| `/api/chat/stream` | `POST` | SSE 流式聊天接口。 |
| `/api/summarize` | `POST` | 生成/维护会话摘要。 |
| `/api/context/estimate` | `POST` | 估算当前输入 tokens 和上下文窗口占用比例。 |

Next.js Route Handler 会把前端 `/api/*` 请求代理到 Python 后端，后端地址由 `AGENT_BACKEND_URL` 控制。

### 2.7 Next.js 前端能力

- 主前端位于 `frontend/`，使用 Next.js 16、React 19、TypeScript、Tailwind CSS。
- 聊天页支持会话列表、新建/切换/重命名/删除、刷新后恢复。
- 会话状态保存在 `localStorage`：`agent:sessions`、`agent:active-session-id`、`agent:model`。
- 每个会话最多保存 80 条消息，最多保存 24 个会话。
- 支持模型选择器、未配置模型置灰、每条 assistant 消息展示实际使用模型。
- 支持 SSE 流式输出、停止生成、120 秒前端超时。
- Markdown 渲染使用 `react-markdown + remark-gfm + rehype-sanitize`。
- 工具步骤支持折叠、参数、结果、stdout、错误、耗时、审批操作。
- 上下文面板展示 `used / context_window tokens`、60%/75%/90% 自动压缩阈值、手动压缩按钮和摘要预览。
- 左侧深色导航支持在“聊天”和“技能与工具管理”之间切换。

### 2.8 部署与验证

- 本地开发：Python 后端默认 `127.0.0.1:8000`，Next.js 前端默认 `localhost:3000`。
- 生产部署：`Dockerfile.backend`、`frontend/Dockerfile`、`docker-compose.yml`、Caddy 反向代理。
- `Makefile` 提供 `make check`、`make deploy-up`、`make deploy-down`、`make deploy-logs`、`make deploy-restart`、`make deploy-update`。
- 自动化测试使用 Python 标准库 `unittest`：`python3 -m unittest discover -s tests`。
- 前端最低验证：`cd frontend && npm run lint && npm run build`。

## 3. 当前产品问题

- Auto 模型路由还未实现，用户仍需要手动选择具体模型。
- 模型列表还没有 provider 分组、成本/速度/上下文标签和可见性管理。
- 技能 YAML 解析较弱，当前只适合扁平字段；已有 `python-expert` 的嵌套 `activation` 示例不会按预期触发。
- 工具审批已经可用，但缺少更细的风险说明、命令 diff 预览和持久化权限策略。
- `shell_exec` 依赖后端进程所在容器/工作区，不是宿主机全盘能力；当前文件读写也锁定在项目工作区。
- 会话、摘要、信任工具都保存在浏览器本地，没有服务端同步、账号体系或跨设备恢复。
- 前端尚无端到端测试，复杂交互主要靠 lint/build 和手工验证。
- 技能管理页已经可用，但表单校验、保存错误展示和 YAML 结构提示仍偏粗糙。

## 4. 路线图

### P0：稳定当前闭环

- 修正技能 YAML 示例与解析规则，让内置 hook 技能真实生效。
- 补齐 `file_write`、`file_edit`、`shell_exec`、`skill_*` 的单测。
- 优化审批卡片：展示权限风险、命令摘要、写入目标路径。
- 保持 `make check` 作为每轮提交前最低验收。

### P1：模型与技能体验

- 增加 Auto 模型模式：简单任务走 Flash，复杂规划/推理走 Pro/Thinking。
- 模型选择器按 provider 分组，展示速度、成本、上下文、推理模式标签。
- 技能管理页增加 YAML 预览/校验，明确 hook 与 invocable 的触发方式。
- 支持从 UI 看到本轮实际激活了哪些 hook 技能。

### P2：更真实的工作 Agent

- 增加计划模式：复杂任务先生成 plan，再按步骤执行工具。
- 增加服务端 trace 存储，记录模型调用、工具调用、耗时和错误。
- 引入 SQLite 保存会话、摘要、配置和工具运行记录。
- 扩展安全策略：目录白名单、写操作 diff、命令 allowlist/denylist 可配置。

### P3：平台化能力

- 多 Agent 配置：不同 system prompt、默认模型、工具权限和知识范围。
- 知识库/RAG：上传文档、索引、引用来源。
- 多用户与认证：demo password、Supabase/Auth 或其他账号体系。
- 成本统计：按会话/模型估算 token 与费用。

## 5. MVP 验收标准

- 本地 5 分钟内能启动后端和前端并完成第一次对话。
- 模型列表能正确展示可用/不可用状态，切换模型后回答展示实际模型。
- 普通问答、时间查询、数学计算、文件读取、仓库搜索都能通过 Agent 工具链路完成。
- 写文件、编辑文件、变更类 shell 命令会出现审批卡片。
- 危险 shell 命令会被后端拦截。
- 会话刷新后可恢复，长对话能按 token 窗口比例手动或自动压缩。
- 技能管理页可以创建/编辑/删除扁平字段技能。
- `python3 -m unittest discover -s tests`、`npm run lint`、`npm run build` 通过。
