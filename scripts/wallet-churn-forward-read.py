#!/usr/bin/env python3
"""wallet-churn-forward-read — is the DEMOTED cohort's positive band-excess a selection artifact?

READ-ONLY. Answers roadmap card `crowdintel-track-churn-inversion` (Backlog, 2026-11-09):

    "14 of 25 track wallets were replaced in ten days, and the DEMOTED cohort carries the
     whole positive band-excess (+4.95pp vs -2.04pp for the ones that were kept)."

The card states its own limit — the +4.95pp was measured on the data that SELECTED those wallets,
"so it is evidence about what the process DISCARDED, not a forecast" — and names one mechanism to
test (whether the drop score reads marks rather than settled outcomes). This instrument fixes both:

  ARM 1  COHORT x WINDOW. The same cohorts (demoted / kept / added) read on three windows:
           IN   prints before the parent run (2026-10-29)          <- the in-sample read
           F1   prints at/after the parent run                     <- post-selection, pre-demotion
           F2   prints at/after the shadow arm (2026-11-09T18:13Z) <- post-demotion, purest
         ONE band baseline is taken over the whole joined population once (so no window can move
         by re-meaning its own bands), and every read is market-clustered with a percentile
         bootstrap CI, plus median / 10%-trimmed mean / ex-top-10 so one or two wallets cannot
         carry the headline.

  ARM 2  MECHANISM. Does the score the scanner DROPS on rank wallets by their own settled
         band-excess? Per-wallet own mean band-excess vs the stored `globalScore`, `roi30d` and
         `winRate30d` (Spearman), on wallets with >= 8 joined bets. Note `winRate30d` has been on
         the SETTLEMENT basis since 2026-11-11 (label-integrity-wallet-win-filter), so this arm
         reads the repaired score too, not only the legacy one the card suspected.

  ARM 3  CHURN CONTINUATION. How many of the frozen 34 are still `status='track'` today, and how
         many of the parent's 25 — the card measured one 10-day window; churn is only "live" if
         the set keeps moving.

COHORT SOURCES (both already committed, nothing re-derived):
  parent 25 = keys of `track_flags` in data/wallet-fdr-audit.json (the 2026-10-30T01:28Z audit run
              carries one flag row per track wallet, all 25)
  frozen 34 = `track_snapshot` in data/wallet-rank-shadow-state.json (frozen at arm 2026-11-09)
  demoted   = parent - frozen (14)      kept = parent & frozen (11)      added = frozen - parent (23)
The 11/14/23 split is ASSERTED at run time: if a committed artifact ever moves, this read fails
loudly instead of silently measuring a different cohort.

BASIS OF EVERY NUMBER PRINTED: level = one first-print bet (wallet, conditionId, outcome) priced at
the detection price; truth = venue settlement from the shared truth caches; excess = bet edge minus
its band's leave-one-wallet-out mean over the WHOLE joined population; clock = ObservedTrade
.timestamp, UTC; population = isDemo=0 BUY prints joined to settled markets.

USAGE
  python3 scripts/wallet-churn-forward-read.py                 # live read + json
  python3 scripts/wallet-churn-forward-read.py --self-test     # synthetic fixture, mutation RED
  python3 scripts/wallet-churn-forward-read.py --no-json

REPRO / ROLLBACK: opens prisma/dev.db mode=ro and writes only data/wallet-churn-forward-read.json.
Deleting that file and this script reverts the run entirely — no schema, rule, state or alert.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import sqlite3
import statistics
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_PATH = os.path.join(ROOT, "scripts", "wallet-fdr-audit.py")
SHADOW_PATH = os.path.join(ROOT, "scripts", "wallet-rank-shadow.py")
STATE_PATH = os.path.join(ROOT, "data", "wallet-rank-shadow-state.json")
SHADOW_JSON = os.path.join(ROOT, "data", "wallet-rank-shadow.json")
PARENT_AUDIT_PATH = os.path.join(ROOT, "data", "wallet-fdr-audit.json")
OUT_PATH = os.path.join(ROOT, "data", "wallet-churn-forward-read.json")

PARENT_SPLIT_ISO = "2026-10-29"     # the parent FDR run; its read is IN-sample to this date
EXPECTED = {"parent": 25, "frozen": 34, "demoted": 14, "kept": 11, "added": 23}
MIN_MECH_BETS = 8                   # the audit's own coverage bar (n_eff >= 8), re-used
RHO_USABLE = 0.10                   # stated here, post-hoc: |rho| below this = no usable ranking
RHO_CARD_BAR = 0.30                 # wallet-fdr-audit's own RHO_BAR, for scale only
BOOT_REPS = 2000


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ms(iso):
    """ISO date or datetime -> epoch ms on the local clock (same helper shape the audit uses)."""
    if len(iso) > 10:
        return int(time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")) * 1000)
    return int(time.mktime(time.strptime(iso, "%Y-%m-%d")) * 1000)


def cohort_sets():
    """(parent25, frozen34, demoted, kept, added) from committed artifacts, with an assertion."""
    parent = set(json.load(open(PARENT_AUDIT_PATH))["track_flags"].keys())
    state = json.load(open(STATE_PATH))
    frozen = set(state["track_snapshot"])
    got = {"parent": len(parent), "frozen": len(frozen), "demoted": len(parent - frozen),
           "kept": len(parent & frozen), "added": len(frozen - parent)}
    bad = {k: (got[k], v) for k, v in EXPECTED.items() if got[k] != v}
    if bad:
        raise SystemExit(
            "cohort artifacts no longer reproduce the card's split "
            + ", ".join(f"{k}: got {g}, card says {e}" for k, (g, e) in bad.items())
            + " -- refusing to print a read on a different population")
    return parent, frozen, parent - frozen, parent & frozen, frozen - parent


def window_rows(bets, cohort, lo_ms=None, hi_ms=None):
    return [b for b in bets
            if b["w"] in cohort
            and (lo_ms is None or b["ts"] >= lo_ms)
            and (hi_ms is None or b["ts"] < hi_ms)]


def concentration(xs):
    """Median / 10%-trimmed mean / ex-top-10 mean / top-10 share of the sum."""
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    k = len(s) // 10
    trimmed = statistics.mean(s[k:len(s) - k]) if len(s) - 2 * k > 0 else statistics.mean(s)
    total = sum(s)
    top = s[-10:]
    return {"n": len(s), "median": statistics.median(s), "trimmed_mean": trimmed,
            "ex_top10_mean": statistics.mean(s[:-10]) if len(s) > 10 else None,
            "top10_share_pct": (100.0 * sum(top) / total) if total else None}


def make_read(SH):
    """Market-clustered read of a bet list, plus the concentration furniture."""
    def read(rows, reps=BOOT_REPS):
        r = SH.cluster_read(rows, reps=reps)
        r["raw_mean"] = statistics.mean([b["edge"] for b in rows]) if rows else None
        r["concentration"] = concentration([b["xedge"] for b in rows])
        return r
    return read


def mechanism(bets, profiles, A, min_bets=MIN_MECH_BETS):
    """Per-wallet own band-excess vs the stored selection scores (Spearman over wallets)."""
    by_w = collections.defaultdict(list)
    for b in bets:
        by_w[b["w"]].append(b)
    pop = []
    for w, bs in by_w.items():
        if len(bs) < min_bets or w not in profiles:
            continue
        p = profiles[w]
        pop.append({"w": w, "excess": statistics.mean([b["xedge"] for b in bs]),
                    "globalScore": p["globalScore"], "roi30d": p["roi30d"],
                    "winRate30d": p["winRate30d"], "status": p["status"], "bets": len(bs)})
    out = {"wallets": len(pop), "min_bets": min_bets,
           "track_in_population": sum(1 for r in pop if r["status"] == "track"), "rho": {}}
    if len(pop) >= 10:
        for key in ("globalScore", "roi30d", "winRate30d"):
            out["rho"][key] = A.spearman([r["excess"] for r in pop], [r[key] for r in pop])
    return out


def _band(p):
    for i, hi in enumerate((0.2, 0.4, 0.6, 0.8)):
        if p < hi:
            return i
    return 4


def _bet(w, cid, px, ts, val):
    return {"w": w, "cid": cid, "px": px, "ts": ts, "v": val,
            "edge": 100.0 * (val - px), "band": _band(px)}


def self_test(A, SH):
    """Synthetic fixture with hand-computable answers; the mutation arm must go RED.

    Every synthetic bet prices inside ONE band (0.40-0.60), so the band baseline is a single cell
    and a group's leave-one-wallet-out excess is its mean minus the rest of the field's. The
    fixture plants the ONLY structure the instrument claims to detect:
      IN  : demoted priced better than the field   -> demoted excess must be POSITIVE
      F2  : EVERY cohort at the field's price      -> demoted excess must be ~ZERO
      MUT : the in-sample edge re-planted forward  -> the zero MUST move, or the read is dead
    The field is deliberately large vs the cohort: a cohort that is most of the window drags the
    leave-one-out baseline toward itself and compresses its own excess.
    """
    read = make_read(SH)
    n_ok = 0
    parent, frozen = set(), set()
    for i in range(14):
        parent.add(f"D{i}")
    for i in range(11):
        parent.add(f"K{i}")
        frozen.add(f"K{i}")
    for i in range(23):
        frozen.add(f"A{i}")
    demoted, kept, added = parent - frozen, parent & frozen, frozen - parent
    assert (len(demoted), len(kept), len(added)) == (14, 11, 23), "partition"
    n_ok += 1

    IN_MS, F2_MS = 1_000_000, 2_000_000

    def px(base, i, j):
        """Deterministic +/-2c jitter, always inside the band, so a t exists."""
        return round(base + ((i * 13 + j * 7) % 5 - 2) * 0.01, 4)

    def plant(cohort, per_wallet, base, ts, val, tag):
        rows = []
        for i, w in enumerate(sorted(cohort)):
            for j in range(per_wallet):
                rows.append(_bet(w, f"{tag}-{w}-{j}", px(base, i, j), ts, val))
        return rows

    bets = []
    bets += plant(demoted, 10, 0.42, IN_MS - 10, 1.0, "din")   # +58pp in-sample
    bets += plant(kept, 10, 0.50, IN_MS - 10, 1.0, "kin")      # the field, +50pp
    bets += plant(added, 30, 0.50, IN_MS - 10, 1.0, "ain")
    bets += plant(demoted, 5, 0.50, F2_MS + 10, 1.0, "dfwd")   # forward: AT the field
    bets += plant(kept, 5, 0.50, F2_MS + 10, 1.0, "kfwd")
    bets += plant(added, 30, 0.50, F2_MS + 10, 1.0, "afwd")
    A.band_excess(bets)

    in_rows = window_rows(bets, demoted, hi_ms=IN_MS)
    fwd_rows = window_rows(bets, demoted, lo_ms=F2_MS)
    r_in, r_fwd = read(in_rows), read(fwd_rows)
    assert (r_in["bets"], r_fwd["bets"]) == (140, 70), (r_in["bets"], r_fwd["bets"])
    n_ok += 1
    assert r_in["mean"] > 5 and r_in["t"] is not None and r_in["t"] > 3, \
        ("in-sample arm must beat the field", r_in["mean"], r_in["t"])
    n_ok += 1
    assert abs(r_fwd["mean"]) < 1.5, ("forward must sit on the field", r_fwd["mean"])
    n_ok += 1
    # MUTATION: re-plant the in-sample edge forward. If the read cannot separate this from the
    # honest forward arm, the assertion fails and the instrument is proven dead.
    mut = [dict(b) for b in bets]
    mpx = px(0.42, 1, 1)
    for b in mut:
        if b["ts"] >= F2_MS and b["w"] in demoted:
            b["px"], b["edge"] = mpx, 100.0 * (b["v"] - mpx)
    A.band_excess(mut)
    r_mut = read(window_rows(mut, demoted, lo_ms=F2_MS))
    assert r_mut["mean"] > r_fwd["mean"] + 4.0, \
        f"mutation must go RED (forward excess did not move): {r_mut['mean']} vs {r_fwd['mean']}"
    n_ok += 1
    # concentration: everything in two legs must show up, not average away
    c = concentration([100.0, 100.0] + [0.0] * 20)
    assert c["median"] == 0.0 and c["ex_top10_mean"] == 0.0 and c["top10_share_pct"] == 100.0, c
    n_ok += 1
    # mechanism arm: planted rank alignment reads +1, its reverse -1, and a thin wallet is excluded
    profiles, mbets = {}, []
    for i in range(60):
        w = f"M{i}"
        profiles[w] = {"globalScore": float(i), "roi30d": float(i) / 100, "winRate30d": 0.5,
                       "status": "watch"}
        for j in range(8):
            mbets.append({"w": w, "cid": f"m-{i}-{j}", "edge": float(i), "xedge": float(i)})
    mech = mechanism(mbets, profiles, A=A)
    assert mech["wallets"] == 60 and abs(mech["rho"]["globalScore"] - 1.0) < 1e-9, mech["rho"]
    n_ok += 1
    flipped = {w: {**p, "globalScore": float(59 - int(w[1:]))} for w, p in profiles.items()}
    assert mechanism(mbets, flipped, A=A)["rho"]["globalScore"] < -0.99
    n_ok += 1
    thin = {**profiles, "thin": {"globalScore": 99.0, "roi30d": 1.0, "winRate30d": 1.0,
                                 "status": "track"}}
    mech3 = mechanism(mbets + [{"w": "thin", "cid": "t", "edge": 999.0, "xedge": 999.0}],
                      thin, A=A)
    assert mech3["wallets"] == 60, mech3["wallets"]
    n_ok += 1
    print(f"self-test: {n_ok}/{n_ok} assertions held  "
          f"[honest: in-sample {r_in['mean']:+.2f}pp, forward {r_fwd['mean']:+.2f}pp; "
          f"mutation must exceed forward+4.0 and read {r_mut['mean']:+.2f}pp]")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-json", action="store_true")
    ap.add_argument("--json", default=OUT_PATH)
    ap.add_argument("--reps", type=int, default=BOOT_REPS)
    args = ap.parse_args(argv)

    A = _load("wallet_fdr_audit", AUDIT_PATH)
    SH = _load("wallet_rank_shadow", SHADOW_PATH)
    SH.A = A
    if args.self_test:
        return self_test(A, SH)
    read = make_read(SH)

    parent, frozen, demoted, kept, added = cohort_sets()
    state = json.load(open(STATE_PATH))
    arm_ms = int(state["shadow_start_ms"])
    parent_ms = _ms(PARENT_SPLIT_ISO)
    if not (parent_ms < arm_ms):
        raise SystemExit(f"windows out of order: parent {parent_ms} >= arm {arm_ms}")

    c = sqlite3.connect("file:" + A.DB + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    cache, settled = A.load_truth()
    t0 = time.time()
    bets, stats = A.load_bets(c, cache)
    A.band_excess(bets)                       # ONE baseline for every cohort and window
    profiles = {r["address"]: dict(r) for r in c.execute(
        "SELECT address,status,globalScore,roi30d,winRate30d,resolvedTradeCount30d,"
        "tradeCount30d,consistencyScore,copyabilityScore,oneHitWonderPenalty,lastScannedAt "
        "FROM WalletProfile WHERE isDemo=0")}
    track_today = {w for w, p in profiles.items() if p["status"] == "track"}

    print(f"population: {len(bets):,} first-print bets over {len({b['w'] for b in bets}):,} wallets "
          f"({len(settled):,} settled markets in the join; load {time.time() - t0:.0f}s)")
    print(f"windows: IN < {PARENT_SPLIT_ISO}   F1 >= {PARENT_SPLIT_ISO}   "
          f"F2 >= {state['shadow_start_iso']}")
    print(f"cohorts: demoted {len(demoted)}  kept {len(kept)}  added {len(added)} "
          f"(parent {len(parent)} -> frozen {len(frozen)})")

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "basis": {"level": "one first-print bet (wallet, conditionId, outcome) at detection price",
                     "truth": "venue settlement from the shared truth caches",
                     "excess": "bet edge minus its band's leave-one-wallet-out mean over the whole join",
                     "concentration": "median / trim10 / ex10 / top10% are per-BET xedge; the mean, t and CI are per-MARKET clustered",
                     "clock": "ObservedTrade.timestamp UTC",
                     "population": "isDemo=0 BUY prints joined to settled markets",
                     "windows": {"IN": f"ts < {PARENT_SPLIT_ISO}", "F1": f"ts >= {PARENT_SPLIT_ISO}",
                                 "F2": f"ts >= {state['shadow_start_iso']}"}},
           "parent_split_iso": PARENT_SPLIT_ISO, "arm_iso": state["shadow_start_iso"],
           "cohorts": {"parent": len(parent), "frozen": len(frozen), "demoted": len(demoted),
                       "kept": len(kept), "added": len(added)},
           "join": {"bets": len(bets), "wallets": len({b["w"] for b in bets}),
                    "settled_markets": len(settled)},
           "churn": {"track_today": len(track_today),
                     "frozen34_still_track": len(frozen & track_today),
                     "parent25_still_track": len(parent & track_today)},
           "arms": {}}

    hdr = (f"\n{'cohort':9} {'window':7} {'bets':>6} {'mkts':>5} {'excess':>8} {'t':>6} "
           f"{'CI95':>18} {'raw':>6} {'median':>7} {'trim10':>7} {'ex10':>7} {'top10%':>7}")
    print(hdr)
    print("  basis: excess / t / CI are market-clustered over per-MARKET means; median / trim10 /"
          " ex10 / top10% are per-BET xedge values, printed beside them so neither can be read alone")
    print("-" * len(hdr))
    windows = {"IN": (None, parent_ms), "F1": (parent_ms, None), "F2": (arm_ms, None)}
    for name, cohort in (("demoted", demoted), ("kept", kept), ("added", added)):
        out["arms"][name] = {}
        for wname, (lo, hi) in windows.items():
            rows = window_rows(bets, cohort, lo_ms=lo, hi_ms=hi)
            r = read(rows, reps=args.reps)
            out["arms"][name][wname] = r
            if r["mean"] is None:
                print(f"{name:9} {wname:7} {0:>6} {0:>5} {'--':>8}")
                continue
            ci = "--" if r["ci_lo"] is None else f"[{r['ci_lo']:+.2f}, {r['ci_hi']:+.2f}]"
            cc = r["concentration"]

            def f(v, w=7, p=2):
                return f"{v:>{w}.{p}f}" if v is not None else f"{'--':>{w}}"

            print(f"{name:9} {wname:7} {r['bets']:>6} {r['markets']:>5} {r['mean']:>+8.2f} "
                  f"{(r['t'] if r['t'] is not None else float('nan')):>6.2f} {ci:>18} "
                  f"{f(r['raw_mean'], 6)} {f(cc.get('median'))} {f(cc.get('trimmed_mean'))} "
                  f"{f(cc.get('ex_top10_mean'))} {f(cc.get('top10_share_pct'), 6, 1)}")

    # per-wallet sign split on the purest window, so a one-wallet answer cannot hide
    per_w = collections.defaultdict(list)
    for b in window_rows(bets, demoted, lo_ms=arm_ms):
        per_w[b["w"]].append(b["xedge"])
    signs = {"wallets": len(per_w),
             "positive": sum(1 for v in per_w.values() if statistics.mean(v) > 0),
             "with_5plus_bets": sum(1 for v in per_w.values() if len(v) >= 5)}
    out["demoted_forward_wallet_split"] = signs

    # cross-check against the shadow's own frozen-baseline forward population
    shadow_pop = None
    if os.path.exists(SHADOW_JSON):
        sj = json.load(open(SHADOW_JSON))
        shadow_pop = ((sj.get("forward") or {}).get("baseline") or {}).get("bets")
    mine = (len(window_rows(bets, kept, lo_ms=arm_ms))
            + len(window_rows(bets, added, lo_ms=arm_ms)))
    out["cross_check_frozen_forward_bets"] = {"instrument": mine, "shadow_artifact": shadow_pop}

    mech = mechanism(bets, profiles, A)
    out["mechanism"] = mech

    d_in, d_f1, d_f2 = (out["arms"]["demoted"]["IN"], out["arms"]["demoted"]["F1"],
                        out["arms"]["demoted"]["F2"])
    flip = bool(d_f2["mean"] is not None and d_f2["ci_lo"] is not None and d_f2["ci_lo"] > 0)
    out["verdict"] = {
        "in_sample_pp": d_in["mean"], "post_selection_pp": d_f1["mean"],
        "post_demotion_pp": d_f2["mean"], "forward_ci_excludes_zero": flip,
        "reading": ("FORWARD-POSITIVE: the drop loop discards a cohort that still beats its bands "
                    "out of sample -> a selection-value finding (Lane A to PROPOSE, never apply)"
                    if flip else
                    "NOT ESTABLISHED FORWARD: the demoted cohort's in-sample excess does not "
                    "survive the post-selection windows, so the card's +4.95pp must not be read "
                    "as discarded alpha"),
        "mechanism_reading": (
            "no usable rank information -- the drop score cannot see a wallet's own settled "
            f"band-excess (|rho| < {RHO_USABLE} on every arm)"
            if mech.get("rho") and all(abs(v) < RHO_USABLE for v in mech["rho"].values())
            else "the drop score DOES carry rank information (see rho)"),
    }

    print(f"\nchurn continuation: track today {len(track_today)}; of the frozen 34 "
          f"{len(frozen & track_today)} still track; of the parent 25 "
          f"{len(parent & track_today)} still track")
    print(f"demoted forward (F2) per wallet: {signs['positive']}/{signs['wallets']} positive, "
          f"{signs['with_5plus_bets']} with >=5 bets")
    print(f"cross-check vs shadow artifact: frozen-set forward bets here {mine}, shadow recorded "
          f"{shadow_pop}"
          + ("  MATCH" if mine == shadow_pop else "  (bets accrue; shadow figure is as of its run)"))
    if mech.get("rho"):
        print(f"mechanism (n={mech['wallets']} wallets with >={mech['min_bets']} joined bets, "
              f"{mech['track_in_population']} of them track): "
              + "  ".join(f"rho({k})={v:+.3f}" for k, v in mech["rho"].items())
              + f"   [card's RHO_BAR {RHO_CARD_BAR}]")
    print(f"\nVERDICT: {out['verdict']['reading']}")
    print(f"MECHANISM: {out['verdict']['mechanism_reading']}")

    if not args.no_json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
        print(f"\n  json -> {os.path.relpath(args.json, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
