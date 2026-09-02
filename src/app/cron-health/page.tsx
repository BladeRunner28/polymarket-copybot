import { readFileSync, readdirSync, statSync } from "fs";
import { join } from "path";
import { homedir } from "os";
import { Card, Stat, Empty } from "@/components/ui";

export const dynamic = "force-dynamic";

interface CronJob {
  id: string;
  name: string;
  schedule_display?: string | null;
  script?: string | null;
  no_agent?: boolean;
  enabled?: boolean;
  state?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  last_error?: string | null;
  last_delivery_error?: string | null;
  next_run_at?: string | null;
  deliver?: string | null;
  failure_streak?: number;
  repeat?: { completed?: number } | null;
}

const CRON_DIR = join(homedir(), ".hermes", "cron");

function relTime(iso?: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diffSec = Math.round((t - Date.now()) / 1000);
  const abs = Math.abs(diffSec);
  const unit =
    abs < 60 ? `${abs}s` :
    abs < 3600 ? `${Math.round(abs / 60)}m` :
    abs < 86400 ? `${Math.round(abs / 3600)}h` :
    `${Math.round(abs / 86400)}d`;
  return diffSec >= 0 ? `in ${unit}` : `${unit} ago`;
}

function statusBadge(status?: string | null) {
  const s = status ?? "never";
  const styles: Record<string, string> = {
    ok: "bg-pos/15 text-pos border-pos/30",
    no_change: "bg-warn/15 text-warn border-warn/30",
    error: "bg-neg/15 text-neg border-neg/30",
    failed: "bg-neg/15 text-neg border-neg/30",
    paused: "bg-warn/15 text-warn border-warn/30",
    never: "bg-edge text-dim border-edge",
  };
  return (
    <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${styles[s] ?? styles.never}`}>
      {s.replace("_", " ")}
    </span>
  );
}

function loadJobs(): CronJob[] {
  try {
    const raw = JSON.parse(readFileSync(join(CRON_DIR, "jobs.json"), "utf8")) as { jobs?: CronJob[] };
    return Array.isArray(raw.jobs) ? raw.jobs : [];
  } catch {
    return [];
  }
}

function latestOutput(id: string): { time: string; preview: string } | null {
  try {
    const dir = join(CRON_DIR, "output", id);
    const files = readdirSync(dir)
      .filter((f) => f.endsWith(".md"))
      .map((f) => ({ f, m: statSync(join(dir, f)).mtimeMs }))
      .sort((a, b) => b.m - a.m);
    if (files.length === 0) return null;
    const newest = files[0];
    const text = readFileSync(join(dir, newest.f), "utf8").replace(/\s+/g, " ").trim();
    return { time: relTime(new Date(newest.m).toISOString()), preview: text.slice(0, 140) };
  } catch {
    return null;
  }
}

export default function CronHealthPage() {
  const jobs = loadJobs();
  if (jobs.length === 0) {
    return <Empty message="~/.hermes/cron/jobs.json missing or unreadable — nothing to show." />;
  }

  const healthy = jobs.filter((j) => j.last_status === "ok" || j.last_status === "no_change").length;
  const erroring = jobs.filter(
    (j) => j.last_status === "error" || j.last_status === "failed" || j.last_error || j.last_delivery_error
  ).length;
  const paused = jobs.filter((j) => !j.enabled || j.state === "paused").length;
  const needsAttention = jobs.filter(
    (j) =>
      (j.last_status === "error" || j.last_status === "failed" || (j.failure_streak ?? 0) > 0) ||
      !!j.last_error ||
      !!j.last_delivery_error
  );

  return (
    <div>
      <h1 className="text-lg font-bold mb-1">Cron Health — Hermes scheduler</h1>
      <p className="text-sm text-dim mb-6">
        Source of truth: <code className="text-accent">~/.hermes/cron/jobs.json</code> — all {jobs.length} jobs
        running the copybot pipeline (scripts, agents, watchdogs).
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <Stat label="Jobs" value={String(jobs.length)} tone="neutral" />
        <Stat label="Healthy (last run)" value={String(healthy)} tone="pos" />
        <Stat label="Errors / issues" value={String(erroring)} tone={erroring > 0 ? "neg" : "pos"} />
        <Stat label="Paused / disabled" value={String(paused)} tone="neutral" />
      </div>

      {needsAttention.length > 0 && (
        <Card title="⚠ Needs attention">
          <ul className="text-sm space-y-2">
            {needsAttention.map((j) => (
              <li key={j.id} className="text-dim">
                <span className="text-ink font-semibold">{j.name}</span>
                {j.last_error && <span className="text-neg"> — {j.last_error.slice(0, 180)}</span>}
                {!j.last_error && j.last_delivery_error && (
                  <span className="text-neg"> — delivery: {j.last_delivery_error.slice(0, 180)}</span>
                )}
                {!j.last_error && !j.last_delivery_error && (j.failure_streak ?? 0) > 0 && (
                  <span className="text-warn"> — failure streak {j.failure_streak}</span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="All jobs">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-dim text-xs uppercase tracking-wide border-b border-edge">
                <th className="py-2 pr-4">Job</th>
                <th className="py-2 pr-4">Schedule</th>
                <th className="py-2 pr-4">Type</th>
                <th className="py-2 pr-4">Deliver</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Last run</th>
                <th className="py-2 pr-4">Next run</th>
                <th className="py-2 pr-4">Runs</th>
                <th className="py-2">Latest output</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => {
                const out = latestOutput(j.id);
                return (
                  <tr key={j.id} className="border-b border-edge/50 align-top">
                    <td className="py-2 pr-4">
                      <span className="font-semibold">{j.name}</span>
                      <span className="block text-[10px] text-dim font-mono">{j.id.slice(0, 8)}</span>
                    </td>
                    <td className="py-2 pr-4 text-dim">{j.schedule_display ?? "—"}</td>
                    <td className="py-2 pr-4 text-dim">{j.no_agent ? "script" : "agent"}</td>
                    <td className="py-2 pr-4 text-dim">{j.deliver ?? "—"}</td>
                    <td className="py-2 pr-4">{statusBadge(j.last_status)}</td>
                    <td className="py-2 pr-4 text-dim">{relTime(j.last_run_at)}</td>
                    <td className="py-2 pr-4 text-dim">{relTime(j.next_run_at)}</td>
                    <td className="py-2 pr-4 text-dim">{j.repeat?.completed ?? "—"}</td>
                    <td className="py-2 text-dim max-w-56">
                      {out ? (
                        <>
                          <span className="text-[10px] text-warn">{out.time}</span>
                          <span className="block text-[10px] truncate">{out.preview}</span>
                        </>
                      ) : (
                        <span className="text-[10px]">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
