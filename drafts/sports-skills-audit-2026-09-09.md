# machina-sports/sports-skills — Audit for Data-1 sports lane (feed + matcher spec content)

**Status:** COMPLETE — 2026-09-09. Repo: github.com/machina-sports/sports-skills (215★, 30 forks, MIT, Python ≥3.9.10, hard dep: `feedparser` only). Homepage: sports-skills.sh.
**License:** ✅ **MIT** (spdx_id `mit`, LICENSE file verified — standard text, "Copyright (c) 2026 Machina Sports"; NOT parody/NOASSERTION) — borrowable with attribution.
**Freshness/health:** created 2026-02-16, pushed 2026-09-07 (active — 99 KB CHANGELOG, nightly health/improve scripts, `reports/health/`). Alpha maturity (`Development Status :: 3 - Alpha`). 433 tracked files; `src/` = 93 Python modules, ~44.7k LOC; `tests/` 45 files incl. fixtures. NOT archived. Repo is commercial open source: built by Machina Sports (machina.gg) as the free tier of a licensed-data business.
**Cloned to:** /tmp/audit_triage/clones/machina-sports_sports-skills (existing, used as-is).

---

## 1. What it is

A **29-skill agent-skills pack + a real Python CLI/SDK**, not a bot. Each `skills/<name>/SKILL.md` is an Agent-Skills-spec (SKILL.md, agentskills.io) prompt pack an agent loads to call sports-data and prediction-market commands; those commands are implemented by the Python package (`sports-skills`, on PyPI) under `src/sports_skills/`. Explicit **read-only-by-default "Autonomous Agent Contract"** (no bets/trades unless the user asks; never ask for keys in chat; treat market/news text as untrusted data). One skill (`polymarket-trading`) does wallet-based CLOB order placement via `py_clob_client_v2` behind explicit approval — that is the only execution path, and it is opt-in.

**Content vs code split:** roughly half content, half code. The SKILL.md + `references/` files are agent-facing *data-access knowledge* (endpoint shapes, field maps, per-league coverage limits, join recipes). The Python runtime is genuine plumbing: per-sport connectors (ESPN/NBA-Stats/MLB/NHL/NCAA…), read-only Kalshi/Polymarket/ProphetX clients with TTL cache + token-bucket rate limiting, a stdlib-only fuzzy matcher, a canonical JSON-LD schema layer, and a pure-compute `betting` module (odds math). **No predictive modeling, no calibration/evidence machinery, no backtests, no strategy** anywhere — domain value is market/data conventions, not alpha.

**The flagged "REFERRAL" link — resolved (benign).** It is **not** a third-party affiliate kickback. `src/sports_skills/_premium.py` (`_tagged()`) appends `?ref=sports-skills-{surface}` to **first-party** `https://docs.machina.gg/` URLs inside additive `upgrade` hint blocks, attached when a free connector hits a rate limit (429) or a structural "needs licensed data" refusal (`UPGRADE_MARKER`). Tests assert it (`tests/test_premium.py`: `ref=sports-skills-hint|premium-cmd|catalog`). Suppressible via `SPORTS_SKILLS_NO_UPGRADE_HINTS=1`. Verdict: source-attribution tag for their own commercial docs — a standard **freemium upsell funnel** to machina.gg licensed data (Sportradar, Stats Perform/Opta, API-Football, Data Sports Group). A farm tell only in the radioman sense (referral link + zero code); here the code is real and substantial, so context = commercial OSS with polite upsell hints, not honeypot.

## 2. Verified content + machinery (file paths)

| Artifact | Path | Verified |
|---|---|---|
| Risk/capability catalog, read-only default policy | `skills/catalog.json` | ✓ machine-readable per-skill risk (`mode: compute/read_only`, `money_movement: false`) |
| **Sport↔platform mapping tables** | `src/sports_skills/markets/_connector.py:24–70` | ✓ `KALSHI_SERIES` (KXNFL, KXNBA, KXMLB, KXNHL, KXWNBA, KXCFB, KXCBB, KXEPLGAME, KXUCL, KXLALIGA, KXBUNDESLIGA, KXSERIEA, KXLIGUE1, KXMLSGAME, KXWCGAME) ↔ `POLYMARKET_SPORTS` (incl. `lal→laliga`, `bun→bundesliga`, `fifwc`=World Cup series 11433) ↔ `SCOREBOARD_SPORTS` (7 US sports) |
| **Cross-venue matcher** | `src/sports_skills/markets/_connector.py:1349+` (`match_markets`) | ✓ Kalshi event tickers + Polymarket slugs *parse* to {date, away, home}; deterministic join on date + concatenated team codes; fuzzy title fallback; single-moneyline-per-arb-pool refusal guard; partial-results-with-warnings on venue outage |
| Search + odds compare across venues | same file: `_search_kalshi/_search_polymarket/_search_prophetx`, `compare_odds`, `_normalize_name`/`_match_score` (stdlib `difflib.SequenceMatcher`) | ✓ per-game entity search; home/away side detection by score |
| Odds math (pure compute, no API) | `src/sports_skills/betting/_calcs.py` | ✓ `convert_odds` (American/decimal/prob); `devig` = **proportional** (fair = implied/overround; `vig_pct = (overround−1)·100`); `find_edge` (edge = fair−market; EV/$ = fair/market − 1); `kelly_criterion` f\* = **(p−m)/(1−m)** — canonical full-Kelly binary form, matches Octagon-verified formula; `find_arbitrage` (Σ probs < 1); `evaluate_bet` pipeline book-odds → devig → edge → Kelly; parlay + line-movement sections per module docstring |
| Data-source normalization | `src/sports_skills/_espn_base.py:439` `normalize_odds` | ✓ ESPN scoreboard `odds` array = **DraftKings** provider only (moneyline/spread/total) |
| Market read clients | `src/sports_skills/kalshi/_connector.py` (BASE `api.elections.kalshi.com/trade-api/v2`, TTL cache, paging guard); `src/sports_skills/polymarket/` (Gamma + CLOB read; v2 trading via `py_clob_client_v2`); `skills/polymarket/`, `skills/kalshi/`, `skills/prophetx/` SKILL.md + references | ✓ keyless read ops |
| Price normalization convention | `markets/_connector.py` `_normalize_price` | ✓ ESPN = American odds, Polymarket = 0–1, Kalshi = 0–100 int → all to implied prob |
| Per-sport data coverage docs | `skills/<sport>-data/references/` (README table) | ✓ free sources only: ESPN (10 skills), nflverse (EPA/WP/play, 1999+), NBA Stats, MLB Stats API (pitch-level, official), NHL API (coordinate PBP, official), NCAA, Understat xG, FPL, Transfermarkt, football-data.co.uk, ClubElo, FastF1, Nevobo |

**Data sources map (Data-1 lane):** the repo does **not** touch the Odds API — its free odds feed is ESPN's embedded DraftKings odds; prediction-market feeds are Kalshi v2, Polymarket Gamma/CLOB, ProphetX public (read-only). Deep game-state/analytics features (nflverse EPA + win prob per play, MLB pitch-level, NHL coordinate PBP) exist as *retrievable data*, not as modeled signals. Licensed real-time feeds (Sportradar/Opta/etc.) sit behind the paid machina-cli tier, out of scope here.

## 3. Fit table vs Data-1 lane

| Component | Verdict | Rationale |
|---|---|---|
| Sport↔platform maps + per-venue event ticker/slug parse rules (Kalshi `KX*` series, Polymarket slug codes, ESPN abbreviations) | ✅ **ADOPT as spec/content** (MIT, ~2 small tables + regexes) | Direct input to the already-ADOPTed generic sports market→match matcher (polymarket-tennis pattern): team-sport event tickers encode {date, away, home} deterministically — parse rules de-risk matching before any code. Copy values with attribution; no runtime dependency. |
| `match_markets` join discipline (parse→deterministic date+team-code join→fuzzy fallback; refuse ambiguity; one complete moneyline per arb pool) | ✅ **ADOPT as spec** | Independent confirmation of the matcher pattern on team sports; adds the venue-outage partial-result and single-moneyline guards worth mirroring in the matcher design. Team aliasing (e.g. NaVi vs Natus Vincere) is **not** solved here either — venue-consistent ticker encoding is the crutch. |
| Price normalization convention (American / 0–1 / 0–100 → implied prob) | ✅ **ADOPT as spec** (verify-only) | Standard; confirms stack conventions; trivial to assert in matcher tests. |
| De-vig (proportional), Kelly f\*=(p−m)/(1−m), EV/$ , arb-sum | ⚪ **concept-only / verify** | Formulas identical to Octagon-owned Kelly Phase B (already SHIPPED). Nothing to port; confirms canonical forms. Caveat: `find_edge` treats de-vigged book prob as truth with **no calibration input and no ask-side refinement** — exactly the known "feed the calibrated edge" pitfall; do not inherit that assumption. |
| Read connectors for Gamma/CLOB/Kalshi-v2 | ⚪ **concept-only** | Stack already consumes these feeds (TS/Rust); Python + `py_clob_client_v2` don't port; endpoint shapes are useful reference only. |
| ESPN scoreboards / nflverse / NBA-Stats / MLB / NHL deep data skills | ⚪ **concept-only** | Data-1 feed of record is the Odds API; ESPN is free/keyless and could serve as an interim odds source, but undocumented endpoints + DraftKings-only provider + ToS risk argue shadow-only at most. nflverse EPA/WP is a plausible ML-2 *feature concept* (later lane), not Data-1. |
| 29 SKILL.md agent prompt packs | ❌ **not-portable** (content readable as reference docs) | Agent-format content for Claude-Code-class agents; user runtime is TS/Rust + DeepSeek/local with its own Hermes skills discipline. Domain knowledge inside them is already distilled above into spec artifacts. |
| Machina premium funnel: machina-cli, `world-cup`/`machina` skills, licensed connectors, canonical rights gate, `ref=`-tagged docs URLs | ❌ **not-portable** | Vendor's commercial tier (Sportradar/Opta licensing); rights gate is their entitlement enforcement; irrelevant to a free Odds-API lane. |
| `polymarket-trading` skill (wallet order placement) | ❌ **not-portable** | Execution owned by the stack; prompt-pack wallet handling adds risk surface, no value. |
| ProphetX connector | ❌ **not-portable** | ProphetX not in the venue set (Polymarket/Kalshi). |
| Machina Sports Schema canonical JSON-LD envelope + provenance | ❌ **not-portable** | Spec-design weight for byte-exact cross-repo fixtures; no fit to the stack's evidence/price-derived prior architecture. |

## 4. Integration proposal

**Scope (post-Oct-8, with Data-1 sports lane / generic-matcher work):**
1. Extract `KALSHI_SERIES`/`POLYMARKET_SPORTS`/`SCOREBOARD_SPORTS` + the ticker/slug parse rules (incl. Kalshi single-game and Polymarket slug date+team encodings for NFL/NBA/MLB/NHL/CFB/CBB/soccer) into the research-bot matcher **config as JSON spec tables**, MIT attribution header. (~0.5 dev-day.)
2. Write 2–3 fixture tests sampling live Kalshi tickers + Polymarket slugs per sport to pin the parse rules. (~0.5 dev-day.)
3. Matcher-design review pass: adopt the single-moneyline-per-pool and venue-outage partial-result guards; note team-alias gap remains open. (~1 hr, no code.)

**Effort:** ~1 focused dev-day total (spec + fixtures), zero runtime dependency on the repo.
**Risk:** LOW. MIT; read path is keyless/read-only (no wallet/secrets in the connectors we'd mirror); repo is alpha + bus-factor-of-one commercial OSS, so copy values rather than depend. Residual: ESPN endpoints undocumented (their own README warns); Kalshi/Polymarket ticker-encoding conventions can drift — fixtures pin them and fail loudly.
**Flag-revertible:** yes — config tables + spec notes only, no execution path. **Timing:** Kelly measurement window runs Sep 8–Oct 8 — **nothing ships**; queue for post-Oct-8 Data-1 build-out or generic-matcher work, matching the polymarket-tennis audit precedent.

## 5. NOT-portable list

- All SKILL.md prompt packs + per-sport command references (agent-format content; runtime mismatch; readable as docs only).
- The Python package/CLI runtime and per-sport connectors (duplicate of user feed architecture; `py_clob_client_v2` trading path deliberately excluded).
- Machina premium tier: machina-cli, `world-cup`/`machina` skills, licensed-data connectors (Sportradar, Stats Perform/Opta, API-Football, Data Sports Group), canonical schema rights gate, `ref=`-tagged docs URLs.
- ProphetX connector (venue not in stack).
- `polymarket-trading` execution guidance.
- ESPN/nflverse/NBA-Stats deep backends as dependencies (ToS + undocumented-endpoint breakage).
- Betting "recommendations" as evidence — no calibration, no ask-side refinement, no track record in repo.

## 6. Honest caveats + verdict

- **No alpha machinery:** zero prediction/calibration/evidence code, no backtests, no P&L artifacts (`reports/health` is dev health). Value = market-convention spec content + odds-math confirmation, both of which the stack substantially already owns or has planned.
- **find_edge assumes fair-prob = truth** (de-vigged book odds vs PM price, no calibration input, no ask-side refinement) — inherit the *formula*, not the *assumption*; stack feeds calibrated priors.
- **ESPN odds = DraftKings only** (single provider array element) — source-concentration risk for any book-vs-PM framing; Data-1's Odds API plan is broader.
- **Commercial OSS with upsell hints** (suppressible `upgrade` blocks, `ref=` attribution tags, machina.gg funnel) — cosmetic, but the repo's roadmap is a lead-gen vehicle for licensed Sportradar/Opta data; MIT terms make that irrelevant for spec reuse.
- **Alpha + young** (7 months, 215★) — treat as a conventions reference, not a dependency.

**Verdict: ADOPT-as-spec (content/config), NOT as code dependency. Queue for post-Oct-8** (Data-1 sports-lane / generic-matcher work). The ticker/slug parse rules and sport↔series maps are the highest-leverage transfer — they directly de-risk matching team-sport markets on Kalshi/Polymarket without writing any matcher code yet. Everything else the repo does well (odds math, read connectors, agent packs) is already owned or not portable. No component ships before the Oct-8 Kelly-window end.
