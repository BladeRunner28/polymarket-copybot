"""Every number quoted in the two asset-audit drafts, computed here (no hand arithmetic)."""

print("== A: venue formula vs docs fee table (100 shares) ==")
for rate, doc_row in ((0.07, "crypto"), (0.05, "sports/econ/culture/weather/other"), (0.04, "finance/politics/mentions/tech"), (0.03, "sports_fees_*_oct26 promo")):
    print(f"  rate {rate}: 100*rate*0.5*0.5 = {100*rate*0.5*0.5:.2f} USDC at p=0.50  [{doc_row}]")

print("\n== A: per-share fee delta, our proxy vs venue, at p=0.50 ==")
for venue, why in ((0.03, "sports promo"), (0.00, "zero_fees/geopolitics"), (0.04, "politics/finance"), (0.05, "exact")):
    proxy = 0.05
    print(f"  venue {venue} vs proxy {proxy}: per-share {proxy*0.25 - venue*0.25:+.5f}  (100 shares: {(proxy*0.25-venue*0.25)*100:+.4f} USDC)  [{why}]")
print("  under-charge case venue 0.05 vs proxy 0.04: per-share "
      f"{0.04*0.25 - 0.05*0.25:+.5f} (100 shares: {(0.04*0.25-0.05*0.25)*100:+.4f} USDC)")

print("\n== A: 5-dp fee precision examples ==")
for p, c, r in ((0.01, 1, 0.05), (0.99, 1, 0.05), (0.5, 100, 0.07)):
    print(f"  p={p} C={c} rate={r}: raw={c*r*p*(1-p):.10f} -> rounded5={round(c*r*p*(1-p), 5)}")

print("\n== A: our own captured data (data/fee-schedules.jsonl, 2026-09-28) ==")
print("  rows 48, all with a venue rate; 27 exact / 21 differ; 14 venue rate 0")
print(f"  14/48 = {14/48*100:.1f}% fee-free markets charged our default 0.05")
print(f"  21/48 = {21/48*100:.1f}% disagree")

print("\n== A: live 2026-10-15 sample (500 top-volume markets, keyless gamma) ==")
print(f"  170/400 with a schedule differ = {170/400*100:.1f}% (first 400 sampled by the script)")
print("  volume-weighted share where our map is wrong: 38.8% of 24h volume (script output)")

print("\n== A: our own book coverage, 25 newest BANKROLL_200 legs ==")
print(f"  gamma serves {6}/25 = {6/25*100:.0f}% ; CLOB clob-markets fd serves {25}/25 = {25/25*100:.0f}%")
print("  venue rate on those 25: 0.05 on all 25 -> proxy delta $0.0000 (no re-pricing win on the recent book)")

print("\n== B: strategy_validator structure ==")
print("  cpcv folds = C(10,2) =", len(list(__import__("itertools").combinations(range(10), 2))))
print("  consistency thresholds: PASS >=0.70 positive folds, CAUTION >=0.55, else FAIL")
print("  min observations for CPCV = n_groups*(purge+embargo+5) = 10*(5+10+5) =", 10*(5+10+5))
print("  DSR: num_obs<10 -> INSUFFICIENT_DATA; delegated to `deflated_sharpe` pkg, else t-test fallback")
