# Asset audit — `mvanhorn/last30days-skill`

**Verdict: ⛔ DROP** — trending repo, wrong job: it is a topic-research agent for humans, and the two
sources it uniquely offers (X, TikTok) are reached through **session cookies**, which our never-handle-
credentials rule forbids. The lead's premise — that it "could restore the Reddit/X recon" — is half
false: our Reddit block is not broken.
*Audited 2026-11-24 08:20 CST · MIT · ★73,873 · pushed today · report only, nothing adopted.*

---

## What it is

An agent **skill** (Claude Code / Codex / Cursor / 50+ Agent Skills hosts) plus a Go MCP server, packaged
as `/last30days <topic>`: it fans out over Reddit (with comments), Hacker News, Polymarket, GitHub, X,
YouTube, TikTok, arXiv, Techmeme, patent filings and company careers pages, scores what it finds by
engagement, and has an LLM judge synthesize a brief. ~100 library modules for the fetch/normalize/rank
layer, plus a vendored Node client (`vendor/bird-search`) for X GraphQL.

## Anatomy that drove the verdict

| Fact | Value | Why it matters |
|---|---|---|
| Licence | MIT | **not** the blocker |
| Stars / forks | 73,873 / 6,518; pushed 2026-11-24; created 2026-01-23 | genuinely popular and maintained — the star count is real, and irrelevant to fit |
| CI | `validate.yml` green (3 newest runs `success`, 2026-11-24) | better maintenance signal than most candidates on this beat |
| Weight | **58.8 MB / 873 files** — 12.1 MB Python (583 files), 23.1 MB committed media, 2.7 MB JSON | a research harness that would dwarf the lane it serves |
| Biggest modules | `doctor.py` 120 KB, `env.py` 116 KB, `github.py` 61 KB, `digg.py` 60 KB, `bird_x.py` 52 KB | integration sprawl, not a small reusable primitive |
| Fetch layer | headless-Chrome CDP (`chrome_cdp.py`, `chrome_cookies.py`, `cookie_extract.py`, `agentcookie.py`) | scrapes with real browser cookies |
| Security posture | 9 in-flight changelog entries of the form `+*-security.md` (cookies-cdp-consent, html-publish-private-files, http-bounds-ssrf-robots-redos, mcp-subprocess-safety, social-scraping-ssrf-secrets) | an actively-hardened scraping surface — the hardening commits are the map of where it was soft |
| Keys/credentials | **none** for its own config, but X requires `AUTH_TOKEN` + `CT0` (`bird_x.py:57,100-103`) with a browser-cookie failover | that is a session credential; we never hold those |
| Telemetry | none found | — |

## The premise check (this is the part worth reading)

The queue note said this was the only candidate that "could restore the Reddit/X recon". Split it:

- **Reddit — not broken.** `scripts/research-collect.py:758-773` runs six Atom feeds (`top/.rss`,
  `search.rss`) with `REDDIT_PAUSE_S = 25`, `REDDIT_RETRY_S = 75` and a 26 h TTL. Only the `.json`
  endpoints 403 from this host; the feeds are served. There is no gap to restore, and last30days' Reddit
  path (shreddit/Arctic keyless listings, `+pr21`/`+pr33` changelog entries are both Reddit-backend
  fixes) would be a rewrite of a working block to gain scores and comment counts — a *salience* upgrade,
  not a capability we lack.
- **X — genuinely absent from our stack, and unavailable on our terms.** `bird_x.py` reads
  `AUTH_TOKEN`/`CT0` session cookies from the environment and falls back to harvesting them from a local
  browser (`chrome_cookies.py`/`agentcookie.py`), with a paid Bright Data path behind it. Our standing
  rule is that no key, token or session credential is handled by this stack. Their own code acknowledges
  the fragility: retries exist specifically for "an HTML anti-bot interstitial from Twitter's edge".

So the one capability it uniquely adds is the one we have deliberately ruled out acquiring.

## Fit table vs roadmap

| Component | Card | Verdict |
|---|---|---|
| Multi-source social research brief | — | ❌ **duplicate of our own lane**: `scripts/research-collect.py` + the DeepSeek research bot + local-LLM sentiment already produce our brief; nothing here accelerates it |
| X / TikTok / YouTube-transcript recon | — | ❌ **rule-blocked**: session cookies + browser-cookie harvesting; ToS risk; untrusted-code surface |
| Polymarket discovery (`polymarket.py`, 81 KB: Gamma `public-search`, "in band under `PRICE_CEILING` with `MIN_DAYS_TO_CLOSE`", race-price floors) | none; `phase-data1` owns market discovery via the leaderboard/wallet funnel | ⚪ **concept only, no card** — a topic→market ranking rule we do not need: our funnel is wallet-driven, and an uncalibrated salience score must not enter a composite |
| Engagement-weighted ranking / LLM judge / fusion | — | ❌ already our research-agent's job, with our own fact sheet as the baseline |
| 58 MB skill harness + Go MCP server | — | ❌ dependency weight with no live-lane payoff |

**Effort to adopt: not applicable — nothing is taken.** Even the one ⚪ idea is ~40 lines of Gamma query we
can write ourselves if a topic-discovery need ever appears.

## Risks / not-portable

- **Credentials**: X via `AUTH_TOKEN`/`CT0`, plus browser-cookie extraction. Violates the never-handle-
  keys rule; also a ToS/EULA exposure we do not need.
- **Untrusted-code hygiene**: 873 files including browser automation, cookie decryption paths and
  subprocess MCP execution; nine security-hardening entries are still in flight. Not something to point
  at a book that holds live paper positions.
- **Scraper fragility**: its own changelog is a list of dead/moved backends (Reddit Arctic, ScrapeCreators,
  StockTwits, Hacker News sitemap). Maintenance cost sits with the upstream scrapers, not with us.
- **It is a journalism tool.** Its output is "what should a human read about X" — our bottleneck is
  venue microstructure and wallet behaviour, which it does not touch.

## Honest caveats

- This is a *drop for fit*, not a quality verdict: MIT, green CI, 73.8k stars, daily commits and a
  clean README with no return promises. Do not read the ⛔ as "bad repo".
- I read the anatomy, the fetch/credential layer and its Polymarket module; I did not execute anything
  (read-only mandate), so its green CI is its own report, not something I verified.
- One genuinely useful artefact if X ever becomes available to us on compliant terms: its list of
  keyless Reddit/X backends is a live map of what still answers today (2026-11-24).
