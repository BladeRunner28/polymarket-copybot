# BTC outside the copy path — what we actually run, and what the skipped BTC copies were worth

**As of 2026-10-13 01:0x UTC (2026-10-12 20:0x CDT)** · question asked 2026-10-12 in thread: *"Are we doing anything outside of copy trading around bitcoin on Polymarket or Kalshi?"*

**Short answer:** yes — three measurement lanes touch BTC, none of them trade BTC directionally with our capital; and the one thing that *would* have been BTC copy-trading (the wallets' intraday BTC trades we skip) is now measured, and the skips were **right**. There is no rule change on the table.

---

## 1. What runs on BTC today (outside the copy path)

**Kalshi venue tape — live, cron `copybot-kalshi-tape`, every 15 min**
Keyless, gap-free window capture of the venue-wide trade tape, filtered to 10 volume families
including **KXBTC15M**, **KXBTCD**, **KXETH15M**. Latest two ticks (01:00Z, 00:43Z): 215k / 210k
prints scanned, 16,412 / 12,479 prints kept verbatim, 761 / 750 per-minute bars, 844.6s / 840.6s
of tape captured, hole 2.9 min → **~94% duty**, no cap hits, `bars_deduped 0`. This is the only
irreversible lane: Kalshi's tape is a rolling ~8-week window, so uncaptured history is gone.

**Kalshi macro shadow lane — hourly, cron `copybot-kalshi-macro`**
CPI / Fed / U3 / GDP / recession / payrolls quotes + settlement rows (2,016 quote rows so far,
6 news rows). Not BTC, but it is the same instrument pattern on the same venue and it is the
only lane that can price macro-series mispricing with our own data.

**Kalshi BTC-15m calibration read** (`scripts/kalshi-btc15m-calibration.py`)
6,438 settled markets (2026-08-06 → 10-12): last print calibrated to the cent in both tails
(<0.02 → realized YES 0.0000, n=3,211; >0.98 → 1.0000, n=3,222) and **99.9% of the sample lives
in those two tails**. So "buy the cheap tail" has no sample to stand on; the open question is
*intra-window* pricing, which the tape is the substrate for.

**Two probes added tonight** (this session): `scripts/kalshi-pm-btc-updown-read.py` and
`scripts/pm-btc-intraday-skip-probe.py`. Both read-only, both keyless, no live-path change.

## 2. The skipped BTC copies: measured, and they were losing trades

Every decision our engine has ever made on `btc-updown-*` is a skip — **1,469 of 1,469** across
**602 markets** (1,427 five-minute, 42 fifteen-minute), and **not one PaperTrade** exists on those
markets. Counterfactual, held to resolution, ground truth = the venue's own resolution read
keylessly from Gamma (closed event + a 1/0 leg — not a snapshot guess):

- **Snapshot entry** (last snapshot ≤ decision, lag-bounded 180s): n=543, 191 markets, win **45.9%**, mean edge **−0.0522 per $1**, market-clustered 95% CI **[−0.0939, −0.0096]** → CI excludes 0 *on the loss side*.
- **Detected entry** (the price our engine actually saw): n=1,466, 599 markets, win **47.8%**, mean edge **−0.0419 per $1**, clustered 95% CI [−0.0835, +0.0012].

Read: copying those wallets on these markets would have **lost** roughly 4–5¢ per dollar staked
before any exit logic. The gates walked away from a coin-flip at ~50¢ minus fees.

**And the blacklist is not why they were skipped.** The C-200 blacklist names the token
`bitcoin`; these markets carry category token **`btc`**, and `score-trades.ts` compares the
blacklist with an exact token match (`botBlacklist.includes(t.marketCategory)`). The actual
reasons, read out of `DecisionJournal.risksJson`, are the generic gates:

- `price drifted X since entry > max 0.0040 (too late)` — our detection arrives after the move;
- `resolves in 0.0h < min 2h` — structural: a 5-minute market can never clear a 2-hour floor;
- `liquidity $0 < min $750`, `price 1.000 near certainty`.

So there is no "unblacklist bitcoin" hygiene bug worth fixing for its own sake either — the
exclusion is incidental and, as measured, correct.

*One real bug was found and killed in the probe itself:* outcome labels in this family are
`UP`/`DOWN`, not `YES`/`NO`. The first version filtered for `YES`/`NO` and silently dropped
every row while printing "0 measurable". Fixed (plus a private DB-snapshot read, because a
`?mode=ro` connect on the live WAL DB had already failed once).

## 3. The cross-venue BTC pair: the oracle basis is the whole story

Kalshi `KXBTC15M` and Polymarket `btc-updown-15m-*` are the **only pair in either venue family
that aligns exactly** — same wall-clock 15-minute window, same binary proposition. The
temperature and oil cross-venue reads die on ontology (one-degree bucket-grid offset; "above
84.99" vs integer strikes → zero exact-alignment rows). But the oracles differ:

- **Kalshi** resolves on the simple average of sixty seconds of **CF Benchmarks' BRTI** before
  the close vs before the open.
- **Polymarket** resolves on the **Chainlink BTC/USD 60s TWAP** over the range.

Measured, 288 windows over 3 days: **282 agree / 5 disagree = 1.74% disagreement, 95% CI
[0.75%, 4.01%]**. That number is not trivia — a paired position (buy Up on one venue, buy Down
on the other) pays exactly 1.00 when the oracles agree and **pays 0.00 when they disagree**, so
1.74% is precisely the probability of losing the whole stake on a "riskless" pair.

**On quotes, the apparent gap was an artifact.** A single-snapshot read suggested ~6–7¢
(PM Up ask 0.09 vs Kalshi Up bid 0.15). Four simultaneous back-to-back reads of the same window,
20s apart, buying the cheap leg on each venue:

- pair cost 1.0900, 1.0000, 1.0400, 0.9890 → **net after fees −0.1122, −0.0182, −0.0554, −0.0017** (all ≤ 0)
- the touch moves fast (Kalshi Up bid 0.77 → 0.86 → 0.911 inside one minute; PM Up ask 0.86 → 0.90)
- **never read Polymarket quotes from Gamma's `bestBid`/`bestAsk`** — they were stale by ~0.6
  (gamma said 0.72/0.73 while the live CLOB book said 0.86/0.90). The CLOB book is the only
  quote source we should trust.

**One thing must be pinned before any net number is quoted:** this market's CLOB reports
`maker_base_fee = taker_base_fee = 1000` (unit unconfirmed), while the repo convention
(`build-decision-dataset.py`) uses `0.07·min(p, 1−p)`. That difference is ~half the apparent gap.

## 4. Verdict and what would change it

**Nothing in the live path changes.** No rule edit, no blacklist edit, no new lane. Measured
result: the BTC copy skips cost nothing (they avoided a −4 to −5¢/dollar trade), and the
cross-venue "arb" on the only aligned pair does not survive simultaneous sampling, before you
even charge it 1.74% oracle-disagreement risk.

**If you want the next step, it is a pre-registered read — recommendation only, not built:**
a paired Kalshi×PM BTC up/down study with *true* simultaneity (both venue books read within ~1s),
full depth at the touch recorded, the PM fee schedule pinned first, n ≥ 288 windows, and a gate
of **net CI lower bound > 0 after the oracle-disagreement haircut**. If that gate fails, the
honest close is "the two venues price the same 15 minutes correctly".

Artifacts: `data/pm-btc-skip-probe-20261013.json`, `scripts/pm-btc-intraday-skip-probe.py`,
`scripts/kalshi-pm-btc-updown-read.py`.
