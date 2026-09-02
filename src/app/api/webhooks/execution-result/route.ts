import { NextResponse } from 'next/server';
import { recordExecutionResult } from '@/lib/paper';
import { requireInternalAuth } from '@/lib/internal-auth';

export async function POST(req: Request) {
  const denied = requireInternalAuth(req);
  if (denied) return denied;
  try {
    const body = await req.json();
    // All bankroll accounting lives in paper.ts — this route is a thin adapter.
    await recordExecutionResult(body);
    console.log(`[Shadow Exec] Recorded FAK trade for ${body.botId} via Rust Engine!`);
    return NextResponse.json({ success: true });
  } catch (e: any) {
    console.error(e);
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
