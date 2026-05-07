# Handmade LLM Agent

一个轻量手写 Agent 示例：

- `server.py`：Python 标准库 HTTP 服务、静态文件服务、OpenAI-compatible LLM 调用、Agent 工具循环
- `frontend/`：Next.js + React + TypeScript 前端聊天界面
- `public/`：旧版原生 HTML/CSS/JS 前端，保留作轻量版本参考
- `config/`：模型配置加载和 `models.yaml`
- `runtimes/`：Handmade、OpenCode、Claude Code 等 runtime adapter 与统一协议
- `tools/registry.py`：工具注册、权限分级、工作区文件/命令/网络工具
- `turns/`：Turn 记录、回滚和重试相关逻辑
- `skills/` 与 `skills/manager.py`：声明式技能系统，支持 hook/invocable 两类技能
- `docs/`：产品、技术、部署、设计和研究文档

运行日志、`.workbuddy/`、临时测试 txt 等本地产物不进入版本库；如果需要长期保留的产品/技术材料，请放到 `docs/` 下对应分类。

## 运行

启动 Python Agent 后端：

```bash
export ZAI_API_KEY="your-zhipu-api-key"
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export WQ_API_KEY="your-wanqing-api-key"
export MIMO_API_KEY="your-mimo-api-key"
python3 server.py
```

启动 Next.js 前端：

```bash
cd frontend
npm run dev
```

打开：

```text
http://127.0.0.1:3000
```

Next.js 前端通过 Route Handler 代理到 Python 后端：

```text
frontend /api/models -> http://127.0.0.1:8000/api/models
frontend /api/tools  -> http://127.0.0.1:8000/api/tools
frontend /api/chat   -> http://127.0.0.1:8000/api/chat
frontend /api/chat/stream -> http://127.0.0.1:8000/api/chat/stream
frontend /api/summarize -> http://127.0.0.1:8000/api/summarize
frontend /api/context/estimate -> http://127.0.0.1:8000/api/context/estimate
frontend /api/skills -> http://127.0.0.1:8000/api/skills
```

`/api/chat/stream` 使用 SSE 返回事件。Agent 工具决策阶段仍使用 JSON 协议；最终面向用户的回答会通过 provider 原生 `stream: true` 逐 token 返回。

如果后端不是 `127.0.0.1:8000`，可以覆盖：

```bash
AGENT_BACKEND_URL="http://127.0.0.1:8001" npm run dev
```

## 正式部署

推荐使用一台 VPS + Docker Compose + Caddy：

```bash
cp .env.production.example .env.production
docker compose up -d --build
```

详细步骤见：

```text
docs/deployment/vps-docker-caddy.md
```

## 测试模型连通性

当前仓库已经没有独立的 `scripts/test_zhipu_api.py`。建议先启动后端，再通过接口验证模型配置和一次真实流式调用：

```bash
export ZAI_API_KEY="your-zhipu-api-key"
python3 server.py
```

另开终端：

```bash
curl http://127.0.0.1:8000/api/models
curl -N http://127.0.0.1:8000/api/chat/stream \
  -H "content-type: application/json" \
  -d '{"model":"zhipu-glm-4.7-flash","messages":[{"role":"user","content":"回复 pong"}]}'
```

返回 `message_start`、`text_delta`、`message_done` 事件即说明后端、API Key 和 provider 调用链路可用。

## 本地验证

后端核心逻辑使用 Python 标准库 `unittest`：

```bash
python3 -m unittest discover -s tests
```

前端最低验收：

```bash
cd frontend
npm run lint
npm run build
```

旧版原生前端仍可直接打开：

```text
http://127.0.0.1:8000
```

## 配置

默认内置模型切换列表：

```text
zhipu-glm-4.7-flash
deepseek-v4-flash
wanqing-kimi-k2.5
deepseek-v4-pro
deepseek-v4-pro-thinking
mimo-v2.5-pro
mimo-v2.5
```

API Key 环境变量：

```bash
export ZAI_API_KEY="your-zhipu-api-key"
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export WQ_API_KEY="your-wanqing-api-key"
export MIMO_API_KEY="your-mimo-api-key"
export TAVILY_API_KEY="your-tavily-api-key" # 仅 web_search 工具需要
```

可以覆盖默认启动模型：

```bash
DEFAULT_MODEL_ID="deepseek-v4-flash" python3 server.py
```

也可以覆盖服务端口：

```bash
PORT=8001 python3 server.py
```

Provider base URL 默认值：

```text
智谱：https://open.bigmodel.cn/api/paas/v4
DeepSeek：https://api.deepseek.com
万擎：http://wanqing.internal/api/gateway/v1/endpoints
小米 MiMo：https://token-plan-sgp.xiaomimimo.com/v1
```

如需覆盖：

```bash
export ZHIPU_BASE_URL="https://open.bigmodel.cn/api/paas/v4"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export WQ_BASE_URL="https://wanqing-api.corp.kuaishou.com/api/gateway/v1/endpoints"
export WQ_MODEL="ep-cvhcjv-1776239525862887187"
export WQ_CONTEXT_WINDOW_TOKENS="128000"
export MIMO_BASE_URL="https://token-plan-sgp.xiaomimimo.com/v1"
export MIMO_CONTEXT_WINDOW_TOKENS="128000"
python3 server.py
```

## 工具系统

工具定义集中在 `tools/registry.py`。每个工具包含名称、描述、权限等级、参数 schema 和执行函数。

当前内置工具：

```text
current_time  - 获取当前本地时间
calculator    - 安全计算数学表达式
file_read     - 读取工作区内文本文件
file_write    - 创建或覆盖工作区内文本文件，需要确认
file_edit     - 基于精确字符串编辑工作区内文本文件，需要确认
repo_search   - 使用 ripgrep 搜索本地仓库
web_fetch     - 读取公开网页文本内容
web_search    - 使用 Tavily 搜索网页，需要 TAVILY_API_KEY
shell_exec    - 在工作区内执行 shell 命令，变更类命令需要确认，危险命令会被后端拦截
invoke_skill  - 主动调用 invocable 技能
skill_create  - 创建或更新技能，需要确认
skill_delete  - 删除技能，需要确认
```

工具列表接口：

```text
GET /api/tools
```

写入、编辑和 shell 等高风险工具会返回 `awaiting_approval` step，前端工具卡片支持“继续执行”“拒绝”和“在本会话中始终信任此工具”。`ls`、`pwd`、`git status` 等观察类 shell 命令会被后端识别为安全命令，可自动执行；`sudo`、`rm -rf /`、`mkfs` 等危险模式即使批准也会被拦截。

## 技能系统

技能定义保存在 `skills/<name>/`：

```text
skill.yaml
instructions.md
```

当前实现支持两类技能：

```text
hook       - 基于上下文中出现的文件路径 glob 自动注入 system prompt
invocable  - 由 Agent 通过 invoke_skill 工具主动调用
```

`skill.yaml` 当前使用轻量解析器，实际支持扁平字段：

```yaml
name: "python-expert"
description: "提供 Python 最佳实践建议"
type: "hook"
paths:
  - "*.py"
trigger_words:
  - "python"
```

`instructions.md` 支持 `` !`cmd` `` 形式的嵌入式观察命令；只有被 `ToolPermission.is_safe_shell_command` 判定为安全的命令会执行并注入结果。

技能管理 API：

```text
GET /api/skills
POST /api/skills
DELETE /api/skills/:name
```

## 会话与上下文

Next.js 前端使用浏览器 `localStorage` 保存本地会话，不依赖后端数据库：

```text
agent:sessions
agent:active-session-id
agent:model
```

当前支持：

```text
新建会话
切换会话
重命名会话
删除会话
刷新后恢复历史会话
按会话保存选用模型
显示当前上下文 token 占用和阈值比例
按 60% / 75% / 90% 配置自动压缩阈值
手动压缩当前会话上下文
自动生成并维护会话摘要
```

上下文占用按模型窗口 token 估算，不按消息条数计算。后端会基于实际发送给 Agent 决策阶段的 system prompt、工具描述和会话消息，返回近似 input token 数、模型 context window、预留输出 token 和占用比例：

```text
POST /api/context/estimate
```

当前默认窗口：

```text
zhipu-glm-4.7-flash       200K tokens
deepseek-v4-flash         1M tokens
deepseek-v4-pro           1M tokens
deepseek-v4-pro-thinking  1M tokens
wanqing-kimi-k2.5         128K tokens，可用 WQ_CONTEXT_WINDOW_TOKENS 覆盖
```

触发上下文压缩后，前端会调用：

```text
POST /api/summarize
```

后端使用当前会话模型生成一段滚动摘要；后续聊天请求会把这段摘要放在上下文最前面，再拼接未压缩消息。摘要目前保存在浏览器 `localStorage`，属于本地会话状态。

## 前端技术栈

新前端位于 `frontend/`，使用：

```text
Next.js 16 App Router
React 19
TypeScript
Tailwind CSS
react-markdown
remark-gfm
rehype-sanitize
lucide-react
```

Markdown 渲染使用 `react-markdown + rehype-sanitize`，避免直接信任模型输出的 HTML。
