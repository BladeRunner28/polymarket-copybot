# Approvals inbox — a durable, non-expiring approval queue (`:3013/approvals`)

**Status:** approved 2026-11-11 (Option 1 + Option 3 semantics, LAN-only).
**Owner:** Lane B build (no rule, sizing, gate or lane changes).

## Problem

Approvals are delivered into a busy Discord DM. Two failures compound:

1. **Discord is the queue.** Interaction buttons expire in ~15 minutes, so a decision surfaced while
   the operator is away cannot be clicked later. Re-surfacing requires a session that remembers.
2. **There is no single store.** On 2026-11-11 the roadmap carried **64** cards tagged
   `awaiting-approval`, **10** tagged `needs-approval`, and **30** tagged `lane-a`. The approval-alert
   job keys only on the first and `lane-a`, so the 10 `needs-approval` cards have **never** pinged.
   Free text in the daily briefs is a fourth, unqueryable place.

Root cause: approvals are a *presentation* concern everywhere and a *state* concern nowhere.

## Design

One store, one page, plain links, and approving creates the work.

```
data/approvals.json          the store (single source of truth)
scripts/approvals-intake.py  cron-driven normaliser: roadmap tags -> store, decisions sticky
/approvals                   server-rendered list (pending + recently decided)
/approvals/decide            GET ?id=<id>&d=approve|decline|undo -> decides, renders the result
```

### Why plain GET links

The requirement is "clickable, never expires, no scrolling, no asking". A URL whose target is our own
server satisfies all four: it survives in a bookmark, an email, a phone home screen, or next week's
memory. There is no interaction token to expire. LAN-only means no crawler or link-preview client
will GET them by accident.

**There is no nonce, and this file does not claim one.** An earlier draft of this document said
"single-use nonce per item"; that was never built. The protections actually in place are: LAN binding,
idempotency (a second click on an approved item creates nothing and says so), and a one-click Undo
that genuinely stops the work. If this surface ever leaves the LAN (Tailscale), a token guard goes in
the same commit — the threat model changes from "my family's network" to "the internet".

### Store schema (`data/approvals.json`)

```json
{
  "version": 1,
  "updatedAt": "2026-11-11T…",
  "items": [
    {
      "id": "apr-price-side-inversion",
      "lane": "A",
      "status": "pending | approved | declined",
      "title": "…",
      "proposal": "…what is being approved…",
      "evidence": "…the measured before/after…",
      "revert": "…how to undo it…",
      "source": "roadmap:<card id> | review:<job>",
      "createdAt": "…",
      "decidedAt": null,
      "decidedVia": null,
      "kanbanTaskId": null
    }
  ]
}
```

`status` and the decision fields are **sticky**: re-running intake never resets a decided item.

### Option 3 semantics — approving creates the task

On `approve`, the decide route:

1. flips the item to `approved` in the store (idempotent — a second click is a no-op, not a duplicate);
2. creates a `medusa` kanban task carrying the item's proposal + evidence + revert, assigned to
   `default`;
3. dispatches, so the worker starts without a second hop;
4. records `kanbanTaskId` on the item so the approval and its execution are the same object.

`decline` flips status and creates nothing. `undo` returns the item to `pending` and **blocks** the
kanban task it created rather than deleting it — the board keeps the audit trail.

### What this deliberately does not do

- No change to the two-lane policy: Lane B repairs still ship without asking; only Lane A decisions and
  explicit proposal cards appear here.
- No off-LAN exposure. Tailscale comes later; the page is bound to the LAN like the rest of `:3013`.
- No new notification channel. Discord keeps the twice-daily count + link; it stops being the queue.

## Verification plan

1. `python3 scripts/approvals-intake.py` writes the store; rerun proves decisions are sticky.
2. Page returns 200 and lists every pending item with a working link.
3. `GET /approvals/decide?id=…&d=approve` flips status, creates a real kanban task, dispatches, and
   the task appears on the board.
4. Second identical GET does not create a second task.
5. `undo` returns the item to pending and blocks the task.

## Results

**Built and verified 2026-11-11. LAN URL: `http://192.168.1.10:3013/approvals`** (nav entry
"Approvals", second item).

### The queue it produces

| Source | Items | Note |
|---|---|---|
| roadmap `awaiting-approval` / `needs-approval` / `lane-a` | 11 | 29 further cards skipped as already closed |
| blocked board cards (`medusa`) | 4 | includes `t_d8ec3c64`, the STANDARD long-shot cap |

**15 pending.** Before this, "what is waiting on you" had four partial answers — and the 10
`needs-approval` cards had never pinged at all. Intake re-run: `new 0 | refreshed 11` — decisions are
sticky, as designed.

### Verification (all measured live, not asserted)

1. `/approvals` → **HTTP 200**, 92,876 bytes, "Waiting on you (15)"; **30 plain decide links**
   (15 approve + 15 decline); spot-checked titles from both sources present.
2. LAN: `http://192.168.1.10:3013/approvals` → **200**.
3. **Approve** on a synthetic item → store flipped, board task **`t_24214476` created, assigned,
   dispatched, status `running`**.
4. **Second identical GET** → *"Already approved — task t_24214476"*, **no second task created**.
5. **Undo** → item back to `pending`; the running task was **reclaimed then blocked** (status
   `blocked`, not a failure message).
6. **Re-approve** → a *new* task `t_7a328d3f` (not the stale one), then undo blocked it too.
7. All three test tasks archived; synthetic item removed; store back to 15 real items.

### Three defects the smoke test caught (all fixed before commit)

1. **Silent no-op that broke the whole guarantee.** The route called
   `kanban block <id> --reason "…"`, but `block` takes its reason as a **positional** — `--reason`
   exists only on `unblock`. argparse dumped top-level usage, the block failed, and the handler still
   reverted the store: **the approval was undone while the worker kept running.** Now positional, with
   a `reclaim` retry for running tasks, and the store reverts reported alongside any failure.
2. **Idempotency key outlived the decision.** After an undo, re-approving returned the *already
   finished* task, so the work never restarted. Keys are now `approvals:<id>:a<attempt>` with the
   attempt bumped on undo — verified by getting a distinct task id each cycle.
3. **"Failed" for something that had already finished.** Undo on a `done` task reported a park
   failure. It now reads the task status first and says *"already finished — nothing was stopped"*.

### Scheduling (the store is cron-driven, not session-driven)

`copybot-approvals-intake` — **`426a060c001d`**, hourly at `:05`, `no_agent` script
`~/.hermes/scripts/copybot-approvals-intake.sh`, `--deliver local` so an unchanged queue never pings.
Prints a one-line pending count plus the queue for the cron tail.

### What is deliberately still open

- **Discord is still the notifier.** It now has a durable link to point at; the daily digests were not
  rewritten to carry it in this change.
- **Two of the four board-sourced items are not really approvals**: `t_2dd307bc` needs the operator
  driving a car, and `t_59b0ffce` is calendar-gated to 2026-11-28. The page labels the block kind, but
  "approve" is not the action those two need — a future intake pass should route them out.
- Off-LAN access is Tailscale work, deliberately deferred.
