# radioman/polymarket-arbitrage-trading-bot — audit (2026-09-08)

**Verdict: ❌ SKIP — do not adopt, do not run, do not copy.** Referral-farming honeypot layered on a hijacked 2016 WebRTC demo repo. Zero trading code in the tree.

## What it actually is
- GitHub API: created **2016-01-28**, language C++, **737 MB**, default branch `staging`, pushed 2026-06-19 (README-only update), license **NOASSERTION**.
- Repo content = a vendored **WebRTC.NET** C++/C# library (71 MB `WebRtcNative/`, NuGet-era `packages/` — Newtonsoft.Json **4.0.8**, Fleck, SocketIO4Net), `web/` with `rtc_main.js`/`adapter.js` (2013-era WebRTC demo shims), a `.sln` — i.e., the *original* project was a WebRTC wrapper demo. The repo was renamed/rewritten into a "Polymarket arbitrage trading bot".
- **Code/README mismatch is total:** README quick-start is an npm/Node dashboard (:3847, `npm run demo`, `config/demo-bot.json`, strategy presets) — there is **no package.json, no config/, no src/, no JS/TS trading code anywhere**. Grep for `polymarket|arbitrage` across py/js/ts/cs/json: **0 hits**.
- Screenshots in the README show a slick "analytics dashboard" that does not exist in the tree.

## Scam/hype signals (each independently disqualifying)
1. **License = parody "FLAT EARTH LICENSE"** (mutated MIT text) — NOASSERTION per API. Nothing borrowable; per policy read-only at absolute best.
2. **SEO-spam description**: "Polymarket trading bot" repeated 7× — keyword stuffing.
3. **Two referral links in the README**: `polymarket.com/?r=cryptoking1106` ("🌟click! so your account will be boosted") + GMGN "Future News" promo banner. Monetization = referral farming, classic star-farmed honeypot.
4. **517★ / 136 forks on a repo whose only branch (`staging`) is a WebRTC C++ library** — stars do not correspond to any shipped product; repo age (2016) + 737 MB history = hijacked shell.
5. **The "strategies" aren't arbitrage**: described mechanics (btc_momentum / odds_favorite / contrarian / mean_revert on 5-min BTC-ETH Up/Down markets, `betSizeUsdc`, entry windows) are directional momentum/gambling heuristics on binary markets — no spread/YES-NO/cross-market arb math exists even at the prose level. "Arbitrage" in the title is bait.

## Fit vs roadmap
No component maps to any open gap (Phase C arb detection, evidence tiers, research bot — all untouched). Nothing to transfer: **not even concept-only**.

## NOT-portable list
- Everything. There is no deterministic core, no math to verify, no execution path.

## Action
- **Do not run the bot, do not connect a wallet, do not click the referral links.**
- If it appeared in a repo-scout candidate list, reject on sight (pattern: hijacked shell + SEO description + referral link + parody license).
- Pattern to remember: repo-created-before-the-topic + default branch named `staging` + README framework (npm) absent from tree + referral link = honeypot.
