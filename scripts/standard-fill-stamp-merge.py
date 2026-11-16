#!/usr/bin/env python3
"""Merge two standard-fill-stamp snapshots into ONE union snapshot (newer wins per leg id).

Standalone (read-only in, one file out):
    python3 scripts/standard-fill-stamp-merge.py OLD.jsonl NEW.jsonl OUT.jsonl

Why it exists: the STANDARD fill booth (scripts/standard-fill-stamp.ts) APPENDS a snapshot per
run. Each run only stamps the legs inside its own --since-ms window, so the newest line alone is
not the evidence set — the union is. This script folds the new snapshot into the union file
(data/standard-fill-stamp.jsonl) that scripts/standard-fill-aware-basis-split.py and
scripts/standard-fill-aware-rerebook.py read (both take the LAST snapshot line).

Rules
  * union by leg id: the newer snapshot wins — EXCEPT that a leg the new run could NOT stamp
    (book == null) never erases a stamp the old snapshot already had. Evidence beats absence;
    the alternative silently shrinks coverage whenever one tick misses the L2 window.
  * the merged line keeps the new snapshot's aggregate blocks (book/tape/refutation/coverage),
    because those describe ONE run, and declares what they cover via `aggregatesCover` so the
    file cannot be misread as aggregates over the whole union.
  * OLD missing/empty (first ever merge) => union = new.
  * the write is atomic (tmp + os.replace) so a crash cannot leave a torn union; OLD and OUT may
    be the same path.

2026-11-16 (Lane B repair): THE UNION NOW CARRIES ITS OWN VERDICT (`unionRefutation`).
Before this change the artifact's only refutation block was the newest incremental run's, so the
card's gate ("fires only when n >= 300 legs carry a mid") could never be read off the file: each
hourly tick stamps ~1 leg, prints `n=1`, `gateMet: false`, and the 1,011-leg union underneath it
was never tested. The gate's population was met 380 legs ago and the file still said NOT
EVALUABLE — an unfalsifiable probe, i.e. a condition the instrument structurally cannot cross.
The thresholds are READ FROM the snapshot's own `refutation` block (gate, bandC) rather than
re-declared here, so this script cannot drift into a second definition of the test.

Stdout: one human line, then one machine line the cron chain parses:
    MERGE old=<n> new=<n> union=<n> added=<n> addedStamped=<n> upgraded=<n> keptOldEvidence=<n> restamped=<n>
  added            leg ids the union did not have
  addedStamped     ... of which the new run stamped (book != null)
  upgraded         ids in both, old had no book, new does
  keptOldEvidence  ids in both, new had no book, old did (the rule above)
  restamped        ids in both with book on both sides whose firstAsk value changed
"""
import json
import os
import sys
import tempfile
from collections import Counter


def last_snap(p):
    if not p or not os.path.exists(p):
        return None
    last = None
    for line in open(p, encoding="utf8"):
        t = line.strip()
        if not t:
            continue
        try:
            o = json.loads(t)
        except json.JSONDecodeError:
            continue  # a torn line is not a snapshot
        if isinstance(o.get("legs"), list):
            last = o
    return last


def first_ask(leg):
    b = leg.get("book")
    return None if not b else b.get("firstAsk")


def _pct(xs):
    return None if not xs else sum(xs) / len(xs)


def _quant(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))]


LAG_LIMITS = ((1e4, "0-10s"), (3e4, "10-30s"), (6e4, "30-60s"), (3e5, "1-5m"),
              (1.8e6, "5-30m"))


def _lag_buckets(legs):
    """(attainable ask - booked) by coverage lag. Separates SPREAD from DRIFT: a fill cost that
    is already there inside 10s is the spread a taker pays; one that grows with lag is drift."""
    out = {}
    for l in legs:
        b = l.get("book")
        dp = l.get("decisionPrice")
        if not b or not dp or b.get("firstAsk") is None:
            continue
        lag = b.get("coverLagMs")
        nm = "30-60m"
        if lag is not None:
            for lim, label in LAG_LIMITS:
                if lag <= lim:
                    nm = label
                    break
        out.setdefault(nm, []).append((b["firstAsk"] - dp) * 100.0)
    return {k: {"n": len(v), "meanAskC": round(sum(v) / len(v), 4)} for k, v in out.items()}


def union_refutation(legs, new):
    """The card's pre-registered test, computed on the UNION instead of the newest tick.

    Thresholds come from the snapshot's own refutation block (the TypeScript booth owns the
    definition); a missing threshold is reported as `thresholds_missing`, never guessed.
    """
    ref = new.get("refutation") or {}
    book_ref = ref.get("book") or {}
    gate = book_ref.get("gate")
    band_c = book_ref.get("bandC")
    if gate is None or band_c is None:
        return {"error": "thresholds_missing", "reason": "snapshot carried no refutation.book.gate/bandC"}
    d_mid, d_ask, ntl, lags, ambiguous = [], [], [], [], 0
    for l in legs:
        b = l.get("book")
        dp = l.get("decisionPrice")
        if not b or not dp:
            continue
        fa, fb = b.get("firstAsk"), b.get("firstBid")
        if fa is None or fb is None:
            continue
        d_ask.append((fa - dp) * 100.0)
        d_mid.append(((fa + fb) / 2.0 - dp) * 100.0)
        ntl.append(l.get("sizeUsd") or 0.0)
        if b.get("coverLagMs") is not None:
            lags.append(b["coverLagMs"])
        if b.get("tokenAmbiguous"):
            ambiguous += 1
    n = len(d_mid)
    within = [x for x in d_mid if abs(x) <= band_c + 1e-9]
    at_or_better = [x for x in d_ask if x <= 0.01]
    worse_1c = [x for x in d_ask if x >= 1 - 0.01]
    mean_mid = _pct(d_mid)
    med_mid = _quant(d_mid, 0.5)
    gate_met = n >= gate
    fired = bool(gate_met and mean_mid is not None and abs(mean_mid) <= band_c + 1e-9)
    tot_ntl = sum(ntl)
    # Money weight: each leg's (ask - booked) delta applied to its own clip, at its own price.
    money = 0.0
    for l in legs:
        b = l.get("book")
        dp = l.get("decisionPrice")
        if not b or not dp or b.get("firstAsk") is None:
            continue
        money += (l.get("sizeUsd") or 0.0) * ((b["firstAsk"] - dp) / dp)

    def r(x, nd=4):
        return None if x is None else round(float(x), nd)

    return {
        "population": "UNION of every stamped leg in this file (not one run)",
        "n": n,
        "offered": len(legs),
        "gate": gate,
        "gateMet": gate_met,
        "bandC": band_c,
        "meanMidC": r(mean_mid),
        "medianMidC": r(med_mid),
        "shareWithinBand": None if not n else round(len(within) / n, 4),
        "fired": fired,
        "meanAskC": r(_pct(d_ask)),
        "medianAskC": r(_quant(d_ask, 0.5)),
        "p10AskC": r(_quant(d_ask, 0.1)),
        "p90AskC": r(_quant(d_ask, 0.9)),
        "shareAtOrBetter": None if not d_ask else round(len(at_or_better) / len(d_ask), 4),
        "shareWorseBy1c": None if not d_ask else round(len(worse_1c) / len(d_ask), 4),
        "notionalUsd": round(tot_ntl, 2),
        "moneyAtAskUsd": round(money, 2),
        "shareNotionalAtAsk": None if not tot_ntl else round(100.0 * money / tot_ntl, 4),
        "medianCoverLagMs": r(_quant(lags, 0.5), 0),
        "lagBuckets": _lag_buckets(legs),
        "ambiguousToken": ambiguous,
        "reason": (
            f"NOT EVALUABLE: n={n} of the required {gate} union legs carry a mid"
            if not gate_met else
            f"FIRED on {n} union legs: mean (attainable - mid) = "
            f"{mean_mid:+.2f}c, inside ±{band_c}c — there is no cent to harvest and a booking "
            f"change has no improvement to sell. Separately, the ASK arm puts attainable "
            f"{_pct(d_ask):+.2f}c ABOVE the booked price on the same legs."
            if fired else
            f"NOT REFUTED on {n} union legs: mean (attainable - mid) = {mean_mid:+.2f}c, "
            f"outside ±{band_c}c."
        ),
    }


def main():
    if len(sys.argv) != 4:
        sys.exit("usage: standard-fill-stamp-merge.py OLD.jsonl NEW.jsonl OUT.jsonl")
    old_p, new_p, out_p = sys.argv[1], sys.argv[2], sys.argv[3]

    old, new = last_snap(old_p), last_snap(new_p)
    if new is None:
        sys.exit(f"[stamp-merge] no snapshot in {new_p} — nothing to merge")
    if old is None:
        old = {"legs": []}

    merged, stats = {}, Counter()
    for l in old["legs"]:
        if l.get("id"):
            merged[l["id"]] = dict(l, _src="old")
    old_ids = set(merged)

    for leg in new["legs"]:
        lid = leg.get("id")
        if not lid:
            continue
        fresh = dict(leg, _src="new")
        if lid not in merged:
            stats["added"] += 1
            if fresh.get("book"):
                stats["addedStamped"] += 1
            merged[lid] = fresh
            continue
        prev = merged[lid]
        if fresh.get("book"):
            if not prev.get("book"):
                stats["upgraded"] += 1
            elif first_ask(fresh) != first_ask(prev):
                stats["restamped"] += 1
            merged[lid] = fresh
        else:
            if prev.get("book"):
                stats["keptOldEvidence"] += 1
            # keep the old record either way: same absence, older provenance is the better trace
    # re-stamp provenance: a leg kept from the old snapshot is 'old', a leg replaced is 'new'
    legs = [dict(l) for l in merged.values()]

    out = dict(new)  # newest snapshot's book/tape/refutation/coverage blocks
    out["legs"] = legs
    out["mergedFrom"] = {"old": (old.get("ranAt")), "new": new.get("ranAt")}
    out["ranAt"] = new.get("ranAt")
    out["unionLegs"] = len(legs)
    out["aggregatesCover"] = {
        "note": "book/tape/refutation/coverage above describe the newest snapshot run ONLY, not the union",
        "legs": len(new["legs"]),
        "scopeSinceMs": (new.get("coverage") or {}).get("scopeSinceMs"),
        "ranAt": new.get("ranAt"),
    }
    out["mergeStats"] = dict(stats)
    out["unionRefutation"] = union_refutation(legs, new)

    d = os.path.dirname(os.path.abspath(out_p))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".stamp-merge-", suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf8") as fh:
            fh.write(json.dumps(out) + "\n")
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; the artifact is a shared repo file
        os.replace(tmp, out_p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    print(
        f"old legs {len(old['legs'])} · new legs {len(new['legs'])} · union {len(legs)} "
        f"· added {stats['added']} (stamped {stats['addedStamped']}) · upgraded {stats['upgraded']} "
        f"· kept old evidence {stats['keptOldEvidence']}"
    )
    print(
        "MERGE "
        f"old={len(old['legs'])} new={len(new['legs'])} union={len(legs)} "
        f"added={stats['added']} addedStamped={stats['addedStamped']} upgraded={stats['upgraded']} "
        f"keptOldEvidence={stats['keptOldEvidence']} restamped={stats['restamped']}"
    )
    print("per-source", Counter(l.get("_src") for l in legs))
    u = out["unionRefutation"]
    print(
        "[stamp-merge] UNION VERDICT (population = the whole union, not this tick): "
        f"n={u.get('n')}/{u.get('offered')} stamped, gate {u.get('gate')} "
        f"{'MET' if u.get('gateMet') else 'NOT MET'}"
    )
    if u.get("error"):
        print(f"[stamp-merge] union verdict unavailable: {u['reason']}")
    else:
        print(
            f"[stamp-merge] (attainable - booked): mid {u['meanMidC']:+.2f}c mean "
            f"({u['medianMidC']:+.2f}c median, {100 * (u['shareWithinBand'] or 0):.0f}% within "
            f"±{u['bandC']}c) | ASK {u['meanAskC']:+.2f}c mean, at-or-better "
            f"{100 * (u['shareAtOrBetter'] or 0):.0f}%, worse-by-1c+ "
            f"{100 * (u['shareWorseBy1c'] or 0):.0f}% | ${u['notionalUsd']:,.0f} notional, "
            f"${u['moneyAtAskUsd']:+,.2f} = {u['shareNotionalAtAsk']:+.2f}% at the ask"
        )
        print(f"[stamp-merge] {u['reason']}")
        _lb = u.get("lagBuckets")
        lb = _lb if isinstance(_lb, dict) else {}
        if lb:
            order = ["0-10s", "10-30s", "30-60s", "1-5m", "5-30m", "30-60m"]
            print("[stamp-merge] ask-minus-booked by coverage lag (spread vs drift): "
                  + " · ".join(f"{k} {lb[k]['meanAskC']:+.2f}c/{lb[k]['n']}"
                               for k in order if k in lb))
    print(
        "UNIONREF "
        f"n={u.get('n')} gate={u.get('gate')} gateMet={u.get('gateMet')} fired={u.get('fired')} "
        f"meanMidC={u.get('meanMidC')} meanAskC={u.get('meanAskC')} "
        f"atOrBetter={u.get('shareAtOrBetter')} moneyAtAskUsd={u.get('moneyAtAskUsd')}"
    )


if __name__ == "__main__":
    main()
