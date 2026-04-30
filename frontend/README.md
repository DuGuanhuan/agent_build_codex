# Agent Frontend

Next.js + React + TypeScript frontend for the handmade Agent backend.

## Run

Start the Python backend from the repo root first:

```bash
export ZAI_API_KEY="your-zhipu-api-key"
export DEEPSEEK_API_KEY="your-deepseek-api-key"
python3 server.py
```

Then run the frontend:

```bash
cd frontend
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

## API Proxy

The frontend uses Next.js Route Handlers to proxy API calls:

```text
/api/models -> http://127.0.0.1:8000/api/models
/api/chat   -> http://127.0.0.1:8000/api/chat
```

Override the backend URL when needed:

```bash
AGENT_BACKEND_URL="http://127.0.0.1:8001" npm run dev
```

## Checks

```bash
npm run lint
npm run build
```
