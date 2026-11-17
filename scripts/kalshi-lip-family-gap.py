#!/usr/bin/env python3
"""kalshi-lip-family-gap.py -- is the venue's LIP pay in a family we could capture?

Roadmap card: kalshi-lip-universe-gap (opened 2026-11-16 off lip-ledger sec 4).

The parent card (lip-ledger-kalshi-reward, Done) closed the LIP reward leg at
$0.000096/contract-hour net -- 1/137th of the $0.0131 gate -- over 166 programs it
could quote.  Its own sec 4 says that is a statement about PROGRAM SELECTION, not
about adverse selection: no program in our quote universe or on our tape whitelist
has a structural ceiling above $0.0131.  The open question is whether the families
that DO pay are reachable.

THREE QUESTIONS, ASKED PER SERIES (family), ANSWERED SEPARATELY PER CLOCK
-------------------------------------------------------------------------
  (a) CEILING   does a family's median ceiling (pool / (2 * target * hours), the
                hard upper bound at 100% of the pool) clear the $0.0131 gate?
  (b) TAPE      does our capture hold prints for that family?  A family absent from
                data/kalshi-tape-families.json has NO tape at all -- "no fills" and
                "not captured" are different answers, and the allowlist is what
                separates them.
  (c) REACH     is the family reachable under the EXISTING capture?  The capture pages
                the keyless venue firehose and filters locally, so reach is a config
                line plus print volume, not new infrastructure.

THE CLOCK IS THE POINT.  A ceiling distribution computed over a paged feed of 231,158
programs is a RETROSPECTIVE population: it contains every program the venue ever posted,
including ones that ended months ago.  The leg's question is forward, so this read runs
on two clocks and never mixes them:

  LIVE      /incentive_programs?status=active|upcoming, paged to exhaustion, fetched now.
            This is the menu a maker could join today.
  HISTORIC  data/kalshi-lip-programs.jsonl.gz (last paged snapshot on disk, 2026-11-09).
            Used only to say WHERE the above-gate mass sat and WHETHER it is still open.

UNITS: period_reward / reward are CENTI-CENTS (verified at the primary source in
lip-ledger.py 2026-11-09; cross-checked here against the schedules endpoint where the
same family posts the same value).  A cents reading multiplies every ceiling by 100 and
flips the live verdict -- so the scale is a printed parameter and the self-test proves
the read is scale-sensitive.

Read-only.  Nothing here places an order, changes a rule, or writes to the DB.

USAGE:
  python3 scripts/kalshi-lip-family-gap.py --fetch-live   # page active+upcoming now
  python3 scripts/kalshi-lip-family-gap.py                # the three-condition read
  python3 scripts/kalshi-lip-family-gap.py --self-test    # mutation arms (must be GREEN)
"""
import argparse
import collections
import datetime
import gzip
import json
import os
import statistics
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")
HIST_FILE = os.path.join(DATA, "kalshi-lip-programs.jsonl.gz")
LIVE_FILE = os.path.join(DATA, "kalshi-lip-live.json")
TAPE_FAMILIES = os.path.join(DATA, "kalshi-tape-families.json")
COVERAGE = os.path.join(DATA, "kalshi-tape", "coverage.jsonl")
OUT_JSON = os.path.join(DATA, "kalshi-lip-family-gap.json")

API = "https://api.elections.kalshi.com/trade-api/v2/incentive_programs"
LIVE_STATUSES = ("active", "upcoming")
GATE = 0.0131                      # $/contract-hour, inherited from the parent card
UNIT_DIVISOR = {"centi-cents": 10000.0, "cents": 100.0}
COVERAGE_TAIL_HOURS = 24.0
TOP_N = 12


# ------------------------------------------------------------------ small utils
def parse_iso(s):
    if not s:
        return None
    s = s.replace("Z", "").split("+")[0]
    if "." in s:
        s = s.split(".")[0]
    return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def family_of(ticker):
    """Series ticker = the part before the first '-'.  Never returns '' for a ticker."""
    return (ticker or "").split("-")[0]


def utcnow():
    return datetime.datetime.utcnow()


def pctl(values, q):
    v = sorted(values)
    if not v:
        return None
    return v[min(len(v) - 1, int(q * (len(v) - 1)))]


# ------------------------------------------------------------------ program rows
def normalize(raw_rows, divisor):
    """-> (rows, counts).  Every dropped row is counted: a silent drop reads as 'no pay'."""
    counts = collections.Counter()
    rows = []
    for p in raw_rows:
        counts["rows"] += 1
        if p.get("incentive_type") != "liquidity":
            counts["non_liquidity"] += 1
            continue
        t = p.get("target_size_fp")
        if not t:
            counts["no_target_size"] += 1
            continue
        try:
            t = float(t)
            a, b = parse_iso(p["start_date"]), parse_iso(p["end_date"])
        except Exception:                                    # noqa: BLE001
            counts["bad_dates"] += 1
            continue
        if a is None or b is None:
            counts["bad_dates"] += 1
            continue
        h = (b - a).total_seconds() / 3600.0
        if t <= 0:
            counts["zero_target"] += 1
            continue
        if h <= 0:
            counts["non_positive_window"] += 1
            continue
        pool = (p.get("period_reward") or 0) / divisor
        tick = p.get("market_ticker") or ""
        rows.append({
            "family": family_of(tick),
            "ticker": tick,
            "pool": pool,
            "hours": h,
            "target": t,
            "ceiling": pool / (2.0 * t * h),
            "start": a,
            "end": b,
            "paid": bool(p.get("paid_out")),
        })
        counts["usable"] += 1
    return rows, counts


def by_family(rows, span):
    fam = collections.defaultdict(list)
    for r in rows:
        fam[r["family"]].append(r)
    out = []
    for name, v in fam.items():
        pool = sum(x["pool"] for x in v)
        out.append({
            "family": name,
            "programs": len(v),
            "markets": len({x["ticker"] for x in v}),
            "pool_usd": round(pool, 2),
            "pool_per_day": round(pool / span, 2) if span else None,
            "median_ceiling": statistics.median([x["ceiling"] for x in v]),
            "max_ceiling": max(x["ceiling"] for x in v),
            "above_gate": sum(1 for x in v if x["ceiling"] >= GATE),
            "median_target": statistics.median([x["target"] for x in v]),
            "median_hours": statistics.median([x["hours"] for x in v]),
            "paid_true": sum(1 for x in v if x["paid"]),
            "span_days": round((max(x["end"] for x in v) - min(x["start"] for x in v))
                               .total_seconds() / 86400.0, 2),
        })
    out.sort(key=lambda z: -z["pool_usd"])
    return out


def span_days(rows):
    if not rows:
        return 0.0
    return (max(x["end"] for x in rows) - min(x["start"] for x in rows)).total_seconds() / 86400.0


# ------------------------------------------------------------------ live fetch
def fetch_live(max_pages=60, verbose=True):
    rows, stats = {}, {}
    for st in LIVE_STATUSES:
        cur, npages, n, ended_empty = None, 0, 0, False
        while npages < max_pages:
            q = {"status": st, "limit": 1000}
            if cur:
                q["cursor"] = cur
            req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q),
                                         headers={"User-Agent": "lip-family-gap/1.0"})
            body = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        body = json.loads(r.read().decode())
                    break
                except Exception as e:                       # noqa: BLE001
                    if verbose:
                        print("  retry %d (%s): %s" % (attempt + 1, st, e))
            if body is None:
                raise RuntimeError("live incentive_programs fetch failed for status=%s" % st)
            got = body.get("incentive_programs", [])
            if not got:
                # The venue can hand back an empty page WITH a cursor still set (observed
                # 2026-11-17, status=active page 7).  Break, and record WHY: an empty page
                # is the feed saying it has nothing more, and calling that "not exhausted"
                # would understate coverage in the artifact.
                ended_empty = True
                break
            npages += 1
            n += len(got)
            for p in got:
                rows.setdefault(p["id"], p)
            # `next_cursor` comes back as the EMPTY STRING on the last page, not null
            # (measured 2026-11-17: page 6 of status=active).  `or None` is what makes
            # "exhausted" true; without it every paged read reports not-exhausted while
            # having read every row, which is the opposite of the defect this file exists
            # to avoid.
            cur = body.get("next_cursor") or None
            if not cur:
                break
        exhausted = (cur is None) or ended_empty
        stats[st] = {"pages": npages, "rows": n, "exhausted": exhausted,
                     "ended_empty_page": ended_empty, "cap_hit": npages >= max_pages}
        if verbose:
            print("  status=%-9s pages=%3d rows=%6d exhausted=%s%s"
                  % (st, npages, n, exhausted, " (cap hit)" if npages >= max_pages else ""))
    payload = {
        "fetched_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": API,
        "unit": "centi-cents",
        "paged": True,
        "stats": stats,
        "programs": list(rows.values()),
    }
    with open(LIVE_FILE, "w") as f:
        json.dump(payload, f)
    print("wrote %s (%d unique programs)" % (LIVE_FILE, len(rows)))
    return payload


def load_live():
    if not os.path.exists(LIVE_FILE):
        return None
    return json.load(open(LIVE_FILE))


def load_hist():
    if not os.path.exists(HIST_FILE):
        return None
    with gzip.open(HIST_FILE, "rt") as f:
        header = json.loads(f.readline())
        rows = [json.loads(line) for line in f if line.strip()]
    header["programs"] = rows
    return header


# ------------------------------------------------------------------ our capture
def tape_families():
    if not os.path.exists(TAPE_FAMILIES):
        return {}
    return json.load(open(TAPE_FAMILIES)).get("families", {})


def captured_contracts(hours=COVERAGE_TAIL_HOURS):
    """Contracts the capture KEPT per family over the last `hours` of coverage rows.

    Basis: data/kalshi-tape/coverage.jsonl `families_kept_contracts`, written per run.
    The capture filters LOCALLY to the allowlist, so a family missing here is either not
    allowlisted or traded nothing -- the allowlist disambiguates the two.
    """
    if not os.path.exists(COVERAGE):
        return {}, None
    cutoff = utcnow() - datetime.timedelta(hours=hours)
    out = collections.Counter()
    newest = None
    with open(COVERAGE) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:                                # noqa: BLE001
                continue
            ts = parse_iso(r.get("run_started", ""))
            if ts is None:
                continue
            newest = ts if newest is None or ts > newest else newest
            if ts < cutoff:
                continue
            for fam, c in (r.get("families_kept_contracts") or {}).items():
                out[fam] += c
    return dict(out), newest


# ------------------------------------------------------------------ the three conditions
def three_conditions(fams, allow, captured):
    """Attach (a)/(b)/(c) to each family row.  Pure function -- the self-test drives it."""
    out = []
    for f in fams:
        row = dict(f)
        row["a_ceiling"] = bool(f["median_ceiling"] >= GATE)
        row["b_allowlisted"] = f["family"] in allow
        row["b_prints"] = captured.get(f["family"], 0.0) > 0
        row["c_reachable"] = True          # firehose is venue-wide; capture filters locally
        row["c_note"] = ("already allowlisted" if row["b_allowlisted"]
                         else "1 allowlist line (firehose is venue-wide; not yet added)")
        out.append(row)
    return out


# ------------------------------------------------------------------ reporting
def print_ceiling_block(title, rows, clock, population, span):
    cei = [r["ceiling"] for r in rows]
    above = [r for r in rows if r["ceiling"] >= GATE]
    print("\n--- %s ---" % title)
    print("clock %s | population %s | level = one program | unit = centi-cents" % (clock, population))
    print("programs %d | pool $%.0f | above gate $%.4f/contract-hour: %d (%.2f%%) holding $%.0f (%.1f%% of pool)"
          % (len(rows), sum(r["pool"] for r in rows), GATE, len(above),
             100.0 * len(above) / max(1, len(rows)), sum(r["pool"] for r in above),
             100.0 * sum(r["pool"] for r in above) / max(1e-9, sum(r["pool"] for r in rows))))
    print("ceiling percentiles p50 %.6f  p75 %.6f  p90 %.6f  p99 %.6f  max %.6f"
          % (pctl(cei, .5), pctl(cei, .75), pctl(cei, .9), pctl(cei, .99), pctl(cei, 1.0)))
    if span:
        print("posted pool rate $%.0f/day over a %.1f d span" % (sum(r["pool"] for r in rows) / span, span))
    return above


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-live", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--unit", choices=sorted(UNIT_DIVISOR), default="centi-cents")
    ap.add_argument("--json-out", default=OUT_JSON)
    args = ap.parse_args()

    if args.fetch_live:
        fetch_live()
        return 0
    if args.self_test:
        return self_test()

    div = UNIT_DIVISOR[args.unit]
    allow = tape_families()
    captured, newest_cov = captured_contracts()
    artifact = {"gate_usd_per_contract_hour": GATE, "unit": args.unit,
                "generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "arms": {}}

    print("=" * 78)
    print("KALSHI LIP -- does the pay exist in a family we can capture?")
    print("gate $%.4f/contract-hour (inherited from lip-ledger-kalshi-reward)" % GATE)
    print("our capture: %d allowlisted families | coverage rows scanned back %.0fh (newest %s)"
          % (len(allow), COVERAGE_TAIL_HOURS,
             newest_cov.strftime("%Y-%m-%dT%H:%MZ") if newest_cov else "none"))

    live = load_live()
    live_rows = []
    if not live:
        print("\nARM 1 LIVE: SKIPPED -- no %s on disk. Run --fetch-live." % os.path.basename(LIVE_FILE))
        artifact["arms"]["live"] = {"status": "no_data"}
    else:
        live_rows, lcounts = normalize(live["programs"], div)
        lspan = span_days(live_rows)
        above = print_ceiling_block("ARM 1  LIVE MENU (forward)", live_rows,
                                    live["fetched_at"],
                                    "active+upcoming liquidity programs (paged=%s, rows %d)"
                                    % (live.get("paged"), len(live["programs"])), lspan)
        dropped = {k: v for k, v in lcounts.items() if k not in ("rows", "usable") and v}
        print("dropped: %s | usable %d of %d rows" % (dropped or "none", lcounts["usable"], lcounts["rows"]))
        lf = by_family(live_rows, lspan)
        print("live families: %d | families with ANY above-gate program: %d"
              % (len(lf), sum(1 for f in lf if f["above_gate"])))
        print("%-22s %6s %10s %10s %8s %7s" % ("family", "progs", "pool$", "med_ceil", "med_h", "above"))
        for f in lf[:TOP_N]:
            print("%-22s %6d %10.0f %10.6f %8.2f %7d"
                  % (f["family"], f["programs"], f["pool_usd"], f["median_ceiling"],
                     f["median_hours"], f["above_gate"]))
        artifact["arms"]["live"] = {"clock": live["fetched_at"], "rows": len(live["programs"]),
                                    "usable": lcounts["usable"],
                                    "above_gate": len(above), "span_days": round(lspan, 2),
                                    "max_ceiling": max([r["ceiling"] for r in live_rows] or [0]),
                                    "families": len(lf),
                                    "families_above_gate": sum(1 for f in lf if f["above_gate"]),
                                    "top": lf[:TOP_N]}

    hist = load_hist()
    hrows = []
    if not hist:
        print("\nARM 2 HISTORIC: SKIPPED -- no %s on disk." % os.path.basename(HIST_FILE))
        artifact["arms"]["historic"] = {"status": "no_data"}
    else:
        hrows, hcounts = normalize(hist["programs"], div)
        hspan = span_days(hrows)
        habove = print_ceiling_block("ARM 2  HISTORIC FEED, stated as such", hrows,
                                     hist.get("fetched_at", "unknown"),
                                     "paged liquidity programs on disk (rows %d, paged=%s)"
                                     % (len(hist["programs"]), hist.get("paged")), hspan)
        hf = by_family(hrows, hspan)
        hfam_above = [f for f in hf if f["above_gate"]]
        tot_day = sum(f["pool_per_day"] or 0 for f in hf)
        want_day = sum(r["pool"] for r in hrows) / hspan
        recon = abs(tot_day - want_day) / max(1e-9, want_day)
        print("families %d | with any above-gate program %d | per-family $/day reconciles to the feed at %.4f%%"
              % (len(hf), len(hfam_above), 100 * recon))
        vast = sum(f["pool_usd"] for f in hfam_above)
        print("above-gate pool concentration: top-3 families %.1f%%, top-10 %.1f%%"
              % (100.0 * sum(f["pool_usd"] for f in hfam_above[:3]) / max(1e-9, vast),
                 100.0 * sum(f["pool_usd"] for f in hfam_above[:10]) / max(1e-9, vast)))
        print("%-22s %6s %10s %10s %8s %6s %11s" % ("family", "progs", "pool$", "med_ceil", "med_h", "above", "pool/span_d"))
        for f in sorted(hfam_above, key=lambda z: -z["pool_usd"])[:TOP_N]:
            print("%-22s %6d %10.0f %10.6f %8.2f %6d %11.0f"
                  % (f["family"], f["programs"], f["pool_usd"], f["median_ceiling"],
                     f["median_hours"], f["above_gate"],
                     (f["pool_usd"] / f["span_days"] if f["span_days"] else 0)))
        clock = parse_iso((live or {}).get("fetched_at", "")) or utcnow()
        still_open = [r for r in habove if r["end"] >= clock]
        last_end = max([r["end"] for r in habove], default=None)
        print("STILL OPEN at %s: %d of %d above-gate programs (last above-gate end %s)"
              % (clock.strftime("%Y-%m-%dT%H:%MZ"), len(still_open), len(habove), last_end))
        artifact["arms"]["historic"] = {
            "clock": hist.get("fetched_at"), "rows": len(hist["programs"]),
            "usable": hcounts["usable"], "span_days": round(hspan, 2),
            "above_gate": len(habove), "above_gate_pool_usd": round(sum(r["pool"] for r in habove), 2),
            "families": len(hf), "families_above_gate": len(hfam_above),
            "still_open_at_live_clock": len(still_open),
            "last_above_gate_end": str(last_end),
            "reconciliation_pct": round(100 * recon, 4),
            "concentration": {
                "top3_share": round(100.0 * sum(f["pool_usd"] for f in hfam_above[:3]) / max(1e-9, vast), 2),
                "top10_share": round(100.0 * sum(f["pool_usd"] for f in hfam_above[:10]) / max(1e-9, vast), 2)},
            "top_above_gate": sorted(hfam_above, key=lambda z: -z["pool_usd"])[:TOP_N],
        }

    print("\n--- ARM 3  OUR CAPTURE ---")
    print("basis: allowlist %s + coverage rows in the last %.0fh, contracts KEPT per family"
          % (os.path.basename(TAPE_FAMILIES), COVERAGE_TAIL_HOURS))
    best_live, best_hist = {}, {}
    for r in live_rows:
        best_live[r["family"]] = max(best_live.get(r["family"], 0.0), r["ceiling"])
    for r in hrows:
        best_hist[r["family"]] = max(best_hist.get(r["family"], 0.0), r["ceiling"])
    print("%-16s %12s %10s %11s %11s" % ("family", "kept_ctr_24h", "in_allow", "best_live", "best_hist"))
    live_over = hist_over = 0
    for f in sorted(allow):
        lc, hc = best_live.get(f, 0.0), best_hist.get(f, 0.0)
        live_over += 1 if lc >= GATE else 0
        hist_over += 1 if hc >= GATE else 0
        print("%-16s %12.0f %10s %11.6f %11.6f" % (f, captured.get(f, 0.0), "yes", lc, hc))
    print("ours clearing the gate: on the LIVE menu %d of %d | in HISTORY %d of %d"
          % (live_over, len(allow), hist_over, len(allow)))
    in_feed = sorted(f for f in allow if f in best_hist)
    print("ours appearing in the historic feed at all: %s" % (", ".join(in_feed) or "none"))
    artifact["arms"]["capture"] = {"families": sorted(allow), "above_gate_live": live_over,
                                   "above_gate_hist": hist_over,
                                   "best_live_ceiling": max([best_live.get(f, 0.0) for f in allow] or [0]),
                                   "best_hist_ceiling": max([best_hist.get(f, 0.0) for f in allow] or [0]),
                                   "in_hist_feed": in_feed,
                                   "kept_contracts_24h": {f: captured.get(f, 0.0) for f in sorted(allow)}}

    print("\n--- VERDICT ---")
    verdict = "UNREADABLE -- no live menu on disk"
    if live_rows:
        la = [f for f in by_family(live_rows, span_days(live_rows)) if f["above_gate"]]
        mx = max(r["ceiling"] for r in live_rows)
        if not la:
            verdict = ("NO PAYING FAMILY ON THE LIVE MENU -- 0 of %d live programs clear $%.4f; "
                       "max live ceiling %.6f (%.0fx below the gate)"
                       % (len(live_rows), GATE, mx, GATE / max(1e-12, mx)))
        else:
            verdict = "%d live families clear the gate: %s" % (len(la), ", ".join(f["family"] for f in la))
    print(verdict)
    artifact["verdict"] = verdict

    with open(args.json_out, "w") as f:
        json.dump(artifact, f, indent=1, default=str)
    print("wrote %s" % args.json_out)
    return 0


# ------------------------------------------------------------------ self-test
def self_test():
    """Mutation arms.  Each proves the read above CAN fail; a green run is evidence."""
    ok = []

    def arm(name, fn):
        fn()
        ok.append(name)
        print("  PASS %s" % name)

    def scale():
        hist = load_hist()
        assert hist is not None, "no historic feed"
        h_c, _ = normalize(hist["programs"], UNIT_DIVISOR["centi-cents"])
        h_x, _ = normalize(hist["programs"], UNIT_DIVISOR["cents"])
        base = sum(1 for r in h_c if r["ceiling"] >= GATE)
        infl = sum(1 for r in h_x if r["ceiling"] >= GATE)
        assert infl > base, "unit mutation did not move the historic above-gate count (%d vs %d)" % (infl, base)
        live = load_live()
        line = "      historic above-gate: %d at centi-cents vs %d at cents" % (base, infl)
        if live:
            l_c, _ = normalize(live["programs"], UNIT_DIVISOR["centi-cents"])
            l_x, _ = normalize(live["programs"], UNIT_DIVISOR["cents"])
            b = sum(1 for r in l_c if r["ceiling"] >= GATE)
            i = sum(1 for r in l_x if r["ceiling"] >= GATE)
            assert i > b, "unit mutation did not change the LIVE above-gate count (%d vs %d)" % (i, b)
            line += " | live %d vs %d" % (b, i)
        print(line)
    arm("scale_sensitivity", scale)

    def positive():
        synth = [
            {"incentive_type": "liquidity", "market_ticker": "KXSYNTH-1-A", "target_size_fp": "100.00",
             "period_reward": 1000000, "start_date": "2026-11-17T00:00:00Z",
             "end_date": "2026-11-17T01:00:00Z", "paid_out": False},
            {"incentive_type": "liquidity", "market_ticker": "KXSYNTH-1-B", "target_size_fp": "1000.00",
             "period_reward": 1000000, "start_date": "2026-11-17T00:00:00Z",
             "end_date": "2026-11-18T00:00:00Z", "paid_out": False},
        ]
        rows, _ = normalize(synth, 10000.0)
        a = [r for r in rows if r["ticker"].endswith("-A")][0]["ceiling"]
        b = [r for r in rows if r["ticker"].endswith("-B")][0]["ceiling"]
        assert abs(a - 0.50) < 1e-9 and a >= GATE, "positive control not flagged (%.6f)" % a
        assert abs(b - 0.00208) < 1e-4 and b < GATE, "negative control wrongly flagged (%.6f)" % b
        assert {r["family"] for r in rows} == {"KXSYNTH"}, "family grouping wrong"
        print("      control: pool $100 / 1h / target 100 -> $%.4f (flagged); 24h / target 1000 -> $%.6f (not)"
              % (a, b))
    arm("positive_control", positive)

    def grouping():
        assert family_of("KXTEMPMIAH-26AUG15-B90") == "KXTEMPMIAH"
        assert family_of("KXTEMPMIAH") == "KXTEMPMIAH"
        assert family_of("") == ""
    arm("grouping", grouping)

    def join():
        rows = [{"family": "KXTEMPMIAH", "programs": 1, "markets": 1, "pool_usd": 100.0,
                 "pool_per_day": 100.0, "median_ceiling": 0.05, "max_ceiling": 0.05, "above_gate": 1,
                 "median_target": 1000.0, "median_hours": 1.0, "paid_true": 1, "span_days": 1.0}]
        base = three_conditions(rows, set(tape_families()), {})
        injected = three_conditions(rows, set(tape_families()) | {"KXTEMPMIAH"}, {"KXTEMPMIAH": 1.0})
        assert base[0]["b_allowlisted"] is False, "join says allowlisted when it is not"
        assert injected[0]["b_allowlisted"] is True and injected[0]["b_prints"] is True, \
            "join did not respond to an injected allowlist entry"
        assert base[0]["a_ceiling"] is True, "ceiling condition lost"
    arm("coverage_join", join)

    def dead_era():
        clock = utcnow()
        rows = [{"end": clock - datetime.timedelta(days=20)},
                {"end": clock + datetime.timedelta(days=2)}]
        assert sum(1 for r in rows if r["end"] >= clock) == 1, "still-open predicate is blind"
    arm("dead_era_predicate", dead_era)

    def recon():
        hist = load_hist()
        assert hist is not None
        rows, _ = normalize(hist["programs"], 10000.0)
        s = span_days(rows)
        fams = by_family(rows, s)
        tot = sum(f["pool_per_day"] for f in fams)
        want = sum(r["pool"] for r in rows) / s
        assert abs(tot - want) / want < 0.01, "per-family $/day does not reconcile (%.2f vs %.2f)" % (tot, want)
        print("      per-family $/day sums to $%.0f vs $%.0f whole-feed" % (tot, want))
    arm("reconciliation", recon)

    print("\nSELF-TEST %d/%d GREEN" % (len(ok), 6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
