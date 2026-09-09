# sstklen/trump-code — audit (2026-09-08)

**Verdict: ❌ do not adopt the code. ⚪ Concept-only: the presidential-socials event lane idea + the 6.2h Truth-Social-leads-X hypothesis, built in OUR pipeline post-Kelly. ✅-adjacent: the MIT open dataset as shadow-seed material (with caveats).**

## What it is
- MIT (clean file, 2025–2026 "Washin Mura Contributors"), 799★, Python, created 2026-03-15, **auto-commits daily** ("chore: daily pipeline data update"). Real engineering effort: ~60 flat .py files, open 140 MB `data/` (Truth Social post archive, features, market JSONs, logs), live dashboard, tri-lingual README, Taiwanese press coverage.
- Claims: 7,400+ Truth Social posts · **31.5M brute-forced rule combos → 551–600 surviving rules** · **61.3% hit rate across "566 verified predictions" (z=5.39)** · closed loop predict→verify→learn→evolve daily.
- Architecture honesty check: has a `circuit_breaker.py` that literally asks "are we better than random?" — the author knows the overfit risk; the README marketing doesn't.

## Verified machinery — the headline number is a backfill, not a track record
Inspected `data/predictions_log.json` directly:
- **All 566 rows were written on 2026-03-14** (created_at: one bulk backfill — repo birthday).
- **564 rows carry signal dates BEFORE the repo existed** (2025-01-23 → 2026-03-13): rules applied retroactively to known market outcomes.
- "61.3%" = 346/564 `correct: True` on that **in-sample backfill**.
- True forward predictions since launch: **2 rows, both PENDING** — and the log still ends 2026-03-14 after 6 months of daily "pipeline data update" commits. Either the evolved rules never fire again or forward logging is dormant. Either way: **there is no live track record; the badge is a backtest presented as verified predictions.**
- "Key Discoveries" table = post-hoc cherry-picks (Apr 9 2025 S&P +9.52%, tariff days, "silence = 80% bullish" — a rising-market base rate).
- 31.5M trials → 551 survivors is textbook multiple-testing; z=5.39 (p≈7e-8) does NOT survive a 31.5M-trial Bonferroni (needs z>6.0). The 551 rules are very likely noise fitted to 14 months of one president's posts.
- Engagement-bait markers (soft): star-lottery banner ("cat-treehouse"), donation links, press badge. Marketing energy > validation energy.

## Fit vs roadmap
| Component | Assessment | Verdict |
|---|---|---|
| Truth-Social/X post → market-signal lane | Their research bot watches Congress/GovInfo/GDELT/Quiver — NOT presidential socials. Trump posts are real-world events (evidence-eligible under the market-firewall, unlike price data). BUT: build it our way (keyless RSS/Truth fetch → shadow A/B → C-tier evidence), never port 551 rules. | ⚪ concept (post-Kelly card) |
| "Truth Social publishes ~6.2h before X" claim | If real, an event-timing lead for detection lanes; unverified here, cheap to test with our own fetcher. | ⚪ concept |
| Circuit-breaker framing (better-than-random? / recent degradation / auto-stop / auto-invert) | Theirs exists in the risk engine; worth a compare-note only. | ⚪ concept |
| Open dataset (7,400+ labeled posts, daily features, market JSONs) | MIT; could seed shadow-A/B eval material. Caveats: market_*.json derived from yfinance etc. (redistribution terms unclear), and labels come from the same backfill. | ⚪ use-with-caveats |
| polymarket_client / kalshi_client | stdlib urllib wrappers — their tested doctrine-encoded lanes are strictly better. | ❌ |
| arbitrage_engine | Not arb: "signal strength × market undervaluation → score" = directional signal scoring (their A2/C-tier machinery already does this with Bayesian log-odds). | ❌ |
| 551-rule evolved engine / learning_engine / rule_evolver | Overfit core; also their rule engine (RuleSet + apply-vNN) is cleaner and gated. | ❌ |
| chatbot_server / "Three Brains" LLM layer | Claude-powered analysis + site chat — LLM layers rarely port (their DeepSeek/local-LLM research stack duplicates). | ❌ |

## Action
- **Skip as code.** Nothing here beats their pipeline; the one real asset is the *concept* of a presidential-socials evidence lane + an open post archive to bootstrap it.
- Optional (post-Kelly, backlog): card "Presidential-socials evidence lane (concept from trump-code audit)" — own fetcher (Truth Social RSS + X), shadow A/B vs rules, C-tier cap, dataset as seed if licensing checks out. Not before Oct 8.
