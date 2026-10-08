# Medusa kanban board — first run (2026-10-07)

**Board:** `medusa` · DB `~/.hermes/kanban/boards/medusa/kanban.db` · default workdir `~/polymarket-copybot`
**Spawn mechanism:** the gateway's embedded dispatcher (60 s tick) turns each `ready` card into a real
worker process. Verified end-to-end with a smoke card before anything real was queued.

## Cards

| card | kind | workspace | status | outcome |
|---|---|---|---|---|
| `t_1a96fb7a` | read-only audit | `dir:` repo | done | measurement-label audit — 5 mismatches, 3 MARK flags |
| `t_4a8a595b` | perf | worktree `wt/analytics-heatmap-cost` | done | /analytics 556→294 ms/req; operator finding below |
| `t_45a4a56f` | bug fix | worktree `wt/outcome-casing-fix` | running | outcome-review casing mismatch |

Nothing was dispatched while `blocked`: `hermes kanban dispatch --dry-run` read `Spawned: 0` before each
human promote. Repo-editing cards run in **git worktrees** (`.worktrees/<card-id>`) on their own branch,
which is the structural fix for the sibling-session clobber — main's worktree was untouched by both
workers apart from the crons' `data/*.jsonl` writes.

## Audit headline (deliverable: `/drafts/measurement-label-audit-20261007`)

28 in-band + 11 out-of-band arms tabled with declared basis, implemented basis and file:line.
**5 declared-vs-implemented mismatches, 3 MARK-not-settled flags.** All five shadow lanes and
`OutcomeReview.finalOutcome` are clean on `didOutcomeWin`.

Independent re-run (`scripts/label-basis-audit.py`) reproduces it: label disagreement **401/5204 = 7.7%**;
C-200 all-finished `wr 0.484 / Brier 0.2373 / AUC 0.6508` vs `resolvedAt`-only `0.626 / 0.2067 / 0.7427`.

Two findings are decision-class, not worker-class:

1. `src/lib/benchmarks.ts:63,69` — the bot-vs-blind comparison **mixes bases**: bot arm is EXIT
   (`realizedPnl`), blind arm is OUTCOME (hold-to-resolution).
2. `src/lib/rule-updater.ts:28-46,106-112` — `minCopyScore` is gated on an **exit-contaminated win rate**.
   A rule input, so it needs an explicit approval like any other gate change.

## Perf headline (branch `wt/analytics-heatmap-cost`, 2 commits, pending review)

Per-row work is only 62 ms in total; the cost is the fetch, and the live process multiplies it ~4x.
`allResolved` fetched 22.4 MB of JS objects (`reasonsJson`/`risksJson`/`rawTradeJson`) for 11,170 rows to
read 7 fields; `include → select` takes the query 492 → 133 ms and `/analytics` 556 → 294 ms/req.
Renders verified data-identical (SVG geometry, titles, text, DOM, RSC payload), `tsc` clean, 379/379 tests.

**Dominant finding — the process, not the page.** The live launchd dashboard burns ~4x CPU on DB-backed
pages only (`/analytics` 3,323 ms wall live vs 556 ms fresh, same build; `/journal` 2,088 vs 400),
because `~/Library/LaunchAgents/com.xsnyde2.copybot-dashboard.plist` sets `ProcessType = Background`
→ background QoS (E-core + reduced memory priority). Operator action, not a repo change:

```bash
# 1. drop ProcessType Background (or set Interactive) in the plist
# 2. relaunch
launchctl kickstart -k gui/$UID/com.xsnyde2.copybot-dashboard
# rollback: restore the plist from its .bak and kickstart again
```

Worth ~5x on every DB-backed page — larger than anything left in `/analytics`.

## Open decisions

- Merge `wt/analytics-heatmap-cost` into main? (draft becomes `/drafts/analytics-heatmap-cost-perf` on merge)
- Apply the `ProcessType` QoS change to the dashboard plist?
- Card the two decision-class audit findings (`benchmarks.ts`, `rule-updater.ts`)?
