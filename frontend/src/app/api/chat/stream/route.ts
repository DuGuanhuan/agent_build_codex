import { proxyBackendStream } from "../../_backend";

export async function POST(request: Request) {
  return proxyBackendStream("/api/chat/stream", {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: await request.text(),
    signal: request.signal,
  });
}
