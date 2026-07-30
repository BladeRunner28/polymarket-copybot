import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";

function authorized(req: NextRequest): boolean {
  const secret = process.env.INTERNAL_API_SECRET;
  if (!secret) return false; // unset secret = endpoint disabled
  return req.headers.get("authorization") === `Bearer ${secret}`;
}

/** GET /api/agents/state — list all reported agents (read-only, no auth). */
export async function GET() {
  const agents = await prisma.agentState.findMany({ orderBy: { updatedAt: "desc" } });
  return NextResponse.json({ agents });
}

/** POST /api/agents/state — upsert an agent's heartbeat. Requires INTERNAL_API_SECRET. */
export async function POST(req: NextRequest) {
  if (!authorized(req)) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  const id = typeof body.id === "string" ? body.id.trim() : "";
  const name = typeof body.name === "string" ? body.name.trim() : "";
  if (!id || !name) {
    return NextResponse.json({ error: "'id' and 'name' are required strings" }, { status: 400 });
  }
  const data = {
    name,
    emoji: typeof body.emoji === "string" ? body.emoji : "🤖",
    role: typeof body.role === "string" ? body.role : "",
    status: typeof body.status === "string" ? body.status : "idle",
    currentTask: typeof body.currentTask === "string" ? body.currentTask : "",
    tasksCompleted: Number.isFinite(body.tasksCompleted) ? Math.trunc(body.tasksCompleted as number) : 0,
    totalCost: Number.isFinite(body.totalCost) ? (body.totalCost as number) : 0,
  };
  const agent = await prisma.agentState.upsert({ where: { id }, create: { id, ...data }, update: data });
  return NextResponse.json({ ok: true, agent });
}
