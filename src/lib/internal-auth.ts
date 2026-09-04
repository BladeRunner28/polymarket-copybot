import { NextResponse } from "next/server";

/**
 * Shared-secret gate for internal API endpoints.
 * Mirrors api/agents/state: Authorization: Bearer <INTERNAL_API_SECRET>.
 * Unset secret = endpoint disabled (fail closed).
 */
export function requireInternalAuth(req: Request): NextResponse | null {
  const secret = process.env.INTERNAL_API_SECRET;
  const deny = (why: string) => {
    // v45 (2026-09-03): denials were SILENT for 3 days — the Rust sidecar's
    // execution-result posts 401'd since Aug 31 00:04 (launchd restart with no
    // env) with zero trace in any log. Log every denial so this failure mode
    // is visible in dashboard.log.
    console.warn(`[AUTH-DENY] ${why} ${new Date().toISOString()} ${req.method} ${new URL(req.url).pathname}`);
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  };
  if (!secret) return deny("secret unset (fail closed)");
  if (req.headers.get("authorization") !== `Bearer ${secret}`) return deny("bad/missing bearer");
  return null;
}
