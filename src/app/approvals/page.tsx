import { Card, Stat, Empty } from "@/components/ui";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

export const dynamic = "force-dynamic";

/**
 * /approvals — the durable approval queue. Approved 2026-11-11 (Option 1 + Option 3 semantics).
 *
 * WHY THIS PAGE EXISTS: approvals were delivered into a busy Discord DM, where interaction buttons
 * expire in ~15 minutes and there is no list to scroll back to. Worse, there was no single store: the
 * roadmap carried three overlapping tags (awaiting-approval / needs-approval / lane-a) and the board
 * carried blocked cards, so "what is waiting on me" had four answers. This page is the one answer.
 *
 * STATE, NOT AN ARTEFACT: like /workers (and unlike /ml) this reads live state. The store
 * `data/approvals.json` IS the state, written by scripts/approvals-intake.py (roadmap + board, cron
 * driven) and by the decide route. It is never derived at render time, so the page cannot drift from
 * what was decided.
 *
 * DEGRADATION RULE: a missing store and an empty queue are NOT the same thing. Missing/unreadable
 * renders a loud red banner naming the generator script, never "nothing to approve".
 */

const STORE = join(process.cwd(), "data", "approvals.json");

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
  createdAt?: string | null;
  decidedAt?: string | null;
  decidedVia?: string | null;
  kanbanTaskId?: string | null;
};

type Store = { updatedAt?: string; counts?: Record<string, number>; items?: Item[] };

function load(): { store: Store | null; error: string | null } {
  if (!existsSync(STORE)) {
    return { store: null, error: `store missing at ${STORE} — run: python3 scripts/approvals-intake.py` };
  }
  try {
    return { store: JSON.parse(readFileSync(STORE, "utf8")) as Store, error: null };
  } catch (e) {
    return { store: null, error: `store unreadable: ${(e as Error).message}` };
  }
}

function Decide({ id, action, label, tone }: { id: string; action: string; label: string; tone: string }) {
  const href = `/approvals/decide?id=${encodeURIComponent(id)}&d=${action}`;
  return (
    <a
      href={href}
      className={`inline-block rounded px-3 py-1.5 text-sm font-semibold ${tone}`}
    >
      {label}
    </a>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-1 text-sm leading-relaxed">
      <span className="text-neutral-500">{label} </span>
      <span className="text-neutral-300">{value}</span>
    </div>
  );
}

export default function ApprovalsPage() {
  const { store, error } = load();

  if (error) {
    return (
      <div className="space-y-4">
        <div className="rounded border border-red-700 bg-red-950/60 p-4 text-red-200">
          <div className="font-semibold">APPROVALS STORE UNAVAILABLE</div>
          <div className="mt-1 text-sm">{error}</div>
          <div className="mt-2 text-sm text-red-300">
            This is a real failure, not an empty queue. Nothing is showing because the read failed.
          </div>
        </div>
      </div>
    );
  }

  const items = store?.items ?? [];
  const pending = items.filter((i) => (i.status ?? "pending") === "pending");
  const decided = items
    .filter((i) => (i.status ?? "pending") !== "pending")
    .sort((a, b) => String(b.decidedAt ?? "").localeCompare(String(a.decidedAt ?? "")));
  const laneA = pending.filter((i) => i.lane === "A").length;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Pending" value={String(pending.length)} tone={pending.length > 0 ? "neg" : "pos"} />
        <Stat label="Lane A (rules/sizing)" value={String(laneA)} />
        <Stat label="Approved" value={String(items.filter((i) => i.status === "approved").length)} tone="pos" />
        <Stat label="Declined" value={String(items.filter((i) => i.status === "declined").length)} tone="neutral" />
      </div>

      <Card title={`Waiting on you (${pending.length})`}>
        {pending.length === 0 ? (
          <Empty message="Nothing pending. The queue is empty and the store was read successfully." />
        ) : (
          <div className="space-y-4">
            {pending.map((i) => (
              <div key={i.id} className="rounded border border-neutral-800 bg-neutral-950/60 p-4">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-bold ${
                      i.lane === "A" ? "bg-amber-500/20 text-amber-300" : "bg-sky-500/20 text-sky-300"
                    }`}
                  >
                    LANE {i.lane ?? "?"}
                  </span>
                  <span className="text-base font-semibold text-neutral-100">{i.title ?? i.id}</span>
                  <span className="ml-auto font-mono text-xs text-neutral-600">{i.source ?? ""}</span>
                </div>

                {i.proposal ? <Line label="Proposal:" value={i.proposal} /> : null}
                {i.evidence ? <Line label="Evidence:" value={i.evidence} /> : null}
                {i.revert ? <Line label="Revert:" value={i.revert} /> : null}
                {i.origin === "kanban" ? (
                  <Line
                    label="Board:"
                    value={`blocked card${i.blockKind ? ` (${i.blockKind})` : ""} — approving unblocks and dispatches it${
                      i.blockKind === "needs_input" ? ", but this card needs YOU driving it, not a green light" : ""
                    }`}
                  />
                ) : null}

                <div className="mt-3 flex flex-wrap gap-2">
                  <Decide id={i.id} action="approve" label="✓ Approve" tone="bg-emerald-600 text-white hover:bg-emerald-500" />
                  <Decide id={i.id} action="decline" label="✕ Decline" tone="bg-neutral-700 text-neutral-200 hover:bg-neutral-600" />
                  <span className="self-center text-xs text-neutral-600">
                    plain link — no expiry, bookmarkable
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={`Decided (${decided.length})`}>
        {decided.length === 0 ? (
          <Empty message="No decisions recorded yet." />
        ) : (
          <div className="space-y-2">
            {decided.map((i) => (
              <div key={i.id} className="flex flex-wrap items-baseline gap-2 border-b border-neutral-900 pb-2 text-sm">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-bold ${
                    i.status === "approved" ? "bg-emerald-500/20 text-emerald-300" : "bg-neutral-700/50 text-neutral-400"
                  }`}
                >
                  {String(i.status ?? "").toUpperCase()}
                </span>
                <span className="text-neutral-300">{i.title ?? i.id}</span>
                {i.kanbanTaskId ? <span className="font-mono text-xs text-neutral-500">{i.kanbanTaskId}</span> : null}
                <span className="text-xs text-neutral-600">{i.decidedAt ?? ""}</span>
                <span className="ml-auto">
                  <Decide id={i.id} action="undo" label="undo" tone="border border-neutral-700 text-neutral-400 hover:text-neutral-200" />
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="text-xs text-neutral-600">
        Store updated {store?.updatedAt ?? "unknown"} · written by{" "}
        <code className="text-neutral-500">scripts/approvals-intake.py</code> (roadmap + board) and the decide route ·
        LAN-only
      </div>
    </div>
  );
}
