import { NextRequest } from "next/server";
import { proxyBackend } from "../../_backend";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ name: string }> }
) {
  const { name } = await params;
  const body = await request.json();
  return proxyBackend(`/api/skills/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ name: string }> }
) {
  const { name } = await params;
  return proxyBackend(`/api/skills/${name}`, {
    method: "DELETE",
  });
}
