import { NextResponse } from "next/server";

/**
 * Shared-secret gate for internal API endpoints.
 * Mirrors api/agents/state: Authorization: Bearer <INTERNAL_API_SECRET>.
 * Unset secret = endpoint disabled (fail closed).
 */
export function requireInternalAuth(req: Request): NextResponse | null {
  const secret = process.env.INTERNAL_API_SECRET;
  if (!secret) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (req.headers.get("authorization") !== `Bearer ${secret}`) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  return null;
}
