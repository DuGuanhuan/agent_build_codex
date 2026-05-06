import { proxyBackend } from "../../_backend";

export async function POST(request: Request) {
  return proxyBackend("/api/runtime/abort", {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: await request.text(),
  });
}
