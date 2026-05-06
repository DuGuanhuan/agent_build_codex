import { proxyBackend } from "../_backend";

export async function GET() {
  return proxyBackend("/api/runtimes");
}
