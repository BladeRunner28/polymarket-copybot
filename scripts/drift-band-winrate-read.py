#!/usr/bin/env python3
"""READ-ONLY: does the drift gate's P&L damage scale with the ENTRY BAND's win rate?

Card: `drift-gate-band-winrate-shadow` (roadmap, Scheduled) — the read due at the
2026-10-08 window close, supplying ONE dimension to the drift-tolerance decision
that `decay-bar-tripped-oct8-decision` / `drift-gate-counterfactual` own. It proposes
NO threshold, moves nothing, and writes nothing.

THE HYPOTHESIS BEING TESTED (external claim, drafts/reddit-late-copy-20260928.md):
copied-market drift is outcome-aligned, so a fixed copy delay is a TAX on a
high-win-rate book and a SUBSIDY on a longshot-heavy one — hence staleness
tolerance should scale with (1 - band win rate). Our side of it: the drift gate is
the #1 skip reason and its only staleness control is a FLAT maxPriceDrift = 0.004
for every entry >= 0.20. If the claim transfers, the FORGONE counterfactual value of
drift-blocked candidates should be LARGER where the band wins more often.

WHAT A POSITIVE / NULL LOOKS LIKE, stated before the numbers are read:
  * transfers  -> blocked-candidate ex-dust mean rises with the band's as-of win rate
                  (and/or across entry bands, longshots cheaper to block);
  * null       -> ex-dust mean is flat across bands and across as-of win-rate splits,
                  i.e. the flat tolerance is not demonstrably mis-scaled and the
                  band dimension adds nothing to the decision.

POPULATION AND CONVENTIONS (must match scripts/drift-relaxation-read.py or the
numbers are not comparable — section 1 re-derives its anchors):
  * duplicate-accumulation REMOVED: one row per distinct signal, key
    (marketId, outcome, wallet), EARLIEST poll wins — this is the shipped
    `dedupeSignals()` convention in src/lib/shadow-drift.ts. Raw poll rows inflate
    N and every per-band statistic (references/exit-rules-and-sample-integrity.md).
  * headline is EX-DUST (entry >= $0.10, tuning #29 rec 1); the excluded count is
    printed, never silently dropped.
  * marked/awaiting split is stated for every bucket (settled vs still unresolved).
  * entry = candidate `currentPrice` (the price the scorer would have copied at),
    stake = $10, settled at 1.00 or 0.00 from the shadow's own `resolve` rows.
  * AS-OF DISCIPLINE: a decision's band win rate uses ONLY settled signals in that
    band with an EARLIER timestamp, and needs >= MIN_PRIOR settled priors to be
    labeled at all (below that it is reported as unlabeled, not guessed). Using the
    band's win rate over the whole sample would be look-ahead; that arm is printed
    too, clearly labelled, so the difference is visible rather than assumed.
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHADOW = ROOT / "data" / "drift-shadow.jsonl"
SUMMARY = ROOT / "data" / "drift-shadow-summary.json"

STAKE = 10.0
DUST_MIN = 0.10
MIN_PRIOR = 30          # settled earlier signals in the band needed for an as-of label
MIN_BUCKET = 25         # below this a bucket is reported as too thin, never as a direction

BANDS = [(0.00, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 1.01)]

NOW = datetime.now(timezone.utc)


def mean_se(xs):
    n = len(xs)
    if n == 0:
        return (float("nan"), float("nan"))
    m = sum(xs) / n
    if n < 2:
        return (m, float("nan"))
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return (m, math.sqrt(var / n))


def clustered_ci(pairs, reps=1000, seed=7):
    if not pairs:
        return (float("nan"), float("nan"))
    by = defaultdict(list)
    for k, v in pairs:
        by[k].append(v)
    keys = list(by)
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        pool = []
        for _ in range(len(keys)):
            pool.extend(by[keys[rng.randrange(len(keys))]])
        means.append(sum(pool) / len(pool))
    means.sort()
    return (means[int(0.025 * reps)], means[int(0.975 * reps)])


def load():
    cands, resolves = [], {}
    with SHADOW.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("type") == "candidate":
                cands.append(r)
            elif r.get("type") == "resolve":
                resolves["%s|%s" % (r.get("marketId"), r.get("outcome"))] = int(r.get("value") or 0)
    return cands, resolves


def ts_ms(c):
    return datetime.fromisoformat(str(c["ts"]).replace("Z", "+00:00")).timestamp() * 1000


def pnl(entry, value):
    if entry <= 0:
        return 0.0
    return ((value - entry) / entry) * STAKE


def band_of(entry):
    for lo, hi in BANDS:
        if lo <= entry < hi:
            return "%0.2f-%0.2f" % (lo, hi)
    return None


def fmt_ci(lo, hi):
    if math.isnan(lo):
        return "n/a"
    return "[%+.2f, %+.2f]" % (lo, hi)


def main():
    cands, resolves = load()
    published = json.loads(SUMMARY.read_text())

    # ---- 1. anchor: reproduce the published instrument on the poll-row basis
    marked = 0
    pnl_all = pnl_ex = 0.0
    marked_ex = 0
    for c in cands:
        v = resolves.get("%s|%s" % (c.get("marketId"), c.get("outcome")))
        if v is None:
            continue
        marked += 1
        e = float(c.get("currentPrice") or 0)
        p = pnl(e, v)
        pnl_all += p
        if e >= DUST_MIN:
            pnl_ex += p
            marked_ex += 1
    print("== 1. ANCHOR — my poll-row recomputation vs the published summary")
    for label, mine, pub in (
        ("candidates", len(cands), published.get("candidates")),
        ("marked", marked, published.get("marked")),
        ("avgPnlPerTradeExDust", round(pnl_ex / marked_ex, 2) if marked_ex else None,
         published.get("avgPnlPerTradeExDust")),
        ("dustExcluded", marked - marked_ex, published.get("dustExcluded")),
    ):
        flag = "OK " if str(mine) == str(pub) else "DIFF"
        print("   %s %-24s mine=%-10s published=%s" % (flag, label, mine, pub))
    sig_pub = published.get("avgPnlPerTradeExDustPerSignal")

    # ---- 2. distinct signals (duplicate-accumulation removed), settled, ex-dust
    signals = {}
    for c in cands:
        k = (c.get("marketId"), c.get("outcome"), c.get("wallet"))
        cur = signals.get(k)
        if cur is None or str(c["ts"]) < str(cur["ts"]):
            signals[k] = c
    settled = {k: c for k, c in signals.items()
               if resolves.get("%s|%s" % (c.get("marketId"), c.get("outcome"))) is not None}
    rows = []
    for k, c in settled.items():
        e = float(c.get("currentPrice") or 0)
        v = resolves["%s|%s" % (c.get("marketId"), c.get("outcome"))]
        rows.append({"key": k, "c": c, "entry": e, "value": v, "pnl": pnl(e, v),
                     "band": band_of(e), "ts": ts_ms(c)})
    ex = [r for r in rows if r["entry"] >= DUST_MIN]
    awaiting = len(signals) - len(settled)
    print("\n== 2. population (duplicate-accumulation removed)")
    print("   poll rows %d -> distinct signals %d -> settled %d (awaiting resolution %d)"
          % (len(cands), len(signals), len(settled), awaiting))
    print("   ex-dust (entry >= $%.2f): %d settled signals, %d dust-excluded"
          % (DUST_MIN, len(ex), len(rows) - len(ex)))
    m, se = mean_se([r["pnl"] for r in ex])
    lo, hi = clustered_ci([(str(r["c"]["marketId"]), r["pnl"]) for r in ex])
    print("   per-signal ex-dust mean $%+.2f (se %.2f; market-clustered 95%% CI %s) | published per-signal %s"
          % (m, se, fmt_ci(lo, hi), sig_pub))

    # ---- 3. by ENTRY BAND (no threshold proposed; this only describes the population)
    print("\n== 3. settled drift-blocked signals by ENTRY BAND (per-signal, ex-dust)")
    print("   band          settled  dust-ex   mean$    se   clustered 95% CI     win%  median entry  markets")
    band_stats = {}
    for lo_b, hi_b in BANDS:
        b = "%0.2f-%0.2f" % (lo_b, hi_b)
        sel = [r for r in ex if r["band"] == b]
        vals = [r["pnl"] for r in sel]
        avg, sd = mean_se(vals)
        clo, chi = clustered_ci([(str(r["c"]["marketId"]), r["pnl"]) for r in sel])
        wins = sum(1 for r in sel if r["value"] > 0)
        med = sorted(r["entry"] for r in sel)[len(sel) // 2] if sel else float("nan")
        mkts = len({str(r["c"]["marketId"]) for r in sel})
        bc = [r for r in rows if r["band"] == b]
        band_stats[b] = {"settled_signals": len(bc), "dust_ex": len(sel), "mean": round(avg, 2),
                         "se": round(sd, 2), "ci": [round(clo, 2), round(chi, 2)],
                         "win_rate": round(wins / len(sel), 4) if sel else None,
                         "markets": mkts, "thin": len(sel) < MIN_BUCKET}
        print("   %-12s %6d  %6d  %+7.2f  %5.2f  %-18s %6s  %8.3f  %6d"
              % (b, len(bc), len(sel), avg, sd, fmt_ci(clo, chi),
                 ("%.0f%%" % (100.0 * wins / len(sel))) if sel else "n/a", med, mkts))

    # ---- 4. AS-OF band win rate (no look-ahead): trailing settled priors only
    by_band = defaultdict(list)
    for r in rows:
        if r["band"]:
            by_band[r["band"]].append(r)
    for b in by_band:
        by_band[b].sort(key=lambda r: r["ts"])
    labeled, unlabeled = [], 0
    for b, rs in by_band.items():
        wins = 0
        n = 0
        for r in rs:
            if n >= MIN_PRIOR:
                r["prior_n"] = n
                r["prior_wr"] = wins / float(n)
                labeled.append(r)
            else:
                unlabeled += 1
            if r["value"] > 0:
                wins += 1
            n += 1
    labeled_ex = [r for r in labeled if r["entry"] >= DUST_MIN]
    print("\n== 4. as-of band win rate (>= %d earlier SETTLED priors in the same band; no look-ahead)"
          % MIN_PRIOR)
    print("   settled signals labeled %d | unlabeled (too little prior) %d | ex-dust labeled %d"
          % (len(labeled), unlabeled, len(labeled_ex)))

    # 4a within each band: above/below that band's own median as-of prior win rate
    print("\n   4a. WITHIN each band (split at the band's own median as-of win rate)")
    print("   band          split       n_ex   mean$    se   clustered 95% CI    as-of wr range  med decision date")
    within = {}
    for lo_b, hi_b in BANDS:
        b = "%0.2f-%0.2f" % (lo_b, hi_b)
        sel = sorted([r for r in labeled_ex if r["band"] == b], key=lambda r: r["prior_wr"])
        if len(sel) < 2 * MIN_BUCKET:
            print("   %-12s  (too thin: %d ex-dust labeled rows, need %d per side) — NO READ"
                  % (b, len(sel), MIN_BUCKET))
            within[b] = {"n_ex": len(sel), "verdict": "too thin"}
            continue
        mid = len(sel) // 2
        for name, part in (("LOW half", sel[:mid]), ("HIGH half", sel[mid:])):
            vals = [r["pnl"] for r in part]
            avg, sd = mean_se(vals)
            clo, chi = clustered_ci([(str(r["c"]["marketId"]), r["pnl"]) for r in part])
            wrs = [r["prior_wr"] for r in part]
            med_day = sorted(r["ts"] for r in part)[len(part) // 2]
            med_txt = datetime.fromtimestamp(med_day / 1000.0, timezone.utc).strftime("%Y-%m-%d")
            print("   %-12s  %-9s %5d  %+7.2f  %5.2f  %-18s %5.2f-%.2f     %s"
                  % (b, name, len(vals), avg, sd, fmt_ci(clo, chi), min(wrs), max(wrs), med_txt))
            within.setdefault(b, {})[name] = {"n_ex": len(vals), "mean": round(avg, 2),
                                              "ci": [round(clo, 2), round(chi, 2)],
                                              "wr_range": [round(min(wrs), 3), round(max(wrs), 3)],
                                              "median_decision_date": med_txt}
    print("   (the median-date column is the TIME CONFOUND control: where the two halves sit on")
    print("    nearly the same date, a HIGH-vs-LOW gap is a win-rate contrast; where they are days")
    print("    apart it is also a time/window contrast and must not be read as win rate alone.)")

    # 4b pooled: quintiles of the as-of band win rate across all bands
    print("\n   4b. POOLED by quintile of the as-of band win rate (all bands)")
    srt = sorted(labeled_ex, key=lambda r: r["prior_wr"])
    q = max(1, len(srt) // 5)
    print("   quintile  n_ex   mean$    se   clustered 95% CI    as-of wr range   bands present")
    pooled = []
    for i in range(5):
        part = srt[i * q:(i + 1) * q] if i < 4 else srt[4 * q:]
        if len(part) < MIN_BUCKET:
            print("   Q%d        %4d  (too thin) — NO READ" % (i + 1, len(part)))
            continue
        vals = [r["pnl"] for r in part]
        avg, sd = mean_se(vals)
        clo, chi = clustered_ci([(str(r["c"]["marketId"]), r["pnl"]) for r in part])
        wrs = [r["prior_wr"] for r in part]
        bl = sorted({r["band"] for r in part})
        pooled.append({"q": i + 1, "n": len(vals), "mean": round(avg, 2), "ci": [round(clo, 2), round(chi, 2)]})
        print("   Q%-8d %4d  %+7.2f  %5.2f  %-18s %.2f-%.2f  %s"
              % (i + 1, len(vals), avg, sd, fmt_ci(clo, chi), min(wrs), max(wrs), ",".join(bl)))

    # 4c CONTROL: the same split on the WHOLE-SAMPLE band win rate (look-ahead) so the
    #     difference between the two arms is visible rather than assumed
    print("\n   4c. CONTROL — pooled quintiles using the WHOLE-SAMPLE band win rate (LOOK-AHEAD, printed only)")
    whole = {b: (sum(1 for r in rs if r["value"] > 0) / float(len(rs)) if rs else 0.0)
             for b, rs in by_band.items()}
    print("   whole-sample band win rates: %s"
          % ", ".join("%s %0.2f" % (b, w) for b, w in sorted(whole.items())))
    print("   (the card forbids using these as the axis; they are here to show the arm the")
    print("    as-of discipline replaces, and to make an accidental look-ahead read visible.)")

    # ---- 5. verdict block
    print("\n== 5. VERDICT INPUTS (no threshold proposed; the decision belongs to the drift card)")
    enough_bands = [b for b, s in band_stats.items() if not s["thin"]]
    print("   bands with >= %d ex-dust settled signals: %s" % (MIN_BUCKET, ", ".join(enough_bands) or "NONE"))
    if enough_bands:
        vals = [(b, band_stats[b]["mean"], band_stats[b]["dust_ex"]) for b in enough_bands]
        vals.sort(key=lambda x: x[0])
        print("   band means (low->high entry): %s"
              % " | ".join("%s $%+.2f (n=%d)" % v for v in vals))
    if pooled:
        mono = [p["mean"] for p in pooled]
        rising = all(b >= a for a, b in zip(mono, mono[1:]))
        falling = all(b <= a for a, b in zip(mono, mono[1:]))
        print("   pooled quintile means (low->high as-of win rate): %s"
              % " | ".join("Q%d $%+.2f (n=%d)" % (p["q"], p["mean"], p["n"]) for p in pooled))
        print("   monotone rising with the band's as-of win rate: %s | monotone falling: %s"
              % (rising, falling))
        print("   (a POSITIVE transfer of the external claim needs the FORGONE value to RISE with the")
        print("    band win rate; a flat series is the null and adds nothing to the tolerance call.)")

    out = {"generatedAt": NOW.isoformat(),
           "poll_rows": len(cands), "distinct_signals": len(signals),
           "settled": len(settled), "awaiting": awaiting, "dust_excluded": len(rows) - len(ex),
           "per_signal_ex_dust_mean": round(m, 2),
           "per_signal_ex_dust_ci": [round(lo, 2), round(hi, 2)],
           "bands": band_stats, "as_of_min_prior": MIN_PRIOR,
           "as_of_labeled": len(labeled), "as_of_unlabeled": unlabeled,
           "within_band": within, "pooled_quintiles": pooled,
           "whole_sample_band_win_rates": {b: round(w, 4) for b, w in whole.items()}}
    print("\nReproduce: python3 scripts/drift-band-winrate-read.py   (reads data/drift-shadow.jsonl; writes nothing)")


if __name__ == "__main__":
    main()
