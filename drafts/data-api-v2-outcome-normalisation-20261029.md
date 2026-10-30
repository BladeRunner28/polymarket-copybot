# Outcome text identity — data-api-v2-outcome-normalisation (Lane B, 2026-10-29)

**Verdict: the card named a mechanism that never fired. The class it was worried about is real but latent, and the measured cost is zero.**

## What the card claimed vs what the data says

The card: Data API v2 strips punctuation, so joins keyed on outcome TEXT break across the 2026-10-19 cutover.

Measured on `prisma/dev.db`, read 2026-10-29T23:10Z, level = token text over all 4,740,734 `ObservedTrade` rows:

- rows whose outcome carries an apostrophe: **0**. The only stored form of the token the card cited is `ANYONES LEGEND`.
- distinct outcome texts **7,245** collapse to **7,231** alnum-only identities → **14 twin pairs**, i.e. 14 tokens the venue spells two ways.
- Their date ranges **interleave inside single eras** and most **predate** the cutover: this is venue name variance, not a version change.

Sample pairs (n = rows): `NONGSHIM RED FORCE` 90 / `NONGSHIM REDFORCE` 1,426 · `PORTLAND FIRE` 250 / `PORTLANDFIRE` 166 · `TEAM SECRET` 39 / `TEAM SECRET ` 24 (trailing space) · `MACCABI TEL AVIV` 114 / `MACCABI TEL-AVIV` 1.

## Cost of the hole, measured at three levels

- **position** (wallet, market, token identity): 0 of 1,278,671 `ObservedTrade` positions and 0 of 4,966 `PaperTrade` positions carry two spellings.
- **cross-table** (copy vs incoming fill): 0 copied positions ever saw a differently-spelled fill.
- **fill** (double-book risk): 0 of 4,390,860 unscored rows would coalesce under one key shape but not the other.

## Fix shipped

One canonical identity module, `src/lib/outcome-identity.ts` (`outcomeIdentity`, `fillIdentityKey`, `positionIdentityKey`, built on the existing `normalizeOutcomeLabel`), now used by the three identity keys that were raw text:

- `scripts/monitor-trades.ts` `seenKey` — fill insert dedupe (mirrors the `@@unique` on `ObservedTrade`)
- `scripts/score-trades.ts` `dupKey` + `openCopyKeys` — v52 sweep dedupe, one open copy per position
- `src/lib/accounting.ts` `dedupeFirstLeg` — published leg accounting

**No-op proof on live data:** 24h lookback 135,495 fills → 135,495 raw keys vs 135,495 identity keys (0 collapsed); 488 open legs → 137 raw keys vs 137 identity keys (0 collapsed); unscored fills coalesce 474 under both shapes. Nothing the bot decides or risks changes today.

## Verification and rollback

- `npx tsc --noEmit` clean; `npx vitest run` **667/667, 67 files** (9 new tests freezing the 14 measured pairs, the keep-apart cases, and the blank-market rule).
- Re-measure any time: `python3 scripts/outcome-text-variant-read.py` (read-only, prints population / clock / level with every number).
- Rollback: revert the commit. The keys return to raw text, which behaves identically on today data.
