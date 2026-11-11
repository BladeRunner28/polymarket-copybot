import { NextRequest } from "next/server";
import { readFileSync, writeFileSync, renameSync, existsSync } from "fs";
import { execFileSync } from "child_process";
import { join } from "path";

export const dynamic = "force-dynamic";

/**
 * GET /approvals/decide?id=<id>&d=approve|decline|undo
 *
 * WHY A GET WITH SIDE EFFECTS: the requirement is a clickable approval that never expires, readable
 * from a bookmark, an email or a phone. A platform interaction token (Discord: ~15 min) cannot do
 * that; a plain URL against our own LAN server can. There is no nonce: the exposure is a CSRF-shaped
 * GET, mitigated by LAN-only binding, idempotency (a second click is a no-op that creates nothing)
 * and a one-click Undo on the result page. Anything stricter would break bookmarked links, which is
 * the whole point of the page.
 *
 * OPTION 3 SEMANTICS: approving does not just record an opinion, it STARTS the work —
 *   - roadmap item  -> create a medusa task (idempotency key = item id), assign, dispatch
 *   - blocked card  -> unblock the existing card and dispatch it
 * FAIL LOUD: if the CLI call fails the item stays PENDING. A recorded approval whose task was never
 * created is the exact defect class this inbox exists to kill.
 */

const STORE = join(process.cwd(), "data", "approvals.json");
const HERMES = "/Users/xsnyde2/.hermes/hermes-agent/.hermes/bin/hermes";

type Item = {
  id: string;
  lane?: string;
  status?: string;
  title?: string;
  proposal?: string;
  evidence?: string;
  revert?: string;
  source?: string;
  origin?: string;
  blockKind?: string;
  attempt?: number;
  decidedAt?: string | null;
  decidedVia?: string | null;
  kanbanTaskId?: string | null;
};
type Store = { version?: number; updatedAt?: string; counts?: Record<string, number>; items: Item[] };

function loadStore(): Store {
  if (!existsSync(STORE)) throw new Error(`approvals store missing at ${STORE}`);
  return JSON.parse(readFileSync(STORE, "utf8")) as Store;
}

function saveStore(store: Store): void {
  store.updatedAt = new Date().toISOString();
  store.items = store.items ?? [];
  store.counts = {
    pending: store.items.filter((i) => i.status === "pending" || !i.status).length,
    approved: store.items.filter((i) => i.status === "approved").length,
    declined: store.items.filter((i) => i.status === "declined").length,
  };
  const tmp = `${STORE}.tmp`;
  writeFileSync(tmp, JSON.stringify(store, null, 2) + "\n");
  renameSync(tmp, STORE);
}

function run(args: string[]): { ok: boolean; out: string } {
  try {
    const out = execFileSync(HERMES, args, {
      encoding: "utf8",
      timeout: 180_000,
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { ok: true, out: String(out).trim() };
  } catch (e) {
    const err = e as { stdout?: unknown; stderr?: unknown; message?: string };
    const detail = String(err.stderr ?? "").trim() || String(err.stdout ?? "").trim() || err.message || "unknown error";
    return { ok: false, out: detail };
  }
}

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function html(body: string): Response {
  return new Response(
    `<!doctype html><html><head><meta charset="utf-8"><title>Approval</title>
     <meta name="viewport" content="width=device-width,initial-scale=1">
     <style>
       body{background:#0a0a0a;color:#e5e5e5;font:16px/1.55 ui-sans-serif,system-ui,-apple-system,sans-serif;
            margin:0;padding:2rem;max-width:52rem}
       a{color:#7dd3fc} h1{font-size:1.25rem;margin:0 0 .25rem}
       .box{border:1px solid #262626;border-radius:.5rem;padding:1rem 1.25rem;margin:1rem 0;background:#111}
       .ok{border-color:#065f46;background:#052e2b} .bad{border-color:#991b1b;background:#2a0f0f}
       .warn{border-color:#92400e;background:#2a1c05} code{color:#a3a3a3}
       .btn{display:inline-block;margin:.5rem .5rem 0 0;padding:.5rem .9rem;border-radius:.375rem;
            text-decoration:none;font-weight:600}
       .pri{background:#059669;color:#fff} .sec{background:#262626;color:#d4d4d4}
     </style></head><body>${body}</body></html>`,
    { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } }
  );
}

function nav(): string {
  return `<p><a href="/approvals">← back to the queue</a></p>`;
}

function taskStatus(id: string): string {
  const res = run(["kanban", "--board", "medusa", "show", id]);
  if (!res.ok) return "unknown";
  const m = res.out.match(/status:\s*([a-z_-]+)/i);
  return m ? m[1].toLowerCase() : "unknown";
}

function parseTaskId(out: string): string | null {
  try {
    const parsed = JSON.parse(out) as Record<string, unknown>;
    const cand = parsed.id ?? parsed.task_id ?? parsed.taskId;
    if (typeof cand === "string" && cand.startsWith("t_")) return cand;
  } catch {
    /* not JSON — fall through to the regex */
  }
  const m = out.match(/t_[0-9a-f]{6,}/);
  return m ? m[0] : null;
}

function taskBody(item: Item): string {
  return [
    `Approved via the approvals inbox at ${new Date().toISOString()}.`,
    "",
    `## Proposal`,
    item.proposal ?? item.title ?? "(none recorded)",
    "",
    item.evidence ? `## Evidence\n${item.evidence}\n` : "",
    item.revert ? `## Revert\n${item.revert}\n` : "",
    `## Provenance`,
    `- approvals id: \`${item.id}\``,
    `- lane: ${item.lane ?? "?"}`,
    `- source: ${item.source ?? "unknown"}`,
    `- decision: APPROVED by the operator (clicked link, no expiry)`,
  ].join("\n");
}

export async function GET(req: NextRequest): Promise<Response> {
  const id = req.nextUrl.searchParams.get("id") ?? "";
  const action = req.nextUrl.searchParams.get("d") ?? "";

  let store: Store;
  try {
    store = loadStore();
  } catch (e) {
    return html(
      `<h1>Store unavailable</h1><div class="box bad">${esc((e as Error).message)}</div>
       <p>Nothing was changed. Run <code>python3 scripts/approvals-intake.py</code>.</p>${nav()}`
    );
  }

  const item = store.items.find((i) => i.id === id);
  if (!id || !item) {
    return html(`<h1>Unknown approval id</h1><div class="box bad">No item matches <code>${esc(id)}</code>.</div>${nav()}`);
  }
  if (!["approve", "decline", "undo"].includes(action)) {
    return html(
      `<h1>Unknown action</h1><div class="box bad">Expected <code>d=approve</code>, <code>d=decline</code> or <code>d=undo</code>; got <code>${esc(action)}</code>.</div>${nav()}`
    );
  }

  const status = item.status ?? "pending";
  const title = esc(item.title ?? item.id);
  const head = `<h1>${title}</h1><p><code>${esc(item.id)}</code> · lane ${esc(item.lane ?? "?")} · ${esc(item.source ?? "")}</p>`;

  // ---------- undo ----------
  if (action === "undo") {
    if (status === "pending") {
      return html(`${head}<div class="box warn">Already pending — nothing to undo.</div>${nav()}`);
    }
    const prevTask = item.kanbanTaskId ?? null;
    const wasCreated = item.origin !== "kanban";
    let warn = "";
    if (prevTask && wasCreated) {
      // A task that already FINISHED cannot be parked — say so instead of reporting a failure.
      const st = taskStatus(prevTask);
      if (st === "done" || st === "archived") {
        warn = `<div class="box warn">Task <code>${esc(prevTask)}</code> already finished (<b>${esc(st)}</b>) —
                nothing was stopped. Re-approving will create a NEW task.</div>`;
      } else {
        // NOTE: `kanban block` takes the reason as a POSITIONAL (there is no --reason flag; that exists
        // only on `unblock`). Passing --reason made argparse dump top-level usage and the block silently
        // failed while the store reverted — approval undone, work still running. Verified 2026-11-11.
        let blocked = run(["kanban", "--board", "medusa", "block", prevTask, "Approval undone via approvals inbox"]);
        if (!blocked.ok) {
          // A running task must be released before it can be parked.
          run(["kanban", "--board", "medusa", "reclaim", prevTask]);
          blocked = run(["kanban", "--board", "medusa", "block", prevTask, "Approval undone via approvals inbox"]);
        }
        if (!blocked.ok) {
          warn = `<div class="box warn">Store reverted, but parking <code>${esc(prevTask)}</code> FAILED:
                  <pre>${esc(blocked.out)}</pre>Stop it by hand
                  (<code>hermes kanban --board medusa reclaim ${esc(prevTask)}</code>) so it does not keep running.</div>`;
        }
      }
    } else if (prevTask && !wasCreated) {
      warn = `<div class="box warn">Card <code>${esc(prevTask)}</code> was unblocked and may have started.
              Re-block it by hand if that was not intended.</div>`;
    }
    item.status = "pending";
    item.decidedAt = null;
    item.decidedVia = null;
    // Bump the attempt so a re-approve gets a FRESH idempotency key. Without this the second approve
    // returned the already-finished task and the work never restarted. Verified 2026-11-11.
    item.attempt = (item.attempt ?? 0) + 1;
    if (wasCreated) item.kanbanTaskId = null;
    saveStore(store);
    return html(`${head}<div class="box ok">Returned to <b>pending</b>.${prevTask ? ` Previous task <code>${esc(prevTask)}</code>.` : ""}</div>${warn}${nav()}`);
  }

  // ---------- decline ----------
  if (action === "decline") {
    if (status !== "pending") {
      return html(
        `${head}<div class="box warn">Already <b>${esc(status)}</b> — not changed. Use undo first if you want to re-decide.</div>${nav()}`
      );
    }
    item.status = "declined";
    item.decidedAt = new Date().toISOString();
    item.decidedVia = "approvals-inbox";
    saveStore(store);
    return html(`${head}<div class="box ok">Declined. No task was created.</div>
      <a class="btn sec" href="/approvals/decide?id=${encodeURIComponent(item.id)}&d=undo">undo</a>${nav()}`);
  }

  // ---------- approve ----------
  if (status === "approved") {
    return html(
      `${head}<div class="box warn">Already approved${item.kanbanTaskId ? ` — task <code>${esc(item.kanbanTaskId)}</code>` : ""}.
       Nothing new was created.</div>
       <a class="btn sec" href="/approvals/decide?id=${encodeURIComponent(item.id)}&d=undo">undo</a>${nav()}`
    );
  }

  let taskId: string | null = item.kanbanTaskId ?? null;
  let detail = "";

  if (item.origin === "kanban") {
    // The card already exists and is blocked: approving means letting it run.
    if (!taskId) {
      return html(`${head}<div class="box bad">This item is board-sourced but carries no task id — refusing to guess.</div>${nav()}`);
    }
    const res = run(["kanban", "--board", "medusa", "unblock", taskId, "--reason", "Approved via approvals inbox"]);
    if (!res.ok) {
      return html(
        `${head}<div class="box bad">UNBLOCK FAILED — item left PENDING, nothing was recorded.<pre>${esc(res.out)}</pre></div>${nav()}`
      );
    }
    detail = `Unblocked board card <code>${esc(taskId)}</code>.`;
  } else {
    const res = run([
      "kanban", "--board", "medusa", "create", item.title ?? item.id,
      "--body", taskBody(item),
      "--assignee", "default",
      "--idempotency-key", `approvals:${item.id}:a${item.attempt ?? 0}`,
      "--json",
    ]);
    if (!res.ok) {
      return html(
        `${head}<div class="box bad">TASK CREATION FAILED — item left PENDING, nothing was recorded.<pre>${esc(res.out)}</pre></div>${nav()}`
      );
    }
    taskId = parseTaskId(res.out) ?? taskId;
    detail = `Created and assigned board task${taskId ? ` <code>${esc(taskId)}</code>` : ""}.`;
  }

  item.status = "approved";
  item.decidedAt = new Date().toISOString();
  item.decidedVia = "approvals-inbox";
  item.kanbanTaskId = taskId;
  saveStore(store);

  const disp = run(["kanban", "--board", "medusa", "dispatch", "--max", "2"]);
  const dispNote = disp.ok
    ? `<div class="box ok"><b>Dispatched.</b><pre>${esc(disp.out.slice(0, 1200))}</pre></div>`
    : `<div class="box warn">Approval recorded and task exists, but dispatch FAILED — it will start on the next dispatcher tick.
       <pre>${esc(disp.out)}</pre></div>`;

  return html(
    `${head}<div class="box ok"><b>Approved.</b> ${detail}</div>${dispNote}
     <a class="btn sec" href="/approvals/decide?id=${encodeURIComponent(item.id)}&d=undo">undo</a>
     ${nav()}`
  );
}
