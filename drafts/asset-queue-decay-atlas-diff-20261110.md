# Asset queue: the decay rule, and one diff against an independent index

*2026-11-10 09:05 CST · card `asset-queue-decay-and-atlas-diff` · Lane B (instrument + measurement, nothing adopted)*

## The key finding, up front

**The card's premise was real but unexercised, and the queue's actual defect is the opposite of the one it named.**
No queue item had ever passed a decay deadline: the oldest open item is 21 days old and the queue held
**0 items pending an audit** at 09:04 today. The zombies the standing rule was written to kill were not
accumulating — the queue was **starved**, not bloated: 105 radar runs since 2026-10-15 produced **7 leads**
(0.067/run, last add 2026-11-03), which is less than one lead a week against an audit worker that claims two
per run.

So this run shipped the decay rule (it is owed, and it is cheap) **and** used the one-off atlas pull to answer
the question the decay rule cannot: is a thin radar flow a thin world, or a blind spot?

## What shipped (Lane B, read-only, reversible)

`scripts/asset-queue.py` gains two commands, wired into the audit cron (`decay --apply` runs before claims):

- **`decay`** — pre-registered rule `asset-queue-decay-v1`. Clock = the local timestamps the instrument
  itself writes; **progress events** are an audit, the user's decision, or a recorded result (a claim is a
  lease, not progress). Population = open verdicts (`watch`, `audit`). TTLs: `abandoned-approved` 30d
  (approved, never worked → expire), `no-ask` 30d (audited, never put to the user → expire),
  `stalled-ask` 21d (ask still open on the **user's** side → annotate and re-surface, **never** auto-withdraw).
  Expiry is idempotent, recorded with its clock, and re-openable only via `add --force`.
- **`atlas-diff`** — read-only diff against `inputoutput9/prediction-market-agent-atlas` (MIT, 44 curated
  entries, liveness as-of **2026-11-09**, curated axes as-of **2026-07-23**). Writes
  `data/atlas-lead-diff.json`. It enqueues nothing.

Both carry `--self-test`; both were made to go **RED** by mutation (the decay TTL mutant drops 9/9 → 8/9,
the maintenance ladder boundary test fails on a one-day shift), so neither is decoration.

## Measured — decay, on the live queue

Population 19 items, clock local 2026-11-10 09:04, level = item.

- open (aged): **10** · skipped/terminal: **9** · **expired today: 0**
- nearest real expiry: `bennyjo/phil` in 9d (`no-ask`), `agent-next/polymarket-paper-trader` in 11d
  (`abandoned-approved`, decided 2026-10-22)
- one ask will be annotated STALLED in 3d: `xyonium/reach-mcp` (pending 18d)
- one label inconsistency surfaced: `mbordash/DRADIS` still reads `verdict=watch` though its result is
  `measured-dropped` — reported, not silently rewritten

## Measured — atlas diff (the only new candidates produced today)

Population 44 curated entries; class = referenced if the id appears as an `owner/repo` token in the queue,
`drafts/*.md` or `data/roadmap.json` (6,645 tokens).

- queued **2** · referenced **14** · vendor-official **7** · flagged **scam 7** · **new third-party leads 14**
- of the 14 new leads, **5 are fresh** by the atlas's own maintenance ladder (maint ≥ 4):

| repo | venue | cap | agent | idle |
| --- | --- | --- | --- | --- |
| `demwick/polymarket-agent-mcp` | polymarket | 4 | 4 | 4d |
| `TexasCoding/kalshi-python-sdk` | kalshi | 5 | 3 | 1d |
| `SpartanLabsXyz/simmer-sdk` | cross | 3 | 4 | 3d |
| `newyorkcompute/kalshi` | kalshi | 4 | 4 | 35d |
| `9crusher/mcp-server-kalshi` | kalshi | 3 | 4 | 51d |

the other **9** are already decaying (idle >180d, 5 of them >300d) — a curated index is a **stock**, not a flow.

## Reality checks

- **The diff first poisoned itself, and the re-run caught it.** The first version counted its own report
  draft as prior knowledge (the draft names every new lead), so a second run classified 5 of them as
  "referenced" and the yield fell 14 -> 9. The corpus now excludes this instrument's own report drafts;
  verified by two consecutive runs returning 14/14 identical. A one-shot diff hides this; it is only
  visible because it was run twice.
- **The 5 fresh leads are infrastructure, not edge** (MCP servers and SDKs). Nothing here changes a rule,
  a size or a threshold, and none of them can be "adopted" without an audit.
- **Agreement is not measurable**: only **2** index entries carry a verdict we actually hold
  (`agent-next` watch / atlas cap 3, `JamesANZ` drop / atlas cap 2). n=2 means *no contradiction found*,
  not *no disagreement*. The other 14 overlaps are radar mentions in drafts, never audited.
- **The curated axes are 110 days old** (2026-07-23). Scores are leads, never verdicts; only the
  maintenance axis is fresh.
- **7 of 44 entries (15.9%) are flagged `scam`, and none of them is in our queue.** Our seeder has no scam
  filter, only licence/stars/recency — so today's exposure is 0, and the flag class is a gap in the bar,
  not a live leak.
- **Concentration**: the whole atlas yield is 5 fresh repos from one pull. Compare it honestly: 7 leads in
  105 radar runs. One curated pull beat 26 days of radar, which says the radar's 35-slot list is the
  constraint — not the world.

## Verdict

Decay rule **SHIPPED** (0 expiries today; the rule binds from 2026-11-19). Atlas diff **MEASURED**: 5 fresh
third-party leads we had never referenced, 0 adopted, 0 enqueued. Nothing tagged `awaiting-approval` — no
decision, size, rule or threshold was touched.

**Worth doing with this (user's call, one command each):** enqueue the 5 fresh leads for audit
(`python3 scripts/asset-queue.py add --id demwick/polymarket-agent-mcp` …), or fix the seeder bar to widen
the radar's slot list. The second is the one that addresses the 0.067 leads/run.

**Rollback:** `git revert` the commit. Queue file untouched today; a future expiry is one JSON field
(`status`) plus a dated `decay` record, and `add --force` re-opens it.

---

Reads: `python3 scripts/asset-queue.py decay` (dry run) · `decay --self-test` ·
`python3 scripts/asset-queue.py atlas-diff` · `data/atlas-lead-diff.json`
