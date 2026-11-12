import { NextRequest } from "next/server";
import { readFileSync, writeFileSync, renameSync, existsSync } from "fs";
import { execFileSync } from "child_process";
import { join } from "path";

export const dynamic = "force-dynamic";

/**
 * /approvals/decide
 *
 * GET  ?id=<id>&d=approve|decline|undo   — one item, one click, from a bookmark or a phone.
 * POST (form) id=<id>&id=<id>…&d=approve|decline — bulk submit from the queue page.
 *
 * WHY A GET WITH SIDE EFFECTS: the requirement is a clickable approval that never expires, readable
 * from a bookmark, an email or a phone. A platform interaction token (Discord: ~15 min) cannot do
 * that; a plain URL against our own LAN server can. There is no nonce: the exposure is a CSRF-shaped
 * GET, mitigated by LAN-only binding, idempotency (a second click is a no-op that creates nothing)
 * and a one-click Undo on the result page. Anything stricter would break bookmarked links, which is
 * the whole point of the page.
 *
 * OPTION 3 SEMANTICS: approving does not just record an opinion, it STARTS the work —
 *   - roadmap item  -> create a medusa task (idempotency key = item id + attempt), assign, dispatch
 *   - blocked card  -> unblock the existing card and dispatch it
 * FAIL LOUD: if the CLI call fails the item stays PENDING. A recorded approval whose task was never
 * created is the exact defect class this inbox exists to kill.
 *
 * ONE DECISION PATH: GET and POST both go through decideOne(). A bulk submit that behaved even
 * slightly differently from a single click would be two implementations of one policy, and the
 * second one is always the one that rots.
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
type Action = "approve" | "decline" | "undo";

type Outcome = {
  id: string;
  title: string;
  lane: string;
  ok: boolean;
  changed: boolean;
  message: string;
  warn: string;
  taskId: string | null;
  /** true when this outcome produced or released a task and a dispatch is warranted */
  needsDispatch: boolean;
};

function loadStore(): Store {
  if (!existsSync(STORE)) throw new Error(`approvals store missing at ${STORE}`);
  return JSON.parse(readFileSync(STORE, "utf8")) as Store;
}

function saveStore(store: Store): void {
  store.updatedAt = new Date().toISOString();
  store.items = store.items ?? [];
  store.counts = {
    pending: store.items.filter((i) => !i.status || i.status === "pending").length,
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
       table{width:100%;border-collapse:collapse;margin-top:.5rem}
       td{padding:.4rem .5rem;border-bottom:1px solid #1f1f1f;vertical-align:top}
       .new{color:#6ee7b7} .fail{color:#fca5a5} .skip{color:#a3a3a3}
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
  // LANE A GUARD: an approval authorises a PROPOSAL, not an apply. Without this the generated task
  // body said nothing about it and a worker could legitimately read "approved" as "go ahead and ship".
  // The two-lane policy is instruction-enforced (a worktree isolates code, not prisma/dev.db).
  const laneGuard =
    item.lane === "A"
      ? [
          "## LANE A CONSTRAINT — PROPOSAL ONLY",
          "",
          "This approval authorises a PROPOSAL, not an apply. Write a `drafts/` document.",
          "You MUST NOT run `scripts/apply-vNN.ts`, MUST NOT write `prisma/dev.db`, and MUST NOT merge to",
          "main. The apply step belongs to the operator after he reads the proposal.",
          "",
        ].join("\n")
      : "";
  return [
    `Approved via the approvals inbox at ${new Date().toISOString()}.`,
    "",
    laneGuard,
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

/**
 * Apply one decision to one item, in place. Does NOT save the store — the caller saves once so a
 * bulk submit is a single atomic write and a partial failure cannot leave the file half-decided.
 */
function decideOne(item: Item, action: Action): Outcome {
  const base = {
    id: item.id,
    title: item.title ?? item.id,
    lane: item.lane ?? "?",
    taskId: item.kanbanTaskId ?? null,
  };
  const status = item.status ?? "pending";

  // ---------- undo ----------
  if (action === "undo") {
    if (status === "pending") {
      return { ...base, ok: false, changed: false, needsDispatch: false, message: "Already pending — nothing to undo.", warn: "" };
    }
    const prevTask = item.kanbanTaskId ?? null;
    const wasCreated = item.origin !== "kanban";
    let warn = "";
    if (prevTask && wasCreated) {
      const st = taskStatus(prevTask);
      if (st === "done" || st === "archived") {
        warn = `Task ${prevTask} already finished (${st}) — nothing was stopped. Re-approving will create a NEW task.`;
      } else {
        // NOTE: `kanban block` takes the reason as a POSITIONAL (there is no --reason flag; that exists
        // only on `unblock`). Passing --reason made argparse dump top-level usage and the block silently
        // failed while the store reverted — approval undone, work still running. Verified 2026-11-11.
        let blocked = run(["kanban", "--board", "medusa", "block", prevTask, "Approval undone via approvals inbox"]);
        if (!blocked.ok) {
          run(["kanban", "--board", "medusa", "reclaim", prevTask]);
          blocked = run(["kanban", "--board", "medusa", "block", prevTask, "Approval undone via approvals inbox"]);
        }
        if (!blocked.ok) {
          warn = `Store reverted, but parking ${prevTask} FAILED: ${blocked.out} — stop it by hand (hermes kanban --board medusa reclaim ${prevTask}).`;
        }
      }
    } else if (prevTask && !wasCreated) {
      warn = `Card ${prevTask} was unblocked and may have started. Re-block it by hand if that was not intended.`;
    }
    item.status = "pending";
    item.decidedAt = null;
    item.decidedVia = null;
    // Bump the attempt so a re-approve gets a FRESH idempotency key. Without this the second approve
    // returned the already-finished task and the work never restarted. Verified 2026-11-11.
    item.attempt = (item.attempt ?? 0) + 1;
    if (wasCreated) item.kanbanTaskId = null;
    return {
      ...base,
      ok: true,
      changed: true,
      needsDispatch: false,
      message: `Returned to pending.${prevTask ? ` Previous task ${prevTask}.` : ""}`,
      warn,
      taskId: null,
    };
  }

  // ---------- decline ----------
  if (action === "decline") {
    if (status !== "pending") {
      return { ...base, ok: false, changed: false, needsDispatch: false, message: `Already ${status} — not changed. Use undo first to re-decide.`, warn: "" };
    }
    item.status = "declined";
    item.decidedAt = new Date().toISOString();
    item.decidedVia = "approvals-inbox";
    return { ...base, ok: true, changed: true, needsDispatch: false, message: "Declined. No task was created.", warn: "" };
  }

  // ---------- approve ----------
  if (status === "approved") {
    return {
      ...base,
      ok: false,
      changed: false,
      needsDispatch: false,
      message: `Already approved${item.kanbanTaskId ? ` — task ${item.kanbanTaskId}` : ""}. Nothing new was created.`,
      warn: "",
    };
  }

  let taskId: string | null = item.kanbanTaskId ?? null;
  let message = "";

  if (item.origin === "kanban") {
    if (!taskId) {
      return { ...base, ok: false, changed: false, needsDispatch: false, message: "Board-sourced item carries no task id — refusing to guess.", warn: "" };
    }
    const res = run(["kanban", "--board", "medusa", "unblock", taskId, "--reason", "Approved via approvals inbox"]);
    if (!res.ok) {
      return { ...base, ok: false, changed: false, needsDispatch: false, message: "UNBLOCK FAILED — item left pending, nothing recorded.", warn: res.out };
    }
    message = `Unblocked board card ${taskId}.`;
  } else {
    const res = run([
      "kanban", "--board", "medusa", "create", item.title ?? item.id,
      "--body", taskBody(item),
      "--assignee", "default",
      "--idempotency-key", `approvals:${item.id}:a${item.attempt ?? 0}`,
      "--json",
    ]);
    if (!res.ok) {
      return { ...base, ok: false, changed: false, needsDispatch: false, message: "TASK CREATION FAILED — item left pending, nothing recorded.", warn: res.out };
    }
    taskId = parseTaskId(res.out) ?? taskId;
    message = `Created and assigned board task${taskId ? ` ${taskId}` : ""}.`;
  }

  item.status = "approved";
  item.decidedAt = new Date().toISOString();
  item.decidedVia = "approvals-inbox";
  item.kanbanTaskId = taskId;
  return { ...base, ok: true, changed: true, needsDispatch: true, message, warn: "", taskId };
}

function dispatch(times: number): { ok: boolean; out: string } {
  return run(["kanban", "--board", "medusa", "dispatch", "--max", String(Math.max(1, Math.min(times, 12)))]);
}

// ---------------------------------------------------------------------------------------------
// GET — one item, one click
// ---------------------------------------------------------------------------------------------
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

  const out = decideOne(item, action as Action);
  if (out.changed) saveStore(store);

  const head = `<h1>${esc(out.title)}</h1><p><code>${esc(out.id)}</code> · lane ${esc(out.lane)} · ${esc(item.source ?? "")}</p>`;
  const cls = out.ok ? "ok" : "warn";
  const dispNote = out.needsDispatch
    ? (() => {
        const d = dispatch(1);
        return d.ok
          ? `<div class="box ok"><b>Dispatched.</b><pre>${esc(d.out.slice(0, 1200))}</pre></div>`
          : `<div class="box warn">Approval recorded and task exists, but dispatch FAILED — it will start on the next dispatcher tick.<pre>${esc(d.out)}</pre></div>`;
      })()
    : "";
  const undoLink = out.changed
    ? `<a class="btn sec" href="/approvals/decide?id=${encodeURIComponent(out.id)}&d=undo">undo</a>`
    : "";

  return html(
    `${head}<div class="box ${cls}">${out.ok ? "<b>" : "<b>No change.</b> "}${esc(out.message)}</div>
     ${out.warn ? `<div class="box warn">${esc(out.warn)}</div>` : ""}${dispNote}${undoLink}${nav()}`
  );
}

// ---------------------------------------------------------------------------------------------
// POST — bulk submit (multi-select on the queue page)
// ---------------------------------------------------------------------------------------------
export async function POST(req: NextRequest): Promise<Response> {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return html(`<h1>Bad form</h1><div class="box bad">Could not read the submitted form.</div>${nav()}`);
  }

  const ids = form.getAll("id").map((v) => String(v)).filter(Boolean);
  const action = String(form.get("d") ?? "");

  if (!["approve", "decline"].includes(action)) {
    return html(
      `<h1>Unknown bulk action</h1><div class="box bad">Bulk submit accepts <code>approve</code> or <code>decline</code>; got <code>${esc(action)}</code>.
       Undo stays single-item on purpose — un-blocking a batch of tasks in one unverified click is not a feature.</div>${nav()}`
    );
  }
  if (ids.length === 0) {
    return html(`<h1>Nothing selected</h1><div class="box warn">Tick at least one item on the queue page, then submit.</div>${nav()}`);
  }

  let store: Store;
  try {
    store = loadStore();
  } catch (e) {
    return html(
      `<h1>Store unavailable</h1><div class="box bad">${esc((e as Error).message)}</div>
       <p>Nothing was changed.</p>${nav()}`
    );
  }

  const byId = new Map(store.items.map((i) => [i.id, i]));
  const outcomes: Outcome[] = [];

  for (const id of ids) {
    const item = byId.get(id);
    if (!item) {
      outcomes.push({
        id, title: id, lane: "?", ok: false, changed: false, needsDispatch: false,
        message: "Unknown id — not in the store (it may have been retired by the intake).", warn: "", taskId: null,
      });
      continue;
    }
    outcomes.push(decideOne(item, action as Action));
  }

  // ONE atomic write for the whole batch: a partial failure must not leave the file half-decided.
  const changed = outcomes.filter((o) => o.changed);
  if (changed.length > 0) saveStore(store);

  const dispensable = outcomes.filter((o) => o.needsDispatch).length;
  let dispNote = "";
  if (dispensable > 0) {
    const d = dispatch(dispensable);
    dispNote = d.ok
      ? `<div class="box ok"><b>Dispatched ${dispensable}.</b><pre>${esc(d.out.slice(0, 1200))}</pre></div>`
      : `<div class="box warn">Decisions recorded and tasks exist, but dispatch FAILED — they will start on the next dispatcher tick.<pre>${esc(d.out)}</pre></div>`;
  }

  const failed = outcomes.filter((o) => !o.ok);
  const verb = action === "approve" ? "Approved" : "Declined";
  const header =
    failed.length === 0
      ? `<div class="box ok"><b>${verb} ${changed.length} of ${outcomes.length}.</b> Every selected item was decided.</div>`
      : `<div class="box warn"><b>${verb} ${changed.length} of ${outcomes.length}.</b>
         ${failed.length} could not be decided and ${failed.length === 1 ? "is" : "are"} unchanged — listed below with the reason.
         A partial batch is reported as partial, never as done.</div>`;

  const rows = outcomes
    .map((o) => {
      const cls = !o.ok ? "fail" : o.changed ? "new" : "skip";
      const undo = o.changed && o.taskId
        ? ` <a href="/approvals/decide?id=${encodeURIComponent(o.id)}&d=undo">undo</a>`
        : o.changed
          ? ` <a href="/approvals/decide?id=${encodeURIComponent(o.id)}&d=undo">undo</a>`
          : "";
      return `<tr><td class="${cls}">${o.ok ? (o.changed ? "✓" : "·") : "✕"}</td>
        <td><code>${esc(o.id)}</code><br><span class="${cls}">${esc(o.title)}</span></td>
        <td>${esc(o.message)}${o.warn ? `<br><span class="fail">${esc(o.warn)}</span>` : ""}${undo}</td></tr>`;
    })
    .join("");

  return html(
    `<h1>Bulk ${action}</h1><p>${outcomes.length} selected · ${changed.length} decided · ${failed.length} unchanged</p>
     ${header}${dispNote}
     <table>${rows}</table>${nav()}`
  );
}
