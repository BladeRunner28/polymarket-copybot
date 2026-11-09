import { execFileSync } from "child_process";
import { readFileSync, existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { Card, Stat, Empty } from "@/components/ui";
import { toEpoch } from "@/lib/epoch";

export const dynamic = "force-dynamic";

/**
 * /workers — the operations board: what is RUNNING, what is OPEN, what is being WORKED, what FINISHED.
 *
 * WHY THIS PAGE EXISTS: the user asked for a separate view of active workers, open cards, current work,
 * and completions in the last 24h. The existing pages each answer a trading question; none answers
 * "what is the machine doing right now".
 *
 * WHY IT READS THE DB LIVE INSTEAD OF A JSON ARTEFACT (deliberate, and the opposite of /ml):
 * /ml renders frozen measurements, so it reads an artefact written by the script that measured them.
 * This page renders LIVE OPERATIONAL STATE. An artefact here would be stale within one dispatcher tick
 * and would show a worker as running after it exited — an artefact with no writer is a card that lies,
 * and an artefact with a 5-minute writer is a card that lies slowly. So this page queries the kanban
 * board SQLite directly on every request, and never caches.
 *
 * DEGRADATION RULE: the board is SQLite in WAL mode and the dispatcher writes to it while we read.
 * A read-only open CAN fail transiently (observed: SQLITE_CANTOPEN, error 14, on -readonly while a
 * checkpoint held the shm). When that happens this page must say so — an empty list and a failed read
 * are indistinguishable once parsed, so a failure is rendered as a loud red banner with the OS error,
 * never as "no workers running". Every query is retried once before being reported as failed.
 */

const HOME = homedir();
const CRON_DIR = join(HOME, ".hermes", "cron");

function boardDb(): string {
  let board = "medusa";
  try {
    const cur = join(HOME, ".hermes", "kanban", "current");
    if (existsSync(cur)) board = readFileSync(cur, "utf8").trim() || board;
  } catch {
    /* fall back to medusa */
  }
  return join(HOME, ".hermes", "kanban", "boards", board, "kanban.db");
}

const sleep = (ms: number) => {
  try {
    execFileSync("sleep", [String(ms / 1000)]);
  } catch {
    /* ignore */
  }
};

/** Read-only query with one retry. Returns an explicit error rather than an empty list. */
function query(db: string, sql: string): { rows: any[]; error?: string } {
  let lastErr = "";
  for (let attempt = 0; attempt < 2; attempt++) {
    // -readonly is the correct mode; plain is the fallback because WAL can refuse a read-only open
    // while another process holds the shm. Both paths only ever run SELECTs.
    for (const mode of [["-readonly"], []] as string[][]) {
      try {
        const out = execFileSync("sqlite3", [...mode, db, "-json", sql], {
          encoding: "utf8",
          timeout: 5000,
          maxBuffer: 16 * 1024 * 1024,
        });
        const t = out.trim();
        return { rows: t ? JSON.parse(t) : [] };
      } catch (e: any) {
        lastErr = String(e?.stderr || e?.message || e).trim().slice(0, 300);
      }
    }
    if (attempt === 0) sleep(150);
  }
  return { rows: [], error: lastErr || "unknown sqlite failure" };
}

const nowS = () => Math.floor(Date.now() / 1000);

/**
 * Timestamp formats are NOT uniform across these stores, and assuming one is how a dashboard lies.
 * `tasks.worker_started_at` is TEXT epoch-MILLISECONDS while every other kanban timestamp is INTEGER
 * epoch-SECONDS. Passing the raw value into arithmetic is what printed "NaNd NaNh" for a running
 * worker's elapsed time on 2026-11-09. The rule now lives in src/lib/epoch.ts so it is testable
 * (tests/epoch-timestamps.test.ts) — a page file cannot carry extra exports, and that defect shipped
 * precisely because the rule was inline and untested.
 */

function ago(ts: number | null): string {
  if (!ts) return "—";
  const d = nowS() - ts;
  if (d < 0) return `in ${dur(-d)}`;
  return `${dur(d)} ago`;
}
function dur(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}
function stamp(ts: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("en-US", {
    timeZone: "America/Chicago",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function LoadError({ what, error }: { what: string; error: string }) {
  return (
    <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm">
      <div className="font-semibold text-red-400">
        READ FAILED — {what}. This is NOT an empty result.
      </div>
      <div className="mt-1 font-mono text-xs text-red-300/80 break-all">{error}</div>
    </div>
  );
}

type Running = {
  id: string; title: string; assignee: string; branch_name: string | null;
  worker_pid: number | null;
  // These columns do NOT agree on type at runtime: the current kanban writer puts a 12-digit TEXT
  // epoch-centisecond value in started_at and leaves worker_started_at NULL, while older rows carry
  // epoch seconds as INTEGER. Typing them `number` was itself part of the defect — it promised the
  // compiler a shape the data does not have, so raw values reached arithmetic unchallenged. `unknown`
  // makes every consumer go through toEpoch.
  worker_started_at: unknown; last_heartbeat_at: unknown; started_at: unknown;
  max_runtime_seconds: number | null;
  current_run_id: number | null;
  run_started_at: unknown;
};
type Open = {
  id: string; title: string; status: string; assignee: string; priority: number;
  created_at: number | null; block_kind: string | null; consecutive_failures: number | null;
  last_failure_error: string | null;
};
type Done = {
  id: string; title: string; completed_at: number; assignee: string;
  outcome: string | null; summary: string | null; started_at: number | null; ended_at: number | null;
};
type CronRun = {
  id: string; job_id: string; pid: number | null; status: string;
  started_at: string | number | null; finished_at: string | null;
};

export default function WorkersPage() {
  const db = boardDb();
  const cutoff = nowS() - 86400;

  const runningQ = query(db, `
    SELECT t.id, t.title, t.assignee, t.branch_name, t.worker_pid, t.worker_started_at,
           t.last_heartbeat_at, t.max_runtime_seconds, t.current_run_id, t.started_at,
           (SELECT r.started_at FROM task_runs r WHERE r.task_id = t.id
             ORDER BY r.id DESC LIMIT 1) AS run_started_at
    FROM tasks t WHERE t.status = 'running'
    ORDER BY COALESCE(t.worker_started_at, t.started_at, 0)`);

  const openQ = query(db, `
    SELECT id, title, status, assignee, priority, created_at, block_kind,
           consecutive_failures, last_failure_error
    FROM tasks WHERE status NOT IN ('done','cancelled')
    ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'blocked' THEN 1 ELSE 2 END,
             priority DESC, COALESCE(created_at,0) DESC`);

  // NOTE: tasks.current_run_id is NULLED when a run ends, so joining it finds nothing and every
  // completed card loses its summary — the page would list titles only, i.e. report the fact of
  // completion without the substance. Join the task's LATEST run instead (works for any retry count).
  const doneQ = query(db, `
    SELECT t.id, t.title, t.completed_at, t.assignee, r.outcome, r.summary, r.started_at, r.ended_at
    FROM tasks t
    LEFT JOIN task_runs r ON r.id = (SELECT MAX(id) FROM task_runs WHERE task_id = t.id)
    WHERE t.completed_at IS NOT NULL AND t.completed_at >= ${cutoff}
    ORDER BY t.completed_at DESC`);

  const failedQ = query(db, `
    SELECT t.id, t.title, t.consecutive_failures, t.last_failure_error, t.status
    FROM tasks t
    WHERE COALESCE(t.consecutive_failures,0) > 0
       OR (t.last_failure_error IS NOT NULL AND t.last_failure_error <> '')
    ORDER BY t.consecutive_failures DESC, COALESCE(t.created_at,0) DESC LIMIT 25`);

  // QUOTA WALLS (added 2026-11-09). A run that exits rate-limited is REQUEUED WITHOUT COUNTING A
  // FAILURE, so a task stalled on provider quota shows consecutive_failures = 0 and reads as
  // perfectly healthy on every failure-based view. Observed: eight consecutive rate_limited
  // requeues on one card between 08:08 and 08:50 while the board reported no failures at all.
  // Derived from task_runs, which already persists every attempt — no schema change, no counter
  // to drift out of step with the events it counts.
  const rateLimitedQ = query(db, `
    SELECT t.id, t.title, t.status, COUNT(r.id) AS rl_runs,
           MAX(r.started_at) AS last_rl
    FROM task_runs r
    JOIN tasks t ON t.id = r.task_id
    WHERE r.status = 'rate_limited' AND r.started_at >= ${cutoff}
    GROUP BY t.id
    ORDER BY rl_runs DESC, last_rl DESC LIMIT 25`);

  const running = runningQ.rows as Running[];
  const open = openQ.rows as Open[];
  const done = doneQ.rows as Done[];
  const failed = failedQ.rows as any[];
  const rateLimited = rateLimitedQ.rows as any[];
  const rateLimitedTotal = rateLimited.reduce((a, r) => a + Number(r.rl_runs || 0), 0);

  // ---- cron: what is executing right now, and what broke ----
  let cronRunning: CronRun[] = [];
  let cronErr = "";
  const cronNames: Record<string, string> = {};
  try {
    const jobs = JSON.parse(readFileSync(join(CRON_DIR, "jobs.json"), "utf8"));
    const list = Array.isArray(jobs) ? jobs : jobs.jobs || [];
    for (const j of list) cronNames[j.job_id] = (j.name || j.job_id) as string;
  } catch (e: any) {
    cronErr = String(e?.message || e).slice(0, 200);
  }
  const cronRunQ = query(join(CRON_DIR, "executions.db"), `
    SELECT id, job_id, pid, status, started_at, finished_at FROM executions
    WHERE status = 'running' AND finished_at IS NULL
    ORDER BY started_at DESC LIMIT 25`);
  if (cronRunQ.error) cronErr = cronRunQ.error;
  cronRunning = cronRunQ.rows as CronRun[];

  const blocked = open.filter((c) => c.status === "blocked");
  const queued = open.filter((c) => c.status !== "blocked" && c.status !== "running");

  const activeCount = running.length + cronRunning.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Workers</h1>
        <p className="mt-1 text-sm text-neutral-400">
          Live operational state — read from the kanban board and cron execution store on every request.
          Nothing here is cached: if the board is unreachable the page says READ FAILED rather than
          showing zero workers.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Active workers" value={String(activeCount)} sub={`${running.length} kanban · ${cronRunning.length} cron`} tone={activeCount > 0 ? "pos" : "neutral"} />
        <Stat label="Blocked on you" value={String(blocked.length)} sub="needs promote / approval" tone={blocked.length > 0 ? "neg" : "neutral"} />
        <Stat label="Queued" value={String(queued.length)} sub="not started" tone="neutral" />
        <Stat label="Completed 24h" value={String(done.length)} sub="cards finished" tone={done.length > 0 ? "pos" : "neutral"} />
        <Stat label="Quota walls 24h" value={String(rateLimitedTotal)} sub={`${rateLimited.length} card(s) requeued`} tone={rateLimitedTotal > 0 ? "neg" : "neutral"} />
      </div>

      {(runningQ.error || openQ.error || doneQ.error || rateLimitedQ.error) && (
        <LoadError
          what="kanban board"
          error={[runningQ.error, openQ.error, doneQ.error, rateLimitedQ.error].filter(Boolean).join(" | ")}
        />
      )}

      {/* ---------- 1. ACTIVE WORKERS ---------- */}
      <Card title="Active workers — running right now">
        {runningQ.error ? (
          <LoadError what="running tasks" error={runningQ.error} />
        ) : running.length === 0 ? (
          <Empty message="No kanban worker is running. Queued cards start on the next dispatcher tick." />
        ) : (
          <div className="space-y-3">
            {running.map((t) => {
              // Three sources, in order of truth: the CURRENT RUN's start (task_runs.started_at,
              // integer epoch seconds, written at every dispatch), then worker_started_at, then the
              // task's started_at — which is the FIRST attempt, so on a retry it reports the card's
              // age as if it were this run's duration. All go through toEpoch: the columns disagree
              // on both type and unit.
              const started =
                toEpoch(t.run_started_at) ?? toEpoch(t.worker_started_at) ?? toEpoch(t.started_at);
              const elapsed = started !== null ? nowS() - started : null;
              const hbS = toEpoch(t.last_heartbeat_at);
              const hbAge = hbS !== null ? nowS() - hbS : null;
              const overCap = elapsed !== null && t.max_runtime_seconds ? elapsed > t.max_runtime_seconds : false;
              const staleHb = hbAge !== null && hbAge > 300;
              return (
                <div key={t.id} className="rounded border border-neutral-700 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-neutral-400">{t.id}</span>
                    <span className="font-medium">{t.title}</span>
                    {overCap && (
                      <span className="rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-300">OVER RUNTIME CAP</span>
                    )}
                    {staleHb && !overCap && (
                      <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300">STALE HEARTBEAT</span>
                    )}
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-neutral-400 md:grid-cols-4">
                    <div>pid <span className="text-neutral-200">{t.worker_pid ?? "—"}</span></div>
                    <div>running <span className="text-neutral-200">{elapsed !== null ? dur(elapsed) : "—"}</span></div>
                    <div>cap <span className="text-neutral-200">{t.max_runtime_seconds ? dur(t.max_runtime_seconds) : "—"}</span></div>
                    <div>heartbeat <span className={staleHb ? "text-amber-300" : "text-neutral-200"}>{hbAge !== null ? `${dur(hbAge)} ago` : "—"}</span></div>
                    <div className="md:col-span-2">branch <span className="font-mono text-neutral-200">{t.branch_name || "—"}</span></div>
                    <div className="md:col-span-2">assignee <span className="text-neutral-200">{t.assignee}</span></div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="mt-5">
          <div className="mb-2 text-sm font-medium text-neutral-300">Cron lanes executing now</div>
          {cronErr && !cronRunning.length ? (
            <LoadError what="cron execution store" error={cronErr} />
          ) : cronRunning.length === 0 ? (
            <Empty message="No cron job is executing at this instant." />
          ) : (
            <div className="space-y-2">
              {cronRunning.map((e) => {
                // An execution row with status='running' and no finished_at is normally a job in
                // flight — but a crashed runner leaves that row behind forever, and reporting it as
                // RUNNING would be the same defect as reading a failed query as an empty list. A run
                // older than 2h is labelled for what it probably is.
                const st = toEpoch(e.started_at);
                const el = st ? nowS() - st : null;
                const abandoned = el !== null && el > 7200;
                return (
                  <div key={e.id} className="flex flex-wrap items-center gap-3 text-xs">
                    <span
                      className={
                        abandoned
                          ? "rounded bg-amber-500/20 px-2 py-0.5 text-amber-300"
                          : "rounded bg-emerald-500/20 px-2 py-0.5 text-emerald-300"
                      }
                    >
                      {abandoned ? "STALE ROW" : "RUNNING"}
                    </span>
                    <span className="font-medium text-neutral-200">{cronNames[e.job_id] || e.job_id}</span>
                    <span className="font-mono text-neutral-500">{e.job_id}</span>
                    <span className="text-neutral-400">runner pid {e.pid ?? "—"}</span>
                    <span className={abandoned ? "text-amber-300" : "text-neutral-400"}>
                      started {el !== null ? `${dur(el)} ago` : "—"}
                      {abandoned ? " — likely an abandoned row, not a live job" : ""}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      {/* ---------- 1b. QUOTA WALLS ---------- */}
      <Card title={`Quota walls — rate-limited requeues (24h) (${rateLimitedTotal})`}>
        {rateLimitedQ.error ? (
          <LoadError what="rate-limited runs" error={rateLimitedQ.error} />
        ) : rateLimited.length === 0 ? (
          <Empty message="No rate-limited requeues in the last 24 hours." />
        ) : (
          <>
            <div className="mb-3 text-xs text-neutral-400">
              A provider quota wall is requeued <span className="text-neutral-200">without counting a
              failure</span>, so a card stalled on quota reports{" "}
              <span className="font-mono">consecutive_failures = 0</span> and reads healthy on every
              failure-based view. Counted from <span className="font-mono">task_runs</span>, which
              records every attempt, so this cannot drift from the events it describes.
            </div>
            <div className="space-y-2">
              {rateLimited.map((r) => (
                <div key={r.id} className="flex flex-wrap items-center gap-3 text-xs">
                  <span className="rounded bg-amber-500/20 px-2 py-0.5 text-amber-300">
                    {r.rl_runs} requeue{r.rl_runs === 1 ? "" : "s"}
                  </span>
                  <span className="font-mono text-neutral-400">{r.id}</span>
                  <span className="text-neutral-200">{String(r.title).slice(0, 70)}</span>
                  <span className="text-neutral-500">status {r.status} · last {stamp(r.last_rl)}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      {/* ---------- 2. BLOCKED ---------- */}
      <Card title={`Blocked — waiting on you (${blocked.length})`}>
        {blocked.length === 0 ? (
          <Empty message="Nothing is waiting on your approval." />
        ) : (
          <div className="space-y-2">
            {blocked.map((c) => (
              <div key={c.id} className="rounded border border-amber-500/30 bg-amber-500/5 p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-neutral-400">{c.id}</span>
                  <span className="text-sm">{c.title}</span>
                  {c.block_kind && (
                    <span className="rounded bg-neutral-700 px-2 py-0.5 text-xs text-neutral-300">{c.block_kind}</span>
                  )}
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  created {stamp(c.created_at)} · <span className="font-mono">hermes kanban promote {c.id}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* ---------- 3. QUEUED ---------- */}
      <Card title={`Open, not started (${queued.length})`}>
        {queued.length === 0 ? (
          <Empty message="No open cards are waiting to start." />
        ) : (
          <div className="divide-y divide-neutral-800">
            {queued.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                <span className="font-mono text-xs text-neutral-500">{c.id}</span>
                <span className="flex-1">{c.title}</span>
                <span className="rounded bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">{c.status}</span>
                <span className="text-xs text-neutral-500">p{c.priority}</span>
                <span className="text-xs text-neutral-500">{ago(c.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* ---------- 4. COMPLETED 24H ---------- */}
      <Card title={`Completed in the last 24 hours (${done.length})`}>
        {doneQ.error ? (
          <LoadError what="completed cards" error={doneQ.error} />
        ) : done.length === 0 ? (
          <Empty message="No card completed in the last 24 hours." />
        ) : (
          <div className="space-y-3">
            {done.map((t) => {
              const took = t.started_at && t.ended_at ? t.ended_at - t.started_at : null;
              return (
                <div key={t.id} className="rounded border border-neutral-700 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-xs text-emerald-300">
                      {t.outcome || "done"}
                    </span>
                    <span className="font-mono text-xs text-neutral-400">{t.id}</span>
                    <span className="font-medium">{t.title}</span>
                  </div>
                  <div className="mt-1 text-xs text-neutral-500">
                    finished {stamp(t.completed_at)} ({ago(t.completed_at)}){took ? ` · took ${dur(took)}` : ""}
                  </div>
                  {t.summary && (
                    <p className="mt-2 line-clamp-4 whitespace-pre-wrap text-xs leading-relaxed text-neutral-400">
                      {t.summary}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* ---------- 5. ATTENTION ---------- */}
      <Card title={`Needs attention (${failed.length})`}>
        {failedQ.error ? (
          <LoadError what="failure state" error={failedQ.error} />
        ) : failed.length === 0 ? (
          <Empty message="No worker has recorded a failure." />
        ) : (
          <div className="space-y-2">
            {failed.map((f) => (
              <div key={f.id} className="rounded border border-red-500/30 bg-red-500/5 p-2">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono text-xs text-neutral-400">{f.id}</span>
                  <span className="flex-1">{f.title}</span>
                  <span className="rounded bg-neutral-800 px-2 py-0.5 text-xs">{f.status}</span>
                  <span className="rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-300">
                    {f.consecutive_failures ?? 0} consecutive
                  </span>
                </div>
                {f.last_failure_error && (
                  <div className="mt-1 font-mono text-xs text-red-300/70 break-all">{f.last_failure_error}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <p className="text-xs text-neutral-600">
        Source: <span className="font-mono">{db}</span> · cron <span className="font-mono">{join(CRON_DIR, "executions.db")}</span> · rendered{" "}
        {new Date().toLocaleString("en-US", { timeZone: "America/Chicago" })}
      </p>
    </div>
  );
}
