# L2 corpus attribution — 21% of the book corpus had no market, now 1.3%

**Card:** `l2-asset-map-backfill` · **Lane:** B (instrument repair) · **Run:** 2026-11-26 09:00 CST
**Instruments:** `scripts/l2-asset-backfill.py`, merge in `src/lib/l2-retention.ts`, `npx tsx scripts/l2-retention.ts`

## Why it mattered
`data/l2/` is one JSONL file per CLOB asset id — the only raw book windows that exist for the days
they cover, and the input four fill instruments read. The single token→market ledger
(`data/l2-asset-map.jsonl`) is appended by the live recorder and only starts ~2026-09-27. Every file
recorded before that had **no market**, so the retention policy classified it `unattributed` and
refused to reason about it — and the ceiling plan left **2.20 GiB of its own target unreachable**.

## Basis (stated once, printed on every run)
- population: files in `data/l2` (one per CLOB asset id)
- level: one token / one file · clock: file mtime · size: apparent bytes
- lookup: gamma `/markets?clob_token_ids=<tok>&closed=true`, accepted **only** when the returned
  market's own `clobTokenIds` contain the queried token. Read 2026-11-26T15:15Z.

## Measured before → after
- unattributed: **26,522 files / 6.03 GiB (21.0%)** → **2,090 files / 0.38 GiB (1.3%)**
- tokens resolved: 24,430 · gamma-absent bodies: 0 · conflicts between the two sources: 0
- 2,092 tokens **notfound**: gamma returns `[]` under `closed=true`, `closed=true&neg_risk=true` and
  `closed=true&active=false&archived=true` alike. That is a named instrument limit, not proof no
  market exists.
- retention plan (still **not applied**): delete 8,618 files / 2.40 GiB with 2.20 GiB unreachable →
  **23,695 files / 4.67 GiB with 0 unreachable**, `deleteUnattributedBytes` still 0.

## Two facts that would have produced a silent wrong answer
1. **`closed=true` is mandatory.** Without it gamma returns `[]` for every settled market — i.e. for
   most of this corpus — so a naive backfill reports "nothing found" and is believed.
2. **data-api v2 ignores `asset_id`/`token_id`.** It accepts the param, returns HTTP 200, and hands
   back the newest global trades. Used as a fallback it would have attributed all 26,520 tokens to
   whichever market traded last. (`condition=` *does* filter, so existing v2 instruments are fine.)

## Guards that keep this honest
- The recorder's map wins any disagreement and conflicts are **counted and printed**, never resolved
  silently.
- `notfound` is an absence: it never attributes a file (unit-test + mutation arm).
- The ledger is the cursor, so a partial run loses nothing and re-running writes 0 new rows.
- Nothing is deleted. The apply path is unchanged and still gated behind
  `--i-know-this-is-irreversible`; the delete decision remains the operator's.

## Verify / roll back
```
python3 scripts/l2-asset-backfill.py --report --verbose
python3 scripts/l2-asset-backfill.py --self-test       # 18/18
npx tsx scripts/l2-retention.ts                        # prints the attribution line
```
Rollback: revert the commit. Nothing in the bot's decision path reads the ledger or the script.
