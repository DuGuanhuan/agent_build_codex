# 项目启动与部署指南

本项目采用前后端分离架构（Python Agent 后端 + Next.js 前端）。根据你的使用场景，分为**本地开发启动**和**VPS 线上部署**两种方式。

## 一、本地开发启动 (Local Development)

在本地测试和开发时，我们需要分别启动后端和前端服务。由于本地环境没有 Docker 的自动变量注入，我们需要手动处理环境变量。

### 1. 准备环境变量

你可以复用线上的 `.env.production`，或者复制一份作为本地使用：

```bash
# 如果没有配置文件，先从 example 复制一份
cp .env.production.example .env.production
```

打开 `.env.production`，填入你的大模型 API Keys：
```env
ZAI_API_KEY=your_key_here
DEEPSEEK_API_KEY=your_key_here
WQ_API_KEY=your_key_here
MIMO_API_KEY=your_key_here
TAVILY_API_KEY=your_key_here
```

其中 `TAVILY_API_KEY` 只影响 `web_search` 工具；万擎默认地址是内网地址，公网/VPS 环境通常无法访问，除非机器在公司网络内或你显式配置了可访问的 `WQ_BASE_URL`。

### 2. 启动 Python 后端

由于 `.env.production` 中的变量通常没有 `export` 前缀，直接 `source` 是无效的。你必须使用 `set -a` 强制导出：

```bash
# 在项目根目录下执行
set -a && source .env.production && set +a
python3 server.py
```
*启动成功后，后端会监听在 `http://127.0.0.1:8000`。*

### 3. 启动 Next.js 前端

新开一个终端窗口：

```bash
cd frontend
npm install  # 首次运行需安装依赖
npm run dev
```
*启动成功后，浏览器访问 `http://localhost:3000` 即可开始使用。前端会自动将 API 请求代理到后端的 8000 端口。*

前端代理默认后端地址是 `http://127.0.0.1:8000`。如果后端端口不同：

```bash
AGENT_BACKEND_URL="http://127.0.0.1:8001" npm run dev
```

### 4. 本地连通性验证

后端启动后可以先验证模型和流式接口：

```bash
curl http://127.0.0.1:8000/api/models
curl -N http://127.0.0.1:8000/api/chat/stream \
  -H "content-type: application/json" \
  -d '{"model":"zhipu-glm-4.7-flash","messages":[{"role":"user","content":"回复 pong"}]}'
```

项目当前没有独立的 `scripts/test_zhipu_api.py`，模型连通性以 `/api/models` 和 `/api/chat/stream` 为准。

---

## 二、VPS 线上部署 (VPS Production Deployment)

在 VPS 上，我们强烈推荐使用 **Docker Compose** 进行一键部署，它会自动处理环境变量注入、容器网络通信以及服务保活。

### 1. 准备配置文件

在 VPS 的项目根目录下：

```bash
cp .env.production.example .env.production
```
编辑 `.env.production`，除了填写 API Keys 之外，**务必正确配置域名**：
```env
APP_DOMAIN=agent.yourdomain.com
```

可选模型相关变量：

```env
DEFAULT_MODEL_ID=zhipu-glm-4.7-flash
LLM_MAX_TOKENS=2048
WQ_CONTEXT_WINDOW_TOKENS=128000
MIMO_CONTEXT_WINDOW_TOKENS=128000
```

### 2. 使用 Docker Compose 一键启动

直接使用 Docker Compose 构建并启动容器（会自动拉起前后端以及 Caddy 反向代理）：

```bash
docker compose up -d --build
```

### 3. 查看运行状态

```bash
# 查看所有容器状态
docker compose ps

# 查看后端日志（排查 Agent 报错）
docker compose logs backend -f

# 查看前端日志
docker compose logs frontend -f
```

### 为何 VPS 部署不需要 `set -a`？
在 Docker Compose 部署模式下，`docker-compose.yml` 文件中配置了 `env_file: .env.production`。Docker 引擎会在启动容器时，自动逐行读取该文件，并将其原生地注入为容器的系统环境变量，所以不需要像本地开发那样在 Shell 层面用 `set -a` 强制导出。

## 三、功能入口

- 聊天页：模型选择、会话列表、上下文 token 估算、手动/自动压缩、工具调用展示。
- 技能与工具页：左侧深色导航中的工具图标入口，可查看工具清单，也可以创建、编辑、删除 `skills/` 目录中的技能。
- 旧版原生前端：后端 `http://127.0.0.1:8000` 会继续服务 `public/`，仅作为参考实现，主迭代入口是 Next.js 前端。
