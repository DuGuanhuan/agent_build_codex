import { proxyBackend } from "../../_backend";

export async function POST(request: Request) {
  return proxyBackend("/api/turns/retry", {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: await request.text(),
    signal: request.signal,
  });
}
