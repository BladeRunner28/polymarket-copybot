# C-200 maker fill: does the fixed 2¢ stay in the model? — NO (recommendation, nothing applied)

**Card** `c200-maker-fill-assumption` · approvals `apr-c200-maker-fill-assumption` (APPROVED 2026-11-12T19:32Z) ·
**Lane A** (booking model) · **recommendation only — no code, rules, DB or cron change in this run**
**Re-measured** 2026-11-12T19:36Z from `prisma/dev.db` opened `immutable=1`, script `scripts/c200-maker-credit-read.py`.

---

## 1. Verdict

**No — the fixed 2¢ does not stay.** It was already retired on 2026-10-10 and there is no
measurement since that reopens it. Keep the **measured per-band credit** as the booking model
(live now, `MAKER_CREDIT_MODE` unset → `measured`), keep `modelled` as a **counterfactual switch only**,
and keep every flat-2¢ figure labelled **pre-2026-10-10 history**.

Two facts decide it, and both got stronger, not weaker, in the 5 weeks since the cutover:

1. **The level is reachable on ~18–19 % of legs within an hour, not ~81 %** (two independent
   instruments — our own 5 s L2 book and the public tape — agreeing to 1 pp). The credit is largest
   exactly where reachability is smallest: 2¢ is 34.9 % of a $0.05 entry and the 0.00–0.10 band's
   measured share is 2.8 %.
2. **The credit was never a fee or a spread cost — it is a fill-probability assumption**, and since
   2026-10-28 the lane no longer needs that assumption: `fillStatus` is resolved per leg from book
   evidence and `bookedPnl()` zeroes unfilled legs outright (`src/lib/paper.ts`, live default).
   Restoring a flat 2¢ would put a **probability-weighted fiction back on top of a per-leg
   observation** — it re-prices legs the resolver already knows never filled.

---

## 2. What the book says today

Same settled population both columns, `botId='BANKROLL_200'`, `isDemo=0`, `closed|resolved` with
`COALESCE(closedAt,resolvedAt)` (TR-15). Counterfactuals use the repo convention
(`src/lib/copy-cost.ts`): hold the exit price and the stake fixed, re-price the entry.

| | pre-cutover (flat 2¢ live) | post-cutover (measured live) |
|---|---|---|
| settled legs | 1,550 | 443 |
| staked | $14,269.03 | $9,458.69 |
| realized PnL, as stored (p(fill)=1) | $5,751.56 | $1.76 |
| realized PnL, fill-aware (live basis) | $4,983.83 | **−$59.17** |
| credit booked | **$2,757.15 = 47.9 % of raw PnL** | $92.39 |
| same book with the **flat 2¢** (fill-aware) | $4,983.83 (no change — it *was* the model) | **+$492.21 (+$551.38)** |
| same book with **no credit** (fill-aware) | $2,548.20 (−$2,435.63) | −$112.07 (−$52.90) |

Read it in one line: **the flat 2¢ was 48 % of the maker-era book, and on today's book it would
manufacture $551 of PnL against the $52.90 the measured credit actually contributes on the same
fill-aware basis (10×) — i.e. it would multiply by ten the one term holding the lane up.** Without any
credit the lane is −$112 post-cutover; the measured credit is the whole distance between a losing and
a flat month. That is exactly why the number has to stay honest: it is the only thing holding the
lane's PnL up, so an unsupported version of it *is* the PnL story.

Per band, post-cutover (fill-aware PnL, and what a flat 2¢ would add):

| intent band | legs | staked | fill-aware PnL | credit booked | flat-2¢ delta |
|---|---|---|---|---|---|
| 0.00–0.10 | 38 | $1,769.47 | −$767.26 | $8.53 | **+$149.45** |
| 0.10–0.20 | 59 | $2,825.34 | $527.05 | $36.84 | **+$304.09** |
| 0.20–0.40 | 186 | $2,226.33 | $84.03 | $34.07 | +$70.62 |
| 0.40–0.60 | 21 | $24.93 | $3.97 | $0.22 | +$0.44 |
| 0.60–0.80 | 122 | $1,092.63 | −$2.14 | $5.73 | +$13.31 |
| 0.80–1.00 | 17 | $1,520.00 | $95.18 | $7.00 | +$13.47 |

82 % of the flat-2¢ delta ($453 of $551) lands in the two cheapest bands — the bands the model is
already sizing UP (v51 ×2.0 under 0.20) and the bands where reachability is 2.8–8.4 %. The unsupported
part of the credit and the long-shot edge are, still, one finding.

---

## 3. Reality checks I ran before answering

**(a) Is `measured` actually what is live?** Yes, three ways: `.env` has no `MAKER_CREDIT_MODE`;
the process env has none (so the code default applies); the sidecar log carries **448
`[Maker Credit]` lines, 100 % `mode=measured`, zero `mode=modelled`**. The running binary's mtime
(Oct 10 03:07) matches the daemon's start (Oct 10 03:07:04), so the process postdates the build.

**(b) Does the booked book match the code, or is a stale process booking something else?**
Reconstruction inverted from `entryPrice` matches the stamped `intentPrice` on **253/253** pre-cutover
BUY legs (max error 0.0000). Post-cutover, of 330 stamped rows, **299 sit exactly on one of the five
band credits** (145 × 0.229, 85 × 0.188, 43 × 0.084, 26 × 0.028); the other 31 are accounted for below
(26 NO-side label artifacts + 5 cutover-day flat-2¢ legs). So the table in the binary is the table in
the book.

**(c) One implementation gap, immaterial.** 5 legs on 2026-10-10 between 04:47 and 06:26 booked a
**flat 2¢** (`intent − entry = 0.02`) with no `[Maker Credit]` log line — the cutover window, small
sizes ($1.25–$20), no recurrences in 5 weeks. Worth one line of record, not an action.

**(d) 26 post-cutover legs carry `entry ≈ 1 − intentPrice`** (e.g. 0.885 vs 0.115), all `unfilled`.
That is the known positional-price / NO-side label defect, not a credit defect; it is out of scope
here and already owned by the price-side card. Flagged so the next reader does not mistake the
residual in the reconstruction for a credit error.

**(e) The EOD's published counterfactual is now priced against a model that no longer runs.**
`src/lib/copy-cost.ts` re-prices **every** maker-era leg at `entry + 0.02` (`MAKER_FEATURE_START_MS`
= 2026-08-28, no cutover split). Pre-cutover that is exactly the flat model. Post-cutover the booked
entry is only `intent − c_m` (0.06–0.46¢), so the code prices a 2¢ step from an entry that is already
credited: on the post-cutover book it prints **$841.14** where an era-correct
`entry + (0.02 − c_m)` re-price gives **$1,055.13**. Neither number is "the fixed 2¢ assumption any
more" — the label is right for the pre-cutover rows and wrong for the 443 rows that follow them.
**This is the one thing here I would change, and it moves a published figure, so it needs your yes**
(exact patch in §5, FLAG 2).

**(f) The ladder statistic, not just the PnL.** Measured 7-settled-day basis (2026-11-05..11-12,
178 legs, $4,359 staked): **$172.04 booked (24.58/day)** vs **$489.68 with the flat 2¢ (69.95/day)** —
a **2.85×** inflation of the exact statistic that decides a ladder rung. Neither clears the 1,000/day
rung ($7,000 / 7 days), so nothing advances either way today; the point is that the flat 2¢ would
have made the advance gate read 3× closer than it is, on PnL that never existed.

---

## 4. The one question the measurement does not close

`fillStatus = 'filled'` means the level *was* reachable — so on those legs the credit is no longer a
probability, it is an observation. On the 100 filled post-cutover legs, as booked they are **−$128.50**;
at the full 2¢ they would be **+$43.49** (**+$171.99**).

That is the only shape in which any part of the 2¢ could come back, and I am **not** recommending it
now: reachability is not fill (it says a counterparty was at that level, not that our size cleared),
and reached legs are the adversely-selected ones (−0.0818 drift vs +0.0038 on unreached legs), so
re-pricing the entry up on exactly the legs that came to us is the assumption that needs the most
evidence, not the least. If it is ever proposed it should arrive as its own pre-registered read on
filled legs (what fraction filled in full at the level, and what the exit drift was on them), not as a
side effect of this card.

---

## 5. Overridable flags (one line each, answer in chat)

- **FLAG 1 — keep `measured` as the C-200 booking model.** *Default: yes (no action; it is what runs).*
  Changes if you say override: `MAKER_CREDIT_MODE=modelled` in `.env` + `launchctl kickstart` → every
  leg books the full 2¢ again; post-cutover book **−$59 → +$492** fill-aware and the 7-day ladder basis
  **$172 → $490**. No rebuild.
- **FLAG 2 — era-split the published credit counterfactual** in `src/lib/copy-cost.ts`
  (`credit = (0.02 − bookedCredit) × (pnl+size)/(entry + 0.02 − bookedCredit)` for legs opened after
  2026-10-10T03:07, unchanged for the flat-era rows), so the EOD prints the counterfactual of the model
  that actually ran. *Default: off (do nothing).* Say override and I patch it in one commit with a
  before/after of the EOD line (post-cutover: $841 → $1,055 modelled, ex-maker edge re-derived).
- **FLAG 3 — conditional-on-fill credit.** *Default: not carded.* Say the word and I card it as a
  measurement (filled-leg fill depth + exit drift), not as a rule change.

## 6. Revert

Nothing was applied in this run. The booking model's revert remains exactly as shipped 2026-10-10:
`MAKER_CREDIT_MODE=modelled` in `~/polymarket-copybot/.env`, then
`launchctl kickstart -k gui/$(id -u)/com.xsnyde2.copybot-rust-sidecar` (env is read per request, so no
rebuild and no relaunch of anything else). The script added here (`scripts/c200-maker-credit-read.py`)
is read-only: it opens the DB `immutable=1` and writes nothing; delete the file to remove it entirely.

## 7. Reproduce

```
python3 scripts/c200-maker-credit-read.py          # every figure in §2, §3(f) and §5
```

It prints the pre/post populations, the three PnL bases (raw / fill-aware / counterfactual), the
per-band table, the reconstruction check against the stamped `intentPrice`, the copy-cost.ts
era-correct delta, and the 7-settled-day ladder basis. `COPYBOT_DB=<path>` overrides the DB.
