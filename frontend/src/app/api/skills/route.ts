import { NextRequest } from "next/server";
import { proxyBackend } from "../_backend";

export async function GET() {
  return proxyBackend("/api/skills");
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  return proxyBackend("/api/skills", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
