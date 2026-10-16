# Audit: Cleverfuxaqo1668/Polymarket-Telegram-Bot — adoption fit for Medusa CopyBot

**Date:** 2026-10-15 · **Auditor:** Hermes asset-audit cron · **Method:** GitHub API metadata + full tree
read (3 blobs) + commit-history pagination + raw read of the repo's only JS file + README read + prior-work
grep across `drafts/`, `data/roadmap.json`, `data/github-scout-seen.json`. **No clone, no install, no
execution** — this job forbids running candidate code. Nothing was pasted from the repo that contains a
key, seed or wallet address, and none was found in the tree.

## Verdict

**DROP — do not read, do not vendor, do not even mine for ideas.** This is not a bot repository; it is an
8.8 KB landing page for a third-party custodial Telegram service that *stores users' Polymarket private
keys and seed phrases on its own server*. The MIT file in the tree names a third author, the commit
history is a ~62,600-commit activity farm, and the single code file's one real idea (a venue-wide activity
WebSocket) was already audited by us on 2026-09-09. Zero transferable content.

## 1. What it is

"🐋 Whale Alerts" — a Telegram bot (`@polyprediction1_bot`) that pushes large-trade alerts and lets a user
place a Polymarket bet in one tap, plus a copy-trading mode. The **product is the bot, not the repo**: the
GitHub tree carries no implementation of it.

| Metadata (GitHub API, 2026-10-15) | |
|---|---|
| Licence | MIT (LICENSE file reads `Copyright (c) 2026 monokin` — matches neither the owner nor the brand) |
| Stars / forks / watchers / open issues | 170 / 135 / 85 / **0** |
| Created / last push | 2026-08-27 / 2026-10-15 (push = commit farm, not development) |
| Default branch / languages | `main` (single branch) / JavaScript 100% |
| Files / content bytes | **3 blobs = 8.8 KB** (LICENSE 1,064 B · README.md 6,091 B · live-feed-example.js 1,674 B) vs repo size 4,699 KB |
| Commits | **~62,600** (Link header: `page=626` at `per_page=100`) |
| Structure | tests NO · CI NO · docker NO · lockfile NO · .env.example NO |
| README signal | key/secret requirement: **wallet** · no telemetry marker · no stub marker (it *is* a stub) |

Anatomy vs claim: a 6 KB README of feature promises over an 8.8 KB tree. The 4,699 KB repo size is history
bloat, not code — the working tree has nothing large in it.

## 2. The three findings that decide it

**(a) The README's core promise is third-party custody of the private key.** Quoting the README's own
words: the wallet "lives inside the bot", and "every private key and seed phrase is automatically encrypted
and stored on the server tied to your account. Access is locked behind a personal PIN code you set
yourself". That is the entire business model — a hosted wallet that signs on the user's behalf. Our line is
absolute (`HERMES.md`: never ask for or handle private keys; nothing to sign), and the repo stack confirms
it: `grep -rn "PRIVATE_KEY" src/ scripts/` → **0 hits** in our repo. A PIN-gated server-side key store is
also the classic key-harvesting shape, not a security design: the operator holds the ciphertext *and* the
decryption path, and the "no confirmation popup, instant sign" pitch removes the last place a user would
see what they authorised.

**(b) The history is a commit farm.** The newest ~100 commits (and the 100 before them) are all
`chore: toggle LICENSE (add)` / `chore: toggle LICENSE (remove)` by `SageAgent831`, one every ~60 seconds,
with occasional `Update LICENSE - <timestamp>` variants — ~62,600 commits on a 3-file repo, i.e. a
green-squares/activity-faking script. The 170 stars / 135 forks / **0 issues** on a repo with no code is the
same signal from the other direction. The licence file itself is copy-pasted from another project
(`monokin`), so even the MIT grant is not this owner's to give.

**(c) The only code file's one good idea is already ours.** `live-feed-example.js` (1,674 B) opens
`wss://ws-live-data.polymarket.com`, subscribes `{action:"subscribe", subscriptions:[{topic:"activity",
type:"orders_matched"}]}` with a spoofed `Origin: https://polymarket.com` / browser UA, keeps a 15 s
ping/pong heartbeat that terminates zombie sockets, reconnects with a 5 s delay, and prints only BUY
activity ≥ $50,000 notional. That primitive — the venue-wide keyless activity push, giving per-wallet
(`proxyWallet`) fills in near-real-time rather than via data-api polling — is **already audited and already
a verdict of ours**:

- `drafts/insider-tracker-audit-2026-09-09.md` I1: same endpoint, subscription
  `{action: subscribe, topic: "activity", type: "trades"}`, "Public + keyless", **✅ ADOPT (slice,
  post-freeze)** for the C-200 whale-lane live-behaviour tap / Phase D insider-score input.
- `drafts/polymarket-mcp-server-audit-2026-09-07.md:75` names the same endpoint again.
- We already operate a Polymarket WebSocket in-tree: `scripts/record-l2.ts:41`
  (`wss://ws-subscriptions-clob.polymarket.com/ws/market`).

The one delta is the subscription `type`: this repo says `orders_matched`, our Sept audit recorded
`trades`. That variant is **unverified** (this run did not check it against `docs.polymarket.com`, and a
repo this one is not a source for venue contracts) — it is not new information and must not be treated as
one.

## 3. Fit table

| Component | Roadmap target | Verdict |
|---|---|---|
| Telegram alert/bet bot | none — no card asks for a Telegram surface | ❌ not portable (hosted service; requires user keys server-side) |
| Hosted wallet + instant sign ("no confirmation popup") | none, and forbidden by `HERMES.md` | ❌ never — third-party key custody |
| Copy-trading mode | C-200 lane does this with our own measurement | ❌ nothing to compare (no code, no method disclosed) |
| Global activity WebSocket tap | already carded via `insider-tracker-audit-2026-09-09.md` I1 / Phase D insider gating | ⚪ already audited by us — no new information |
| `ws-live-data` `orders_matched` subscription variant | none | ⚪ unverified variant, not worth a card |
| LICENSE / README | — | ❌ the MIT grant is copy-pasted from another author |

## 4. Integration proposal

None. There is no component to adopt, wire, flag-gate or revert.

## 5. NOT portable

Everything, explicitly: the bot (closed service), the key store (forbidden), the alerting/UX layer
(nothing in our stack consumes Telegram), the commit farm (obviously), and the one code file (its endpoint
is already covered by a standing audit and its second-highest-value detail, the Origin/UA spoof, is a
hygiene anti-pattern we would not copy).

## 6. Honest caveats

- No clone, no test run (job constraint); there is nothing to run — no tests, no CI, no lockfile.
- The WS subscription shape was not validated against Polymarket's own docs in this pass; the endpoint is
  documented in our own September audits, and the claim is labelled unverified above rather than dropped.
- Star/fork counts are taken from the API at 2026-10-15 and are not trusted as a quality signal for the
  reasons in §2(b).
- The README is a marketing page whose "free until 10.10.2026" window has already expired; I did not visit
  the Telegram bot or its Terms page (out of scope and out of policy for a key-custody service).

## 7. Ready-to-paste registry/card block

This run's deliverable is the audit doc + queue record, so no `data/roadmap.json` write was made. If the
parent wants the finding in the registry:

```
AUDIT INPUT (2026-10-15, drop; drafts/asset-audit-polymarket-telegram-bot-20261015.md): Cleverfuxaqo1668/Polymarket-Telegram-Bot is NOT a bot repo — 3 blobs / 8.8 KB of content vs ~62,600 commits ("toggle LICENSE" every ~60s by SageAgent831), MIT file copy-pasted from author "monokin", 170★/135 forks/0 issues. Its pitch is server-side custody of the user's Polymarket private key + seed (PIN-locked) — never adopt, never vendor. Its only code file's idea (wss://ws-live-data.polymarket.com activity tap, keyless, per-proxyWallet fills) is ALREADY audited: drafts/insider-tracker-audit-2026-09-09.md I1 (✅ adopt slice post-freeze, type "trades"); this repo's variant says type "orders_matched" and is unverified. No card needed; no recommendation. Do not re-audit a future re-surface of this repo — greps for the name should land on this file.
```
