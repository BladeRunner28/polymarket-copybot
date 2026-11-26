# Asset audit — `lori1635/krypolybot-polymarket-mcp-whale-trader`

**Audited:** 2026-11-25 · **Verdict: ⛔ DROP — malware-distribution lure, not software.**
Dashboard: http://localhost:3013/drafts/asset-audit-krypolybot-polymarket-mcp-whale-trader-20261125

---

## What it is

A one-day-old repo published under a keyword-stuffed name ("Krypolybot Polymarket MCP Whale
Trader [2026]") whose README is a download landing page for a **password-protected Windows
`.exe` inside a zip** (`krypolybot-polymarket-mcp-whale-trader-v1.2.0-win64.zip`, 4.8 MB,
archive password `2026`). There is no trading system in the repo. There is no Polymarket code in
the repo. The name is bait.

## Anatomy facts that drove the verdict

| Fact | Value | Why it matters |
| --- | --- | --- |
| Created / last push | 2026-11-25 00:02Z / 09:18Z | 9 hours old, 130★ and 24 forks already |
| Delivery | password-protected `.exe` in zip, 42 downloads | Password-gated archive defeats AV/static scanning — standard malware-delivery shape |
| Real code | **1.2 KB** `src/.../engine.py` + 528 B `doc.go` | The "Python 69% / Go 30%" language split is two stub files |
| Docs weight | 72 KB HTML landing pages, 47 KB PNG, 13 KB markdown | ~99% of the tree is SEO surface, not code |
| Tests / lockfile | none / none | — |
| Licence | `NOASSERTION` = MIT text **truncated** (missing the warranty clause) | Moot; nothing here worth borrowing |
| Config target | Solana mainnet RPC + Jito block engine, `require_mint_renounced`, `min_initial_liquidity_sol` | Solana memecoin sniping, unrelated to the venue it names |
| Topics | 19 keyword-spam tags (`...-pc`, `...-bundler`, `...-config`) | Search-manipulation |

### The tell: the CI job exists only to fake activity

`.github/workflows/build.yml` runs **hourly** and its single step commits to
`.github/telemetry_stamp` with a randomly generated message:

```js
const words = ['fix','update','refactor','optimize','sync','tune','validate', ...];
const msg = `${pick()} ${pick()} #${100 + Math.floor(Math.random() * 8900)}`;
```

That is why the commit log reads `patch optimize #4345`, `tune validate #441`,
`verify update #6965` from `github-actions[bot]` — manufactured "actively developed" signal so a
recency filter (pushed ≤ 90 d) rates it alive. The `.github/telemetry_stamp` file and the
`docs/<md5>.txt` marker are the same trick.

The actual source file is the whole system:

```python
async def run_heartbeat(self) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {TARGET_MODULE} initialized (paper_mode=...)')
    await asyncio.sleep(0.05)
```

No market data, no order path, no wallet, no MCP server, no Polymarket or Kalshi client.

## What we could reuse

**Nothing.** Not the code (a print statement), not the design (there is none), not the config
(a Solana sniping profile). The only transferable item is a *detection* rule, now recorded in the
`github-repo-audit` skill reference.

## Risks

- **Executing the release is the risk.** A password-protected x64 binary from a 9-hour-old account
  with a fake-commit CI and no source is the archetypal infostealer/clipper lure. It must never be
  downloaded onto any host in this stack, and the release URL should not be fetched "just to hash
  it" from the trading machine.
- **Star/fork inflation** (130★ / 24 forks in 9 h, zero issues answered) means GitHub popularity
  signals are being farmed here — a reminder that `★ ≥ 5` in the radar seed bar is not a quality gate.

## Recommendation

**Drop, no adoption, no follow-on.** Do not add it to a roadmap card. Incidental fix worth making:
the radar seed gate (`licence ≠ none`, ★≥5, pushed ≤90 d) passes repos whose activity is a
self-committing CI bot and whose "licence" is a truncated MIT under `NOASSERTION` — this one was
seeded by it. If the seed bar is touched later, the cheap additional check is
"reject when >80% of tree bytes are `.html`/`.png`" and "reject when the newest commits are all
`github-actions[bot]` message-shuffles".
