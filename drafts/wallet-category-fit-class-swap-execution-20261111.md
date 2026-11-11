# Wallet category basis: the slug token is out, the real class is in (v72)

**Card** `wallet-category-fit-class-swap` (approved via the approvals inbox 2026-11-11,
`apr-wallet-category-fit-class-swap`, kanban `t_eb3d3136`) · **status** SHIPPED on RuleSet **v72** ·
**date** 2026-11-11 · **measurement it follows** `drafts/wallet-category-fit-class-swap-20260923.md`

## What changed (one rule field + the code that reads it)

| | before | after |
|---|---|---|
| `walletCategoryBasis` (RuleSet) | `token` (default) | **`class`** (v72) |
| Strength map key | `t.marketCategory` — the raw event-slug token | `t.marketCategoryClass` — the real coarse class |
| `bestCategory` on a track wallet | `lol`, `mlb`, `alaska`, `highest` | `esports`, `sports`, `politics`, `weather` |
| `categoryFitScore` input (`score-trades.ts`) | `cats[t.marketCategory]` | `cats[t.marketCategoryClass]`, resolved on the basis the map was **built** on |
| Fine class | not stored | stored beside the coarse map as a **diagnostic only** (never feeds a score) |
| v45 per-bot blacklist, 15-per-slug cap | token | **unchanged** — token granularity is by design there |

Files: `src/lib/scoring/wallet.ts` (basis + `encode/decodeCategoryStrengths` + `categoryWinRateFor`),
`src/lib/rules.ts` (field, default `token`), `scripts/scan-wallets.ts` (stores the payload; adds an
opt-in `WALLET_SCAN_STATUS` filter), `scripts/score-trades.ts` (basis-aware lookup),
`src/app/wallets/[address]/page.tsx` (labels which basis it renders), `prisma/seed.ts`,
`scripts/apply-v72.ts` (apply/revert), `scripts/verify-v72-category-basis.ts` (live instrument),
`tests/wallet-scoring.test.ts` (+6 tests, incl. the revert guarantee that the DEFAULT stays `token`).

## Why the payload carries its own basis

A swap only re-keys a wallet when the hourly scan reaches it, so for days the table holds two
generations at once: 3,856 legacy rows (bare flat maps, token-keyed by construction) and the rows the
scan has re-scored. A reader that assumed one key space would look a token up in a class map, find
nothing, and silently fall back to the neutral 50 — an invisible change in admissions. So the stored
JSON is now `{basis, strengths, fine}` and both the scorer and the wallet page read the basis from the
artifact itself. Legacy flat maps decode as `token`; nothing has to be backfilled.

## The measurement does NOT claim an edge — read this before quoting it

The 2026-09-23 measurement on this card is **negative for ranking**: with the wallet's bucket win rate
as the score and the market outcome as the label, the class basis sits at chance in both lanes (C-200
coarse AUC 0.487 / fine 0.502; STANDARD coarse 0.493 / fine 0.522; every wallet-clustered CI includes
0.5) — the same null as the token basis. What the class basis *does* fix is the **label**: 3 buckets
per wallet instead of 14, 33 trades per bucket instead of 2.5, 87–91% of legs getting a defined fit
instead of 69–84%, and no `bestCategory` that reads `will` / `what` / `world` / `highest`.

So this ships as a consistency/label change on the operator's explicit approval, not as an edge claim.
It is a RuleSet version rather than a code edit precisely because it does move the component: the two
bases disagree by more than 10 win-rate points on **388 C-200 and 2,577 STANDARD legs**.

**Pre-registered reopen (carried from the card's gate):** a class-based `categoryFit` must clear the
lane MDE with a CI excluding 0.5 where the token basis does not. Until then, no sizing or admission
claim may rest on this swap.

## Live verification (this is the evidence, not a description of it)

`npx tsx scripts/verify-v72-category-basis.ts --limit 4` on RuleSet v72, wallets holding settled legs,
each scored from the same fetched sample under both bases:

| wallet | sample | token buckets → bestCategory | class buckets → bestCategory |
|---|---|---|---|
| 0x52b7…0aa1 | 199 trades, 100% class | 7 → `lol` | 3 → `esports` |
| 0x17dd…44c | 173 trades, 100% class | 70 → `alaska` | 9 → `politics` |
| 0x885f…8ed9 | 198 trades, 100% class | 26 → `mlb` | 4 → `sports` |
| 0x85f0…3f67 | 200 trades, 100% class | 12 → `nba` | 2 → `sports` |

- Every fetched trade carried a class (**770/770**), round-trip loss 0, and a class-keyed map never
  answered from a token field (0 bad key reads).
- The **stored** payload read back through the production path (`WalletProfile.categoryStrengthsJson`
  → decode → lookup) returned the same win rate as the fresh fetch on all four wallets.

Write path, end to end: `WALLET_SCAN_STATUS=track WALLET_SCAN_LIMIT=25 npm run scan:wallets` re-scored
the cohort the lane actually copies from — **25/25 track wallets are now `basis: "class"`**, with
`bestCategory` distributing sports 10 / esports 7 / other 5 / crypto 2 / politics 1. Whole table:
27 class-keyed, 3,856 legacy token rows still reading correctly.

RuleSet state: `v71 → v72`, `{"walletCategoryBasis":"token"} → {"walletCategoryBasis":"class"}`,
recorded in `RuleChange` as `hermes-v72-wallet-category-basis`; the loader read-back
(`getActiveRules()`, the same call the scanner makes) returns `class`.

## Revert (one field, one command)

```
npx tsx scripts/apply-v72.ts --apply --token     # back to the shipped default
```

`DEFAULT_RULES.walletCategoryBasis` stays `"token"`, so any ruleset lacking the field — including a
rollback of the RuleSet row — scores byte-identically to pre-v72, and a test pins that default.

## Flags a reviewer may want to override

- **`WALLET_SCAN_STATUS` is opt-in and cron does not set it.** The rotation is
  least-recently-scanned-first across ~3,900 profiles, so without this filter the 25 tracked wallets
  (the only cohort whose stored map moves admissions) sat at the **back** of a ~6-day queue. One run
  with the filter re-keyed them immediately. Say the word and I wire it into the hourly cron instead.
- **`uncategorized` can no longer be `bestCategory`.** It is the absence of a category; advertising it
  as a strength was a lying label under either basis. Affects 0 track wallets today.
- **The fine-class map is stored but unread** (diagnostics only, per the card's scoping note). It costs
  ~1.5 KB/wallet in `categoryStrengthsJson`.
