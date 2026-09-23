# PSMI vs our C-200 P&L — measured, null result (2026-09-23)

**Card:** `polycopy-psmi-regime-measurement`. **Status: closed on a NULL.** No gating, no rule, no shadow
lane — and on this evidence PSMI must not gate anything.

**What shipped:** `data/polycopy-psmi-history.csv` (their 57 daily closes, stored as the immovable record),
`scripts/fetch-psmi-history.py` (idempotent refresh of that file from the two sanctioned endpoints; existing
rows are never rewritten), `scripts/psmi-regime-measure.py` (the read-only measurement; one command
re-runs everything below). Neither script is wired into cron and neither touches the copybot.

---

## 1. The feed (sanctioned endpoints only)

- `GET https://polycopy.app/api/indexes/smi/public` → today's `score`, `zone`, `date`, `methodologyVersion`, cohort note.
- `GET https://polycopy.app/api/indexes/smi/history?format=csv` → daily closes, 57 rows **2026-07-28 → 2026-09-22**,
  columns `date, score, zone, momentum, breadth, participation, conviction, methodology_version, is_backfill`
  (weights 30/25/25/20; `is_backfill=false` on every stored row).
- Attribution is carried in both scripts and the CSV keeps their header: *"Polycopy's Polymarket Smart Money
  Index (PSMI), methodology 2.0.0"*.
- Their `robots.txt` disallows `/api/` in general; these two are the endpoints their own page advertises as
  free to use, and **nothing else on `/api/` is touched** by anything here.

## 2. The join

| | |
|---|---|
| window | 2026-07-28 → 2026-09-22 (57 PSMI days) |
| joined n | **45 days** with ≥1 settled C-200 leg (12 PSMI days have no C-200 book — the July era — and are excluded rather than counted as $0 days) |
| legs | 1,872 settled C-200 legs |
| realized | **+$2,694.14 on $14,298.79 cost = 18.8% of cost** |
| daily legs | min 1 · median 38 · max 152 |
| our side convention | LOCAL calendar day, `closedAt ?? resolvedAt`, `status ∈ {closed,resolved}`, `isDemo=0` — the same bucket the phase ladder and the EOD report use |

Every association below is accompanied by a **day-resampled bootstrap CI** and a **pairing permutation p**
(20,000 shuffles); the zone test uses a *pooled* permutation (shuffling inside one group cannot move that
group's mean — that mistake always returns p = 1.000).

## 3. Results

### 3.1 Level correlation, PSMI vs our daily book (n = 45 days)

| PSMI component | vs daily PnL $ | 95% CI | perm p | Spearman |
|---|---|---|---|---|
| **score** | **+0.267** | [−0.003, +0.458] | 0.077 | +0.142 |
| momentum | +0.271 | [+0.010, +0.458] | 0.075 | +0.172 |
| breadth | +0.149 | [−0.084, +0.362] | 0.326 | +0.042 |
| participation | +0.004 | [−0.189, +0.198] | 0.982 | +0.092 |
| conviction | +0.318 | [−0.034, +0.525] | 0.036 | +0.163 |
| delta (day-over-day) | −0.089 | [−0.459, +0.314] | 0.561 | −0.102 |

Against **daily edge %** (PnL / cost) nothing clears p = 0.27 (score +0.125, p = 0.45); against
**PnL per leg** nothing clears p = 0.22. So the one eye-catching number (conviction, p = 0.036) is 1 of
18 component × metric tests — one false positive at α = 0.05 is exactly what 18 tests produce — and its own
rank correlation (+0.163, p = 0.28) and CI (which spans zero) do not support it.

### 3.2 Lead / lag — PSMI(t) vs C-200 PnL(t+k)

| k | n | Pearson | perm p | Spearman |
|---|---|---|---|---|
| 0 | 45 | +0.267 | 0.076 | +0.142 |
| **+1** | 45 | **+0.291** | 0.053 | +0.243 |
| +2 | 45 | +0.178 | 0.245 | +0.089 |
| +3 | 45 | +0.075 | 0.625 | −0.019 |
| −1 | 44 | +0.137 | 0.387 | −0.007 |
| −2 | 43 | +0.166 | 0.293 | +0.075 |

No horizon is significant, and the shape (peak at +1, gone by +3) is what a two-day coincidence looks like,
not what a regime signal looks like.

### 3.3 Zone split (the way the index is actually marketed)

| zone | days | legs | mean PnL | median PnL | win-days | median edge | median win-leg share |
|---|---|---|---|---|---|---|---|
| ACTIVE | 18 | 909 | +$137.06 | +$4.78 | 10/18 (56%) | +2.4% | 0.49 |
| WATCHING | 27 | 963 | +$8.41 | −$3.11 | 13/27 (48%) | −2.9% | 0.52 |

Pooled permutation: **p = 0.080 for the mean difference, p = 0.528 for the median difference.** Leg-level
(day-clustered bootstrap): ACTIVE mean leg +$2.71 [−$0.03, +$6.80] vs WATCHING +$0.24 [−$1.09, +$1.68] —
both intervals include zero, and the win-leg shares are the same (50.4% vs 51.6%). The ACTIVE/WATCHING
contrast is a mean-versus-median artifact of the tail, not a regime.

### 3.4 PSMI quintiles (descending score)

| bucket | score range | days | legs | mean PnL | median PnL | win-days | median edge |
|---|---|---|---|---|---|---|---|
| Q1 | 65–73 | 9 | 546 | +$129.25 | +$16.34 | 7/9 | +24.5% |
| Q2 | 55–65 | 9 | 363 | +$144.87 | −$27.77 | 3/9 | −9.3% |
| Q3 | 51–54 | 9 | 192 | −$13.59 | −$4.57 | 3/9 | −33.7% |
| Q4 | 44–51 | 9 | 426 | +$52.62 | +$2.81 | 5/9 | +21.0% |
| Q5 | 31–44 | 9 | 345 | −$13.81 | +$0.15 | 5/9 | +0.1% |

**Non-monotone** — Q1 and Q2 lead, Q3 is the worst bucket, Q5 is middling — i.e. no dose-response.

### 3.5 Two checks that could have faked a signal

- **Throughput**, not edge: an activity index could move *how much* we trade without moving how well.
  PSMI vs legs/day: +0.133 (p = 0.38). PSMI vs cost/day: +0.280 (p = 0.066). Weak and not significant.
- **Control lane:** PSMI vs STANDARD daily PnL: **+0.043 (p = 0.75)** — a market-wide regime story would
  have shown up here too. It doesn't.

### 3.6 Outlier sensitivity — the +0.267 is two days

| trimming | n | Pearson | perm p | Spearman |
|---|---|---|---|---|
| none | 45 | +0.267 | 0.075 | +0.142 |
| drop 1 best + 1 worst | 43 | +0.246 | 0.110 | +0.127 |
| drop 2 best + 2 worst | 41 | +0.136 | 0.406 | +0.027 |
| drop 3 best + 3 worst | 39 | **−0.036** | 0.824 | −0.093 |

The best two days (2026-09-16 +$743.38 and 2026-09-18 +$993.70 — the latter on **12 legs**, a Kelly-sized
longshot win) are **64% of the sample's entire realized PnL**. Remove them and the association is gone. The
C-200 daily series is too heavy-tailed for a 45-day Pearson to mean anything on its own, which is why the
rank, median, win-share and trimmed views are all printed: every one of them says ≈ 0.

## 4. Verdict

**Null: no measured relationship between PSMI (level, delta, or any component, at any horizon −2…+3 days,
by level, rank, zone or quintile) and our C-200 daily P&L or edge on 45 overlapping days.** Therefore:

- PSMI **gates nothing** and is not a shadow lane; any proposal to use it needs its own card and a
  pre-registered test on a longer sample.
- The card closes. The instrument stays (`scripts/psmi-regime-measure.py`, one command), so a re-test after
  the series doubles is cheap.

**What this null does and does not exclude:** with n = 45 days this design has ~80% power against |r| ≈ 0.40
and would miss a true |r| = 0.30 roughly half the time. So the honest statement is "no strong relationship,
and no dose-response" — not "PSMI is irrelevant to the market". The CI on the score term still admits a
moderate positive day-level correlation, and the index — a cohort aggregate over 1,000 parity-verified
wallets with market makers excluded — remains a plausible *market* regime descriptor that our
wallet-selection book simply does not load on.

**Why the null is unsurprising:** our daily P&L is decided by a handful of legs (median 38 legs/day, 64% of
the sample's PnL from 2 days), a copy-score-filtered book of ~25 wallets, and Kelly sizing that deliberately
concentrates; a broad index of smart-money activity has no obvious channel into that.

## 5. Not shipped, offered separately

A **daily append** of the history (one curl + append via `fetch-psmi-history.py`) would let a future re-test
run on 2–3× the days without re-fetching a shallow window (their free depth is 24 months, so nothing is lost
by waiting — but the local record is the only thing that keeps *today's* rows from being silently revised
later). Not wired; it is a new standing process, so it is the user's call.

## 6. Reproduce

```bash
python3 scripts/fetch-psmi-history.py          # refresh the stored CSV (idempotent, reports no-op)
python3 scripts/psmi-regime-measure.py         # the whole measurement above, writes nothing
```

Both are stdlib-only Python 3.9-compatible, read `data/polycopy-psmi-history.csv` + `prisma/dev.db`
(read-only URI), and print a `Reproduce:` footer. `prisma/dev.db` datetimes are Unix-ms.
