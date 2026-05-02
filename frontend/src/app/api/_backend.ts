const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

export function backendUrl(path: string) {
  const baseUrl = process.env.AGENT_BACKEND_URL || DEFAULT_BACKEND_URL;
  return new URL(path, baseUrl).toString();
}

export async function proxyBackend(path: string, init?: RequestInit) {
  let response: Response;
  try {
    response = await fetch(backendUrl(path), {
      ...init,
      cache: "no-store",
    });
  } catch {
    return Response.json({ error: "后端服务未启动或暂时不可用" }, { status: 503 });
  }

  const body = await response.text();

  return new Response(body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
    },
  });
}

export async function proxyBackendStream(path: string, init?: RequestInit) {
  let response: Response;
  try {
    response = await fetch(backendUrl(path), {
      ...init,
      cache: "no-store",
    });
  } catch {
    const frame = `event: error\ndata: ${JSON.stringify({ message: "后端服务未启动或暂时不可用" })}\n\n`;
    return new Response(frame, {
      status: 503,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
      },
    });
  }

  return new Response(response.body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") || "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
    },
  });
}
