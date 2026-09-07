# livetennisapi/polymarket-tennis — Audit for short-TTR sports lane + Data-1

**Status:** COMPLETE — 2026-09-07. Repo: github.com/livetennisapi/polymarket-tennis (325★, 285 forks, MIT, Python ≥3.10, single dep `httpx`).
**License:** ✅ **MIT** (spdx_id `mit`) — borrowable with attribution.
**Freshness:** created 2026-08-18, head commit 8076bb3 dated 2026-08-23 (shallow clone), GitHub pushed_at 2026-09-05. ~5 weeks old, v0.1.0, 94/94 package tests + 7/7 example tests pass on Python 3.11.15.
**Cloned to:** /tmp/polymarket-tennis (~3,500 LOC; src ~1,900 across 9 modules + `arena/`).

---

## 1. What it is

An **observe-only data layer** (explicitly *not* a bot) for tennis on Polymarket: discover tennis markets on the keyless Gamma API, match each market to a live match/fixture from the **Live Tennis API** (a paid data vendor), and join market prices next to live score state (score line, server, break-point flag) into one staleness-tracked snapshot (`LiveMarketView`). Ships a CLI (`pmtennis discover|match|watch|arena`), an offline replay/paper-trading harness (`arena/`, fixed $10 stakes, baselines only — **no sizing math anywhere**), a Claude-Code watcher example, and a vendor marketing site/docs. **Repo is authored and maintained by the Live Tennis API vendor** (disclosed in README, pyproject, and module docstrings) — judge accordingly, but code quality is genuine.

## 2. Verified machinery (from source; tests executed)

**A. Market discovery (`discovery.py`, 144 LOC).** Two-layer filter: query Gamma `/events?tag_slug=tennis` (server side), then *re-verify each event locally* (`is_tennis_event`: tag slug OR slug prefix `atp|wta|itf|challenger|ch` OR title hints) so a mis-tagged payload never slips through. Classifies per-match events via slug regex `^(?:atp|wta|itf|challenger|ch)(?:-doubles)?-.+-\d{4}-\d{2}-\d{2}$` or `" vs "` in title; flags doubles via `-doubles-`/`(doubles)`/`/` in names. `TennisMarket.from_gamma` (`models.py`) defends against Gamma's JSON-string-encoded `outcomes`/`outcomePrices`/`volumeNum` fields, pads price arrays, keeps `.raw`. Slug-date parsed from the trailing `YYYY-MM-DD` of the event slug.

**B. Market→match mapping (`matching.py`, 292 LOC) — the crown jewel.** Deterministic name+date scoring, refuses to guess:
- `fold_name`: NFKD → strip diacritics → lowercase → `[-'.]`→space → collapse. Retirement/walkover wording stripped from names (`(Retired)`, ` w/o`).
- `_name_similarity` ladder (folded): exact = **1.0**; token-subset either direction (`"J. Lehecka"` vs `"Jiri Lehecka"`, `"Davidovich Fokina"` single-token label) = **0.9**; surname-only agreement (last token) = **0.75**; else 0.0.
- `_pair_score`: score = max over both orientations of `min(sim(p1,n1), sim(p2,n2))` — **both** players must agree (one-player agreement = 0). Date gate from slug date vs candidate `scheduled_time`/`start_time`: ±1 day → **+0.05 bonus (capped 1.0)**; >1 day → **hard 0.0 reject**.
- Decision rule (`match_market`): best score ≥ `MATCH_THRESHOLD 0.70` **and** top-2 gap ≥ `AMBIGUITY_MARGIN 0.10`, else `None`. Never guesses. Doubles rejected in v0.1. Explicit `override_match_id` honored at confidence 1.0 (visible note when id not in candidate set). Output carries `method` ("explicit" | "names+date" | "names") + notes.
- Sanity: surname-only (0.75) alone clears 0.70 — deliberately loose floor, but ambiguity margin + hard date reject + both-players-required are the real guards. Shared-surname disambiguation by full names verified in tests (two live "Moeller" matches resolve to distinct ids; same-pair-on-two-days returns `None`).
- **Outcome alignment**: the matcher returns the match, not the side mapping. Side mapping is `outcome_player_index` (arena/baselines) and `server_outcome` (watcher): folded full-name match, else *unique* surname match, else `None`.

**C. Price-vs-live-state signal logic (`join.py` + watcher example).**
- Break-point rule (verified standard: receiver is one point from the game): receiver at `AD`, or receiver `40` vs server `0/15/30`; **never** in tiebreak; `False` on any null (completed matches carry null points). `derive_break_point()` is conservative on nulls.
- Staleness tracked per feed (`market_as_of` = Gamma `updatedAt` vs `live_as_of` = score `timestamp`).
- Watcher signal (the only "strategy-ish" thing in the repo): **"favourite faces break point"** — when the favourite is serving and a break point is on, open a *paper* entry long the favourite's outcome at current price; resolve when the game counter moves; record the price move. It is an observation harness (does the market overreact when a favourite faces BP?), **not** a validated predictive model. `fade-first-break` arena baseline is the same idea faded. Settlement: only clean `completed` + winner marks 1/0; retirements/walkovers are **never** settled by code — venue text is surfaced instead (correct discipline, no hard-coded venue rule).
- Arena replay: JSONL tape (raw Gamma market + raw live match per poll) → deterministic replay → `PaperBook` (shares = size/price, P&L = shares·(p−price), no fees/slippage — stated). Forbidden-import AST gate (`py_clob_client`, `web3`, `eth_account`, …) keeps paper lanes paper. 50-entry cap.

**D. Data sources.** `gamma.py`: keyless GET-only httpx client (`/events`, `/markets`), injectable client for `MockTransport` tests. `livetennis.py`: keyed client for `api.livetennisapi.com` free tier (30 req/min, **100 req/day**), 429 surfaced; per-poll cost is 2 requests (live + fixtures). Note: vendor's paid tiers sell market-prices/win-probability fields the toolkit conspicuously avoids.

## 3. Fit table vs roadmap gaps

| Component | Verdict | Roadmap gap it fills |
|---|---|---|
| `matching.py` name+date matcher (fold/similarity ladder/thresholds/ambiguity refusal/override) | **ADOPT** (MIT, port ~250 LOC) | Short-TTR sports/esports lane: correct Polymarket market id for a given live fixture. Wrong-match = garbage paper P&L; this discipline ("None, never guess") is exactly what a copy/paper lane needs before any entry. |
| `discovery.py` tag→events→markets, local re-verify, slug classification | **ADOPT** as pattern, re-parametrized | Phase Data-1 / PMA tape ingestion & any sport category on Gamma — swap `tennis` tag + slug regexes for per-sport config (esports slugs/tags differ per title). |
| `models.py` Gamma normalizer (JSON-string fields, price padding, `.raw` retention) | **ADOPT** (~150 LOC) | Same Gamma payload drift handling any market feed code needs; copybot TS scorer already consumes Gamma — this is the Python-research-bot equivalent. |
| `join.py` staleness-aware dual-feed snapshot + derived live-state flags | **ADOPT** as pattern | Feature-vector scaffold for the sports lane; tennis rules → esport-state features (map/round/match-point). ML-2 independent-entry lane needs exactly this labeled-view pipeline. |
| Arena replay harness (tape → protocol → paper book, settlement discipline) | **ADOPT** as pattern | ML-1 outcome labeling exists; replay/tape determinism is a clean label-generation + backtest scaffold for the research bot. Do NOT adopt the strategy API wholesale (stack has its own scorer/executor). |
| Watcher BP-observation loop (enter on state event, resolve on transition, measure move) | **concept-only** | The *method* transfers to esports (state-transition reaction studies for the daily-PnL lane); no validated edge to import. |
| `livetennis.py` vendor client | **not-portable** | Proprietary keyed feed; free tier 100 req/day cannot sustain multi-match live polling; vendor conflict of interest. Matcher needs only `{players: [p1,p2 names], scheduled_time, status, outcome, winner}` — plug any feed (Odds API per Data-1, or a score API) behind the same shape. |
| Arena baselines (hold-favourite / fade-first-break, $10 fixed) | **not-portable** | No edge claims, no validation, no sizing math (none exists in repo — kelly/edge/risk greps return nothing). Stack sizing is v49/v50; nothing to add. |

## 4. Integration proposal (sports-lane market-matching module, research bot)

**Scope:** port `matching.py` + `discovery.py` + `models.py` (~550 LOC, pure functions, no I/O coupling beyond injected httpx client) into the Python research bot as a `sports_match` module, parametrized by sport config `{gamma_tag_slug, event-slug regex(es), doubles/team-mode, name_source: players|teams}`. Tennis config ships first; esports config(s) follow once slug conventions are sampled from Gamma. Fixture-style tests with trimmed real captures (repo's own pattern).
**Effort:** ~1 focused dev-day for the port + tests; ~half-day to wire to existing fetchers/store. Low single-dependency surface (httpx only, Python ≥3.10).
**Risk:** LOW — MIT, no execution path, no wallet/secrets, pure deterministic functions, 94 tests green locally. Residual: (a) Gamma payload drift (mitigated by defensive `models.py`); (b) vendor repo bus-factor 1 + marketing incentives (mitigated by copying code, not depending on the vendor feed); (c) esports team-name aliasing (`"NaVi"` vs `"Natus Vincere"`) is **not** handled by the matcher — needs an alias table (initials/surname logic is tennis-specific and just no-ops for teams).
**Flag-revertible:** yes — stateless library code behind the sports-lane research flag; paper-only by construction (no order path in the module); disable with zero unwind. **Timing:** kelly window runs Sep 8–Oct 8 — nothing ships before Oct 8; queue for the post-Oct-8 sports-lane build-out or Data-1 external-dataset work.

## 5. NOT-portable list

- Sizing/execution/risk math — **absent by design** (repo is observe-only; `FORBIDDEN_MODULES` gate enforces it). Not a gap.
- The vendor live-score feed and its free-tier polling budget (30/min, 100/day).
- Tennis-specific hard-codings: slug regex prefixes (`atp|wta|itf|challenger|ch`), doubles handling, `" vs "` match classification, surname heuristics, break-point rule, retirement/walkover settlement assumptions (intentionally unhardcoded).
- Arena leaderboard/docs site/Claude-Code skill packaging (vendor marketing surface).
- The committed synthetic tape numbers — not validated, not real evidence of edge.

## 6. Honest caveats + verdict

- Repo is 5 weeks old, v0.1.0, and is a **vendor funnel** (docs site + arena + skill packaging exist to drive livetennisapi.com signups; 325★ in ~3 weeks is marketing-velocity). None of that falsifies the code — the matching core is well-tested, honestly documented (README claims match source exactly), and genuinely useful.
- The matcher is **tennis-tuned but feed-agnostic**; its real transferable insight is the *decision discipline* (both-sides agreement, ±1-day gate, ambiguity refusal, explicit override) — which is worth more to a copy/paper stack than any tennis logic.
- No predictive signal exists in this repo (break-point watcher is observation scaffolding), so there is **no edge to adopt** — only plumbing that enables the sports lane to *build* its own edge research.
- **Verdict: ADOPT the pattern, queue the build for post-Oct-8** (short-TTR sports-lane market-matching module, or Data-1 as the sports-feed work lands). Adopt-now is blocked by the Kelly measurement window; skip is wrong because no equivalent generic sports market-matching exists in the stack today and this is the cheapest proven route to it.
