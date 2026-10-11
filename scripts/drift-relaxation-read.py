#!/usr/bin/env python3
"""READ-ONLY: price the pre-registered maxPriceDrift/longshotDriftPct relaxation.

The 2026-09-20 decay bar (tuning #31 rec 2) says a drift relaxation is brought
forward when the drift gate's counterfactual is at/below $0.50/trade ex-dust for
7 consecutive days AND the trailing-7d cohort mean is also at/below the bar.

This script decides nothing. It (1) reproduces the published instrument so the
read is anchored, (2) re-reads the population on axes the published summary does
not carry - per-decision-day, distinct signals instead of poll rows, and screened
by the NON-drift gates so "would have been copied" is true rather than assumed -
and (3) prices what each candidate tolerance would actually admit, at the price
the gate would have paid, marked to settlement, with market-clustered intervals.

Era note (verified in RuleSet): the whole drift-shadow window (2026-09-17 ->) sits
under minCopyScore 80 / minConfidence 0.7 / maxSpread 0.06 / minLiquidity 750 /
maxPriceDrift 0.004 (stable v43 -> v61), so screening on those is era-correct.

Nothing here writes to a live artifact.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHADOW = ROOT / "data" / "drift-shadow.jsonl"
SUMMARY = ROOT / "data" / "drift-shadow-summary.json"
SERIES = ROOT / "data" / "drift-decay-series.jsonl"
DB = ROOT / "prisma" / "dev.db"

STAKE = 10.0
DUST_MIN = 0.10
BAR_USD = 0.50
DAYS_REQUIRED = 7
MAKER_IMPROVEMENT = 0.02  # the Rust sidecar books BANKROLL_200 at intent - $0.02

# active v61 non-drift gates: the drift shadow records EVERY row whose risks mention
# price drift, including rows the score/confidence/spread/liquidity gates would have
# blocked anyway, so a "would-have-copied" read must screen them.
MIN_COPY_SCORE = 80
WATCHLIST_SCORE = 35  # v37+: rawConfidence = (score - 35) / 65, stable across the window
MIN_CONFIDENCE = 0.7
MAX_SPREAD = 0.06
MIN_LIQUIDITY = 750
MIN_TTR_H = 2
MAX_ENTRY = 0.95

NOW = datetime.now(timezone.utc)


def mean_se(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return (float("nan"), float("nan"))
    m = sum(xs) / n
    if n < 2:
        return (m, float("nan"))
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return (m, math.sqrt(var / n))


def clustered_ci(pairs: list[tuple[str, float]], reps: int = 1000, seed: int = 7) -> tuple[float, float]:
    """Bootstrap the mean by resampling MARKET clusters: one market is polled many
    times and copied for several wallets, so the rows are not independent."""
    if not pairs:
        return (float("nan"), float("nan"))
    by: dict[str, list[float]] = defaultdict(list)
    for k, v in pairs:
        by[k].append(v)
    keys = list(by)
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        pool: list[float] = []
        for _ in range(len(keys)):
            pool.extend(by[keys[rng.randrange(len(keys))]])
        means.append(sum(pool) / len(pool))
    means.sort()
    return (means[int(0.025 * reps)], means[int(0.975 * reps)])


def load() -> tuple[list[dict], dict[str, int]]:
    cands: list[dict] = []
    resolves: dict[str, int] = {}
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
                resolves[f"{r.get('marketId')}|{r.get('outcome')}"] = int(r.get("value") or 0)
    return cands, resolves


def pnl(entry: float, value: int, maker: bool = False) -> float:
    """Counterfactual PnL for a $10 clip bought at `entry`, settled at `value`."""
    e = entry - MAKER_IMPROVEMENT if maker else entry
    if e <= 0:
        return 0.0
    return ((value - e) / e) * STAKE


def raw_confidence(copy_score: float) -> float:
    """v37: rawConfidence = (copyScore - watchlistScore) / (100 - watchlistScore).
    watchlistScore is 35 for every RuleSet in the shadow window (v43 -> v61), so the
    real confidence is recoverable from the recorded copyScore. It has to be: the
    drift shadow stores `result.confidence`, which is 0 BY CONSTRUCTION on every skip
    path (src/lib/scoring/trade.ts:46) - so its `confidence` field is structurally
    zero and the gate must be read off rawConfidence."""
    return round(((copy_score - WATCHLIST_SCORE) / (100 - WATCHLIST_SCORE)) * 100) / 100


def passes_other_gates(c: dict) -> bool:
    # minConfidence 0.7 <=> copyScore >= 80.5, so the score and confidence gates are
    # the same constraint on this population; minCopyScore is 80.
    return (
        raw_confidence(float(c.get("copyScore") or 0)) >= MIN_CONFIDENCE
        and float(c.get("spread") if c.get("spread") is not None else 9) <= MAX_SPREAD
        and float(c.get("liquidity") or 0) >= MIN_LIQUIDITY
        and float(c.get("ttrHours") or 0) >= MIN_TTR_H
        and float(c.get("currentPrice") or 0) <= MAX_ENTRY
    )


def lane_eligible(c: dict) -> bool:
    """Short-TTR lane (shortTtrMaxDrift 0.05, score >= 35, ttr <= 72h): drift up to 5c
    for short-dated signals is already admitted today, so those rows are not marginal
    to a flat-tolerance change."""
    return (
        float(c.get("ttrHours") or 1e9) <= 72
        and float(c.get("copyScore") or 0) >= 35
        and float(c.get("drift") or 1e9) <= 0.05
    )


def main() -> None:
    cands, resolves = load()
    out: dict = {"generatedAt": NOW.isoformat()}

    # 1 ---------------------------------------------------------- validation
    published = json.loads(SUMMARY.read_text())
    marked = wins = 0
    pnl_all = pnl_ex = 0.0
    marked_ex = 0
    cohort_cut = (NOW - timedelta(days=7)).timestamp() * 1000
    coh_pnl = coh_n = 0
    for c in cands:
        v = resolves.get(f"{c.get('marketId')}|{c.get('outcome')}")
        if v is None:
            continue
        marked += 1
        if v > 0:
            wins += 1
        e = float(c.get("currentPrice") or 0)
        p = pnl(e, v)
        pnl_all += p
        if e >= DUST_MIN:
            pnl_ex += p
            marked_ex += 1
            ts = datetime.fromisoformat(str(c["ts"]).replace("Z", "+00:00")).timestamp() * 1000
            if ts >= cohort_cut:
                coh_pnl += p
                coh_n += 1
    repro = {
        "candidates": len(cands),
        "marked": marked,
        "wins": wins,
        "winRate": round(wins / marked, 4) if marked else None,
        "wouldHavePnl": round(pnl_all, 2),
        "avgPnlPerTrade": round(pnl_all / marked, 2) if marked else None,
        "avgPnlPerTradeExDust": round(pnl_ex / marked_ex, 2) if marked_ex else None,
        "dustExcluded": marked - marked_ex,
        "cohort7d": round(coh_pnl / coh_n, 2) if coh_n else None,
        "cohort7dMarked": coh_n,
    }
    out["reproduction"] = repro
    print("== 1. instrument reproduction (mine vs published data/drift-shadow-summary.json)")
    for k, mine in repro.items():
        pub = published.get(k if k != "cohort7d" else "avgPnlPerTradeExDustLast7dCohort")
        print(f"   {k:<22} mine={mine!s:<11} published={pub}")
    print(f"   decayBar published     {json.dumps(published.get('decayBar'))[:280]}")

    # 2 ------------------------------------------------- distinct signals + gating
    signals: dict[tuple, dict] = {}
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for c in cands:
        k = (c.get("marketId"), c.get("outcome"), c.get("wallet"))
        by_key[k].append(c)
        cur = signals.get(k)
        if cur is None or str(c["ts"]) < str(cur["ts"]):
            signals[k] = c
    for k in by_key:
        by_key[k].sort(key=lambda c: str(c["ts"]))
    settled = {
        k: c for k, c in signals.items()
        if resolves.get(f"{c.get('marketId')}|{c.get('outcome')}") is not None
    }
    screened = {k: c for k, c in settled.items() if passes_other_gates(c)}
    out["signals"] = {"poll_rows": len(cands), "distinct": len(signals),
                      "settled": len(settled), "screened": len(screened)}
    print(f"\n== 2. population\n   poll rows {len(cands)} -> distinct signals {len(signals)} "
          f"-> settled {len(settled)} -> clearing the non-drift gates {len(screened)}")
    for label, src in (("all settled signals", settled), ("screened", screened)):
        exs = [pnl(float(c["currentPrice"]), resolves[f"{c.get('marketId')}|{c.get('outcome')}"])
               for c in src.values() if float(c["currentPrice"]) >= DUST_MIN]
        m, se = mean_se(exs)
        pairs = [(str(c["marketId"]),
                  pnl(float(c["currentPrice"]), resolves[f"{c.get('marketId')}|{c.get('outcome')}"]))
                 for c in src.values() if float(c["currentPrice"]) >= DUST_MIN]
        lo, hi = clustered_ci(pairs)
        mk = [pnl(float(c["currentPrice"]), resolves[f"{c.get('marketId')}|{c.get('outcome')}"], maker=True)
              for c in src.values() if float(c["currentPrice"]) >= DUST_MIN]
        mm, _ = mean_se(mk)
        print(f"   {label:<20} first-decision ex-dust n={len(exs):<5} mean=${m:+.2f} (se {se:.2f}; "
              f"market-clustered 95% CI [{lo:+.2f}, {hi:+.2f}]) | at the maker fill ${mm:+.2f}")

    # 2b ---------------------------------------- where the counterfactual's money is
    print("\n== 2b. settled drift-blocked signals by copyScore band (first-decision ex-dust)")
    bands = [(0, 40), (40, 60), (60, 80), (80, 101)]
    band_rows = {}
    for lo_b, hi_b in bands:
        sel = [k for k, c in settled.items()
               if lo_b <= float(c.get("copyScore") or 0) < hi_b]
        vals = [pnl(float(settled[k]["currentPrice"]),
                    resolves[f"{settled[k].get('marketId')}|{settled[k].get('outcome')}"])
                for k in sel if float(settled[k]["currentPrice"]) >= DUST_MIN]
        m_b, se_b = mean_se(vals)
        w_b = [k for k in sel]
        band_rows[f"{lo_b}-{hi_b}"] = {"n": len(w_b), "n_ex": len(vals), "mean": round(m_b, 2),
                                       "se": round(se_b, 2)}
        print(f"   score {lo_b:>2}-{hi_b - 1:<3}  n={len(w_b):<5} dust-ex {len(vals):<5} "
              f"mean=${m_b:+.2f} (se {se_b:.2f})")
    out["score_bands"] = band_rows

    # 3 ------------------------------------ per-decision-day, distinct-signal basis
    day: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for k, c in settled.items():
        v = resolves[f"{c.get('marketId')}|{c.get('outcome')}"]
        e = float(c["currentPrice"])
        if e < DUST_MIN:
            continue
        day[str(c["ts"])[:10]].append((str(c["marketId"]), pnl(e, v)))
    hist: dict[str, float] = {}
    for r in SERIES.read_text().splitlines():
        if r.strip():
            d = json.loads(r)
            hist[d["day"]] = d["avgPnlPerTradeExDust"]
    print("\n== 3. decision-day ex-dust mean per distinct signal (today's marks) vs the "
          "published series (a daily sample of the CUMULATIVE mean)")
    days = sorted(day)[-14:]
    for d in days:
        pairs = day[d]
        m, se = mean_se([p for _, p in pairs])
        flag = "<=bar" if m <= BAR_USD else "above"
        print(f"   {d}  n={len(pairs):<5} mean=${m:+.2f} (se {se:.2f}) {flag:<6} "
              f"[published cumulative that day ${hist.get(d)}]")
    streak = 0
    for d in reversed(days):
        m, _ = mean_se([p for _, p in day[d]])
        if m <= BAR_USD:
            streak += 1
        else:
            break
    out["recut_day_streak"] = streak
    print(f"   consecutive per-signal days at/below the bar: {streak} of {DAYS_REQUIRED}")

    # 4 ------------------------------------------------------ tolerance options
    def admission(tol_flat: float, ls_pct: float | None = None,
                  ls_max_price: float = 0.20, ls_cap: float = 0.02,
                  use: dict | None = None) -> dict:
        use = screened if use is None else use
        rows: list[tuple[str, float, bool, bool]] = []  # market, pnl, is_marginal, lane_eligible
        for k, first in use.items():
            v = resolves[f"{first.get('marketId')}|{first.get('outcome')}"]
            row = None
            for c in by_key.get(k, ()):
                e = float(c.get("currentPrice") or 0)
                tol = tol_flat
                if ls_pct and e < ls_max_price:
                    tol = min(ls_cap, max(tol_flat, ls_pct * e))
                if float(c.get("drift") or 1e9) <= tol:
                    row = c  # rows are ts-ascending: the first admitted poll is the fill
                    break
            if row is None:
                continue
            e = float(row["currentPrice"])
            if e < DUST_MIN:
                continue
            if not passes_other_gates(row):
                continue
            rows.append((str(first["marketId"]), pnl(e, v), float(first.get("drift") or 0) > 0.004,
                         lane_eligible(first)))
        adm = [p for _, p, _, _ in rows]
        marg = [(m, p) for m, p, is_m, _ in rows if is_m]
        am, ase = mean_se(adm)
        mm, mse = mean_se([p for _, p in marg])
        lo, hi = clustered_ci(marg)
        nonlane = [p for _, p, is_m, is_lane in rows if is_m and not is_lane]
        nm, nse = mean_se(nonlane)
        return {"admitted_n": len(adm), "admitted_mean": round(am, 2), "admitted_se": round(ase, 2),
                "marginal_n": len(marg), "marginal_markets": len({m for m, _ in marg}),
                "marginal_mean": round(mm, 2), "marginal_se": round(mse, 2),
                "marginal_ci": [round(lo, 2), round(hi, 2)],
                "marginal_total": round(sum(p for _, p in marg), 2),
                "marginal_nonlane_n": len(nonlane),
                "marginal_nonlane_mean": round(nm, 2), "marginal_nonlane_se": round(nse, 2)}

    print(f"\n== 4. tolerance options on the SCREENED population (n={len(screened)} settled signals; "
          f"dust-excluded; $10 clip)")
    print("   tol       admitted n/mean$ | MARGINAL newly admitted: n markets mean$ se CI total$")
    options = {}
    for tol in (0.004, 0.005, 0.006, 0.008, 0.010, 0.015, 0.020, 0.030, 0.050):
        r = admission(tol)
        options[f"flat_{tol}"] = r
        print(f"   {tol:<9} {r['admitted_n']:<9}{r['admitted_mean']:>+7.2f}  | "
              f"{r['marginal_n']:<5} {r['marginal_markets']:<7} {r['marginal_mean']:>+7.2f} "
              f"{r['marginal_se']:>5.2f} [{r['marginal_ci'][0]:+.2f},{r['marginal_ci'][1]:+.2f}] "
              f"{r['marginal_total']:>+9.2f}")
    for p_ in (0.10, 0.12, 0.16, 0.20):
        r = admission(0.004, ls_pct=p_)
        options[f"longshot_{p_}"] = r
        print(f"   ls{p_:<7} {r['admitted_n']:<9}{r['admitted_mean']:>+7.2f}  | "
              f"{r['marginal_n']:<5} {r['marginal_markets']:<7} {r['marginal_mean']:>+7.2f} "
              f"{r['marginal_se']:>5.2f} [{r['marginal_ci'][0]:+.2f},{r['marginal_ci'][1]:+.2f}] "
              f"{r['marginal_total']:>+9.2f}")
    out["options"] = options

    # 5 ------------------------------------------------------- the incumbent book
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT entryPrice, simulatedPositionSize, realizedPnl,
               COALESCE(resolvedAt, closedAt) AS settled_ms
        FROM PaperTrade
        WHERE botId='BANKROLL_200' AND status IN ('resolved','closed')
          AND realizedPnl IS NOT NULL AND simulatedPositionSize > 0
          AND COALESCE(resolvedAt, closedAt) IS NOT NULL
        """
    ).fetchall()
    first_cand = min(str(c["ts"]) for c in cands)[:10]

    def book_read(since_iso: str | None) -> dict:
        per10_ex, per_trade = [], []
        for r in rows:
            st = datetime.fromtimestamp(r["settled_ms"] / 1000, timezone.utc).isoformat()
            if since_iso and st < since_iso:
                continue
            x = r["realizedPnl"] / r["simulatedPositionSize"] * 10.0
            per_trade.append(r["realizedPnl"])
            if r["entryPrice"] >= DUST_MIN:
                per10_ex.append(x)
        m10, se10 = mean_se(per10_ex)
        mt, _ = mean_se(per_trade)
        return {"n": len(per_trade), "n_ex": len(per10_ex), "per10_ex_mean": round(m10, 2),
                "per10_ex_se": round(se10, 2), "per_trade_mean": round(mt, 2)}

    inc = {"since_shadow_start": book_read(first_cand + "T00:00:00+00:00"), "all": book_read(None)}
    out["incumbent"] = inc
    print("\n== 5. incumbent C-200 book (BANKROLL_200, per-$10 staked, dust-excluded)")
    print(f"   settled since the shadow started ({first_cand}): {json.dumps(inc['since_shadow_start'])}")
    print(f"   all time: {json.dumps(inc['all'])}")
    con.close()

    (ROOT / "data" / "drift-relaxation-read.json").write_text(json.dumps(out, indent=2))
    print("\nwrote data/drift-relaxation-read.json")


if __name__ == "__main__":
    main()
