const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

export function backendUrl(path: string) {
  const baseUrl = process.env.AGENT_BACKEND_URL || DEFAULT_BACKEND_URL;
  return new URL(path, baseUrl).toString();
}

export async function proxyBackend(path: string, init?: RequestInit) {
  const response = await fetch(backendUrl(path), {
    ...init,
    cache: "no-store",
  });
  const body = await response.text();

  return new Response(body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
    },
  });
}
