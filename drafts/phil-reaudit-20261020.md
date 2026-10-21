# bennyjo/phil — RE-AUDIT (re-surface check, not a fresh audit)

**Standing audit:** `drafts/phil-audit-2026-09-28.md` (full audit, HEAD `b21f909`, pushed 2026-09-28T18:14Z).
**This pass:** 2026-10-20 · HEAD `b78d084` ("lease: cloud released"), pushed 2026-10-20T12:23:04Z · Apache-2.0 unchanged.
**Method:** GitHub API only (metadata, commit history by path, workflow-run health, issues, `contents` for the files named below) plus my own recompute from the two data files the repo publishes raw — `journal/ledger.jsonl` (75 rows) and `journal/forecasts.jsonl` (2,439 rows), downloaded and aggregated locally. No clone, nothing installed, no candidate code executed, no key/address touched.

**Verdict re-stated: unchanged.** SKIP as a dependency; keep the three adopted mechanisms (one now executed in our repo, two still Backlog); one genuinely new artifact graded **concept-only**. Nothing here justifies a second full audit doc or a new approval ask.

---

## 1. What actually moved on their side

| Fact | 2026-09-28 audit | now | Note |
|---|---|---|---|
| Stars / forks | 153 / 37 | **232 / 137** | community signal only — see caveat |
| Size | not recorded by the standing audit | **248,315 KB (~242 MB)** | journal growth (`.jsonl` 82 MB, `.md` 3.5 MB) |
| Commits since audit | — | **≥300** (3 full pages of 100) | subject mix of the newest 100: `lease` 51, `cycle` 23, `retro` 19, `cycle(triggered)` 4, `deep-retro` 2, `cycle-note` 1 |
| CI health | — | **last 5 runs: success** | not inferred from my own run — read off `actions/workflows/ci.yml/runs` |
| Test suite | **none** ("zero unit tests is itself a finding") | **5 offline test scripts wired into CI** | `core/test_{lease,real,screener_log,token_ids,headline_arena}.py` + `validate.py` + `score.py --json` parse + `ruff --select E9,F` + the boundary job |
| New code since audit | — | `core/release_calendar.py` (24.5 KB), `headline_arena.py`, `mechlog.py`, `screen_value_check.py`, `pmapi.py` + the 5 tests | §6 |
| **Audited core** | `replay.py`, `forward_test.py`, `policy.py` | **frozen: last touched 2026-09-02** (`49c8476`, `be26e26`, `fb55f18`) | this is the whole finding |

Half the commit volume is `lease:` churn from their two-runner cloud/local topology — activity that says nothing about the strategy. The rewrite cadence is unchanged: 19 `retro:` + 2 `deep-retro:` commits in 22 days (~0.95 LLM edit-commits/day), same rate the audit measured (116 in the newest 500).

**The audited machinery is byte-stable.** `core/replay.py` (the sealed-cutoff forward test), `.github/scripts/forward_test.py` (the frozen pass criteria) and `strategy/policy.py` (the only coded decision rule) have not been committed to since 2026-09-02. Everything the standing audit verified by re-derivation — the fill model, `cw_return = roi − stake-weighted SE`, `train = settled_ts ≤ TS / test = settled_ts > TS`, `MIN_BETS=15`, the single-bet-dominance cap — is the same code today. **There is no new math to check, so this digest carries no new technical information.** What changed is the record the machinery scores.

---

## 2. The record got worse, and the probability claim replicated at ~2× sample

Recomputed from the published data files (my arithmetic, not their `score.py`; row set = rows with `status∈{won,lost}`):

| Measure | Standing audit snapshot | Now (70 settled) |
|---|---|---|
| Settled bets | 48 | **70** (34 W / 36 L) |
| Realized PnL | −$7.92 | **−$20.73** on $350 staked (−5.9% ROI) |
| Brier — agent | 0.2903 | 0.2249 |
| Brier — market at entry | 0.2050 | 0.1678 |
| Brier delta (agent − market) | +0.0853 | **+0.0571 (still behind)** |
| Claimed edge > 0.10 ("outside-view veto" case) | 0W/5L, −$25 (their prose) | **11 settled, 2 W, −$12.67** |

Split at the audit date: pre-audit 51 settled / 22 W / −$6.80; **post-audit 19 settled / 12 W / −$13.94**. On that 19-row slice agent Brier is 0.0822 vs market 0.0838 (delta −0.0016) — i.e. *level* with the market — while PnL is −$13.94. That combination is n=19 noise, not a turnaround: a 12-of-19 run at 0.6–0.9 entry prices pays ~$0.6–1.1 per win against a flat −$5 per loss. The 70-row figure is the one that carries weight, and it says the same thing the audit said, harder.

**Forecast stream (the stake-free one, which is the honest calibration instrument):**

| | 2026-09-28 | now |
|---|---|---|
| Settled forecasts | 1,039 | **2,177** |
| Brier agent / market | not printed by the standing audit | **0.3720 / 0.3584** |
| Delta (agent − market) | +0.0092 | **+0.0136** |

Post-audit subset alone: 992 settled, 0.3689 vs 0.3577 → **+0.0112**. So the "agent's probabilities are worse than the market price" finding **replicated on a doubled sample at slightly larger magnitude** — this is now the most robust negative in the repo, and it is the number that should anchor any future re-read.

---

## 3. The sealed forward read stopped reporting (mechanism finding)

`forward_test.py` produced exactly one public verdict — issue #3, created 2026-09-10: **FAIL, forward `cw_return` −0.1557 on 169 settled rows** (worse than the −0.0730 the standing audit computed from a smaller window). It was closed 2026-10-13.

Since then **1,735 forecast rows have settled after that same 2026-09-02 cutoff** — ten times the sample the verdict rested on — and no new verdict exists. The reason is in the workflow, not in the results: `forward-test.yml` opens the issue once and then short-circuits (`if [ -n "$(gh issue list --label forward-test ...)" ]; then ... not opening another`). The daily 06:17 cron now runs green forever and reports nothing. The one artifact that let this repo publish its own FAIL has become a dead read.

**Reusable caution, and a check on us:** a once-only alert emitter turns a recurring measurement into a one-shot one. Our equivalent (`data/shadow-forward-read.jsonl`) accumulates per-run rows rather than de-duplicating, so the emitter is not the problem here — but the *cadence* is: 4 rows total (2 smoke, 2 `preregistered`) and nothing schedules a re-read. The 2026-10-10 pre-registered read is our only one, and it was run by hand.

---

## 4. Roadmap re-map — what changed on OUR side is what moves the verdict

The standing audit's three ADOPT rows are now:

| Adopted mechanism | Card | State today |
|---|---|---|
| Sealed-cutoff forward test + pre-registered pass criteria | `phil-trial-a-oct8-forward-read` | **Done, and it produced a real result** — pre-registered read ran 2026-10-10 14:47 CDT: `late_drift_gate` **FAIL** on criterion (c) (clustered 95% CI [−8.88%, +16.82%] includes 0; era signs inconsistent) and `min_confidence_gate` **FAIL** on (c) ([−9.70%, +14.31%]); both cleared the ≥150-settled power bar, so both are powered fails, not "underpowered" |
| Machine-enforced frozen-artifact tripwire (CI) | `phil-frozen-artifact-tripwire` | **Backlog — and its stated rationale has expired.** The card was justified as enforcement under "our Kelly freeze (window closes 2026-10-08)"; that window is closed (`precommit-mid-oct-kelly-gate` = Done). The *mechanism* is more relevant now than when it was written, but for different objects: the frozen pre-registered gates that are live in the tree — `wx2` and `btx2` (both "gate frozen before the first in-window sample"), the `shadow-forward-read` criteria, `c200-entry-floor-005-prereg` (gate 2026-10-24). Re-point the card at those or close it; do not leave it resting on a deadline that has passed |
| Counterfactual-ledger primitive for declined decisions | `phil-counterfactual-ledger-primitive` | **Backlog, unchanged** and still the right shape (`lowconf-shadow-dust-floor` is the live example of the bug class it prevents) |

New cards added since 2026-09-28 that touch this audit's fit rows: `measurement-label-integrity` (Done), `data-api-v2-migration` / `data-api-v2-outcome-normalisation` (Scheduled), `nearcertainty-tail-shadow` (Backlog), `c200-entry-floor-005-prereg` (Scheduled), `ml-doctrine-time-and-era-splits` (In Progress). **None of them makes any phil component newly adoptable** — the doctrine rows were already covered, and `nearcertainty-tail-shadow` asks for a *price read on our own tail*, which phil cannot inform (zero markets in their ledger below 0.05 entry; their flat-$5 payoff at high prices is a caution about stakes, not a data source).

Net: **phil's marginal value as a source is largely spent.** One mechanism executed with a real verdict, two mechanisms sitting as Backlog cards, and no new code in the parts that ported.

---

## 5. Fit-table delta (only the rows that move)

| phil component | 2026-09-28 | now | Why |
|---|---|---|---|
| Sealed-cutoff forward test + pre-reg criteria | ✅ adopt | ✅ **adopted and consumed** (`phil-trial-a-oct8-forward-read` Done) | card closed with both lanes failing on (c) |
| Frozen-artifact tripwire | ✅ adopt (pattern) | ✅ adopt (pattern) — **rationale needs re-pointing** | §4 |
| Counterfactual-ledger primitive | ✅ adopt | ✅ adopt — still Backlog | unchanged |
| Zero unit tests | caveat | **caveat narrowed** | 5 offline tests now gate CI; still no `tests/`, no `pyproject.toml`/`requirements.txt`, and **no test touches the trading math** (replay/score/ledger arithmetic, the fill model). The tested surface is lease, real-settle fail-closed, screener-log rotation, token ids, headline-arena payload shape |
| `core/release_calendar.py` (NEW) | — | ⚪ **concept-only** | §6 — dormant, zero call sites |
| Self-rewriting loop | ⚪ concept-only | ⚪ concept-only | 19 retro commits in 22 days, still prose-gated; unchanged |
| In-sample replay as promotion gate | ❌ anti-pattern | ❌ anti-pattern | unchanged, and the repo now has no live forward read at all (§3) |

---

## 6. The one new artifact: `core/release_calendar.py` (dormant)

A scheduled-release calendar: a hard-coded agency table (BLS/BEA/Fed/ECB/BoE times as explicit UTC instants, dates read off the source pages) → joined to **open gamma markets that resolve on that print**, → emitted as `core/watch.py` calendar entries at `release_utc − lead_hours`. Three tests decide a match, all on gamma title/slug: their own family mapper calls it an econ print; the playbook's "mechanical-econ" carve-out holds (named official series, numeric/directional criterion, no company-event shape); the series pattern fires. Of the releases at or before the market's end date, the one whose **named reference month** wins, else the nearest, under `--max-lag-days 21`.

What makes it worth a row rather than a shrug: it is **network-light (gamma only, one page of 100), read-only, keyless, and it PRINTS — it writes nothing**. Its own docstring states the bar for switching it on lives in `journal/lane-coverage-decision.md` and that turning it on is an operator act. It also carries a real bug story worth remembering: it cannot be named `core/calendar.py`, because `core/` is `sys.path[0]` and a sibling module of that name shadows the stdlib `calendar` that `_strptime` needs — `validate.py` dies on its first `strptime`.

**Gap check in our tree (verified, not asserted):** `release_calendar|releaseCalendar|econ_release|economicCalendar` → **0 hits** in `src/`, `scripts/`, `lib/`; no `drafts/` design doc mentions a release calendar; no `prisma` model (`Watchlist`/`CalendarEvent`/`EconRelease` all absent). The `fomc|bls|bea` hits are categorisation and lane code only (`src/lib/market-category.ts`, `scripts/kalshi-macro-shadow.py` — series keyword map, no schedule/timing logic in 340 lines — `scripts/build-ml-dataset.py`, `scripts/wallet-concentration-test.py`). No roadmap card asks for a release calendar; the nearest is `kalshi-macro-shadow-lane` (In Progress, a calibration instrument) and `kalshi-gdelt-context-v2` (Backlog).

**Grade: ⚪ concept-only — math/logic to reimplement behind our gates, not a capability to copy.** Two reasons, both mechanical: the module has **zero call sites in their own product** (their own docstring says so), so there is no wiring to study and no evidence its thresholds are calibrated; and the transferable part is a *join rule* (release → market end date → reference-month match → lag cap), which is ~150 lines of our own TypeScript if a lane ever wants it.

**Honest limit on the value:** this is a **timing/discovery** gain — it says *when a print lands and which market resolves on it* — not an alpha gain. Our funnel is wallet-copy; the calendar only helps if tracked wallets actually trade the print-window markets, and their own justification for it is a journal claim (`screener-value-decision.md`: scheduled prints are one of two families where research beats the price) that I have **not** verified and that says nothing about our copy lane. Sequence it behind a measurement of how much of our declined/admitted flow sits in econ-print families near a release.

---

## 7. NOT-portable (additions since the standing audit)

The standing list (unaudited LLM threshold edits, admission on narrative, in-sample promotion, Pearl/real-money leg, Olas mech, odds-API client, 6,911-line playbook, flat-$5 caps, "self-improving" as evidence) stands unchanged. New:

10. ❌ **The once-only forward-test emitter** (§3). Copying it would give us a read that fires once and then reports green forever.
11. ❌ **The dormant-module pattern as a deliverable.** `release_calendar.py` is well-documented and never called; their own `screen_value_check.py`/`mechlog.py` sit the same way. Ship code that has a caller or ship nothing — their repo is the cautionary example, not the model.
12. ❌ **Stars/forks as a quality signal here.** 232★/137 forks against a −$20.73 ledger that publishes its own FAIL: the fork ratio (0.59 forks/star, tripled in three weeks) is people cloning a *demo of self-rewriting agents*, not a validated strategy. Nothing about the community number should reach a roadmap note.

---

## 8. Caveats

- **Recompute, not their scorer.** My PnL/Brier figures come from `journal/ledger.jsonl` with `status∈{won,lost}` (70 rows; 5 rows still open, no status). The standing audit printed 48 settled with `score.py`; the difference is row-set, not disagreement — `score.py` drops rows it cannot mark (no ask at entry, superseded rows), and I did not run it. Where the two differ I quoted both.
- **The forecast `brier_market` baseline uses the recorded mid** (`market_prob_at_record`), which is what `score.py:48-64` documents for that stream; the bet-side baseline uses the ask. Not comparable to each other, comparable across time — which is all §2 uses them for.
- **CI green ≠ the math works.** The 5 new tests cover lease exclusion, real-settle fail-closed, screener-log rotation, token ids and adapter payload shape. Nothing tests `replay.py`'s cost model, `score.py`'s arithmetic or the ledger's cash reconciliation. The suite's honest description is "the infra no longer silently breaks", not "the engine is verified".
- **Deep-retro agent and cloud routine still not in the repo** — unchanged from the standing audit; everything about the second auditor rests on its 407+ output files.
- **I did not re-derive the replay/fill math** because the files are unchanged since 2026-09-02; the standing audit's line-by-line verification is the authority for those formulas, and I am deliberately not re-asserting them as freshly checked.
- **`release_calendar.py`'s hard-coded table I did not verify against the agencies' pages.** I read the code and its documented conventions (BLS/BEA 08:30 ET; FOMC 14:00 ET / ECB 14:15 CET / BoE 12:00 London as *standing* times, not per-date); a live check against bls.gov/bea.gov/federalreserve.gov is the first step if anyone adopts the join rule.

---

## 9. Recommendation

**No adoption, no new approval ask. Verdict: `watch` — re-read `core/` history, not the journal, next time.**

- **Re-state the standing verdict**: SKIP as a dependency; the three mechanisms stay as they are. There is nothing new to adopt, and the marginal value of this repo as a source is now mostly spent — one mechanism executed with a real verdict in our repo, two sitting as Backlog cards.
- **Amendment 1 (roadmap, no approval needed to note):** `phil-frozen-artifact-tripwire` should be re-pointed from the closed Kelly window to the *live* frozen gates (`wx2`, `btx2`, `shadow-forward-read` criteria, `c200-entry-floor-005-prereg`), or closed. As written its WHY cites a deadline that passed on 2026-10-08.
- **Amendment 2 (optional card, flagged as unprompted so it can be vetoed):** a `release-calendar-primitive` card in Backlog — *assess*, not implement: measure what share of our declined/admitted C-200 flow sits in econ-print families within `lead` days of a scheduled release, before any calendar code is written. Gate: the measurement comes back non-trivial (>5% of flow) AND a lane asks for it. Effort ~2h read-only; reversibility: delete the card. I did not add it — this run's constraints are the audit doc plus the queue, and a card nobody asked for should be the user's call, not mine. Paste-ready if wanted:

```json
{"id":"release-calendar-primitive","title":"Econ-print release calendar — measure before any calendar code","column":"Backlog","effort":"~2h read-only measurement","dates":"Carded 2026-10-20 (phil re-audit, concept-only row; unprompted — veto freely)","gate":"flow share >5% of C-200 declined+admitted sits in econ-print families within `lead` days of a scheduled release","note":"AUDIT INPUT (2026-10-20, concept-only; drafts/phil-reaudit-20261020.md): phil's core/release_calendar.py joins a hard-coded agency release table (BLS/BEA/Fed/ECB/BoE, explicit UTC instants) to open gamma markets that resolve on the print, matching on family mapper + mechanical-econ carve-out + series pattern, resolving ties by named reference month under --max-lag-days 21, and emits core/watch.py calendar entries at release_utc - lead. DORMANT in their repo: zero call sites, operator-only switch-on. Our tree has 0 hits for release_calendar|econ_release|economicCalendar, no prisma calendar model, and no card asking for it; nearest is kalshi-macro-shadow-lane (calibration instrument) and kalshi-gdelt-context-v2. Value is TIMING/DISCOVERY, not alpha — our funnel is wallet-copy, so measure the flow share first.","tags":["measurement","macro","data"]}
```

- **For this job's queue:** `watch`, not `drop` — the repo is alive, still publishing its own failures, and its `core/` could change. The re-read trigger is a **commit touching `core/replay.py`, `core/ledger.py`, `core/score.py` or `forward_test.py`**; absent that, this repo should not consume another audit slot, only one line in a future brief if its ledger or forecast delta moves.
- **One thing worth telling the user regardless:** the audit→harness chain worked. A 2026-09-28 note about a donated repo's measurement convention produced a powered, pre-registered FAIL on two of our own shadow lanes by 2026-10-10. That is the asset this repo actually delivered, and it did not require adopting a line of its code.
