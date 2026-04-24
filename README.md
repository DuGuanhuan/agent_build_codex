# Handmade LLM Agent

一个不依赖前端框架、不使用 Agent 框架的轻量示例：

- `server.py`：Python 标准库 HTTP 服务、静态文件服务、OpenAI-compatible LLM 调用、Agent 工具循环
- `public/`：原生 HTML/CSS/JS 前端聊天页

## 运行

```bash
python3 server.py
```

打开：

```text
http://127.0.0.1:8000
```

## 配置

默认读取：

```python
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://wanqing-api.corp.kuaishou.com/api/gateway/v1/endpoints")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("WQ_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "ep-r8b5g8-1772540899002785977")
```

推荐用环境变量覆盖：

```bash
export LLM_API_KEY="your-key"
export LLM_MODEL="ep-r8b5g8-1772540899002785977"
python3 server.py
```
