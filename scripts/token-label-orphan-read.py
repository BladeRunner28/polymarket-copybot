#!/usr/bin/env python3
"""token-label-orphan-read.py — card `token-label-alias-phantom-loss` (LANE B, READ-ONLY).

QUESTION
  A venue token can be RENAMED between our ingest and its settlement. `didOutcomeWin`
  (src/lib/resolution.ts) compares LABELS, so a leg opened under the retired label can only
  ever read "lost" against the new one. The card holds one such leg (ufc-jon5-jos27-2026-11-07,
  'JOSE HENRIQUE' -$9.00, same token as the 'JOSE SOUZA' leg that won +$4.14) and pre-registers:
      ACT   when the class reaches >= $100 of booked PnL OR >= 5 legs;
      REFUTE if a further audit of >= 500 more markets finds no further instances.
  This instrument answers that, at whole-book scale, and nothing else.

BASIS (printed with every number this script emits)
  population : settled PaperTrade legs (isDemo=0, status='resolved', resolvedAt NOT NULL) — the
               only legs whose PnL can depend on a label compare. Early exits are excluded.
  level      : one leg / one market
  clock      : resolvedAt (UTC); every market's label set is read at the run's own instant, and the
               snapshot time is stamped in the artifact.
  truth      : CLOB `GET /markets/<conditionId>` -> tokens[].outcome / tokens[].winner. Local
               caches are used first (data/.clob-truth-raw/, data/fill-tape-cache/,
               data/cheap-funnel-cache/, data/market-truth-clob.json,
               data/seat-evidence-market-truth.json); only the residue is fetched, and each fetch
               is written back so the next run is free.

WHAT COUNTS AS AN INSTANCE (deliberately narrow — a wide definition invents instances)
  RENAME-ORPHAN := stored label is NON-BINARY, the venue market has exactly TWO tokens, BOTH venue
  labels are non-binary, and the stored label is absent from the venue's current label set.
  Excluded and counted separately, because they are different defects:
    * binary_vs_named — our 'YES'/'NO' against named tokens (label SPACE mismatch; didOutcomeWin
      returns null on it, it does not book a loss);
    * multi_token_absent — >2 tokens (neg-risk groups) where an absent label is normal.
  An orphan is only PRICED when the token it held can be established:
    * twin_flip  — the venue published the SAME print under both labels (same condition, |dPrice|
                   <= 0.01, |dt| <= 1h), so the rename is on the record itself;
    * sibling_leg— another leg on the same market carries a current label at the same entry
                   (|d| <= 0.005) within 2h.
  Everything else is counted UNRESOLVED and never priced as an error: the leg may have held the
  losing token, in which case the booked loss is right.

READ-ONLY: SQLite opened mode=ro. Writes data/token-label-orphan-read.json + the fetch cache.
No rule, size, threshold, gate or settlement call site is touched.

RUN
  python3 scripts/token-label-orphan-read.py --self-test
  python3 scripts/token-label-orphan-read.py --fetch-truth      # fill the cache, then report
  python3 scripts/token-label-orphan-read.py                    # report off the cache
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("COPYBOT_DB", str(ROOT / "prisma" / "dev.db")))
OUT = ROOT / "data" / "token-label-orphan-read.json"
CACHE_DIR = ROOT / "data" / ".clob-truth-raw"
LOCAL_TRUTH_FILES = [
    ROOT / "data" / "market-truth-clob.json",
    ROOT / "data" / "seat-evidence-market-truth.json",
]
LOCAL_TRUTH_DIRS = [
    ROOT / "data" / ".clob-truth-raw",
    ROOT / "data" / "fill-tape-cache",
    ROOT / "data" / "cheap-funnel-cache",
]
CLOB = "https://clob.polymarket.com"
UA = {"accept": "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)"}

BINARY = {"YES", "NO"}
PRICE_TOL_FLIP = 0.01      # twin_flip: same print, two labels
DT_FLIP_SEC = 3600
PRICE_TOL_SIBLING = 0.005  # sibling_leg: same entry on two legs
DT_SIBLING_SEC = 7200

# Card's pre-registered gates, restated here so the script prints them itself.
LOCALS: dict = {}   # main() hands the fetch summary to measure() through here, without a global result
ACT_PNL_USD = 100.0
ACT_LEGS = 5
REFUTE_EXTRA_MARKETS = 500
PRIOR_AUDIT_MARKETS = 537   # ml-feed-recorder-audit-external-pm (2026-11-16): 537 markets / 715 legs


# ----------------------------------------------------------------------------- pure helpers
def norm(label) -> str:
    """Same normalisation as normalizeOutcomeLabel() in src/lib/resolution.ts."""
    if label is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(label).lower()).upper()


def is_binary(n: str) -> bool:
    return n in BINARY


def win_pnl(entry_price: float, size: float) -> float:
    """Our booking convention, verified against the two card legs: size * (1/entry - 1)."""
    if not entry_price or entry_price <= 0:
        return 0.0
    return size * (1.0 / entry_price - 1.0)


def classify(stored_label, tokens) -> str:
    """ok | rename_orphan | binary_vs_named | multi_token_absent."""
    want = norm(stored_label)
    if not want:
        return "no_label"
    labels = [norm(t[0]) for t in tokens if t and t[0]]
    if not labels:
        return "no_venue_labels"
    if want in labels:
        return "ok"
    if len(tokens) != 2:
        return "multi_token_absent"
    if is_binary(want) != is_binary(labels[0]):
        return "binary_vs_named"
    return "rename_orphan"


def truth_shape(payload):
    """CLOB market payload -> (labels[(label, winner, token_id)], closed, slug), or None."""
    if not isinstance(payload, dict):
        return None
    toks = payload.get("tokens")
    if not isinstance(toks, list) or not toks:
        return None
    out = []
    for t in toks:
        if not isinstance(t, dict):
            return None
        out.append((t.get("outcome"), bool(t.get("winner")), t.get("token_id")))
    return out, bool(payload.get("closed")), payload.get("market_slug")


def load_truth() -> tuple[dict, dict, dict]:
    """-> (cid -> tokens list, cid -> meta, slug -> cid). Local caches only; no network."""
    cid_tokens, cid_meta, slug_cid = {}, {}, {}

    def take(payload, fallback_cid=None):
        shape = truth_shape(payload)
        if not shape:
            return
        toks, closed, slug = shape
        cid = payload.get("condition_id") or fallback_cid
        if not cid:
            return
        cid_tokens[cid] = toks
        cid_meta[cid] = {"closed": closed, "slug": slug}
        if slug:
            slug_cid[slug] = cid

    for d in LOCAL_TRUTH_DIRS:
        if not d.is_dir():
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, fn)) as fh:
                    take(json.load(fh))
            except Exception:
                continue  # a half-written cache entry is skipped, never guessed from
    for p in LOCAL_TRUTH_FILES:
        if not p.exists():
            continue
        try:
            with open(p) as fh:
                doc = json.load(fh)
        except Exception:
            continue
        markets = doc.get("markets", doc) if isinstance(doc, dict) else {}
        if not isinstance(markets, dict):
            continue
        for cid, v in markets.items():
            if not isinstance(v, dict) or "tokens" not in v:
                continue
            toks = v["tokens"]
            # market-truth-clob.json stores [[label, winner], ...]; the CLOB shape is a dict list
            if toks and isinstance(toks[0], list):
                toks = [{"outcome": t[0], "winner": bool(t[1]) if len(t) > 1 else False} for t in toks]
                v = dict(v, tokens=toks, condition_id=cid)
            take(v, fallback_cid=cid)
    return cid_tokens, cid_meta, slug_cid


# ----------------------------------------------------------------------------- data
def load_legs(db_path: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT pt.id, pt.marketId, pt.outcome, pt.entryPrice, pt.simulatedPositionSize,
               pt.realizedPnl, pt.resolvedAt, pt.openedAt, pt.botId,
               ot.conditionId
        FROM PaperTrade pt
        LEFT JOIN DecisionJournal dj ON dj.id = pt.decisionJournalId
        LEFT JOIN ObservedTrade ot ON ot.id = dj.observedTradeId
        WHERE pt.isDemo = 0 AND pt.status = 'resolved' AND pt.resolvedAt IS NOT NULL
        """
    ).fetchall()
    legs = []
    for r in rows:
        legs.append(
            {
                "id": r["id"],
                "marketId": r["marketId"] or "",
                "conditionId": r["conditionId"],
                "outcome": r["outcome"] or "",
                "entryPrice": float(r["entryPrice"] or 0),
                "size": float(r["simulatedPositionSize"] or 0),
                "bookedPnl": float(r["realizedPnl"] or 0),
                "openedAt": int(r["openedAt"] or 0),
                "resolvedAt": int(r["resolvedAt"] or 0),
                "botId": r["botId"] or "",
            }
        )
    con.close()
    return legs


def load_observed_prints(db_path: Path, cids: set[str], since_ms: int) -> dict[str, list[dict]]:
    """Prints we observed on the implicated conditions, for the twin_flip identity arm."""
    if not cids:
        return {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    marks = ",".join("?" * len(cids))
    rows = con.execute(
        f"""SELECT conditionId, outcome, walletEntryPrice, timestamp
            FROM ObservedTrade
            WHERE conditionId IN ({marks}) AND timestamp >= ?""",
        [*cids, since_ms],
    ).fetchall()
    con.close()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["conditionId"], []).append(
            {"outcome": r["outcome"] or "", "price": float(r["walletEntryPrice"] or 0), "ts": int(r["timestamp"] or 0)}
        )
    return out


# ----------------------------------------------------------------------------- fetch
def fetch_truth(cid: str, timeout: int = 20) -> tuple[dict | None, str]:
    """-> (payload, reason). The reason is recorded so a failed fetch is never silent."""
    url = f"{CLOB}/markets/{cid}"
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()), "ok"
    except urllib.error.HTTPError as e:
        return None, f"http_{e.code}"
    except urllib.error.URLError as e:
        return None, f"url_error:{getattr(e, 'reason', e)}"[:80]
    except (TimeoutError, json.JSONDecodeError) as e:
        return None, type(e).__name__.lower()


def write_cache(cid: str, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / f".{cid}.tmp"
    dest = CACHE_DIR / f"{cid}.json"
    with open(tmp, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, dest)


def fill_truth(cids: list[str], tokens_by_cid: dict) -> dict:
    """Fetch the residue. Politeness: one request at a time, back off once on a 429."""
    fetched = 0
    reasons: dict[str, int] = {}
    for cid in cids:
        if cid in tokens_by_cid:
            continue
        payload, reason = fetch_truth(cid)
        if payload is None:
            time.sleep(1.0)
            payload, reason = fetch_truth(cid)
        if payload is None:
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        write_cache(cid, payload)
        fetched += 1
        time.sleep(0.12)
    return {"fetched": fetched, "failed": sum(reasons.values()), "reasons": reasons}


# ----------------------------------------------------------------------------- measure
def build_truth_index(cid_tokens: dict, cid_meta: dict, slug_cid: dict):
    """Slug-only markets (no conditionId on the leg) get their tokens through the slug map."""
    def tokens_for(leg):
        if leg["conditionId"] and leg["conditionId"] in cid_tokens:
            return cid_tokens[leg["conditionId"]]
        cid = slug_cid.get(leg["marketId"])
        if cid and cid in cid_tokens:
            return cid_tokens[cid]
        return None

    return tokens_for


def measure(db_path: Path) -> dict:
    legs = load_legs(db_path)
    cid_tokens, cid_meta, slug_cid = load_truth()
    tokens_for = build_truth_index(cid_tokens, cid_meta, slug_cid)

    counts = {"ok": 0, "rename_orphan": 0, "binary_vs_named": 0, "multi_token_absent": 0,
              "no_label": 0, "no_venue_labels": 0, "no_truth": 0}
    covered_markets, audited_markets = set(), set()
    orphans, other_absent = [], []
    no_identity, no_truth_other = [], []
    for leg in legs:
        toks = tokens_for(leg)
        if toks is None:
            counts["no_truth"] += 1
            # A leg with NO slug and NO venue-resolvable condition can never be audited by any
            # instrument. That cohort is already measured and deliberately left booked: see
            # card `parlay-rows-in-decision-path` (2026-11-06) and
            # drafts/resolution-label-bug-plan.md §5 — 40 legs, -$412.97, no market identity.
            (no_identity if not leg["marketId"] else no_truth_other).append(leg)
            continue
        covered_markets.add(leg["marketId"])
        audited_markets.add(leg["conditionId"] or leg["marketId"])
        cls = classify(leg["outcome"], toks)
        counts[cls] += 1
        if cls == "rename_orphan":
            orphans.append({**leg, "tokens": toks})
        elif cls in ("binary_vs_named", "multi_token_absent"):
            other_absent.append({**leg, "tokens": toks, "class": cls})

    # identity evidence
    cids = {o["conditionId"] for o in orphans if o.get("conditionId")}
    since = min((o["openedAt"] for o in orphans), default=0) - 86_400_000
    prints = load_observed_prints(db_path, cids, since)
    by_market: dict[str, list[dict]] = {}
    for o in orphans:
        by_market.setdefault(o["marketId"], []).append(o)

    priced = []
    for o in orphans:
        labels = [norm(t[0]) for t in o["tokens"]]
        rec = {
            "id": o["id"], "botId": o["botId"], "marketId": o["marketId"],
            "outcome": o["outcome"], "entryPrice": o["entryPrice"], "size": o["size"],
            "bookedPnl": o["bookedPnl"], "openedAt": o["openedAt"],
            "venueLabels": [t[0] for t in o["tokens"]],
            "venueWinner": next((t[0] for t in o["tokens"] if t[1]), None),
        }
        identity_label, evidence = None, None
        # twin_flip: the same print appears under the retired AND a current label
        for p in prints.get(o.get("conditionId") or "", []):
            pn = norm(p["outcome"])
            if pn == norm(o["outcome"]):
                continue
            if pn not in labels:
                continue
            if abs(p["price"] - o["entryPrice"]) > PRICE_TOL_FLIP:
                continue
            if abs(p["ts"] - o["openedAt"]) > DT_FLIP_SEC * 1000:
                continue
            identity_label, evidence = pn, "twin_flip"
            break
        if identity_label is None:
            for sib in by_market.get(o["marketId"], []):
                if sib["id"] == o["id"]:
                    continue
                if norm(sib["outcome"]) not in labels:
                    continue
                if abs(sib["entryPrice"] - o["entryPrice"]) > PRICE_TOL_SIBLING:
                    continue
                if abs(sib["openedAt"] - o["openedAt"]) > DT_SIBLING_SEC * 1000:
                    continue
                identity_label, evidence = norm(sib["outcome"]), "sibling_leg"
                break
        if identity_label is None:
            rec["identity"] = "unresolved"
            rec["identityEvidence"] = None
            rec["identityPnl"] = None
            rec["pnlError"] = None
        else:
            won = next((bool(t[1]) for t in o["tokens"] if norm(t[0]) == identity_label), None)
            ident = win_pnl(o["entryPrice"], o["size"]) if won else -o["size"]
            rec["identity"] = "won" if won else "lost"
            rec["identityEvidence"] = evidence
            rec["identityPnl"] = round(ident, 2)
            rec["pnlError"] = round(ident - o["bookedPnl"], 2)
        priced.append(rec)

    resolved = [p for p in priced if p["pnlError"] is not None]
    err = [p["pnlError"] for p in resolved]
    booked = [p["bookedPnl"] for p in priced]
    order = sorted(resolved, key=lambda p: -abs(p["pnlError"]))
    top = order[0] if order else None

    total_legs = sum(counts.values())
    result = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "basis": {
            "population": "settled PaperTrade legs (isDemo=0, status='resolved', resolvedAt NOT NULL)",
            "level": "one leg / one market",
            "clock": "resolvedAt (UTC); venue label sets read at generated_at",
            "truth": "CLOB /markets/<conditionId> tokens[].outcome / [].winner; local caches first",
        },
        "book": {
            "settled_legs": total_legs,
            "legs_with_venue_truth": total_legs - counts["no_truth"],
            "markets_audited": len(covered_markets),
            "truth_coverage_pct": round(100.0 * (total_legs - counts["no_truth"]) / total_legs, 2) if total_legs else 0.0,
            "local_conditions_cached": len(cid_tokens),
        },
        "classes": counts,
        "unmeasured": {
            "legs_no_venue_truth": counts["no_truth"],
            "no_market_identity_legs": len(no_identity),
            "no_market_identity_pnl": round(sum(l["bookedPnl"] for l in no_identity), 2),
            "no_market_identity_note": "blank marketId + event-id conditionId (404 at CLOB); already measured "
                                       "on card parlay-rows-in-decision-path (-$412.97, left booked on purpose)",
            "other_missing_legs": len(no_truth_other),
            "other_missing_markets": sorted({l["marketId"] for l in no_truth_other})[:10],
        },
        "classes_detail": {k: v for k, v in counts.items()},
        "other_absent": [
            {"marketId": x["marketId"], "outcome": x["outcome"], "class": x["class"],
             "venueLabels": [t[0] for t in x["tokens"]], "bookedPnl": x["bookedPnl"]}
            for x in other_absent[:20]
        ],
        "instances": priced,
        "class_read": {
            "instance_legs": len(priced),
            "instance_markets": len({p["marketId"] for p in priced}),
            "booked_pnl_on_instances": round(sum(booked), 2),
            "priced_legs": len(resolved),
            "unresolved_legs": len(priced) - len(resolved),
            "booked_pnl_error_usd": round(sum(err), 2),
            "ex_top_instance_error_usd": round(sum(err) - (top["pnlError"] if top else 0.0), 2),
            "largest_instance": top,
        },
        "gates": {
            "act_pnl_usd": ACT_PNL_USD,
            "act_legs": ACT_LEGS,
            "act_fired_pnl": round(sum(err), 2) >= ACT_PNL_USD,
            "act_fired_legs": len(priced) >= ACT_LEGS,
            "refute_extra_markets": REFUTE_EXTRA_MARKETS,
            "prior_audit_markets": PRIOR_AUDIT_MARKETS,
            "markets_beyond_prior": len(covered_markets) - PRIOR_AUDIT_MARKETS,
            "refuted": len(covered_markets) - PRIOR_AUDIT_MARKETS >= REFUTE_EXTRA_MARKETS and len(priced) <= 1,
        },
    }
    return result


# ----------------------------------------------------------------------------- self-test
def self_test() -> int:
    fails = []

    def ck(name, cond, detail=""):
        if not cond:
            fails.append(f"{name} {detail}")
        print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))

    toks = [("Jose Souza", True, "111"), ("Jonny Parsons", False, "222")]
    ck("orphan: retired label on a 2-name market", classify("JOSE HENRIQUE", toks) == "rename_orphan")
    ck("ok: current label", classify("Jose Souza", toks) == "ok")
    ck("ok: normalisation is the resolver's", classify("JONNY   PARSONS.", toks) == "ok")
    ck("binary_vs_named is NOT an orphan", classify("NO", toks) == "binary_vs_named")
    ck("multi-token absence is NOT an orphan",
       classify("X", [("A", False, "1"), ("B", True, "2"), ("C", False, "3")]) == "multi_token_absent")
    ck("blank label has no verdict", classify("", toks) == "no_label")

    # Mutation: if the classifier ignored the label set it would call everything ok.
    mutated_ok = all(classify(x, toks) == "ok" for x in ("JOSE HENRIQUE", "NO", ""))
    ck("MUTATION: a label-set-blind classifier fails", mutated_ok is False)

    ck("win_pnl reproduces the card's +$4.14 leg", abs(win_pnl(0.685, 9.0) - 4.14) < 0.02, f"{win_pnl(0.685, 9.0):.4f}")
    # The card's own instance, priced: a booked -$9.00 that identity says won is +$4.14, i.e. $13.14 of error.
    ck("identity error on the card leg is $13.14", abs((win_pnl(0.685, 9.0) - -9.0) - 13.14) < 0.02,
       f"{(win_pnl(0.685, 9.0) - -9.0):.4f}")
    ck("a losing identity leaves a correct loss at $0 error", abs((-9.0 - -9.0)) < 1e-9)

    shape = truth_shape({"tokens": [{"outcome": "Yes", "winner": False}, {"outcome": "No", "winner": True}],
                         "closed": True, "market_slug": "s"})
    ck("truth_shape reads the CLOB contract", shape is not None and shape[0][1][1] is True and shape[1] is True)
    ck("truth_shape refuses a payload with no tokens", truth_shape({"closed": True}) is None)

    # The list shape used by data/market-truth-clob.json must survive the same path.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"markets": {"0xdead": {"closed": True, "tokens": [["Yes", False], ["No", True]]}}}, fh)
        tmp = fh.name
    try:
        saved = list(LOCAL_TRUTH_DIRS), list(LOCAL_TRUTH_FILES)
        LOCAL_TRUTH_DIRS.clear()
        LOCAL_TRUTH_FILES[:] = [Path(tmp)]
        cid_tokens, _, _ = load_truth()
        ck("list-shaped truth file is indexed", cid_tokens.get("0xdead", []) and cid_tokens["0xdead"][1][1] is True)
        LOCAL_TRUTH_DIRS.extend(saved[0])
        LOCAL_TRUTH_FILES[:] = saved[1]
    finally:
        os.unlink(tmp)

    print(f"\n{len(fails)} failing" if fails else "\nall self-test arms green")
    return 1 if fails else 0


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--fetch-truth", action="store_true")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 2

    if args.fetch_truth:
        legs = load_legs(db_path)
        cid_tokens, _, slug_cid = load_truth()
        need = []
        for leg in legs:
            cid = leg["conditionId"] or slug_cid.get(leg["marketId"])
            if cid and cid not in cid_tokens and cid not in need:
                need.append(cid)
        print(f"[truth] {len(need)} condition(s) with no local truth; fetching", flush=True)
        res = fill_truth(need, cid_tokens)
        print(f"[truth] fetched {res['fetched']}, failed {res['failed']} {res['reasons']}", flush=True)
        LOCALS["truth_fetch"] = {"requested": len(need), **res}

    res = measure(db_path)
    if "truth_fetch" in LOCALS:
        res["truth_fetch"] = LOCALS["truth_fetch"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=2, sort_keys=True)

    b, c, g = res["book"], res["classes"], res["gates"]
    print(f"[label-orphans] settled legs {b['settled_legs']}  with venue truth {b['legs_with_venue_truth']} "
          f"({b['truth_coverage_pct']}%)  markets audited {b['markets_audited']}")
    print(f"[label-orphans] rename_orphan {c['rename_orphan']}  binary_vs_named {c['binary_vs_named']}  "
          f"multi_token_absent {c['multi_token_absent']}  no_truth {c['no_truth']}")
    cr = res["class_read"]
    print(f"[label-orphans] instance legs {cr['instance_legs']} markets {cr['instance_markets']} "
          f"booked {cr['booked_pnl_on_instances']} priced {cr['priced_legs']} "
          f"error ${cr['booked_pnl_error_usd']} ex-top ${cr['ex_top_instance_error_usd']}")
    print(f"[label-orphans] gates: act=>= ${g['act_pnl_usd']} -> {g['act_fired_pnl']}; "
          f"act=>= {g['act_legs']} legs -> {g['act_fired_legs']}; "
          f"markets beyond prior {g['markets_beyond_prior']}; refuted -> {g['refuted']}")
    um = res["unmeasured"]
    print(f"[label-orphans] unmeasured {um['legs_no_venue_truth']} legs: {um['no_market_identity_legs']} have no "
          f"market identity (${um['no_market_identity_pnl']}, already carded), {um['other_missing_legs']} other")
    print(f"[label-orphans] wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
