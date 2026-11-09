#!/usr/bin/env python3
"""
c200-taker-bookwalk — what would TAKING have cost on the legs we booked as MAKER?

CARD: t_20d58083 (board medusa) — "book-walk taker-fill replay on booked C-200 BUY legs
(decides the taker arm)". Approved 2026-11-09. READ-ONLY: no rule, size, gate or booked
figure moves; this writes an artifact and a draft only.

QUESTION (pre-registered)
The Rust sidecar books every C-200 BUY at `entry = intent - credit`, where the credit was a
FLAT 2c until 2026-10-09 and has been the MEASURED per-band fill share since 2026-10-10
(MAKER_CREDIT_MODE=measured, the live default; `modelled` restores the flat 2c). That credit
is an ASSUMPTION about a resting bid filling. A taker pays the ask ladder. This script walks
the recorded L2 book at the dispatch instant and reports the VWAP premium of a taker fill
over our assumed fill.

  DECISION RULE (fixed before the read): VWAP premium <= $0.02 on >= 50% of joined legs,
  with n >= 150 joined legs => open a maker-vs-taker comparison; ELSE close the taker arm
  permanently and record the null.
  The rule is evaluated on the FULL joined population, as written. Because the credit
  convention changed mid-population, the same statistic is ALSO reported per credit era —
  the flat-2c numbers are HISTORY and only the measured-era arm describes the lane today.

METHOD
  population  FillIntent (botId=BANKROLL_200, side=BUY) JOIN PaperTrade (booked legs only)
  book        data/l2/<tokenId>.jsonl (top-25 ladder, 5 s cadence). Primary snapshot is the one
              NEAREST the dispatch inside [-30s, +90s]; every row carries its signed lag.
  fill        shares = simulatedPositionSize / entryPrice (the lane risks DOLLARS, so a fixed
              dollar clip buys FEWER shares at a worse price); walk asks ascending until filled.
              Depth shortfalls are flagged, never silently priced at the top level.
  premium     vwap_ask - booked entryPrice  (the number the decision rule is written on).
              Also reported vs intentPrice (the venue mid we detected) and vs intent-0.02.

SENSITIVITY ARMS (same population, one assumption changed at a time)
  B  shares sized off intentPrice instead of entryPrice
  C  the first snapshot AT OR AFTER the dispatch (what a taker could hit going forward)
  D  primary arm restricted to |lag| <= 15 s

TOKEN IDENTITY (the trap that decides this measurement)
  A market has TWO outcome tokens and the sibling's book is ~1 - our price, so opening the
  wrong file manufactures a ~+50c "premium". Tokens are resolved from the venue's own labels
  (CLOB /markets/<conditionId> -> tokens[].outcome), cached to data/c200-token-map.jsonl, and
  every leg is then sanity-checked by mid proximity (|mid-intent| must beat |mid-(1-intent)|);
  a leg that fails is flagged `wrong_side` and EXCLUDED from the headline, never averaged in.

USAGE
  python3 scripts/c200-bookwalk-taker.py              # summary to stdout
  python3 scripts/c200-bookwalk-taker.py --json       # machine line only
  python3 scripts/c200-bookwalk-taker.py --md drafts/<f>.md
Artifact: data/c200-bookwalk-taker.jsonl (append-only run records)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sqlite3
import statistics
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
L2_DIR = os.path.join(ROOT, "data", "l2")
TOKEN_MAP = os.path.join(ROOT, "data", "c200-token-map.jsonl")
META = os.path.join(ROOT, "data", "c200-market-meta.jsonl")
OUT = os.path.join(ROOT, "data", "c200-bookwalk-taker.jsonl")

PREMIUM_BAR = 0.02      # decision rule: VWAP premium of a taker fill over our assumed fill
MIN_N = 150
WIN_LO_S, WIN_HI_S = 30, 90   # snapshot search window around the dispatch
CREDIT_CUTOVER_MS = 1791590400000   # 2026-10-10T00:00:00Z — first measured-credit legs
CLOB = "https://clob.polymarket.com/markets/%s"

# Documented Polymarket taker fee (docs.polymarket.com/trading/fees, fetched 2026-10-22):
# fee = shares x rate x p x (1-p). Rates are per category, carried by ObservedTrade's
# marketCategoryClass. Same table as scripts/fee-sign-flip-test.py::DOCS_RATE.
CLASS_MAP = {"crypto": "crypto", "sports": "sports", "esports": "sports", "politics": "politics",
             "tech": "tech", "econ": "economics", "culture": "culture", "weather": "weather",
             "other": "other"}
DOCS_RATE = {"crypto": 0.07, "sports": 0.05, "finance": 0.04, "politics": 0.04,
             "economics": 0.05, "culture": 0.05, "weather": 0.05, "other": 0.05,
             "mentions": 0.04, "tech": 0.04, "geopolitics": 0.0, "combos": 0.05}


def leg_fee_rate(klass):
    """Per-market taker rate from the documented category table (0.05 when unclassified)."""
    return DOCS_RATE.get(CLASS_MAP.get(str(klass or "").lower(), "other"), 0.05)


def db():
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


def norm(s):
    return " ".join(str(s or "").strip().lower().split())


def load_legs(since_ms=None):
    """Booked C-200 BUY legs. The PaperTrade join is the population: an intent with no row
    was gated or never filled and has no 'assumed fill' to be a premium over."""
    q = """
    SELECT f.id AS intentId, f.marketId, f.outcome, f.intentPrice, f.sizeUsd, f.dispatchedAt,
           p.id AS paperTradeId, p.entryPrice, p.simulatedPositionSize, p.status, p.openedAt,
           o.marketCategoryClass AS klass
    FROM FillIntent f
    JOIN PaperTrade p ON p.id = f.paperTradeId
    LEFT JOIN DecisionJournal j ON j.id = p.decisionJournalId
    LEFT JOIN ObservedTrade o ON o.id = j.observedTradeId
    WHERE f.botId = 'BANKROLL_200' AND UPPER(f.side) = 'BUY'
    """
    args = []
    if since_ms:
        q += " AND f.dispatchedAt >= ?"
        args.append(since_ms)
    return [dict(r) for r in db().execute(q + " ORDER BY f.dispatchedAt", args)]


def condition_map(markets):
    m = {}
    ids = [x for x in markets if x]
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        for r in db().execute(
                "SELECT DISTINCT marketId, conditionId FROM ObservedTrade "
                "WHERE conditionId IS NOT NULL AND marketId IN (%s)" % ",".join("?" * len(chunk)),
                chunk):
            m[r["marketId"]] = r["conditionId"]
    if os.path.exists(META):
        for line in open(META):
            try:
                o = json.loads(line)
            except Exception:
                continue
            m.setdefault(o.get("marketId"), o.get("conditionId"))
    return m


def token_map(markets, allow_network=True):
    """marketId -> {'conditionId':..., 'tokens':[{tokenId, outcome}]}. Cached on disk."""
    cached = {}
    if os.path.exists(TOKEN_MAP):
        for line in open(TOKEN_MAP):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("marketId") and o.get("tokens"):
                cached[o["marketId"]] = o
    missing = [m for m in markets if m not in cached]
    if missing and allow_network:
        cmap = condition_map(missing)
        for i, m in enumerate(missing):
            cid = cmap.get(m)
            if not cid:
                continue
            raw = subprocess.run(["curl", "-s", "--max-time", "25", CLOB % cid],
                                 capture_output=True, text=True).stdout
            try:
                o = json.loads(raw)
                toks = [{"tokenId": t.get("token_id"), "outcome": t.get("outcome")}
                        for t in (o.get("tokens") or []) if t.get("token_id")]
            except Exception:
                toks = []
            if toks:
                rec = {"marketId": m, "conditionId": cid, "tokens": toks,
                       "ts": int(time.time() * 1000)}
                cached[m] = rec
                with open(TOKEN_MAP, "a") as fh:
                    fh.write(json.dumps(rec) + "\n")
            if i and i % 50 == 0:
                time.sleep(0.5)
    return cached


def pick_token(rec, outcome):
    """Venue-label match only; never guess between ambiguous labels."""
    if not rec:
        return None, "no-token-map"
    want = norm(outcome)
    hits = [t for t in rec["tokens"] if norm(t["outcome"]) == want]
    if len(hits) == 1:
        return hits[0]["tokenId"], "venue-label"
    if len(hits) > 1:
        return None, "ambiguous-label"
    return None, "label-miss(%s)" % "/".join(t["outcome"] for t in rec["tokens"])


def _line_ts(fh):
    """Next complete JSON line from the current position -> (ts, None) or (None, None)."""
    while True:
        ln = fh.readline()
        if not ln:
            return None
        if ln[:1] != b"{":
            continue
        try:
            return json.loads(ln).get("ts")
        except Exception:
            continue


def l2_window(path, t0, lo_s=WIN_LO_S, hi_s=WIN_HI_S):
    """Snapshots inside [t0-lo, t0+hi].

    The files are append-only and ts-monotonic, but the WRITE RATE is not uniform: the recorder
    subscribes to a market in bursts separated by days of silence, so mapping a timestamp to a
    byte offset by linear interpolation between the first and last ts lands in the wrong region
    for exactly those files and silently reports `no_snapshot_in_window` for legs that ARE
    covered (measured 2026-11-09: 43 of 50 such legs had 14-24 snapshots inside the window).
    Binary-search the byte offset of the first line with ts >= t_lo instead, then stream to t_hi.
    """
    t_lo = t0 - lo_s * 1000
    t_hi = t0 + hi_s * 1000
    size = os.path.getsize(path)
    out = []
    with open(path, "rb") as fh:
        lo, hi, best = 0, size, size
        while lo < hi:
            mid = (lo + hi) // 2
            fh.seek(mid)
            if mid:
                fh.readline()          # drop the partial line
            ts = _line_ts(fh)
            if ts is None or ts >= t_lo:
                best = mid if ts is not None else best
                hi = mid
            else:
                lo = mid + 1
        start = max(0, best - 65536)
        fh.seek(start)
        if start:
            fh.readline()
        read = 0
        while read < 4_000_000:        # a window holds ~24 lines; the cap only bounds damage
            ln = fh.readline()
            if not ln:
                break
            read += len(ln)
            if ln[:1] != b"{":
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            ts = o.get("ts")
            if ts is None:
                continue
            if ts > t_hi:
                break
            if ts >= t_lo and o.get("asks"):
                out.append(o)
    return out


def walk(asks, shares):
    """Ascending ask ladder -> (vwap, filled_fraction, depth_short)."""
    lv = []
    for p, s in asks:
        try:
            lv.append((float(p), float(s)))
        except Exception:
            continue
    lv.sort()
    need, cost, got = float(shares), 0.0, 0.0
    for px, sz in lv:
        if need <= 1e-12:
            break
        take = min(sz, need)
        cost += take * px
        got += take
        need -= take
    if got <= 0:
        return None, 0.0, True
    return cost / got, got / float(shares), need > 1e-9


def analyse(legs, allow_network=True):
    markets = sorted({l["marketId"] for l in legs})
    tmap = token_map(markets, allow_network=allow_network)
    rows, skip = [], collections.Counter()

    for l in legs:
        intent = float(l["intentPrice"])
        entry = float(l["entryPrice"]) if l["entryPrice"] else intent
        # Era is classified by the CREDIT ACTUALLY BOOKED, not by the calendar: the cutover
        # happened during 2026-10-10 (10 of that day's legs still carry the full 2c) and the
        # measured credit tops out at 0.458c, so credit == 2c uniquely identifies the retired
        # modelled convention.
        era = "flat2c" if (intent - entry) >= 0.0199 else "measured"
        rec = tmap.get(l["marketId"])
        token, how = pick_token(rec, l["outcome"])
        if not token:
            skip[how.split("(")[0]] += 1
            rows.append({"intentId": l["intentId"], "status": "no_token", "why": how,
                         "t0": l["dispatchedAt"], "era": era})
            continue
        path = os.path.join(L2_DIR, "%s.jsonl" % token)
        if not os.path.exists(path):
            skip["no_l2_file"] += 1
            rows.append({"intentId": l["intentId"], "status": "no_l2_file", "token": token,
                         "t0": l["dispatchedAt"], "era": era})
            continue
        snaps = l2_window(path, l["dispatchedAt"])
        if not snaps:
            skip["no_snapshot_in_window"] += 1
            rows.append({"intentId": l["intentId"], "status": "no_snapshot_in_window",
                         "token": token, "t0": l["dispatchedAt"], "era": era})
            continue
        # A one-sided book (asks only, no bids) can price a taker BUY but cannot pass the
        # mid-proximity identity check, so it is excluded AND labelled: calling it
        # "no_snapshot" when snapshots exist is the label-lies defect.
        snaps = [o for o in snaps if o.get("bids")]
        if not snaps:
            skip["one_sided_book"] += 1
            rows.append({"intentId": l["intentId"], "status": "one_sided_book",
                         "token": token, "t0": l["dispatchedAt"], "era": era})
            continue

        snap = min(snaps, key=lambda o: abs(o["ts"] - l["dispatchedAt"]))
        after = [o for o in snaps if o["ts"] >= l["dispatchedAt"]]
        snap_after = min(after, key=lambda o: o["ts"]) if after else None

        best_bid = max(float(x[0]) for x in snap["bids"])
        best_ask = min(float(x[0]) for x in snap["asks"])
        mid = (best_bid + best_ask) / 2.0
        usd = float(l["simulatedPositionSize"] or l["sizeUsd"])
        shares_entry = usd / entry if entry > 0 else 0.0
        shares_intent = usd / intent if intent > 0 else 0.0

        vwap, filled, short = walk(snap["asks"], shares_entry)
        vwap_b, _, short_b = walk(snap["asks"], shares_intent)
        vwap_c = None
        short_c = True
        if snap_after is not None:
            vwap_c, _, short_c = walk(snap_after["asks"], shares_entry)

        wrong = False
        if abs(0.5 - intent) > 0.1:
            wrong = abs(mid - (1.0 - intent)) < abs(mid - intent)

        # sibling book (the other outcome of the same market): the identity control. For a
        # correctly-labelled leg it must sit at ~1 - our mid; for a wrong-side leg at ~our intent.
        sib_mid, sib_label = None, None
        if rec:
            for t in rec["tokens"]:
                if t["tokenId"] != token:
                    sib_label = t["outcome"]
                    sp = os.path.join(L2_DIR, "%s.jsonl" % t["tokenId"])
                    if os.path.exists(sp):
                        ss = [o for o in l2_window(sp, l["dispatchedAt"]) if o.get("bids")]
                        if ss:
                            so = min(ss, key=lambda o: abs(o["ts"] - l["dispatchedAt"]))
                            sb = max(float(x[0]) for x in so["bids"])
                            sa = min(float(x[0]) for x in so["asks"])
                            sib_mid = round((sb + sa) / 2.0, 4)
                    break

        rows.append({
            "intentId": l["intentId"], "marketId": l["marketId"], "outcome": l["outcome"],
            "status": "ok", "token": token, "tokenResolvedBy": how,
            "klass": l.get("klass"),
            "t0": l["dispatchedAt"], "era": era,
            "lag_s": round((snap["ts"] - l["dispatchedAt"]) / 1000.0, 1),
            "lag_after_s": None if snap_after is None else round((snap_after["ts"] - l["dispatchedAt"]) / 1000.0, 1),
            "n_snaps": len(snaps), "intent": intent, "entry": entry, "size_usd": usd,
            "shares": round(shares_entry, 6), "best_bid": best_bid, "best_ask": best_ask,
            "spread": round(best_ask - best_bid, 4), "mid": round(mid, 4),
            "vwap": None if vwap is None else round(vwap, 6), "filled_frac": round(filled, 4),
            "depth_short": short, "wrong_side": wrong,
            "vwap_B": None if vwap_b is None else round(vwap_b, 6), "depth_short_B": short_b,
            "vwap_C": None if vwap_c is None else round(vwap_c, 6), "depth_short_C": short_c,
            "sib_mid": sib_mid, "sib_label": sib_label,
            "premium_vs_entry": None if vwap is None else round(vwap - entry, 6),
            "premium_vs_intent": None if vwap is None else round(vwap - intent, 6),
            "premium_vs_flat2c": None if vwap is None else round(vwap - max(0.01, intent - 0.02), 6),
            "premium_B": None if vwap_b is None else round(vwap_b - entry, 6),
            "premium_C": None if vwap_c is None else round(vwap_c - entry, 6),
        })
    return rows, skip


def _stat(arr):
    a = sorted(arr)
    n = len(a)
    if not n:
        return None

    def pick(q):
        return a[min(n - 1, int(q * (n - 1)))]

    return {"n": n, "mean": round(statistics.mean(a), 4), "median": round(statistics.median(a), 4),
            "p10": round(pick(.1), 4), "p25": round(pick(.25), 4), "p75": round(pick(.75), 4),
            "p90": round(pick(.9), 4)}


def arm(rows, key="premium_vs_entry", label=None):
    """Decision statistic for one premium column on the rows that carry it."""
    vals = [(r[key], r["size_usd"]) for r in rows if r.get(key) is not None]
    if not vals:
        return None
    prem = [v for v, _ in vals]
    usd = sum(w for _, w in vals)
    d = {"premium": _stat(prem),
         "share_le_2c": round(sum(1 for x in prem if x <= PREMIUM_BAR) / len(prem), 4),
         "share_le_1c": round(sum(1 for x in prem if x <= 0.01) / len(prem), 4),
         "share_le_0": round(sum(1 for x in prem if x <= 0.0) / len(prem), 4),
         "usd_weighted_mean": round(sum(v * w for v, w in vals) / usd, 4) if usd else None,
         "share_le_2c_usd_weighted": round(
             sum(w for v, w in vals if v <= PREMIUM_BAR) / usd, 4) if usd else None,
         "filled_full_share": round(sum(1 for r in rows if r.get("filled_frac", 0) >= 0.999) / len(rows), 4)}
    if label:
        d["label"] = label
    d["passes_rule"] = bool(len(prem) >= MIN_N and d["share_le_2c"] >= 0.5)
    return d


def tape_label_control(rows):
    """Independent label source: the older print-through tape pick (outcome-label) per intent.
    A venue-label pick that disagrees with it would mean the token map is wrong, not the tape."""
    p = os.path.join(ROOT, "data", "c200-printthrough.jsonl")
    if not os.path.exists(p):
        return None
    tape = {}
    with open(p) as fh:
        for ln in fh:
            try:
                o = json.loads(ln)
            except Exception:
                continue
            for l in o.get("legs") or []:
                if l.get("intentId") and l.get("token"):
                    tape[l["intentId"]] = l["token"]
    j = [r for r in rows if r.get("status") == "ok" and r["intentId"] in tape]
    return {"joined_with_tape_label": len(j),
            "agree": sum(1 for r in j if tape[r["intentId"]] == r["token"])}


def summarise(rows):
    ok = [r for r in rows if r.get("status") == "ok" and r.get("vwap") and not r["depth_short"]]
    clean = [r for r in ok if not r["wrong_side"]]
    out: dict = {"legs_in": len(rows), "joined": len(ok), "joined_clean": len(clean),
           "wrong_side_excluded": len(ok) - len(clean),
           "depth_short_excluded": sum(1 for r in rows if r.get("status") == "ok" and r.get("depth_short"))}
    if not clean:
        out["decision"] = "CLOSE_TAKER_ARM"
        return out

    primary = arm(clean, "premium_vs_entry")
    out["primary"] = primary
    out["premium_vs_entry"] = primary["premium"]
    out["share_premium_le_2c"] = primary["share_le_2c"]
    out["share_premium_le_1c"] = primary["share_le_1c"]
    out["share_premium_le_0"] = primary["share_le_0"]
    out["usd_weighted_premium"] = primary["usd_weighted_mean"]
    out["share_premium_le_2c_usd_weighted"] = primary["share_le_2c_usd_weighted"]
    out["filled_full_share"] = primary["filled_full_share"]
    out["premium_vs_intent"] = arm(clean, "premium_vs_intent")
    out["premium_vs_flat2c"] = arm(clean, "premium_vs_flat2c")
    out["premium_vs_entry"] = primary["premium"]
    out["spread"] = _stat([r["spread"] for r in clean])
    out["lag_s"] = _stat([r["lag_s"] for r in clean])

    # sensitivity arms
    out["arms"] = {
        "A_primary": primary,
        "B_shares_off_intent": arm(clean, "premium_B"),
        "C_first_snapshot_at_or_after": arm(clean, "premium_C"),
        "D_lag_within_15s": arm([r for r in clean if abs(r["lag_s"]) <= 15], "premium_vs_entry"),
    }

    # the credit convention changed mid-population: the rule was written about the flat-2c
    # era, the lane books measured credit today. Report both, never blend them silently.
    eras = {}
    for e in ("flat2c", "measured"):
        sub = [r for r in clean if r["era"] == e]
        a = arm(sub, "premium_vs_entry")
        if a:
            eras[e] = a
    out["by_era"] = eras

    def band(p):
        for lo, hi in ((0.0, .1), (.1, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
            if lo <= p < hi:
                return "%.2f-%.2f" % (lo, hi)
        return "?"

    by_band = collections.defaultdict(list)
    for r in clean:
        by_band[band(r["entry"])].append(r["premium_vs_entry"])
    out["by_band"] = {k: {"n": len(v), "mean": round(statistics.mean(v), 4),
                          "median": round(statistics.median(v), 4),
                          "share_le_2c": round(sum(1 for x in v if x <= PREMIUM_BAR) / len(v), 3)}
                      for k, v in sorted(by_band.items())}

    # A taker pays the venue fee on top of the crossed price; the decision rule is written on
    # the VWAP premium alone, so this arm answers "would the verdict survive the fee?".
    # fee/share = rate * p * (1-p) (src/lib/scoring/price-edge.ts), rates 0.04/0.05/0.07
    # are the category map's min/default/max; fee-free categories make these upper bounds.
    out["with_fee"] = {}
    for rate in (0.04, 0.05, 0.07):
        vals = [(r["premium_vs_entry"] + rate * r["vwap"] * (1 - r["vwap"]), r["size_usd"])
                for r in clean]
        prem = [v for v, _ in vals]
        out["with_fee"]["rate_%.2f" % rate] = {
            "n": len(prem), "mean": round(statistics.mean(prem), 4),
            "median": round(statistics.median(prem), 4),
            "share_le_2c": round(sum(1 for x in prem if x <= PREMIUM_BAR) / len(prem), 4),
            "share_le_2c_usd_weighted": round(
                sum(w for v, w in vals if v <= PREMIUM_BAR) / sum(w for _, w in vals), 4)}
    # the measured-credit era is the arm the draft leans on, so the fee must be shown there too
    out["with_fee_by_era"] = {}
    for e, a in out.get("by_era", {}).items():
        sub = [r for r in clean if r["era"] == e]
        a["with_fee"] = {}
        a["with_fee"]["actual"] = round(
            sum(1 for r in sub
                if r["premium_vs_entry"] + leg_fee_rate(r.get("klass")) * r["vwap"] * (1 - r["vwap"])
                <= PREMIUM_BAR) / len(sub), 4)
        for rate in (0.04, 0.05, 0.07):
            prem = [r["premium_vs_entry"] + rate * r["vwap"] * (1 - r["vwap"]) for r in sub]
            a["with_fee"]["rate_%.2f" % rate] = round(
                sum(1 for x in prem if x <= PREMIUM_BAR) / len(prem), 4)
        out["with_fee_by_era"][e] = {"n": len(sub),
                                     "share_le_2c_with_fee": a["with_fee"]}

    # the per-market rate is the primary fee arm: the category table covers 100% of these legs
    fvals = [(r["premium_vs_entry"] + leg_fee_rate(r.get("klass")) * r["vwap"] * (1 - r["vwap"]),
              r["size_usd"]) for r in clean]
    fprem = [v for v, _ in fvals]
    out["with_fee_actual"] = {
        "n": len(fprem), "mean": round(statistics.mean(fprem), 4),
        "median": round(statistics.median(fprem), 4),
        "share_le_2c": round(sum(1 for x in fprem if x <= PREMIUM_BAR) / len(fprem), 4),
        "share_le_2c_usd_weighted": round(
            sum(w for v, w in fvals if v <= PREMIUM_BAR) / sum(w for _, w in fvals), 4),
        "rate_counts": dict(collections.Counter(
            "%.2f" % leg_fee_rate(r.get("klass")) for r in clean))}

    out["decision"] = "OPEN_MAKER_VS_TAKER" if primary["passes_rule"] else "CLOSE_TAKER_ARM"

    # identity control: the sibling book must sit at ~1 - our mid on a correctly-labelled leg,
    # and at ~our intent on a wrong-side leg. Reported so §side-finding is reproducible.
    ctl = [r for r in clean if r.get("sib_mid") is not None]
    ws = [r for r in ok if r["wrong_side"]]
    wsib = [r for r in ws if r.get("sib_mid") is not None]
    out["identity_control"] = {
        "clean_with_sibling_book": len(ctl),
        "clean_sibling_off_1_minus_mid_gt_5c": sum(
            1 for r in ctl if abs(r["sib_mid"] - (1 - r["mid"])) > 0.05),
        "wrong_side_n": len(ws), "wrong_side_with_sibling_book": len(wsib),
        "wrong_side_sibling_within_1c_of_intent": sum(
            1 for r in wsib if abs(r["sib_mid"] - r["intent"]) <= 0.01),
        "wrong_side_sibling_within_3c_of_intent": sum(
            1 for r in wsib if abs(r["sib_mid"] - r["intent"]) <= 0.03),
        "wrong_side_inconclusive": [
            {"marketId": r["marketId"], "outcome": r["outcome"], "intent": r["intent"],
             "sib_mid": r["sib_mid"], "sib_label": r.get("sib_label")}
            for r in wsib if abs(r["sib_mid"] - r["intent"]) > 0.03],
    }
    skip_era = collections.Counter(
        "%s/%s" % (r.get("status", "?"), r.get("era", "?"))
        for r in rows if r.get("status") != "ok")
    out["skipped_by_status_era"] = dict(skip_era)
    return out


def write_md(s, path_):
    L = []
    L.append("# C-200 taker book-walk replay — what crossing the spread would have cost\n")
    L.append("_Generated by `scripts/c200-bookwalk-taker.py` — every figure below is printed by that "
             "script from `FillIntent` × `PaperTrade` × `data/l2/`; nothing here is hand-typed._\n")
    L.append("## Decision rule (pre-registered 2026-11-09)\n")
    L.append("> VWAP premium <= 2c on >= 50% of joined legs with n >= 150 => open a maker-vs-taker "
             "comparison; ELSE close the taker arm permanently and record the null.\n")
    L.append("**Result: %s** — %d clean joined legs, %.1f %% of legs at or under the 2c bar "
             "(usd-weighted %.1f %%).\n" % (s["decision"], s["joined_clean"],
                                            100 * s["share_premium_le_2c"],
                                            100 * (s["share_premium_le_2c_usd_weighted"] or 0)))
    L.append("## Population and coverage\n")
    L.append("| item | value |")
    L.append("|---|---|")
    L.append("| booked C-200 BUY legs (PaperTrade join) | %d |" % s["legs_in"])
    L.append("| joined to an L2 book at dispatch | %d |" % s["joined"])
    L.append("| wrong-side legs excluded | %d |" % s["wrong_side_excluded"])
    L.append("| depth-short legs excluded | %d |" % s.get("depth_short_excluded", 0))
    L.append("| clean analysable | %d |" % s["joined_clean"])
    sk = s.get("skipped") or {}
    for k, v in sorted(sk.items()):
        L.append("| skipped: %s | %d |" % (k, v))
    L.append("")
    L.append("## Premium of a taker fill (cents, vs the booked maker entry)\n")
    L.append("| stat | value |")
    L.append("|---|---|")
    p = s["premium_vs_entry"]
    for k in ("mean", "median", "p10", "p25", "p75", "p90"):
        L.append("| %s | %+.2fc |" % (k, 100 * p[k]))
    L.append("| share <= 2c | %.1f %% |" % (100 * s["share_premium_le_2c"]))
    L.append("| share <= 1c | %.1f %% |" % (100 * s["share_premium_le_1c"]))
    L.append("| share <= 0 | %.1f %% |" % (100 * s["share_premium_le_0"]))
    L.append("| usd-weighted mean | %+.2fc |" % (100 * (s["usd_weighted_premium"] or 0)))
    L.append("")
    L.append("### Decomposition: which fill assumption the premium is measured against\n")
    L.append("| basis compared with | n | median premium | share <= 2c |")
    L.append("|---|---|---|---|")
    for key, label in (("premium_vs_entry", "booked maker entry (live convention)"),
                       ("premium_vs_intent", "venue mid at dispatch (pure crossing cost)"),
                       ("premium_vs_flat2c", "intent - 2c (retired flat convention, HISTORY)")):
        a = s.get(key)
        if not a:
            continue
        if "premium" in a:
            med = a["premium"]["median"]
            share = a["share_le_2c"]
            n = a["premium"]["n"]
        else:
            med = a["median"]
            share = s["share_premium_le_2c"]
            n = a["n"]
        L.append("| %s | %d | %+.2fc | %.1f %% |" % (label, n, 100 * med, 100 * share))
    L.append("")
    L.append("## By credit era (the convention changed 2026-10-10)\n")
    L.append("| era | n | median premium | mean | share <= 2c | rule |")
    L.append("|---|---|---|---|---|---|")
    for e, a in s.get("by_era", {}).items():
        L.append("| %s | %d | %+.2fc | %+.2fc | %.1f %% | %s |" % (
            e, a["premium"]["n"], 100 * a["premium"]["median"], 100 * a["premium"]["mean"],
            100 * a["share_le_2c"], "PASS" if a["passes_rule"] else "FAIL"))
    L.append("")
    L.append("## By price band (clean legs, primary arm)\n")
    L.append("| band | n | median premium | mean | share <= 2c |")
    L.append("|---|---|---|---|---|")
    for k, v in s.get("by_band", {}).items():
        L.append("| %s | %d | %+.2fc | %+.2fc | %.0f %% |" % (
            k, v["n"], 100 * v["median"], 100 * v["mean"], 100 * v["share_le_2c"]))
    L.append("")
    L.append("## Sensitivity arms\n")
    L.append("| arm | n | median | mean | share <= 2c |")
    L.append("|---|---|---|---|---|")
    for k, a in s.get("arms", {}).items():
        if not a:
            continue
        L.append("| %s | %d | %+.2fc | %+.2fc | %.1f %% |" % (
            k, a["premium"]["n"], 100 * a["premium"]["median"], 100 * a["premium"]["mean"],
            100 * a["share_le_2c"]))
    L.append("")
    ic = s.get("identity_control")
    if ic:
        L.append("## Token identity control (the other outcome's book)")
        L.append("")
        L.append("| check | value |")
        L.append("|---|---|")
        L.append("| clean legs with a sibling book | %d |" % ic["clean_with_sibling_book"])
        L.append("| clean legs whose sibling mid is >5c off 1 - our mid | %d |"
                 % ic["clean_sibling_off_1_minus_mid_gt_5c"])
        L.append("| wrong-side legs / with sibling book | %d / %d |"
                 % (ic["wrong_side_n"], ic["wrong_side_with_sibling_book"]))
        L.append("| wrong-side legs whose SIBLING mid is within 1c of our intent | %d |"
                 % ic["wrong_side_sibling_within_1c_of_intent"])
        L.append("| wrong-side legs whose SIBLING mid is within 3c of our intent | %d |"
                 % ic["wrong_side_sibling_within_3c_of_intent"])
        tc = s.get("tape_label_control")
        if tc:
            L.append("| joined legs also labelled by the print-through tape / agreeing | %d / %d |"
                     % (tc["joined_with_tape_label"], tc["agree"]))
        L.append("")
    L.append("## With the taker fee added (fee/share = rate x p x (1-p))")
    L.append("")
    L.append("| fee basis | n | median premium+fee | mean | share <= 2c |")
    L.append("|---|---|---|---|---|")
    fa = s.get("with_fee_actual")
    if fa:
        L.append("| per-market category rate (%s legs) | %d | %+.2fc | %+.2fc | %.1f %% |" % (
            "+".join("%s:%d" % (k, v) for k, v in sorted(fa["rate_counts"].items())),
            fa["n"], 100 * fa["median"], 100 * fa["mean"], 100 * fa["share_le_2c"]))
    for k, a in s.get("with_fee", {}).items():
        L.append("| flat %s | %d | %+.2fc | %+.2fc | %.1f %% |" % (
            k.replace("rate_", ""), a["n"], 100 * a["median"], 100 * a["mean"], 100 * a["share_le_2c"]))
    L.append("")
    L.append("| era | n | per-market rate | flat 0.05 | flat 0.07 |")
    L.append("|---|---|---|---|---|")
    for e, v in s.get("with_fee_by_era", {}).items():
        f = v["share_le_2c_with_fee"]
        L.append("| %s | %d | %.1f %% | %.1f %% | %.1f %% |" % (
            e, v["n"], 100 * f["actual"], 100 * f["rate_0.05"], 100 * f["rate_0.07"]))
    L.append("")
    with open(path_, "w") as fh:
        fh.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-ms", type=int)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md")
    ap.add_argument("--offline", action="store_true",
                    help="no CLOB fetches; use the cached token map only")
    a = ap.parse_args()

    legs = load_legs(a.since_ms)
    rows, skip = analyse(legs, allow_network=not a.offline)
    s = summarise(rows)
    s["skipped"] = dict(skip)
    s["ranAt"] = int(time.time() * 1000)
    s["premium_bar"] = PREMIUM_BAR
    s["min_n"] = MIN_N
    s["l2_seek"] = "binary_search_ts_v2"   # v1 (linear byte interpolation) under-joined: see draft §Method
    tc = tape_label_control(rows)
    if tc:
        s["tape_label_control"] = tc

    with open(OUT, "a") as fh:
        fh.write(json.dumps({"ranAt": s["ranAt"], "summary": s, "rows": rows}) + "\n")

    if a.md:
        write_md(s, a.md)
    if a.json:
        print(json.dumps(s))
    else:
        print("JOINED %d clean of %d booked BUY legs (%d wrong-side excluded, skips %s)"
              % (s.get("joined_clean", 0), s["legs_in"], s.get("wrong_side_excluded", 0), dict(skip)))
        for k in ("premium_vs_entry", "spread", "lag_s"):
            if k in s:
                v = s[k]
                print("%-18s n=%d mean %+.4f median %+.4f p10 %+.4f p90 %+.4f"
                      % (k, v["n"], v["mean"], v["median"], v["p10"], v["p90"]))
        print("premium<=2c %.1f%%  <=1c %.1f%%  <=0 %.1f%%  (usd-weighted <=2c %.1f%%)"
              % (100 * s["share_premium_le_2c"], 100 * s["share_premium_le_1c"],
                 100 * s["share_premium_le_0"], 100 * (s["share_premium_le_2c_usd_weighted"] or 0)))
        for e, a in s.get("by_era", {}).items():
            print("era %-9s n=%3d median %+.4f share<=2c %.1f%% %s"
                  % (e, a["premium"]["n"], a["premium"]["median"], 100 * a["share_le_2c"],
                     "PASS" if a["passes_rule"] else "FAIL"))
        for k in ("premium_vs_intent", "premium_vs_flat2c"):
            a = s.get(k)
            if a:
                print("vs %-17s n=%3d median %+.4f share<=2c %.1f%%"
                      % (k.replace("premium_vs_", ""), a["premium"]["n"],
                         a["premium"]["median"], 100 * a["share_le_2c"]))
        for k, a in s.get("arms", {}).items():
            if a:
                print("arm %-30s n=%3d median %+.4f share<=2c %.1f%%"
                      % (k, a["premium"]["n"], a["premium"]["median"], 100 * a["share_le_2c"]))
        fa = s.get("with_fee_actual")
        if fa:
            print("with fee (per-market rate)  share<=2c %.1f%%  mean %+.4f  rates %s"
                  % (100 * fa["share_le_2c"], fa["mean"], fa["rate_counts"]))
        print("decision: %s (bar: <=2c on >=50%% of joined legs, n>=%d)" % (s["decision"], MIN_N))
        for k, v in s.get("by_band", {}).items():
            print("  band %-9s n=%3d mean %+.4f median %+.4f share<=2c %.2f"
                  % (k, v["n"], v["mean"], v["median"], v["share_le_2c"]))


if __name__ == "__main__":
    main()
