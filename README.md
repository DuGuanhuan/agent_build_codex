# Handmade LLM Agent

一个轻量手写 Agent 示例：

- `server.py`：Python 标准库 HTTP 服务、静态文件服务、OpenAI-compatible LLM 调用、Agent 工具循环
- `frontend/`：Next.js + React + TypeScript 前端聊天界面
- `public/`：旧版原生 HTML/CSS/JS 前端，保留作轻量版本参考

## 运行

启动 Python Agent 后端：

```bash
export ZAI_API_KEY="your-zhipu-api-key"
export DEEPSEEK_API_KEY="your-deepseek-api-key"
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
frontend /api/chat   -> http://127.0.0.1:8000/api/chat
```

如果后端不是 `127.0.0.1:8000`，可以覆盖：

```bash
AGENT_BACKEND_URL="http://127.0.0.1:8001" npm run dev
```

## 测试智谱 API Key

项目内置了一个零依赖连通性测试脚本：

```bash
export ZAI_API_KEY="your-zhipu-api-key"
python3 scripts/test_zhipu_api.py
```

脚本默认调用智谱 OpenAI-compatible 接口：

```text
https://open.bigmodel.cn/api/paas/v4/chat/completions
```

默认测试模型是 `glm-4.7-flash`。也可以覆盖：

```bash
ZAI_API_KEY="your-zhipu-api-key" python3 scripts/test_zhipu_api.py --model glm-4.7
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
deepseek-v4-pro
deepseek-v4-pro-thinking
```

API Key 环境变量：

```bash
export ZAI_API_KEY="your-zhipu-api-key"
export DEEPSEEK_API_KEY="your-deepseek-api-key"
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
```

如需覆盖：

```bash
export ZHIPU_BASE_URL="https://open.bigmodel.cn/api/paas/v4"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
python3 server.py
```

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
