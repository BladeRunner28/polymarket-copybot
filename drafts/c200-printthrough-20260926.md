# C-200 intent print-through — first read

Generated 2026-09-26 01:17 CDT by `scripts/c200-printthrough.py` (measurement only — nothing in the trade path reads this). Card: `c200-intent-printthrough-check`.

```
[printthrough] C-200 intent print-through — did the market print/offer at or below (intent - $0.02)?
[printthrough] legs 6 | tape-analysable 3 (+3 tape-silent, excluded) | book-analysable 6
[printthrough] PRINTS (public tape, 5m): 0/3 = 0%   (pre-registered archive bar 74.3%)
[printthrough] PRINTS (public tape, 1h): 0/3 = 0%   (archive bar 81.1%)
[printthrough] BOOK (our 5s L2 corpus, 1h): min best-ask <= level on 0/6 legs — a seller at/below our level = the bid fills
[printthrough] ANCHOR: intent == detection mid 6/6 · intent == the copied wallet's own print 0/6 · level sits BELOW the first covered best bid on 4/6
[printthrough] COVERAGE: our L2 book starts 8.6/7.7/5.6/4.6/2.7/2.7 min AFTER dispatch -> the 5-min horizon has NO in-house book coverage on any leg
[printthrough]   nhl-sea-van-2026-09-26 KRAKEN: intent 0.525 (wallet print 0.52) level 0.505 | tape prints 5m/1h 0/1 reached 5m=False 1h=False (n/a) | book min ask 0.53 over 616 snaps from +8.6min (bid 0.52/ask 0.53) reachable=False | drift 1h 0.01
[printthrough]   nhl-nj-nyi-2026-09-26 DEVILS: intent 0.515 (wallet print 0.5100001617) level 0.495 | tape prints 5m/1h 0/0 (SILENT) reached 5m=False 1h=False (n/a) | book min ask 0.51 over 627 snaps from +7.7min (bid 0.48/ask 0.52) reachable=False | drift 1h None
[printthrough]   cfb-clmb-gtwn-2026-09-26-total-51pt5 OVER: intent 0.465 (wallet print 0.47) level 0.445 | tape prints 5m/1h 2/4 reached 5m=False 1h=False (n/a) | book min ask 0.47 over 569 snaps from +5.6min (bid 0.46/ask 0.47) reachable=False | drift 1h -0.0
[printthrough]   cfb-ri-ncat-2026-09-26-total-53pt5 OVER: intent 0.430 (wallet print 0.4200000232) level 0.410 | tape prints 5m/1h 0/0 (SILENT) reached 5m=False 1h=False (n/a) | book min ask 0.44 over 449 snaps from +4.6min (bid 0.41/ask 0.44) reachable=False | drift 1h None
[printthrough]   cfb-tx-tenn-2026-09-26-spread-home-2pt5 TENNESSEE: intent 0.315 (wallet print 0.3) level 0.295 | tape prints 5m/1h 0/0 (SILENT) reached 5m=False 1h=False (n/a) | book min ask 0.33 over 209 snaps from +2.7min (bid 0.3/ask 0.33) reachable=False | drift 1h None
[printthrough]   cfb-ill-ohiost-2026-09-26-1h-spread-home-16pt5 OHIO STATE: intent 0.460 (wallet print 0.45) level 0.440 | tape prints 5m/1h 1/1 reached 5m=False 1h=False (n/a) | book min ask 0.47 over 209 snaps from +2.7min (bid 0.45/ask 0.47) reachable=False | drift 1h 0.0278
[printthrough] adverse selection (mean px_end - anchor, 1h): reached n/a (archive 0.4-0.6 band -0.0323) | not reached +0.0126 (n=3)
[printthrough] CAVEAT: a print/touch at our level is not queue position and ignores size — the reading is 'the level was reachable', never 'we would have been filled'. Measurement only.
```

## What this first read does and does not establish

- **ESTABLISHED:** the level (intent - $0.02) was **not reachable** on any of the 6 measured legs in the hour after dispatch — 0/6 on our own L2 book (best ask at or below the level) and 0/3 on the public tape where the tape had prints. The archive's base rate (74.3% within 5 min / 81.1% within 1 h at C-200's price mix) does not show up on this sample.
- **ESTABLISHED, and the mechanical reason to expect a gap:** the intent price is the detection **midpoint** (`ObservedTrade.detectedPrice`), not the copied wallet's own print — 6/6 legs. The assumed fill is therefore `mid - 2c`, which on a 1c spread sits ~1.5c BELOW the prevailing best bid (below the first covered best bid on 4/6 legs). The archive measured “a print at p, then a print at or below p - 2c”: a level anchored on the MID is a deeper, different event, so the 74.3% may not transfer by construction.
- **NOT ESTABLISHED:** the number the card's gate asks for. n=6, 3 of them tape-silent, and our own book never covers the first 2.7-8.6 min after a dispatch, so the 5-minute horizon has no in-house coverage at all. Read this as a direction plus a data-availability finding, not a rate.
- **BLOCKERS before this can decide anything:** (1) the L2 recorder's universe refresh admits a market only after a copy exists, so coverage always starts AFTER the dispatch — subscribing at copy time is the fix (observability change, not approved); (2) the public tape is thin on these markets (2-50 rows for the whole market); (3) n. The gate stands: >=50 measured legs, then the share vs 74.3%.

## Reproduce

```
python3 scripts/c200-printthrough.py
sqlite3 "file:prisma/dev.db?mode=ro" "SELECT COUNT(*) FROM FillIntent;"
```

Artifacts: `data/c200-printthrough.jsonl` (append-only), `data/c200-tape/` (tape cache).
