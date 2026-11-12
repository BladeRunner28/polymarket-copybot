#!/usr/bin/env python3
"""Wallet-ranking SHADOW -- two ranking arms + a coverage gate, scored forward. Lane A, shadow-only.

CARD (roadmap `crowdintel-wallet-fdr-audit` -> approval card `t_7c91b4a1`, operator approved
2026-11-09 for the SHADOW build only). Nothing here selects a wallet the bot copies, changes a
status, a size, a rule or a risk. It reads, ranks, scores, and writes its own data file.

PRE-REGISTERED ARMS (frozen at `shadow_start_ms` in data/wallet-rank-shadow-state.json; the fit
window is every bet with timestamp < shadow_start, the forward window is every bet >= it):

  hard-q      admit wallet w iff  n_eff >= 8  AND  BH q <= 0.10  AND  band-excess > 0
              (q from the parent instrument, BH over the full screened family)
  shrunk      rank by empirical-Bayes band-excess: per-wallet mean band-excess x_w (the mean over
              the wallet's first-print bets, the same statistic the audit reports per wallet) with
              a market-clustered standard error se_w, shrunk toward the band prior (0 excess by
              construction) with B_w = tau^2 / (tau^2 + se_w^2), tau^2 = max(0, var(x) - mean(se^2));
              admit every coverage-eligible wallet with shrunk excess > 0. This is the BREADTH arm:
              the pooled tracked-set read (+2.59pp over its bands on 2026-10-29) reproduces exactly on
              its own 25-wallet set and truth join, but 14 of those 25 wallets have since been demoted
              and they carry the whole positive read -- see drafts/wallet-rank-shadow-20261109.md --
              so a ranking that keeps many wallets is the alternative to a 54-wallet elite that
              re-admits none of them.
  baseline    "keep the current track set": the WalletProfile snapshot with status='track' taken at
              shadow_start (frozen, so a later status edit cannot move the goalposts).

COVERAGE GATE (applies to both arms, never to the baseline): no ranking decision on a wallet with
n_eff < 8 market clusters, and none on a wallet with no settled print at all. Those wallets are
ranked by nothing and admitted by nothing.

DECISION RULE (pre-registered on the card, applied literally, same window and bands for both arms):
an arm ships out of shadow only if, on >= 200 forward bets, its forward band-excess per market
(a) beats the keep-the-set baseline's, and (b) has a market-clustered bootstrap 95% CI excluding
zero. (b) binds on the ARM-MINUS-BASELINE difference (paired on shared markets when >= 10 exist),
not on the arm's own excess: the baseline is itself a positive-expectation book, so clearing zero
is not the same test as beating the set. A comparison CI that straddles zero is a TIE and kills
the arm, per the rule's own "a tie or a loss kills it". A tie or a loss kills it and the null is recorded. Until the forward window holds 200 settled
bets the verdict is PENDING -- never PASS on a thin window.

REFUTATION: neither arm beats keep-the-set => wallet selection is worth keeping as-is, no ranking
product is built, and the null is recorded. No re-slicing.

BAND-EXCESS DEFINITION: identical to scripts/wallet-fdr-audit.py (imported, not re-implemented):
edge = 100*(settled_value - detection_price) in probability points, first print per
(wallet, conditionId, outcome); excess = edge minus the same band's mean edge across the whole
measured population with the wallet under test left out. On the forward read the band mean is the
FORWARD window's own population mean, so both arms and the baseline are priced against the same,
contemporaneous bands.

TRUTH COVERAGE: the whole read is bounded by settlement truth in data/wallet-fdr-truth.json. `--fetch
N` widens it, prioritising (1) markets that carry a FORWARD print (the window the decision reads),
then (2) markets a current track wallet printed, then (3) the rest by distinct-wallet count. A
market the venue has not settled is recorded unsettled, never dropped.

USAGE
  python3 scripts/wallet-rank-shadow.py --fetch 2000     # widen truth, then score
  python3 scripts/wallet-rank-shadow.py                  # score from cache only
  python3 scripts/wallet-rank-shadow.py --selftest-split 2026-08-20
        harness self-test on a HISTORICAL split (fit before the date, score after it). Writes
        data/wallet-rank-shadow-selftest.json and touches neither the state nor the history.
  python3 scripts/wallet-rank-shadow.py --json data/wallet-rank-shadow.json

Read-only on prisma/dev.db (mode=ro). Writes: data/wallet-fdr-truth.json (with --fetch),
data/wallet-rank-shadow-state.json (first run only, plus selection hashes),
data/wallet-rank-shadow-history.jsonl (one line per run), and the --json path.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import math
import os
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_PATH = os.path.join(ROOT, "scripts", "wallet-fdr-audit.py")
STATE_PATH = os.path.join(ROOT, "data", "wallet-rank-shadow-state.json")
DEFAULT_JSON = os.path.join(ROOT, "data", "wallet-rank-shadow.json")
SELFTEST_JSON = os.path.join(ROOT, "data", "wallet-rank-shadow-selftest.json")
HISTORY_PATH = os.path.join(ROOT, "data", "wallet-rank-shadow-history.jsonl")

MIN_NEFF_DECISION = 8         # the card's coverage gate and both arms' admission floor
Q_BAR = 0.10                  # the card's q bar
MIN_FWD_BETS = 200            # the card's forward sample floor
BOOT_REPS = 5000
BOOT_SEED = 20261109
CI = 0.95

RULE_TEXT = {
    "arms": {
        "hard_q": "n_eff >= 8 AND BH q <= 0.10 AND band-excess > 0",
        "shrunk": "n_eff >= 8 AND EB-shrunk band-excess > 0 (tau^2 = max(0, var(x)-mean(se^2)))",
    },
    "coverage_gate": "no ranking decision on n_eff < 8 or on a wallet with no settled print",
    "baseline": "WalletProfile.status='track' snapshot taken at shadow_start",
    "decision": ("arm beats keep-the-set on forward band-excess per market AND its market-clustered "
                 "bootstrap 95% CI excludes zero, on >= 200 forward bets; tie or loss kills it. "
                 "The CI that binds is the ARM-MINUS-BASELINE difference (paired on shared markets "
                 "when >= 10 exist), because the baseline is itself a positive-expectation book: an "
                 "arm can clear zero and still be indistinguishable from keeping the current set"),
    "pending": "fewer than 200 forward settled bets => PENDING, never PASS",
    "binding_ci": "arm_minus_baseline",
    "rule_fix": ("2026-11-11: verdict() was keyed on the arm's own excess CI. It printed PASS for "
                 "hard_q with the arm-minus-baseline CI at [-2.91, +5.99]. Now binds on the "
                 "difference; that case reads TIE."),
}


SELFTEST_RULE_CASES = [
    # (name, arm mean, arm ci, base mean, diff paired ci, bets, expected)
    ("arm beats baseline, difference CI excludes zero", 2.27, (0.21, 4.34), 0.76, (0.50, 3.00), 1251, "PASS"),
    ("arm clears zero but is a TIE vs baseline (the 2026-11-12 shape)", 2.27, (0.21, 4.34), 0.76,
     (-1.38, 4.94), 1251, "TIE"),
    ("arm below baseline", -0.37, (-1.66, 0.90), 0.76, (-3.90, 2.79), 7050, "FAIL"),
    ("positive arm, no baseline rows to compare", 1.20, (0.10, 2.30), 0.40, None, 400, "TIE"),
    ("thin forward window cannot pass", 9.00, (8.00, 10.00), 0.10, (8.00, 10.00), 150, "PENDING"),
]


def selftest_rule():
    """Negative controls for the verdict: a PASS must be unreachable without beating the baseline."""
    bad = 0
    for name, am, aci, bm, dci, n, want in SELFTEST_RULE_CASES:
        arm = {"mean": am, "ci_lo": aci[0], "ci_hi": aci[1], "bets": n}
        base = {"mean": bm, "ci_lo": -9.0, "ci_hi": 9.0, "bets": 334}
        diff = None if dci is None else {"paired_shared": {"markets": 40, "mean": am - bm,
                                                          "ci_lo": dci[0], "ci_hi": dci[1]},
                                         "ci_lo": dci[0] - 1, "ci_hi": dci[1] + 1}
        got, why = verdict(arm, base, n, diff)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {got:8} (want {want:7}) {'OK ' if ok else 'BAD'}  {name}")
        if not ok:
            print(f"      {why}")
    print(f"selftest-rule: {len(SELFTEST_RULE_CASES) - bad}/{len(SELFTEST_RULE_CASES)}")
    return 1 if bad else 0


def _load_audit():
    spec = importlib.util.spec_from_file_location("wallet_fdr_audit", AUDIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_iso_ms(s):
    s = s.strip()
    fmt = "%Y-%m-%dT%H:%M:%S" if len(s) >= 19 else "%Y-%m-%d"
    return int(time.mktime(time.strptime(s[:19], fmt)) * 1000)


# ---------------------------------------------------------------- truth widening
def widen_truth(a, cache, budget, shadow_start, track):
    """Spend `budget` fetches on the markets the decision depends on.

    Order: forward-window markets first (the only ones the forward read can use), then every market
    a current track wallet printed, then the rest by distinct-wallet count. Same needs-fetch logic as
    the parent instrument: settled records are never re-fetched, unsettled ones only once their end
    has passed.
    """
    import sqlite3
    c = sqlite3.connect("file:" + a.DB + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    now = time.time() * 1000
    mk_wallets = collections.defaultdict(set)
    mk_bets = collections.Counter()
    mk_fwd = collections.Counter()
    seen = set()
    for r in c.execute("""SELECT walletAddress w, conditionId cid, outcome o, timestamp ts
                          FROM ObservedTrade
                          WHERE isDemo=0 AND side='BUY' AND conditionId IS NOT NULL
                          ORDER BY timestamp"""):
        key = (r["w"], r["cid"], (r["o"] or "").strip().upper())
        if key in seen:
            continue
        seen.add(key)
        mk_wallets[r["cid"]].add(r["w"])
        mk_bets[r["cid"]] += 1
        if r["ts"] >= shadow_start:
            mk_fwd[r["cid"]] += 1

    def needs(cid):
        rec = cache.get(cid)
        if not rec:
            return True
        if not rec.get("unsettled"):
            return False
        end = rec.get("end")
        if not end:
            return True
        try:
            return time.mktime(time.strptime(end[:19], "%Y-%m-%dT%H:%M:%S")) * 1000 <= now
        except Exception:
            return True

    fwd = [cid for cid in mk_fwd if needs(cid)]
    fwd.sort(key=lambda cid: -mk_fwd[cid])
    taken = set(fwd)
    trk = [cid for cid, ws in mk_wallets.items() if cid not in taken and (ws & track) and needs(cid)]
    trk.sort(key=lambda cid: -mk_bets[cid])
    taken |= set(trk)
    rest = [cid for cid in mk_wallets if cid not in taken and needs(cid)]
    rest.sort(key=lambda cid: (-len(mk_wallets[cid]), -mk_bets[cid]))
    todo = (fwd + trk + rest)[:budget]
    print(f"  truth fetch: {len(fwd):,} forward markets need truth, {len(trk):,} track markets, "
          f"spending {len(todo):,} fetches (budget {budget:,})")
    if not todo:
        return cache
    got = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, (cid, rec) in enumerate(ex.map(a._fetch_one, todo), 1):
            if rec:
                cache[cid] = rec
                got += 1
            else:
                fail += 1
            if i % 2000 == 0:
                print(f"    {i:,}/{len(todo):,}  ok {got:,}  failed {fail:,}  {time.time()-t0:.0f}s")
    payload = {"generated_at": _now_iso(),
               "source": "https://clob.polymarket.com/markets/<conditionId> tokens[].winner",
               "note": "wallet-FDR truth expansion; merged with data/market-truth-clob.json at read",
               "markets": {k: v for k, v in cache.items()}}
    with open(a.FDR_TRUTH, "w") as f:
        json.dump(payload, f, separators=(",", ":"), sort_keys=True)
    print(f"  fetched {got:,} markets, {fail:,} failed, {time.time()-t0:.0f}s; "
          f"cache now {len(cache):,} -> {os.path.relpath(a.FDR_TRUTH, ROOT)}")
    return cache


# ---------------------------------------------------------------- ranking arms
def per_market_se(wallet_rows):
    """(w -> (se of the market-clustered mean, market-clustered sd, n markets)) from bets."""
    by_mk = collections.defaultdict(lambda: collections.defaultdict(list))
    for b in wallet_rows:
        by_mk[b["w"]][b["cid"]].append(b["xedge"])
    out = {}
    for w, mks in by_mk.items():
        means = [statistics.mean(v) for v in mks.values()]
        n = len(means)
        sd = statistics.stdev(means) if n > 1 else None
        out[w] = (sd / math.sqrt(n) if sd is not None else None, sd, n)
    return out


def eb_shrink(wallets, eligible, ses):
    """Empirical-Bayes shrinkage of band-excess toward the band prior (0), by n_eff."""
    xs = [wallets[w]["xmean"] for w in eligible if ses.get(w, (None,))[0] is not None]
    s2 = [ses[w][0] ** 2 for w in eligible if ses.get(w, (None,))[0] is not None]
    out = {"tau2": 0.0, "tau": 0.0, "mean_se2": None, "var_x": None, "n": len(xs), "shrunk": {}}
    if len(xs) < 10:
        out["note"] = "too few eligible wallets with a finite se to estimate tau^2"
        return out
    var_x = statistics.variance(xs)
    mean_se2 = statistics.mean(s2)
    tau2 = max(0.0, var_x - mean_se2)
    out.update({"tau2": tau2, "tau": math.sqrt(tau2), "mean_se2": mean_se2, "var_x": var_x})
    for w in eligible:
        se = ses.get(w, (None,))[0]
        if se is None:
            continue
        b = tau2 / (tau2 + se * se) if (tau2 + se * se) > 0 else 0.0
        out["shrunk"][w] = {"x": wallets[w]["xmean"], "se": se, "b": b,
                            "shrunk": b * wallets[w]["xmean"], "n_eff": wallets[w]["n_eff"]}
    if tau2 <= 0:
        out["note"] = ("tau^2 collapsed to 0: between-wallet spread does not exceed sampling noise, "
                       "so every shrunk estimate is 0 and the breadth arm admits nobody")
    return out


def select_arms(wallets, eligible, qs, shrink):
    hard = sorted([w for w in eligible
                   if qs.get(w) is not None and qs[w] <= Q_BAR and wallets[w]["xmean"] > 0])
    shr = sorted([w for w in eligible
                  if shrink["shrunk"].get(w) and shrink["shrunk"][w]["shrunk"] > 0],
                 key=lambda w: -shrink["shrunk"][w]["shrunk"])
    return hard, shr


# ---------------------------------------------------------------- forward read
def cluster_read(rows, reps=BOOT_REPS, seed=BOOT_SEED):
    """Market-clustered mean band-excess with a percentile bootstrap CI over markets."""
    per_mk = collections.defaultdict(list)
    for b in rows:
        per_mk[b["cid"]].append(b["xedge"])
    means = [statistics.mean(v) for v in per_mk.values()]
    n = len(means)
    rec = {"bets": len(rows), "markets": n, "mean": None, "t": None, "df": None,
           "p_pos": None, "ci_lo": None, "ci_hi": None}
    if n == 0:
        return rec
    rec["mean"] = statistics.mean(means)
    if n > 1:
        sd = statistics.stdev(means)
        if sd > 0:
            t = rec["mean"] / (sd / math.sqrt(n))
            rec["t"] = t
            rec["df"] = n - 1
            rec["p_pos"] = A.t_sf(t, n - 1)
        rnd = random.Random(seed)
        boots = []
        for _ in range(reps):
            s = [means[rnd.randrange(n)] for _ in range(n)]
            boots.append(statistics.mean(s))
        boots.sort()
        lo = int((1 - CI) / 2 * reps)
        hi = int((1 + CI) / 2 * reps) - 1
        rec["ci_lo"] = boots[max(0, lo)]
        rec["ci_hi"] = boots[min(reps - 1, hi)]
    return rec


def diff_read(rows_a, rows_b, reps=BOOT_REPS, seed=BOOT_SEED + 1):
    """Unpaired market-clustered bootstrap of mean(a) - mean(b); plus the paired read if shared."""
    pa = collections.defaultdict(list)
    pb = collections.defaultdict(list)
    for b in rows_a:
        pa[b["cid"]].append(b["xedge"])
    for b in rows_b:
        pb[b["cid"]].append(b["xedge"])
    ma = [statistics.mean(v) for v in pa.values()]
    mb = [statistics.mean(v) for v in pb.values()]
    if not ma or not mb:
        return None
    rnd = random.Random(seed)
    boots = []
    for _ in range(reps):
        sa = [ma[rnd.randrange(len(ma))] for _ in range(len(ma))]
        sb = [mb[rnd.randrange(len(mb))] for _ in range(len(mb))]
        boots.append(statistics.mean(sa) - statistics.mean(sb))
    boots.sort()
    lo = int((1 - CI) / 2 * reps)
    hi = int((1 + CI) / 2 * reps) - 1
    shared = sorted(set(pa) & set(pb))
    paired = None
    if len(shared) >= 10:
        d = [statistics.mean(pa[c]) - statistics.mean(pb[c]) for c in shared]
        pb2 = []
        for _ in range(reps):
            s = [d[rnd.randrange(len(d))] for _ in range(len(d))]
            pb2.append(statistics.mean(s))
        pb2.sort()
        paired = {"markets": len(shared), "mean": statistics.mean(d),
                  "ci_lo": pb2[lo], "ci_hi": pb2[hi]}
    return {"mean": statistics.mean(ma) - statistics.mean(mb),
            "ci_lo": boots[max(0, lo)], "ci_hi": boots[min(reps - 1, hi)],
            "unpaired": True, "paired_shared": paired}


def binding_diff_ci(diff):
    """The CI the card's rule names: arm MINUS keep-the-set, market-clustered.

    Paired on shared markets when there are >= 10 of them (same markets, both arms), else the
    unpaired two-sample bootstrap. Returns (ci_lo, ci_hi, basis) or (None, None, why-not).
    """
    if not diff:
        return None, None, "no baseline rows to compare against"
    paired = diff.get("paired_shared")
    if paired and paired.get("ci_lo") is not None:
        return paired["ci_lo"], paired["ci_hi"], f"paired on {paired['markets']} shared markets"
    if diff.get("ci_lo") is None:
        return None, None, "bootstrap CI unavailable"
    return diff["ci_lo"], diff["ci_hi"], "unpaired two-sample bootstrap"


def verdict(arm_read, base_read, arm_bets, diff=None):
    """BINDING RULE (pre-registered): the ARM must beat keep-the-set, not merely beat zero.

    A PASS on the arm's own excess CI is not evidence about the comparison: the baseline is a
    positive-expectation book too, so an arm can clear zero while being indistinguishable from
    keeping the current track set. The 2026-11-12 run did exactly that -- hard_q printed PASS with
    its own CI at [+0.21, +4.34] while the arm-minus-baseline CI was [-2.91, +5.99]. The binding
    condition is therefore the DIFFERENCE CI above zero (paired on shared markets where possible),
    and the arm's own absolute CI is reported beside it, never in place of it.
    """
    if arm_bets < MIN_FWD_BETS:
        return "PENDING", f"{arm_bets} forward settled bets < {MIN_FWD_BETS}"
    if arm_read["mean"] is None or base_read["mean"] is None:
        return "PENDING", "no forward read for the arm or the baseline"
    beats = arm_read["mean"] > base_read["mean"]
    own_ci_ok = arm_read["ci_lo"] is not None and arm_read["ci_lo"] > 0
    d_lo, d_hi, d_basis = binding_diff_ci(diff)
    diff_ok = d_lo is not None and d_lo > 0
    head = (f"forward excess {arm_read['mean']:+.2f}pp vs baseline {base_read['mean']:+.2f}pp, "
            f"arm CI [{arm_read['ci_lo']:+.2f}, {arm_read['ci_hi']:+.2f}], n={arm_bets}")
    if beats and own_ci_ok and diff_ok:
        return "PASS", (f"{head}; BEATS keep-the-set on the binding test: difference "
                        f"{arm_read['mean'] - base_read['mean']:+.2f}pp, CI [{d_lo:+.2f}, "
                        f"{d_hi:+.2f}] excludes zero ({d_basis})")
    why = [head]
    if not beats:
        why.append(f"does not beat keep-the-set ({arm_read['mean']:+.2f}pp vs "
                   f"{base_read['mean']:+.2f}pp)")
    elif d_lo is not None:
        why.append(f"TIE: beats the baseline point estimate by "
                   f"{arm_read['mean'] - base_read['mean']:+.2f}pp but the arm-minus-baseline CI "
                   f"[{d_lo:+.2f}, {d_hi:+.2f}] includes zero ({d_basis})")
    else:
        why.append(f"no arm-minus-baseline CI ({d_basis})")
    if not own_ci_ok:
        if arm_read["ci_hi"] is not None and arm_read["ci_hi"] < 0:
            why.append(f"arm CI lies entirely below zero [{arm_read['ci_lo']:+.2f}, "
                       f"{arm_read['ci_hi']:+.2f}] (negative excess)")
        else:
            why.append(f"arm CI includes zero [{arm_read['ci_lo']:+.2f}, {arm_read['ci_hi']:+.2f}]")
    return ("TIE" if beats else "FAIL"), "; ".join(why)


# ---------------------------------------------------------------- main
def _state_template(shadow_start, track, truth_n, truth_settled):
    return {
        "arm": "wallet-rank-shadow (Lane A, shadow-only)",
        "preregistered_at": _now_iso(),
        "shadow_start_ms": shadow_start,
        "shadow_start_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(shadow_start / 1000)),
        "rule": RULE_TEXT,
        "constants": {"min_neff": MIN_NEFF_DECISION, "q_bar": Q_BAR,
                      "min_forward_bets": MIN_FWD_BETS, "boot_reps": BOOT_REPS,
                      "ci": CI, "bands": A.BAND_NAMES},
        "instruments": {"scripts/wallet-rank-shadow.py": _sha256(os.path.abspath(__file__)),
                        "scripts/wallet-fdr-audit.py": _sha256(AUDIT_PATH)},
        "truth_at_arm": {"markets": truth_n, "settled": truth_settled},
        "track_snapshot": sorted(track),
        "selection_hash": None,
        "selection_history": [],
    }


def run(args):
    global A
    A = _load_audit()
    selftest = args.selftest_split is not None
    import sqlite3
    c = sqlite3.connect("file:" + A.DB + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    cache, settled = A.load_truth()
    status = {r[0]: r[1] for r in c.execute("SELECT address, status FROM WalletProfile")}
    track_now = {w for w, s in status.items() if s == "track"}

    # ---- state / pre-registration
    state = None
    if selftest:
        shadow_start = _parse_iso_ms(args.selftest_split)
        print(f"  MODE: selftest -- historical split {args.selftest_split} (no state, no history)")
    elif os.path.exists(STATE_PATH):
        state = json.load(open(STATE_PATH))
        shadow_start = state["shadow_start_ms"]
    else:
        shadow_start = int(time.time()) * 1000
        print(f"  ARMING: no state file; pre-registering shadow_start="
              f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(shadow_start / 1000))}")

    if args.fetch:
        cache = widen_truth(A, cache, args.fetch, shadow_start, track_now)
        settled = {k for k, v in cache.items() if not v.get("unsettled")}

    bets, stats = A.load_bets(c, cache)
    if not bets:
        print("no truth-joined bets -- nothing to measure (widen truth with --fetch N)")
        return 1
    fit = [b for b in bets if b["ts"] < shadow_start]
    fwd = [b for b in bets if b["ts"] >= shadow_start]
    distinct_cid = c.execute("SELECT COUNT(DISTINCT conditionId) FROM ObservedTrade "
                             "WHERE conditionId IS NOT NULL").fetchone()[0]
    print(f"\ntruth cache: {len(cache):,} markets, {len(settled):,} settled "
          f"({100.0*len(settled)/distinct_cid:.2f}% of {distinct_cid:,} distinct conditionIds)")
    print(f"bets joined: {len(bets):,}  fit(ts<start) {len(fit):,}  forward(ts>=start) {len(fwd):,}")

    if state is None and not selftest:
        state = _state_template(shadow_start, track_now, len(cache), len(settled))
    track = set(state["track_snapshot"]) if (state and state.get("track_snapshot")) else track_now

    # ---- fit on pre-window prints only
    A.band_excess(fit) if fit else None
    wallets = A.wallet_table(fit) if fit else {}
    tested = sorted([w for w, r in wallets.items()
                     if r["n_eff"] >= A.MIN_NEFF_TEST and r["p_pos"] is not None])
    qs = {w: q for w, q in zip(tested, A.bh_q([wallets[w]["p_pos"] for w in tested]))}
    print(f"\n=== FIT WINDOW (pre-registration) ===")
    print(f"  wallets with a settled print: {len(wallets):,}   BH family m={len(tested):,}   "
          f"band baseline (pp): " + "  ".join(
              f"{k} {v:+.2f}" for k, v in sorted(
                  ((nm, statistics.mean([b['edge'] for b in fit if b['band'] == nm]))
                   for nm in A.BAND_NAMES if any(b['band'] == nm for b in fit)), key=lambda x: x[0])))
    eligible = sorted([w for w, r in wallets.items() if r["n_eff"] >= MIN_NEFF_DECISION])
    ses = per_market_se(fit) if fit else {}
    shrink = eb_shrink(wallets, eligible, ses) if eligible else {"shrunk": {}, "tau2": 0.0}
    hard, shr = select_arms(wallets, eligible, qs, shrink)
    print(f"  coverage gate: {len(wallets):,} with a settled print, {len(eligible):,} with "
          f"n_eff >= {MIN_NEFF_DECISION}; {len(wallets)-len(eligible):,} screened out for thin "
          f"coverage (and {len(track) - len([w for w in track if w in wallets])} track wallets have "
          f"no settled print at all)")
    print(f"  EB shrink: tau={shrink['tau']:.2f}pp  var(x)={shrink['var_x']}  "
          f"mean(se^2)={shrink['mean_se2']}" if shrink.get("var_x") is not None
          else f"  EB shrink: {shrink.get('note')}")
    print(f"  ARM hard-q : {len(hard):>4} wallets admitted  "
          f"(of which current track: {sum(1 for w in hard if w in track)})")
    print(f"  ARM shrunk : {len(shr):>4} wallets admitted  "
          f"(of which current track: {sum(1 for w in shr if w in track)})")
    print(f"  baseline   : {len(track):>4} current track wallets (frozen snapshot)")

    # ---- freeze the SCORED selection at arm time: the forward read must not chase a moving fit.
    # A later truth widening improves the pre-window fit, so the refit is recomputed and its drift is
    # recorded, but the arm that gets scored stays the one frozen when the shadow was armed.
    sel_fit = {"hard_q": hard, "shrunk": shr, "baseline": sorted(track)}
    h_fit = hashlib.sha256(json.dumps(sel_fit, sort_keys=True).encode()).hexdigest()[:16]
    drift = None
    if state is not None and state.get("selection"):
        frozen = state["selection"]
        drift = {name: {"added": sorted(set(sel_fit[name]) - set(frozen.get(name) or [])),
                        "removed": sorted(set(frozen.get(name) or []) - set(sel_fit[name]))}
                 for name in sel_fit}
        if any(drift[n]["added"] or drift[n]["removed"] for n in drift):
            print("\n  REFIT DRIFT (truth widening moved the fit; the forward read still scores the "
                  "FROZEN arm, recorded for audit):")
            for n in ("hard_q", "shrunk"):
                print(f"    {n}: +{len(drift[n]['added'])} / -{len(drift[n]['removed'])} "
                      f"vs frozen selection")
        scored = frozen
    else:
        scored = sel_fit
    hard_s, shr_s = list(scored.get("hard_q") or []), list(scored.get("shrunk") or [])

    # ---- coverage gate checked against the current track set
    trk_in = [w for w in sorted(track) if w in wallets]
    trk_thin = [w for w in sorted(track) if w in wallets and wallets[w]["n_eff"] < MIN_NEFF_DECISION]
    trk_none = [w for w in sorted(track) if w not in wallets]
    print(f"  coverage gate on today's track set: {len(trk_in)} measured, {len(trk_thin)} with "
          f"n_eff<{MIN_NEFF_DECISION} (no ranking decision), {len(trk_none)} with no settled print "
          f"(no ranking decision)")

    # ---- forward read
    print(f"\n=== FORWARD WINDOW (from {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(shadow_start/1000))}) ===")
    arms = {}
    base = None
    base_meas = None
    if fwd:
        A.band_excess(fwd)
        base_rows = [b for b in fwd if b["w"] in track]
        base = cluster_read(base_rows)
        meas_track = {w for w in track if w in wallets}
        base_meas = cluster_read([b for b in fwd if b["w"] in meas_track])
        print(f"  baseline keep-the-set: {base['bets']:,} bets in {base['markets']:,} markets, "
              f"mean {base['mean']:+.2f}pp" if base["mean"] is not None
              else "  baseline keep-the-set: no forward bets yet")
        for name, members in (("hard_q", hard_s), ("shrunk", shr_s)):
            members = set(members)
            rows = [b for b in fwd if b["w"] in members]
            r = cluster_read(rows)
            d = diff_read(rows, base_rows) if rows and base_rows else None
            v, why = verdict(r, base, r["bets"], d)
            arms[name] = {"admitted": len(members), "read": r, "vs_baseline": d,
                          "verdict": v, "why": why, "scored_frozen": scored is not sel_fit,
                          "refit_admitted": len(sel_fit[name]),
                          "refit_of_track": sum(1 for w in sel_fit[name] if w in track)}
            print(f"  ARM {name:7}: {r['bets']:,} bets / {r['markets']:,} markets  "
                  f"mean {r['mean']:+.2f}pp  CI [{r['ci_lo']:+.2f}, {r['ci_hi']:+.2f}]  "
                  # d["mean"] is the arm MINUS the baseline, not the baseline's own level --
                  # printing it as "vs baseline" read as the baseline figure (2026-11-11).
                  f"diff {d['mean']:+.2f}pp (baseline {base['mean']:+.2f}pp)  -> {v}"
                  if r["mean"] is not None
                  else f"  ARM {name:7}: no forward bets in the admitted set -> PENDING")
            if why:
                print(f"           {why}")
        bm = ("n/a" if base_meas["mean"] is None else f"{base_meas['mean']:+.2f}pp")
        print(f"  (measurable-only baseline for reference: {base_meas['bets']:,} bets, "
              f"{base_meas['markets']:,} markets, mean {bm})")
    else:
        meas_track = {w for w in track if w in wallets}
        print("  no forward bets yet: every joined bet predates shadow_start -- the shadow is ARMED, "
              "not measured")

    # ---- persist: the frozen selection is written once, refits are recorded beside it
    h = hashlib.sha256(json.dumps(scored, sort_keys=True).encode()).hexdigest()[:16]
    if state is not None and not selftest:
        if not state.get("selection"):
            state["selection"] = scored
            state["selection_hash"] = h
        if drift is not None and any(drift[n]["added"] or drift[n]["removed"] for n in drift):
            state.setdefault("selection_history", []).append(
                {"at": _now_iso(), "refit_hash": h_fit,
                 "drift": {k: {"added": len(v["added"]), "removed": len(v["removed"])}
                           for k, v in drift.items()}})
        state["last_run"] = {"at": _now_iso(), "truth_settled": len(settled),
                             "forward_bets": len(fwd), "track_now_n": len(track_now),
                             "refit_hash": h_fit, "scored_hash": state["selection_hash"]}
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=1, sort_keys=True)

    out = {
        "generated_at": _now_iso(),
        "mode": "selftest" if selftest else "shadow",
        "lane": "A / shadow-only -- no selection, status, size or rule changes",
        "shadow_start_ms": shadow_start,
        "shadow_start_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(shadow_start / 1000)),
        "rule": RULE_TEXT,
        "truth": {"markets": len(cache), "settled": len(settled),
                  "coverage_pct": round(100.0 * len(settled) / distinct_cid, 3)},
        "bets_joined": len(bets), "bets_fit": len(fit), "bets_forward": len(fwd),
        "wallets_fit": len(wallets), "bh_family_m": len(tested),
        "eligible_neff8": len(eligible),
        "eb": {k: shrink.get(k) for k in ("tau2", "tau", "var_x", "mean_se2", "note")},
        "arms": {"hard_q": {"admitted": len(hard_s), "wallets": hard_s,
                            "of_track": sum(1 for w in hard_s if w in track),
                            "refit_admitted": len(hard)},
                 "shrunk": {"admitted": len(shr_s), "wallets": shr_s,
                            "of_track": sum(1 for w in shr_s if w in track),
                            "refit_admitted": len(shr)}},
        "baseline": {"track_n": len(track), "wallets": sorted(track)},
        "coverage_gate": {"track_measured": len(trk_in), "track_thin_neff": trk_thin,
                          "track_no_settled_print": trk_none,
                          "screened_thin": len(wallets) - len(eligible)},
        "forward": {"baseline": base, "baseline_measurable_only": base_meas if fwd else None,
                    "arms": arms},
        "selection_hash": h, "selection_drift": drift,
        "decision": {k: {"verdict": v["verdict"], "why": v["why"],
                         # BINDING: the arm-minus-baseline difference CI (paired on shared
                         # markets where possible). Fixed 2026-11-11 after hard_q printed PASS
                         # with this CI at [-2.91, +5.99] -- an arm clearing zero is not an arm
                         # that beats keep-the-set, and the verdict had been keyed on the former.
                         "diff_ci_excludes_zero": bool(binding_diff_ci(v["vs_baseline"])[0] or 0) > 0
                         if binding_diff_ci(v["vs_baseline"])[0] is not None else None,
                         "diff_ci": None if binding_diff_ci(v["vs_baseline"])[0] is None
                         else [binding_diff_ci(v["vs_baseline"])[0], binding_diff_ci(v["vs_baseline"])[1]],
                         "diff_ci_basis": binding_diff_ci(v["vs_baseline"])[2],
                         "binding": True}
                     for k, v in arms.items()}
                    if arms else {k: {"verdict": "PENDING", "why": "no forward bets yet",
                                      "diff_ci_excludes_zero": None, "diff_ci": None, "binding": True}
                                  for k in ("hard_q", "shrunk")},
    }
    path = args.json or (SELFTEST_JSON if selftest else DEFAULT_JSON)
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n  json -> {os.path.relpath(path, ROOT)}")
    if not selftest:
        with open(HISTORY_PATH, "a") as f:
            f.write(json.dumps({
                "at": _now_iso(), "shadow_start_ms": shadow_start,
                "truth_settled": len(settled), "coverage_pct": out["truth"]["coverage_pct"],
                "forward_bets": len(fwd),
                "baseline": None if not base else {"bets": base["bets"], "markets": base["markets"],
                                                   "mean": base["mean"]},
                "arms": {k: {"admitted": out["arms"][k]["admitted"],
                             "bets": v["read"]["bets"], "mean": v["read"]["mean"],
                             "ci": [v["read"]["ci_lo"], v["read"]["ci_hi"]],
                             "vs_baseline": (v["vs_baseline"] or {}).get("mean"),
                             "verdict": v["verdict"]}
                         for k, v in arms.items()},
            }) + "\n")
    print(f"  verdicts: " + "  ".join(f"{k}={v['verdict']}" for k, v in out["decision"].items()))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", type=int, default=0, help="widen settlement truth by up to N markets")
    ap.add_argument("--json", default=None, help="write the full read here")
    ap.add_argument("--selftest-split", default=None,
                    help="ISO date: harness self-test on a historical split (no state, no history)")
    ap.add_argument("--selftest-rule", action="store_true",
                    help="negative controls for the verdict (no DB, no network)")
    args = ap.parse_args()
    if args.selftest_rule:
        return selftest_rule()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
