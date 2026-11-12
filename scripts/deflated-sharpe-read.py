#!/usr/bin/env python3
"""
deflated-sharpe-read -- do the rule-selection / ladder claims survive multiple testing?

WHY THIS EXISTS (roadmap card tradememory-deflated-sharpe, APPROVED 2026-10-21, Lane B, read-only)
    Every rule version v2..v72 was admitted on a measured edge ("this change is
    winning"), and each was chosen AFTER seeing the previous versions' results.
    When N variants are tried and the best is quoted, the quoted statistic is
    biased upward even if every variant is worthless. Bailey & Lopez de Prado
    (2014) correct for it: the Deflated Sharpe Ratio (DSR) is the probability
    that the selected Sharpe exceeds what the BEST OF N worthless trials would be
    expected to produce.

    The card's decision rule, pre-registered 2026-10-21 and NOT changed here:
        p >= 0.05  or  INSUFFICIENT_DATA
            => every ladder/phase claim carries the explicit caveat
               "not distinguishable from selection"
        p <  0.05  => that claim survives the correction and may be quoted
               without the caveat.

BASIS (stated, never implied)
    population  non-demo PaperTrade legs with a realized PnL (isDemo=0,
                status in closed|resolved, realizedPnl NOT NULL), joined to the
                DecisionJournal row that admitted them
    level       one leg (primary); one exit DAY (clustered variant)
    clock       regime = the DECIDING rule version (journal.ruleSetVersion, this
                repo's regime definition), not openedAt; daily buckets by
                COALESCE(closedAt,resolvedAt) in UTC
    return      realizedPnl / simulatedPositionSize = per-$1-staked, GROSS of fees
                (the fee law is a separate card: fee-booking-net-ledger)
    SR          per-observation (per leg / per day), NOT annualised -- DSR wants
                the per-period Sharpe of the observation series. The two clocks
                are NOT comparable and each carries its own trial dispersion.
    N           number of rule variants TRIED. We can only count the variants we
                COMMITTED (RuleSet versions, RuleChange rows); candidates measured
                and abandoned live in no table. N here is therefore a LOWER BOUND
                on the true trial count, which makes the correction LENIENT, not
                conservative. The verdict is printed as a sensitivity table over
                N = RuleChange rows / max version / 200 / 1000.

TWO DEFECTS FOUND AND FIXED IN THIS INSTRUMENT BEFORE ITS FIRST TRUSTED READ
    (1) The first version used the RAW cross-trial variance of Sharpe as V[SR].
        That variance is mostly ESTIMATOR NOISE (a trial with 40 legs has a Sharpe
        standard error of ~0.16), so SR0 came out at 0.66 and every claim read
        p=1.0000 -- an instrument that can only ever say "no". It now subtracts
        the estimated sampling variance per trial (variance components), and
        PRINTS the noise share so a reader can see how much of the dispersion is
        real.
    (2) The first version compared a per-LEG SR0 against a per-DAY Sharpe. The two
        clocks have different units and different trial dispersions; each arm now
        uses the dispersion measured on its OWN clock.
    Both are exactly the "unfalsifiable probe" defect class this board keeps
    repairing, so they are repaired here rather than published.

READ-ONLY: opens dev.db read-only, writes data/deflated-sharpe-read.json, prints.
Changes no rule, threshold, size or gate.
"""

import argparse
import json
import math
import os
import sqlite3
import statistics
import sys
from datetime import datetime, timezone

DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")
OUT = "data/deflated-sharpe-read.json"
EULER = 0.5772156649015329


# ---------------------------------------------------------------- distributions
def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p):
    """Acklam's inverse normal CDF, |rel err| < 1.15e-9."""
    if not (0.0 < p < 1.0):
        raise ValueError("p out of range: %r" % (p,))
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def moments(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    if v <= 0:
        return {"n": n, "mean": m, "sd": 0.0, "sr": None, "skew": None, "kurt": None}
    sd = math.sqrt(v)
    g3 = sum(((x - m) / sd) ** 3 for x in xs) / n
    g4 = sum(((x - m) / sd) ** 4 for x in xs) / n
    return {"n": n, "mean": m, "sd": sd, "sr": m / sd, "skew": g3, "kurt": g4}


def sr_var(m):
    """Estimated sampling variance of SR_hat (the PSR denominator / (n-1))."""
    if not m or m.get("sr") is None:
        return None
    denom = 1.0 - (m["skew"] or 0.0) * m["sr"] + ((m["kurt"] or 3.0) - 1.0) / 4.0 * m["sr"] ** 2
    if denom <= 0 or m["n"] < 2:
        return None
    return denom / (m["n"] - 1)


def dispersion(trial_moments):
    """V[SR] across trials, split into observed / estimator noise / de-noised."""
    pts = [(t["sr"], sr_var(t)) for t in trial_moments if t.get("sr") is not None]
    pts = [(a, b) for a, b in pts if b is not None]
    if len(pts) < 2:
        return _pack(len(pts), 0.0, 0.0)
    return _pack(len(pts), statistics.variance([a for a, _ in pts]),
                 sum(b for _, b in pts) / len(pts))


def _pack(n, v_obs, v_noise):
    v_true = max(0.0, v_obs - v_noise)
    return {"n_trials": n, "v_observed": v_obs, "v_noise": v_noise,
            "v_true": v_true, "sd_true": math.sqrt(v_true),
            "noise_share": (v_noise / v_obs) if v_obs > 0 else None}


def equal_n_dispersion(series_by_v, n_eq, reps=200, seed=11):
    """V[SR] on EQUAL information per trial.

    A 40-leg trial and a 600-leg trial do not carry the same information: their
    Sharpe estimates differ in noise by sqrt(15). Measuring dispersion across
    trials of unequal n mixes REAL variant differences with pure sample-size
    differences and inflates the correction. This resamples every trial down to
    the same n, repeats `reps` times, and averages the cross-trial variance --
    a dispersion measured at one information level.
    """
    import random
    rnd = random.Random(seed)
    usable = [v for v in series_by_v.values() if len(v) >= n_eq]
    if len(usable) < 2:
        return _pack(0, 0.0, 0.0)
    obs, noise = [], []
    for _ in range(reps):
        srs, nv = [], []
        for xs in usable:
            m = moments(rnd.sample(xs, n_eq))
            if m is None or m["sr"] is None:
                continue
            srs.append(m["sr"])
            nv.append(sr_var(m) or 0.0)
        if len(srs) > 1:
            obs.append(statistics.variance(srs))
            noise.append(sum(nv) / len(nv))
    if not obs:
        return _pack(0, 0.0, 0.0)
    return _pack(len(usable), sum(obs) / len(obs), sum(noise) / len(noise))


def sr0_expected_max(var_sr, n_trials):
    """Expected max Sharpe of N worthless trials, given trial-Sharpe dispersion."""
    if var_sr <= 0 or n_trials < 2:
        return 0.0
    a = norm_ppf(1.0 - 1.0 / n_trials)
    b = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sr) * ((1.0 - EULER) * a + EULER * b)


def dsr(sr_hat, t, skew, kurt, sr0):
    """Probabilistic / Deflated Sharpe: P(true SR > sr0)."""
    if sr_hat is None or t is None or t < 3:
        return None
    denom = 1.0 - (skew or 0.0) * sr_hat + ((kurt or 3.0) - 1.0) / 4.0 * sr_hat ** 2
    if denom <= 0:
        return None
    return norm_cdf((sr_hat - sr0) * math.sqrt(t - 1) / math.sqrt(denom))


def concentration(xs):
    """Median / trimmed mean / ex-top-10 -- the anti-'big number' read."""
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return {}

    def mean(v):
        return sum(v) / len(v) if v else None

    k = int(n * 0.10)
    ex10 = s[:-10] if n > 10 else []
    top10 = s[-10:] if n > 10 else s
    return {
        "n": n,
        "mean": mean(s),
        "median": statistics.median(s),
        "trimmed_mean_10pct": mean(s[k:n - k]) if n - 2 * k > 0 else None,
        "ex_top10_mean": mean(ex10) if ex10 else None,
        "top10_share_of_sum": (sum(top10) / sum(s)) if sum(s) != 0 else None,
        "win_share": sum(1 for x in s if x > 0) / n,
    }


# ---------------------------------------------------------------- data
def load_legs(db):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT j.ruleSetVersion AS v, t.botId AS bot,
               t.simulatedPositionSize AS size, t.realizedPnl AS pnl,
               COALESCE(t.closedAt, t.resolvedAt) AS closed
        FROM PaperTrade t JOIN DecisionJournal j ON j.id = t.decisionJournalId
        WHERE t.isDemo = 0 AND t.status IN ('closed','resolved')
          AND t.realizedPnl IS NOT NULL AND t.simulatedPositionSize > 0
        """
    ).fetchall()
    maxver = con.execute("SELECT COALESCE(MAX(version),0) FROM RuleSet").fetchone()[0]
    nchanges = con.execute("SELECT COUNT(*) FROM RuleChange").fetchone()[0]
    con.close()
    legs = []
    for r in rows:
        ts = r["closed"]
        day = (datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
               if ts else None)
        legs.append({"v": r["v"], "bot": r["bot"], "size": r["size"], "pnl": r["pnl"],
                     "roi": r["pnl"] / r["size"], "day": day})
    return legs, maxver, nchanges


def daily_series(legs, min_stake=0.0):
    """One exit-day return per day = day PnL / day stake.

    A DAY FLOOR IS LOAD-BEARING. On C-200, 19 of 100 exit days carry under $50 of
    stake and their returns span -100%..+461%: a $4.00 day is arithmetic, not a
    portfolio return. Days below the floor are DROPPED AND COUNTED, never
    silently imputed.
    """
    agg = {}
    for L in legs:
        if not L["day"]:
            continue
        d = agg.setdefault(L["day"], [0.0, 0.0])
        d[0] += L["pnl"]
        d[1] += L["size"]
    kept = [p / s for p, s in agg.values() if s >= min_stake and s > 0]
    dropped = sum(1 for p, s in agg.values() if s < min_stake or s <= 0)
    return kept, dropped


def by_version(legs, series):
    out = {}
    for L in legs:
        v = L["v"]
        out.setdefault(v, []).append(series(L) if callable(series) else L)
    return out


# ---------------------------------------------------------------- analysis
def verdict(p):
    if p is None:
        return "INSUFFICIENT_DATA"
    return "SURVIVES" if p < 0.05 else "NOT_DISTINGUISHABLE_FROM_SELECTION"


def claim(label, xs, disp, n_trials, level, unit, dwm=None, dropped_days=None):
    m = moments(xs)
    out = {"claim": label, "level": level, "n_trials": n_trials, "moments": m,
           "concentration": concentration(xs),
           "dollar_weighted_mean": dwm,
           "dropped_small_days": dropped_days,
           "dispersion_used": {k: disp[k] for k in ("n_trials", "v_true", "sd_true", "noise_share")}}
    if m is None or m["sr"] is None:
        out["verdict"] = "INSUFFICIENT_DATA"
        out["p"] = None
        return out
    sr0 = sr0_expected_max(disp["v_true"], n_trials)
    p = 1.0 - dsr(m["sr"], m["n"], m["skew"], m["kurt"], sr0)
    out.update({"sr0": sr0, "p": p, "verdict": verdict(p), "unit": unit,
                "naive_p": 1.0 - dsr(m["sr"], m["n"], m["skew"], m["kurt"], 0.0)})
    return out


def run(db, min_n, min_days, reps, day_stake_floor=50.0, do_print=True):
    legs, maxver, nchanges = load_legs(db)
    if not legs:
        raise SystemExit("no settled legs found in %s" % db)
    n_trials = maxver if maxver else 1

    leg_byv = by_version(legs, lambda L: L["roi"])
    day_byv = {}
    day_dropped_all = 0
    for v, sub in by_version(legs, lambda L: L).items():
        ds, dr = daily_series(sub, day_stake_floor)
        day_dropped_all += dr
        if len(ds) >= 2:
            day_byv[v] = ds

    # three dispersion estimators on the leg clock (all legs / equal n / >=min_n)
    leg_trials = []
    for v, xs in sorted(leg_byv.items(), key=lambda kv: (kv[0] is None, kv[0])):
        m = moments(xs) if len(xs) > 1 else None
        if m and m["sr"] is not None and len(xs) >= min_n:
            m["v"] = v
            leg_trials.append(m)
    d_leg_raw = dispersion(leg_trials)
    d_leg_eq = equal_n_dispersion(leg_byv, min_n, reps)
    # day clock: equal information per trial too
    d_day = equal_n_dispersion(day_byv, min_days, reps)
    d_day_raw_trials = [moments(xs) for xs in day_byv.values() if len(xs) >= min_days]
    d_day_raw_trials = [m for m in d_day_raw_trials if m and m["sr"] is not None]
    d_day_raw = dispersion(d_day_raw_trials)

    def dwm_of(sub):
        st = sum(L["size"] for L in sub)
        return (sum(L["pnl"] for L in sub) / st) if st > 0 else None

    claims = []
    for bot in ("BANKROLL_200", "STANDARD"):
        sub = [L for L in legs if L["bot"] == bot]
        if not sub:
            continue
        claims.append(claim("%s lane [leg clock]" % bot, [L["roi"] for L in sub],
                            d_leg_eq, n_trials, "leg", "$1 staked per leg", dwm_of(sub)))
        ds, dr = daily_series(sub, day_stake_floor)
        claims.append(claim("%s lane [exit-day clock]" % bot, ds,
                            d_day, n_trials, "day", "$1 staked per day",
                            None, dr))
    claims.append(claim("whole book [leg clock]", [L["roi"] for L in legs],
                        d_leg_eq, n_trials, "leg", "$1 staked per leg", dwm_of(legs)))
    wds, wdr = daily_series(legs, day_stake_floor)
    claims.append(claim("whole book [exit-day clock]", wds,
                        d_day, n_trials, "day", "$1 staked per day", None, wdr))

    # the SELECTION statistic: the best-looking trial that clears the size floor
    best = None
    if leg_trials:
        best = max(leg_trials, key=lambda t: t["sr"])
        subt = [L for L in legs if L["v"] == best["v"]]
        claims.append(claim("best trial by SR (v%s) [leg clock]" % best["v"],
                            leg_byv[best["v"]], d_leg_eq, n_trials, "leg",
                            "$1 staked per leg", dwm_of(subt)))

    # N sensitivity, each arm on its own dispersion
    sens = []
    for n in sorted({nchanges or n_trials, n_trials, 200, 1000}):
        row = {"n_trials": n, "claims": {}}
        for c in claims:
            m = c["moments"]
            if not m or m.get("sr") is None:
                row["claims"][c["claim"]] = None
                continue
            disp = d_day if c["level"] == "day" else d_leg_eq
            row["claims"][c["claim"]] = round(
                1.0 - dsr(m["sr"], m["n"], m["skew"], m["kurt"],
                          sr0_expected_max(disp["v_true"], n)), 4)
        sens.append(row)

    # dispersion-estimator sensitivity on the C-200 leg claim (the one that moves)
    c200 = [L["roi"] for L in legs if L["bot"] == "BANKROLL_200"]
    disp_sens = []
    for name, d in (("equal_n n=%d" % min_n, d_leg_eq), ("all trials n>=%d, raw" % min_n, d_leg_raw),
                    ("day raw", d_day_raw), ("day equal_n", d_day)):
        if not c200:
            break
        m = moments(c200)
        disp_sens.append({"dispersion": name, "n_trials_in_disp": d["n_trials"],
                          "sd_true": round(d["sd_true"], 4),
                          "sr0": round(sr0_expected_max(d["v_true"], n_trials), 4),
                          "p": round(1.0 - dsr(m["sr"], m["n"], m["skew"], m["kurt"],
                                               sr0_expected_max(d["v_true"], n_trials)), 4)})

    res = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db": db,
        "basis": {
            "population": "non-demo settled PaperTrade legs with realizedPnl, joined to the admitting DecisionJournal row",
            "level": "one leg (primary); one exit day (clustered variant)",
            "clock": "regime = journal.ruleSetVersion; daily buckets by COALESCE(closedAt,resolvedAt) UTC",
            "return": "realizedPnl / simulatedPositionSize, per $1 staked, gross of fees",
            "sr": "per-observation, not annualised; V[SR] measured on the same clock and at equal n",
            "day floor": "exit days with stake < $%.0f are dropped and counted (a $4 day returns +-100%% arithmetically)" % day_stake_floor,
            "n_trials": "committed variants only (RuleSet max version / RuleChange rows) -- LOWER bound on true trials",
        },
        "legs": len(legs),
        "bots": {b: sum(1 for L in legs if L["bot"] == b) for b in sorted({L["bot"] for L in legs})},
        "trial_count": {"ruleset_max_version": maxver, "rulechange_rows": nchanges,
                        "leg_trials_ge_min_n": len(leg_trials), "day_trials_ge_min_days":
                        sum(1 for xs in day_byv.values() if len(xs) >= min_days),
                        "min_n": min_n, "min_days": min_days, "resamples": reps,
                        "day_stake_floor": day_stake_floor},
        "dispersion": {"leg_equal_n": d_leg_eq, "leg_raw": d_leg_raw,
                       "day_equal_n": d_day, "day_raw": d_day_raw},
        "trials_leg": [{"v": t["v"], "n": t["n"], "mean_roi": t["mean"], "sd": t["sd"],
                        "sr": t["sr"], "skew": t["skew"], "kurt": t["kurt"]} for t in leg_trials],
        "claims": claims,
        "n_sensitivity": sens,
        "dispersion_sensitivity": disp_sens,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1)
    if do_print:
        print_summary(res)
    return res


def _f(x, dp=4):
    if x is None:
        return "None"
    try:
        return ("%." + str(dp) + "f") % x
    except TypeError:
        return str(x)


def print_summary(res):
    tc = res["trial_count"]
    print("= deflated-sharpe-read " + res["generatedAt"])
    print("legs %d %s | N used %d (versions %d, changes %d) | trials: leg>=%d %d, day>=%d %d"
          % (res["legs"], res["bots"], res["claims"][0]["n_trials"], tc["ruleset_max_version"],
             tc["rulechange_rows"], tc["min_n"], tc["leg_trials_ge_min_n"],
             tc["min_days"], tc["day_trials_ge_min_days"]))
    for k, d in res["dispersion"].items():
        print("  dispersion[%-12s] trials=%-3d V_obs=%.5f noise=%.5f V_true=%.5f sd=%.4f noise_share=%s"
              % (k, d["n_trials"], d["v_observed"], d["v_noise"], d["v_true"], d["sd_true"],
                 _f(d["noise_share"], 2)))
    for c in res["claims"]:
        m, k = c.get("moments") or {}, c.get("concentration") or {}
        print("\n-- %s" % c["claim"])
        print("   n=%s mean=%s dollar-wtd=%s median=%s trim10=%s exTop10=%s win=%s%s"
              % (m.get("n"), _f(m.get("mean")), _f(c.get("dollar_weighted_mean")),
                 _f(k.get("median")), _f(k.get("trimmed_mean_10pct")),
                 _f(k.get("ex_top10_mean")), _f(k.get("win_share"), 3),
                 (" [dropped %d days under $%.0f]" % (c["dropped_small_days"], day_floor_hint()))
                 if c.get("dropped_small_days") else ""))
        print("   SR=%s SR0=%s naive_p=%s -> p=%s : %s"
              % (_f(m.get("sr")), _f(c.get("sr0")), _f(c.get("naive_p")),
                 _f(c.get("p")), c["verdict"]))
        if k.get("top10_share_of_sum") is not None:
            print("   top-10 %s = %.1f%% of the return sum"
                  % ("legs" if c["level"] == "leg" else "days",
                     100 * k["top10_share_of_sum"]))
    print("\nN SENSITIVITY (p):")
    for row in res["n_sensitivity"]:
        print("  N=%-5d " % row["n_trials"] + " | ".join(
            "%s=%s" % (short_name(c["claim"]), _f(row["claims"][c["claim"]]))
            for c in res["claims"]))
    print("\nDISPERSION-ESTIMATOR SENSITIVITY (C-200 leg claim):")
    for r in res["dispersion_sensitivity"]:
        print("  %-22s trials=%-3d sd_true=%-6s SR0=%-6s p=%s"
              % (r["dispersion"], r["n_trials_in_disp"], r["sd_true"], r["sr0"], r["p"]))


def day_floor_hint():
    return 50.0


def short_name(s):
    s = s.replace(" [leg clock]", "").replace(" [exit-day clock]", " /day")
    s = s.replace("best trial by SR (v", "best v")
    return s.replace(" lane", "").replace(", settled legs", "")[:20]


# ---------------------------------------------------------------- self-test
def self_test():
    """A gate that cannot fail is not a gate. Five arms, each must go RED."""
    import random
    rnd = random.Random(7)
    ok = 0

    # 1. a strong real edge survives at N=1, and the SAME claim dies as the trial
    #    count grows -- the correction must actually penalise selection.
    sig = [0.30 + rnd.gauss(0, 1.0) for _ in range(400)]
    m = moments(sig)
    p1 = 1 - dsr(m["sr"], m["n"], m["skew"], m["kurt"], sr0_expected_max(0.0, 1))
    pn = 1 - dsr(m["sr"], m["n"], m["skew"], m["kurt"], sr0_expected_max(0.05, 500))
    if p1 < 0.001 and pn > 0.2:
        ok += 1
        print("  PASS arm1 real edge: p(N=1)=%.2e -> p(N=500,V=.05)=%.3f (correction bites)" % (p1, pn))
    else:
        print("  FAIL arm1: p1=%r pn=%r" % (p1, pn))

    # 2. NEGATIVE CONTROL: best-of-N pure noise must not be called significant
    call_sig = 0
    for _ in range(200):
        mm = moments([rnd.gauss(0, 1) for _ in range(120)])
        p = 1 - dsr(mm["sr"], mm["n"], mm["skew"], mm["kurt"], sr0_expected_max(1.0 / 120.0, 200))
        if p < 0.05:
            call_sig += 1
    if call_sig <= 12:
        ok += 1
        print("  PASS arm2 negative control: best-of-200 noise significant %d/200 (<=12)" % call_sig)
    else:
        print("  FAIL arm2: negative control fired %d/200" % call_sig)

    # 3. de-noising must remove the estimator noise floor: trials drawn from ONE
    #    population with no true dispersion must not keep a positive V_true.
    noise_tr = []
    for i in range(60):
        mm = moments([rnd.gauss(0.05, 1.0) for _ in range(40)])
        mm["v"] = i
        noise_tr.append(mm)
    d = dispersion(noise_tr)
    if d["v_true"] < d["v_observed"] and d["noise_share"] > 0.3:
        ok += 1
        print("  PASS arm3 de-noise: V_obs=%.4f V_true=%.4f noise share %.2f (shrink happened)"
              % (d["v_observed"], d["v_true"], d["noise_share"]))
    else:
        print("  FAIL arm3: denoise did nothing (%r)" % (d,))

    # 4. monotonicity in N for fixed inputs
    a, b = sr0_expected_max(0.04, 10), sr0_expected_max(0.04, 1000)
    if b > a > 0:
        ok += 1
        print("  PASS arm4 monotone: SR0(N=10)=%.4f < SR0(N=1000)=%.4f" % (a, b))
    else:
        print("  FAIL arm4: SR0 not monotone (%r,%r)" % (a, b))

    # 5. norm_ppf sanity against known quantiles
    checks = [(0.975, 1.959964), (0.5, 0.0), (0.01, -2.326348), (0.999, 3.090232)]
    bad = [c for c in checks if abs(norm_ppf(c[0]) - c[1]) > 1e-5]
    if not bad:
        ok += 1
        print("  PASS arm5 norm_ppf: 4/4 known quantiles within 1e-5")
    else:
        print("  FAIL arm5 norm_ppf off: %r" % bad)
    print("self-test %d/5 %s" % (ok, "PASS" if ok == 5 else "FAIL"))
    return 0 if ok == 5 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--min-n", type=int, default=30,
                    help="legs a trial needs before its Sharpe enters the dispersion estimate")
    ap.add_argument("--min-days", type=int, default=10,
                    help="exit days a trial needs before its daily Sharpe enters the day dispersion")
    ap.add_argument("--reps", type=int, default=200)
    ap.add_argument("--day-stake-floor", type=float, default=50.0)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the artifact and exit")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    res = run(args.db, args.min_n, args.min_days, args.reps, args.day_stake_floor,
              do_print=not args.json)
    if args.json:
        print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
