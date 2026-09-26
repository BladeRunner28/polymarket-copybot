# Historical archive inventory — Polymarket-v1 + quant-bench on `/Volumes/Storage`

**Date:** 2026-09-25 · **Status:** ACQUIRED + VERIFIED (nothing written to the internal volume; no rule/PnL/number change)
**Trigger:** user-approved pull ("Let's do quant-bench and Polymarket-v on Storage and card and hold on SII-WANGZJ")
**Provenance:** the download itself predated this session — a sibling session ran it at 18:03–18:38 and wrote the manifests. **Everything below was re-verified by me** (own duckdb row counts, own file walk, own column/era checks); the numbers I did not reproduce are labelled as inherited.

---

## 1. What landed, and where

| dataset | path | size on disk | files | free space after |
|---|---|---|---|---|
| **TimeSeventeen/Polymarket-v1** | `/Volumes/Storage/pm-data/polymarket-v1` | **52.89 GB** | 2,152 parquet | — |
| **smf-ulm/polymarket-quant-bench** | `/Volumes/Storage/pm-data/quant-bench` | **0.61 GB** | 1,417 parquet | — |
| both | `/Volumes/Storage` (external `NX-512 2280` NVMe, APFS) | **53.5 GB** | | **377 GiB free** (was 427 GB before the pull) |

Internal volume untouched: **183 GiB free, unchanged**. Stale `.incomplete` leftovers from the sibling's interrupted first attempt (2 per dataset, 6 MB total cache) were removed after confirming every target file exists — parquet counts afterwards unchanged at **2,152 / 1,417**.

## 2. Independent verification (my own queries, not the manifest's)

Row counts reproduced with `duckdb` against HF's published datasets-server totals — **exact match on all seven tables**:

| config | files | rows (mine) | rows (published) | match |
|---|---|---|---|---|
| `OrderFilled` | 42 | **1,201,580,990** | 1,201,580,990 | ✅ |
| `CTF` | 5 | **838,688,922** | 838,688,922 | ✅ |
| `daily_aligned` | 1,248 | **601,934,424** | 601,934,424 | ✅ |
| `daily_aligned_multi` | 857 | **144,175,988** | 144,175,988 | ✅ |
| `bars_daily` (qb) | 147 | **1,462,282** | 1,462,282 | ✅ |
| `bars_hourly` (qb) | 1,266 | **12,655,266** | 12,655,266 | ✅ |
| `markets` (qb) | 4 | **36,831** | 36,831 | ✅ |

Zero missing files, zero size mismatches, zero zero-byte files. Span verified from the data itself: `OrderFilled.block_timestamp` runs **2022-11-21 19:50:09 → 2026-04-28 11:00:40 UTC** (matches the paper's stated span exactly), **1,703,782 distinct token_asset_id**.

## 3. What is actually in it — better than the paper's headline

`OrderFilled` columns: `id, maker, taker, block_timestamp, maker_asset_id, taker_asset_id, maker_direction, taker_direction, token_asset_id, token_amount, usdc_amount, price, fee_usdc`.

- **`maker_direction` / `taker_direction` are populated on 100% of 1,201,580,990 rows** (verified by count, not by sampling) — this is the ground-truth aggressor direction the paper claims, and the field our own stack has never had.
- **`fee_usdc` is populated on 100% of rows**, but **its regime is era-dependent — verified across three files:**

| file | fills | fills with fee > 0 | maker_buy share |
|---|---|---|---|
| `2022_11.parquet` | 138 | **0.0%** | 57% |
| `2024_08.parquet` | 2,856,591 | 0.03% | 61% |
| `2026_04.parquet` | **227,285,666** | **88.03%** | 84% |

  ⇒ two things at once: (a) the modern era is **fee-bearing** and the archive carries the actual dollar fee per fill — the calibration input `c200-maker-fill-assumption` and the taker-fee measurement were both missing; (b) **any fee/fill model must be era-gated**, because pre-2025 fills are effectively fee-free.
- `daily_aligned` adds per-market context on top of the fill stream: `condition_id, outcome_seq, neg_risk, category, category_refined, outcome_label, winning_outcome_label, resolution_status, taker_base_fee, maker_base_fee, opens_at, close_at, resolved_at, market_slug, p_event` — i.e. **resolution labels and the venue's own base-fee parameters per market**, joined at fill level.
- `quant-bench` gives `token_id, period_start, period_end, open, high, low, close, vwap, volume_usd, n_trades, n_buys, n_sells` (daily + hourly) plus 36,831 markets with `clob_token_ids` — a cheap external cross-check on our own CLOB price pager.

## 4. The boundary that governs how this may be used

**The archive ends 2026-04-28 — before our bot era.** First paper trade: 2026-06-18 (7.7 GB live DB). So:

- ✅ **legitimate uses:** fee-model and fill-probability calibration on ground-truth direction; the (price × τ) calibration surface at 1.2B-trade scale; era/regime studies; ML pretraining features; external cross-checks.
- ❌ **never:** pricing any of our own decisions, or standing in for our rolling `clob /prices-history` capture (which remains the layer for our window and for anything after 2026-04-28). It also covers **CTF Exchange v1**, which terminated — the venue's current book is not this.

## 5. SII-WANGZJ — HELD (user decision, 2026-09-25)

`SII-WANGZJ/Polymarket_data` is real and MIT (**232.5 GB / 5,412,260,320 rows** today: `orderfilled` 110.3 GB, `users` 47.7, `trades` 37.5, `quant` 36.7, `markets` 0.29). It is **not** pulled, by explicit user instruction: hold until the NAS is connected **or** another storage drive is acquired.

**Release gate (pre-registered):** pull only when (a) `freenas` @ 192.168.1.55 has a readable pool with **≥400 GB free** (credentials required — guest SMB and SSH are both closed to this host), **or** (b) a new drive ≥512 GB is attached; and start with `markets.parquet` + `users.parquet` before the 110 GB `orderfilled`. It must not land in `/Volumes/Storage/pm-data` (would leave <200 GiB free on the volume that also holds the archive tier).

## 6. Query recipes

```bash
DUCKDB=/Volumes/Storage/pm-data/.venv/bin/python   # venv already has duckdb 1.5.5

# one-line fee/era sanity check
$DUCKDB -c "import duckdb;print(duckdb.sql(\"SELECT COUNT(*), SUM(CASE WHEN fee_usdc>0 THEN 1 ELSE 0 END) FROM read_parquet('/Volumes/Storage/pm-data/polymarket-v1/OrderFilled/2026_04.parquet')\").fetchall())"

# maker/taker split by price band over the whole archive (heavy — run off-hours)
duckdb -c "SELECT round(price,1) band, COUNT(*) n, ROUND(100*AVG(CASE WHEN taker_direction='BUY' THEN 1 ELSE 0 END),1) taker_buy_pct
           FROM read_parquet('/Volumes/Storage/pm-data/polymarket-v1/OrderFilled/*.parquet') GROUP BY 1 ORDER BY 1"

# resolution labels + venue base-fee parameters
duckdb -c "SELECT category_refined, COUNT(DISTINCT condition_id) mkts, AVG(taker_base_fee) taker_fee
           FROM read_parquet('/Volumes/Storage/pm-data/polymarket-v1/daily_aligned/*.parquet') GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
```

**Known limits (carry these into any study):** `quant-bench` is daily+hourly only (no 1m/5m) and covers high-liquidity resolved markets only; neither archive has order-book depth (our own `data/l2/` remains the only depth source, PM since 2026-08-31); licence is **CC-BY-4.0 on the HF card but CC BY-SA 4.0 on the paper text** — reconcile before redistributing anything derived; all licence/attribution obligations travel with derived artifacts.

*Verification summary: the pull was performed by a sibling session; I reproduced every row count, the timestamp span, the direction/fee field population, the fee-era gradient and the file inventory myself. Numbers I did not reproduce are labelled "published".*
