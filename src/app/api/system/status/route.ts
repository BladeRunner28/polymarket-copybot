import { execFileSync } from "child_process";
import { readFileSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/** Sidecar is healthy if its TCP listener answers at all (it 404s on unknown paths). */
async function probeSidecar(): Promise<{ up: boolean; pid?: number; secs?: number }> {
  let pid: number | null = null;
  try {
    const out = execFileSync("pgrep", ["-f", "polyhydra-whale-signal"], { encoding: "utf8" });
    pid = parseInt(out.trim().split("\n")[0], 10);
  } catch {
    /* not running */
  }

  let up = false;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 1500);
    const r = await fetch("http://127.0.0.1:3014/", { signal: ctrl.signal });
    clearTimeout(t);
    up = r.status >= 100 && r.status < 600; // any HTTP response = listener alive
  } catch {
    up = false;
  }

  let secs: number | undefined;
  if (pid) {
    try {
      const lstart = execFileSync("ps", ["-o", "lstart=", "-p", String(pid)], { encoding: "utf8" }).trim();
      const t = Date.parse(lstart);
      if (!Number.isNaN(t)) secs = Math.max(0, Math.floor((Date.now() - t) / 1000));
    } catch {
      /* unknown */
    }
  }

  return { up: up && pid != null, pid: pid ?? undefined, secs };
}

function cronStats(): { total: number; healthy: number; attention: number; attentionNames: string[] } {
  try {
    const raw = JSON.parse(readFileSync(join(homedir(), ".hermes", "cron", "jobs.json"), "utf8")) as {
      jobs?: Array<{
        name?: string;
        last_status?: string | null;
        last_error?: string | null;
        last_delivery_error?: string | null;
        failure_streak?: number;
      }>;
    };
    const jobs = Array.isArray(raw.jobs) ? raw.jobs : [];
    const healthy = jobs.filter((j) => j.last_status === "ok" || j.last_status === "no_change").length;
    const attention = jobs.filter(
      (j) =>
        j.last_status === "error" ||
        j.last_status === "failed" ||
        (j.failure_streak ?? 0) > 0 ||
        !!j.last_error ||
        !!j.last_delivery_error
    );
    return {
      total: jobs.length,
      healthy,
      attention: attention.length,
      attentionNames: attention.map((j) => j.name ?? "?").slice(0, 5),
    };
  } catch {
    return { total: 0, healthy: 0, attention: 0, attentionNames: [] };
  }
}

export async function GET() {
  const [sidecar, cron] = await Promise.all([probeSidecar(), Promise.resolve(cronStats())]);
  return NextResponse.json({
    ts: Date.now(),
    sidecarUp: sidecar.up,
    sidecarPid: sidecar.pid ?? null,
    sidecarSecs: sidecar.secs ?? null,
    cronTotal: cron.total,
    cronHealthy: cron.healthy,
    cronAttention: cron.attention,
    cronAttentionNames: cron.attentionNames,
  });
}
