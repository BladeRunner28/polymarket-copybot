# C-200 fill-aware booking — union read (2026-11-22T15:05:43.850Z)

Read-only instrument: `npx tsx scripts/c200-fill-aware-pnl.ts`. Nothing applied.

```
[c200-fill-aware] artifact data/c200-printthrough.jsonl · 571 snapshots (571 carrying legs) · ranAt 2026-09-26T06:16:35.494Z .. 2026-11-22T14:44:08.659Z · POPULATION = UNION
[c200-fill-aware] union: 955 distinct intents · evidence rule newer-wins-except-absence (kept older evidence 2, upgraded 4, newer kept 187099)
[c200-fill-aware] joined to a booked leg 937/955 · settled 911 · book evidence 936 · tape evidence 913
[c200-fill-aware] CENSUS (clock = dispatchedAt, now 2026-11-22T15:05:43.850Z; level = intent − live credit)
[c200-fill-aware]   window   legs  stamped  bookEvid  tapeEvid  bookReach  tapeReach@1h(flat)
[c200-fill-aware]   7d        150      150       150       145     +33.3%              +17.9%
[c200-fill-aware]   30d       473      473       473       462     +31.3%              +14.7%
[c200-fill-aware]   90d       955      955       954       930     +32.9%              +16.5%
[c200-fill-aware]   all       955      955       954       930     +32.9%              +16.5%
[c200-fill-aware] GATE (card profit-c200-reachability-stamp: >=200 stamped legs inside 30d) = MET — 30d stamped 473 of 473 dispatched (book 473, tape 462; overlapping arms, never summed)

[c200-fill-aware] mode=flat (mode=flat): reachable 159/937 = 17.0% (unresolved 0, excluded from the rate)
[c200-fill-aware] booked +$1380.67 on $14412.36 (+9.6%) · fill-aware -$1117.13 (-7.8% per intended copy, -39.6% given fill) · delta -$2497.80
[c200-fill-aware] band         n  unres   reach   booked$  bookROI  fillaware$  ROI|fill  per-copy  ex-top10-fill
[c200-fill-aware] 0.00-0.10   66      0   12.1%    -$78.10     -2.6%     -$331.50    -96.2%    -10.9%        n/a
[c200-fill-aware] 0.10-0.20  120      0   13.3%  +$1164.64    +20.7%     -$530.90    -40.5%     -9.4%   -$600.00
[c200-fill-aware] 0.20-0.40  357      0   22.1%   +$267.12     +6.3%     -$287.11    -28.3%     -6.8%   -$636.38
[c200-fill-aware] 0.40-0.60  196      0   18.4%     +$0.21     +0.1%      +$15.17    +34.8%     +6.6%     -$0.30
[c200-fill-aware] 0.60-0.80  196      0    9.7%    +$30.17     +2.3%      +$17.83    +17.3%     +1.4%    -$13.08
[c200-fill-aware] 0.80-1.00    2      0   50.0%     -$3.37    -45.1%       -$0.62    -25.0%     -8.3%        n/a

[c200-fill-aware] mode=live (mode=live): reachable 314/936 = 33.5% (unresolved 1, excluded from the rate)
[c200-fill-aware] booked +$1380.67 on $14412.36 (+9.6%) · fill-aware -$896.40 (-6.2% per intended copy, -18.7% given fill) · delta -$2277.07
[c200-fill-aware] band         n  unres   reach   booked$  bookROI  fillaware$  ROI|fill  per-copy  ex-top10-fill
[c200-fill-aware] 0.00-0.10   66      0   21.2%    -$78.10     -2.6%     -$690.56    -98.0%    -22.7%   -$400.00
[c200-fill-aware] 0.10-0.20  119      1   26.9%  +$1164.64    +20.7%     -$177.54     -8.6%     -3.2%  -$1427.97
[c200-fill-aware] 0.20-0.40  357      0   34.2%   +$267.12     +6.3%      -$92.04     -6.2%     -2.2%   -$499.13
[c200-fill-aware] 0.40-0.60  196      0   39.8%     +$0.21     +0.1%      +$17.89    +19.1%     +7.8%     +$0.37
[c200-fill-aware] 0.60-0.80  196      0   34.2%    +$30.17     +2.3%      +$46.47    +10.2%     +3.6%    -$12.25
[c200-fill-aware] 0.80-1.00    2      0   50.0%     -$3.37    -45.1%       -$0.62    -25.0%     -8.3%        n/a

[c200-fill-aware] maker-vs-taker delta mode=flat: booked +9.9% vs fill-aware -8.0% per $1 intended = -17.9pp (95% CI [-37.6, -0.7]pp; market-clustered bootstrap, 873 settled markets, 2000 reps, seed 20261122)
[c200-fill-aware] maker-vs-taker delta mode=live: booked +9.9% vs fill-aware -6.4% per $1 intended = -16.3pp (95% CI [-33.2, -1.2]pp; market-clustered bootstrap, 873 settled markets, 2000 reps, seed 20261122)
```

Attainable = REACHABILITY, not a fill: a best ask at/below the level ignores queue position and size.
