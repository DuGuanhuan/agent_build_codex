import { proxyBackend } from "../../_backend";

export async function GET(request: Request) {
  const url = new URL(request.url);
  return proxyBackend(`/api/runtime/artifacts${url.search}`);
}
