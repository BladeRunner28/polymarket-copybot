#!/usr/bin/env python3
"""prereg-grade -- dated gates grade as ROWS, not as bespoke scripts.

WHY THIS FILE EXISTS
--------------------
This repo has pre-registered gates (C-200 entry floor 2026-10-24, the C-200 ladder advance,
the price-side reads), and every one of them lives as a hand-written script that re-decides
its own population, its own clock and its own sample requirement on every run. That makes two
very different situations indistinguishable:

  * a gate that is still accumulating evidence, and
  * a gate whose population stopped moving weeks ago and can never resolve.

Measured example this instrument was built for: entry-floor gate A reported `n=31` -- unchanged
-- on 17 consecutive reads from 2026-10-17 to 2026-11-09, and the bespoke script reported
INSUFFICIENT_N each time. Nothing in that output could tell a reader "this number is FROZEN;
stop waiting for it". A registry row plus a deterministic grader can:

    grade  id                 state      value     n  need   n_all  frozen
    1      entry-floor-a      FROZEN     -0.5518   0    60     31     16 reads at n=31

WHAT IT DOES
------------
`data/prereg-registry.jsonl` holds one spec per gate, with FIXED fields:

    id          slug, unique
    frozen_at   ISO date/datetime; rows at or before it are NEVER graded
    metric      one of the closed vocabulary below
    venue       Polymarket | Kalshi | all
    slice       structured population filter (closed key set)
    op          <= | < | >= | > | ==
    threshold   the number the metric is compared to
    min_n       the sample the spec author demands
    state       written by the grader (last verdict)
    last_n      written by the grader (sample size of the last read)
    reads       written by the grader (number of reads incl. imported legacy reads)

`prereg-grade.py grade` recomputes every metric from `prisma/dev.db`, appends one read row to
`data/prereg-reads.jsonl`, and rewrites the three mutable fields in the registry. Everything
else about a read (the value, the sample, the state, the spec hash) lives in the append-only
read log, so HISTORY IS NOT REWRITABLE: editing a spec changes its `spec_sha` and the next read
says MODIFIED instead of silently re-basing the gate.

GUARDS (the point of the exercise -- each one prevents a specific known lie)
---------------------------------------------------------------------------
1. CLOSED VOCABULARY. Metric names, slice keys and spec keys are allowlists. One unknown key
   (a typo'd `minN`, a `slices` misspelling) makes the spec REJECTED and it is never graded --
   the failure is loud, not a silently different population.
2. STRICTLY POST-FREEZE ROWS. A row is graded only if its clock (settlement for settled
   metrics, open time otherwise) is strictly after `frozen_at`. A gate whose population is
   entirely pre-freeze grades at n=0 and reads UNGRADEABLE, which is the correct verdict.
3. max(min_n, FLOOR). Each metric carries a declared noise floor; the effective bar is
   max(spec.min_n, FLOOR[metric]). A spec cannot buy itself a verdict by asking for n=1.
4. UNGRADEABLE. n below the bar, or a metric that is undefined (zero denominator), is a
   STATE, never a zero or a null that reads as a result.
5. REJECT A SPEC ALREADY TRUE PRE-FREEZE. If the predicate already held, with n >= bar, on
   the pre-freeze population, the spec is REJECTED_PRE_TRUE: it was written after the fact, so
   passing it post-freeze carries no information.
6. SUPPORTED-BUT-ALREADY-TRUE = NO_INFORMATION. If the predicate held pre-freeze with n below
   the bar (the "PASS carried by legs the venue can never confirm" shape) and later reads
   SUPPORTED, the state is NO_INFORMATION, not SUPPORTED.
7. FROZEN. The population of the slice (`n_all`) is compared across reads; when it has not
   moved for >= 7 consecutive graded reads the state becomes FROZEN (with the underlying
   verdict kept). This is the guard that would have flagged gate A.
8. SPEC HASH. Each read stores sha256 of the immutable spec fields; a change is reported as
   MODIFIED. A gate edited after freeze is not the gate that was frozen.

METRIC VOCABULARY (closed)
--------------------------
  legs                 rows in the slice
  pnl                  sum(realizedPnl)
  roi                  sum(realizedPnl) / sum(simulatedPositionSize)
  hit_rate             share of rows with realizedPnl > 0
  mean_entry           mean entryPrice
  inverted_legs        rows whose booked entry is the complement of the copied wallet's fill
                       (the price-side defect classifier of scripts/profit-price-side.py)
  inverted_share       inverted_legs / rows
  inverted_pnl_share   PnL of inverted legs / PnL of all rows
  fill_reach           filled / stamped (fillStatus in filled|unfilled)
  unfilled_pnl_share   PnL of unfilled stamped legs / PnL of stamped legs

SLICE KEYS (closed)
-------------------
  bot                BANKROLL_200 | STANDARD | all
  status             settled (default) | open | all
  clock              settled (default: COALESCE(closedAt,resolvedAt)) | opened
  ruleSetVersionMin  int, joins DecisionJournal
  entryMin/entryMax  entryPrice range, min inclusive / max exclusive
  fillBasis          e.g. book-window
  fillStatus         filled | unfilled | stamped
  since / until      YYYY-MM-DD inclusive day window on `dayBasis`
  dayBasis           local (default, the ladder's calendar) | utc

ADOPTION RULE (from the approved card)
--------------------------------------
Adopt iff >= 2 of 3 hand-read gates reproduce: `prereg-grade.py adopt` re-derives each spec's
`hand_read` (value + sample, from the bespoke script that first computed it) through the generic
engine on the ALL-ROWS basis and writes `data/prereg-adoption.json`.

Sample reproduction: a BOUNDED slice (since/until) is closed, so its n must match exactly. A
CUMULATIVE slice only grows -- the hand read carries a date, not an instant, so legs settling
later that day are legitimately missing from it -- and reproduction requires n_got >= hand_n
(a shrinking population fails). `n_drift` records the difference on every gate.

USAGE
-----
    python3 scripts/prereg-grade.py grade [--dry-run] [--json] [--now ISO]
    python3 scripts/prereg-grade.py validate
    python3 scripts/prereg-grade.py adopt
    python3 scripts/prereg-grade.py import-legacy [--id entry-floor-a]
    python3 scripts/prereg-grade.py self-test

READ-ONLY on prisma/dev.db. Writes only data/prereg-registry.jsonl (state/last_n/reads),
data/prereg-reads.jsonl (append) and data/prereg-adoption.json. Revert: `git revert` the commit,
or delete the registry + read log -- no live path reads any of them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "prisma" / "dev.db"
REGISTRY = REPO / "data" / "prereg-registry.jsonl"
READS = REPO / "data" / "prereg-reads.jsonl"
ADOPTION = REPO / "data" / "prereg-adoption.json"
LEGACY_ENTRY_FLOOR = REPO / "data" / "entry-floor-read.jsonl"

LOCAL_TZ = datetime.now().astimezone().tzinfo

REQUIRED_FIELDS = ("id", "frozen_at", "metric", "venue", "slice", "op",
                   "threshold", "min_n", "state", "last_n", "reads")
OPTIONAL_FIELDS = ("note", "hand_read", "spec_sha")

SLICE_KEYS = {"bot", "status", "clock", "ruleSetVersionMin", "entryMin", "entryMax",
              "fillBasis", "fillStatus", "since", "until", "dayBasis"}

VENUES = ("Polymarket", "Kalshi", "all")
OPS = {"<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
       ">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
       "==": lambda a, b: abs(a - b) <= 1e-9}

STATES = ("UNGRADED", "PENDING", "SUPPORTED", "REFUTED", "UNGRADEABLE",
          "NO_INFORMATION", "FROZEN", "REJECTED", "REJECTED_PRE_TRUE")

# Declared noise floors: the smallest sample at which the metric has a chance of being
# about the population rather than about one leg. A spec cannot set min_n below these.
FLOOR = {
    "legs": 1,
    "pnl": 20,
    "roi": 30,
    "hit_rate": 100,
    "mean_entry": 20,
    "inverted_legs": 20,
    "inverted_share": 100,
    "inverted_pnl_share": 100,
    "fill_reach": 50,
    "unfilled_pnl_share": 50,
}

METRIC_NEEDS = {
    "legs": set(),
    "pnl": {"pnl"},
    "roi": {"pnl"},
    "hit_rate": {"pnl"},
    "mean_entry": set(),
    "inverted_legs": {"observed"},
    "inverted_share": {"observed"},
    "inverted_pnl_share": {"observed", "pnl"},
    "fill_reach": {"fill"},
    "unfilled_pnl_share": {"fill", "pnl"},
}

TOL = {"legs": 0.0, "pnl": 0.05, "roi": 0.002, "hit_rate": 0.002, "mean_entry": 0.002,
       "inverted_legs": 0.0, "inverted_share": 0.002, "inverted_pnl_share": 0.002,
       "fill_reach": 0.002, "unfilled_pnl_share": 0.002}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

# price-side classifier constants, identical to scripts/profit-price-side.py
PS_MIRROR, PS_SEP, PS_TOL = 0.06, 0.10, 0.06


# --------------------------------------------------------------------- time
def parse_dt(s):
    """ISO date or datetime -> aware datetime. Date-only is local midnight."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=LOCAL_TZ)
    s = str(s).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        d = datetime.strptime(s, "%Y-%m-%d")
        return d.replace(tzinfo=LOCAL_TZ)
    txt = s.replace("Z", "+00:00")
    d = datetime.fromisoformat(txt)
    if d.tzinfo is None:
        d = d.replace(tzinfo=LOCAL_TZ)
    return d


def as_dt(v):
    """SQLite DATETIME column -> aware datetime (this DB stores Unix-ms ints)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=LOCAL_TZ)
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000.0).astimezone()
    s = str(v).strip()
    if not s:
        return None
    if re.match(r"^\d{9,}$", s):
        return datetime.fromtimestamp(int(s) / 1000.0).astimezone()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=LOCAL_TZ)


# ------------------------------------------------------------------- specs
def immutable_spec(spec):
    return {k: v for k, v in spec.items() if k not in ("state", "last_n", "reads", "spec_sha")}


def spec_sha(spec):
    blob = json.dumps(immutable_spec(spec), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def required_n(spec):
    return max(int(spec["min_n"]), FLOOR[spec["metric"]])


def validate_spec(spec):
    """Return a list of human-readable errors. Empty list == gradeable."""
    errs = []
    if not isinstance(spec, dict):
        return ["spec is not an object"]
    unknown = sorted(set(spec) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS))
    if unknown:
        errs.append("unknown spec key(s): %s" % ", ".join(unknown))
    missing = [k for k in REQUIRED_FIELDS if k not in spec]
    if missing:
        errs.append("missing required field(s): %s" % ", ".join(missing))
        return errs

    if not isinstance(spec["id"], str) or not ID_RE.match(spec["id"]):
        errs.append("id must match %s" % ID_RE.pattern)
    try:
        parse_dt(spec["frozen_at"])
    except Exception:
        errs.append("frozen_at is not an ISO date/datetime: %r" % (spec["frozen_at"],))
    if spec["metric"] not in FLOOR:
        errs.append("unknown metric %r (closed vocabulary: %s)"
                    % (spec["metric"], ", ".join(sorted(FLOOR))))
    if spec["venue"] not in VENUES:
        errs.append("unknown venue %r" % (spec["venue"],))
    if spec["op"] not in OPS:
        errs.append("unknown op %r" % (spec["op"],))
    if not isinstance(spec["threshold"], (int, float)) or isinstance(spec["threshold"], bool):
        errs.append("threshold must be a number")
    if not isinstance(spec["min_n"], int) or isinstance(spec["min_n"], bool) or spec["min_n"] < 1:
        errs.append("min_n must be an integer >= 1")
    if spec.get("state") not in STATES:
        errs.append("state %r is not one of %s" % (spec.get("state"), ", ".join(STATES)))
    if spec.get("last_n") is not None and not isinstance(spec["last_n"], int):
        errs.append("last_n must be an integer or null")
    if not isinstance(spec["reads"], int) or isinstance(spec["reads"], bool) or spec["reads"] < 0:
        errs.append("reads must be an integer >= 0")

    sl = spec["slice"]
    if not isinstance(sl, dict):
        errs.append("slice must be an object")
        return errs
    unknown = sorted(set(sl) - SLICE_KEYS)
    if unknown:
        errs.append("unknown slice key(s): %s" % ", ".join(unknown))
    if "bot" in sl and sl["bot"] not in ("BANKROLL_200", "STANDARD", "all"):
        errs.append("slice.bot must be BANKROLL_200, STANDARD or all")
    if "status" in sl and sl["status"] not in ("settled", "open", "all"):
        errs.append("slice.status must be settled, open or all")
    if "clock" in sl and sl["clock"] not in ("settled", "opened"):
        errs.append("slice.clock must be settled or opened")
    if "dayBasis" in sl and sl["dayBasis"] not in ("local", "utc"):
        errs.append("slice.dayBasis must be local or utc")
    if "fillStatus" in sl and sl["fillStatus"] not in ("filled", "unfilled", "stamped"):
        errs.append("slice.fillStatus must be filled, unfilled or stamped")
    for k in ("entryMin", "entryMax"):
        if k in sl and not isinstance(sl[k], (int, float)):
            errs.append("slice.%s must be a number" % k)
    if "ruleSetVersionMin" in sl:
        if not isinstance(sl["ruleSetVersionMin"], int) or isinstance(sl["ruleSetVersionMin"], bool):
            errs.append("slice.ruleSetVersionMin must be an integer")
    for k in ("since", "until"):
        if k in sl:
            try:
                parse_dt(sl[k])
            except Exception:
                errs.append("slice.%s is not a date: %r" % (k, sl[k]))
    if "since" in sl and "until" in sl:
        try:
            if parse_dt(sl["since"]).date() > parse_dt(sl["until"]).date():
                errs.append("slice.since is after slice.until")
        except Exception:
            pass
    if "clock" in sl and sl["clock"] == "opened" and METRIC_NEEDS[spec["metric"]] & {"pnl"}:
        errs.append("a PnL metric on clock=opened is not a settled population")

    hr = spec.get("hand_read")
    if hr is not None:
        if not isinstance(hr, dict):
            errs.append("hand_read must be an object")
        else:
            unknown = sorted(set(hr) - {"value", "n", "n_basis", "source", "date", "tol"})
            if unknown:
                errs.append("unknown hand_read key(s): %s" % ", ".join(unknown))
            if not isinstance(hr.get("value"), (int, float)):
                errs.append("hand_read.value must be a number")
            if "n" in hr and (not isinstance(hr["n"], int) or isinstance(hr["n"], bool)):
                errs.append("hand_read.n must be an integer")
            if hr.get("n_basis", "population") not in ("population", "numerator"):
                errs.append("hand_read.n_basis must be population or numerator")
    return errs


# -------------------------------------------------------------------- data
def connect():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row
    return con


def fetch_rows(con, spec):
    """Rows admitted by the slice's static filters (time window applied in Python)."""
    sl = spec["slice"]
    needs = METRIC_NEEDS[spec["metric"]]
    where, args = ["p.isDemo = 0"], []
    if spec["venue"] != "all":
        where.append("p.venue = ?")
        args.append(spec["venue"])
    if sl.get("bot", "all") != "all":
        where.append("p.botId = ?")
        args.append(sl["bot"])
    status = sl.get("status", "settled")
    if status == "settled":
        where.append("p.status IN ('closed','resolved')")
    elif status == "open":
        where.append("p.status = 'open'")
    if "entryMin" in sl:
        where.append("p.entryPrice >= ?")
        args.append(float(sl["entryMin"]))
    if "entryMax" in sl:
        where.append("p.entryPrice < ?")
        args.append(float(sl["entryMax"]))
    if "fillBasis" in sl:
        where.append("p.fillBasis = ?")
        args.append(sl["fillBasis"])
    fs = sl.get("fillStatus")
    if fs == "stamped":
        where.append("p.fillStatus IS NOT NULL")
    elif fs:
        where.append("p.fillStatus = ?")
        args.append(fs)
    join = ""
    if "ruleSetVersionMin" in sl or "observed" in needs:
        join += " JOIN DecisionJournal d ON d.id = p.decisionJournalId"
    if "observed" in needs:
        join += " JOIN ObservedTrade o ON o.id = d.observedTradeId"
    cols = ["p.id", "p.botId", "p.marketId", "p.outcome", "p.walletAddress", "p.entryPrice",
            "p.simulatedPositionSize", "p.realizedPnl", "p.status", "p.fillStatus",
            "p.openedAt", "p.closedAt", "p.resolvedAt"]
    if "ruleSetVersionMin" in sl:
        cols.append("d.ruleSetVersion")
    else:
        cols.append("NULL AS ruleSetVersion")
    if "observed" in needs:
        cols.append("o.walletEntryPrice AS walletEntryPrice")
    else:
        cols.append("NULL AS walletEntryPrice")
    sql = "SELECT %s FROM PaperTrade p%s WHERE %s" % (", ".join(cols), join, " AND ".join(where))
    if "ruleSetVersionMin" in sl:
        sql += " AND d.ruleSetVersion >= ?"
        args.append(int(sl["ruleSetVersionMin"]))
    rows = [dict(r) for r in con.execute(sql, args)]
    out = []
    for r in rows:
        t = as_dt(r["openedAt"]) if sl.get("clock", "settled") == "opened" \
            else (as_dt(r["closedAt"]) or as_dt(r["resolvedAt"]))
        if t is None:
            continue
        r["_t"] = t
        if "since" in sl and t.date() < parse_dt(sl["since"]).date():
            continue
        if "until" in sl and t.date() > parse_dt(sl["until"]).date():
            continue
        out.append(r)
    return out


def classify_price_side(r):
    b, w = r["entryPrice"], r["walletEntryPrice"]
    if w is None:
        return "neither"
    d_same = abs(b - w)
    d_mirror = abs(b - (1.0 - w))
    if d_mirror + 0.01 < d_same and d_mirror < PS_MIRROR and d_same > PS_SEP:
        return "INVERTED"
    if d_same <= PS_TOL:
        return "consistent"
    return "neither"


def compute_metric(metric, rows):
    """-> dict(value, n, numerator). value None means the metric is undefined here."""
    n = len(rows)
    if metric == "legs":
        return {"value": float(n), "n": n, "numerator": n}
    if metric == "pnl":
        return {"value": sum(r["realizedPnl"] or 0.0 for r in rows), "n": n, "numerator": n}
    if metric == "roi":
        ntl = sum(r["simulatedPositionSize"] or 0.0 for r in rows)
        pnl = sum(r["realizedPnl"] or 0.0 for r in rows)
        return {"value": (pnl / ntl) if ntl > 0 else None, "n": n, "numerator": n}
    if metric == "hit_rate":
        if n == 0:
            return {"value": None, "n": 0, "numerator": 0}
        wins = sum(1 for r in rows if (r["realizedPnl"] or 0.0) > 0)
        return {"value": wins / float(n), "n": n, "numerator": wins}
    if metric == "mean_entry":
        if n == 0:
            return {"value": None, "n": 0, "numerator": 0}
        return {"value": sum(r["entryPrice"] for r in rows) / float(n), "n": n, "numerator": n}
    if metric in ("inverted_legs", "inverted_share", "inverted_pnl_share"):
        inv = [r for r in rows if classify_price_side(r) == "INVERTED"]
        if metric == "inverted_legs":
            return {"value": float(len(inv)), "n": n, "numerator": len(inv)}
        if metric == "inverted_share":
            return {"value": (len(inv) / float(n)) if n else None, "n": n, "numerator": len(inv)}
        total = sum(r["realizedPnl"] or 0.0 for r in rows)
        if n == 0 or total == 0:
            return {"value": None, "n": n, "numerator": len(inv)}
        return {"value": sum(r["realizedPnl"] or 0.0 for r in inv) / total,
                "n": n, "numerator": len(inv)}
    if metric in ("fill_reach", "unfilled_pnl_share"):
        stamped = [r for r in rows if r["fillStatus"] in ("filled", "unfilled")]
        if metric == "fill_reach":
            if not stamped:
                return {"value": None, "n": 0, "numerator": 0}
            filled = sum(1 for r in stamped if r["fillStatus"] == "filled")
            return {"value": filled / float(len(stamped)), "n": len(stamped), "numerator": filled}
        total = sum(r["realizedPnl"] or 0.0 for r in stamped)
        if not stamped or total == 0:
            return {"value": None, "n": len(stamped), "numerator": 0}
        unf = sum(r["realizedPnl"] or 0.0 for r in stamped if r["fillStatus"] == "unfilled")
        return {"value": unf / total, "n": len(stamped),
                "numerator": sum(1 for r in stamped if r["fillStatus"] == "unfilled")}
    raise KeyError(metric)


def observation(con, spec, freeze):
    rows = fetch_rows(con, spec)
    pre = [r for r in rows if r["_t"] <= freeze]
    post = [r for r in rows if r["_t"] > freeze]
    m_all = compute_metric(spec["metric"], rows)
    m_pre = compute_metric(spec["metric"], pre)
    m_post = compute_metric(spec["metric"], post)
    return {"n_all": m_all["n"], "value_all": m_all["value"], "num_all": m_all["numerator"],
            "n_pre": m_pre["n"], "value_pre": m_pre["value"],
            "n_post": m_post["n"], "value_post": m_post["value"], "num_post": m_post["numerator"]}


# ------------------------------------------------------------------ states
def streak_for(reads, spec_id, n_all):
    """Consecutive graded reads (this one included) with the same slice population."""
    if n_all is None:
        return 0
    graded = [r for r in reads
              if r.get("id") == spec_id and r.get("state") not in ("PENDING", "REJECTED",
                                                                   "REJECTED_PRE_TRUE")]
    streak = 0
    for r in reversed(graded):
        if r.get("n_all") == n_all:
            streak += 1
        else:
            break
    return streak + 1  # + the read being taken now


def evaluate(spec, obs, now=None, streak=None):
    """Pure state machine. obs keys: n_all, value_all, n_pre, value_pre, n_post, value_post."""
    now = now or datetime.now().astimezone()
    freeze = parse_dt(spec["frozen_at"])
    bar = required_n(spec)
    op = OPS[spec["op"]]
    thr = spec["threshold"]

    if now < freeze:
        return {"state": "PENDING", "reason": "frozen_at %s not reached" % spec["frozen_at"],
                "bar": bar, "pre_true": False, "streak": 0}

    pre_true = obs["value_pre"] is not None and op(obs["value_pre"], thr)
    if pre_true and obs["n_pre"] >= bar:
        return {"state": "REJECTED_PRE_TRUE", "bar": bar, "pre_true": True, "streak": 0,
                "reason": "predicate already true pre-freeze with n=%d >= %d"
                          % (obs["n_pre"], bar)}

    if obs["n_post"] < bar:
        state = "UNGRADEABLE"
        reason = "post-freeze n=%d < required %d (max(min_n=%d, floor=%d))" % (
            obs["n_post"], bar, spec["min_n"], FLOOR[spec["metric"]])
    elif obs["value_post"] is None:
        state, reason = "UNGRADEABLE", "metric undefined on the post-freeze population"
    elif op(obs["value_post"], thr):
        if pre_true:
            state, reason = "NO_INFORMATION", (
                "SUPPORTED but the predicate already held pre-freeze (n=%d, below the bar)"
                % obs["n_pre"])
        else:
            state, reason = "SUPPORTED", "post-freeze value clears the threshold"
    else:
        state, reason = "REFUTED", "post-freeze value fails the threshold"

    streak = streak if streak is not None else 0
    frozen = streak >= 7 and state in ("UNGRADEABLE", "SUPPORTED", "NO_INFORMATION")
    if frozen:
        reason = "FROZEN: population n=%d unchanged across %d consecutive graded reads; %s" % (
            obs["n_all"], streak, reason)
        state = "FROZEN"
    return {"state": state, "reason": reason, "bar": bar, "pre_true": pre_true,
            "streak": streak}


# ------------------------------------------------------------------- files
def load_jsonl(path):
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit("%s:%d is not JSON: %s" % (path, i, exc))
    return out


def append_jsonl(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def write_registry(specs, path=None):
    path = path or REGISTRY
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for s in specs:
            fh.write(json.dumps(s, sort_keys=False) + "\n")
    tmp.replace(path)


# -------------------------------------------------------------------- cmds
def cmd_validate(args):
    specs = load_jsonl(REGISTRY)
    bad = 0
    seen = set()
    for s in specs:
        errs = validate_spec(s)
        sid = s.get("id", "<no-id>")
        if sid in seen:
            errs = errs + ["duplicate id %r" % sid]
        seen.add(sid)
        if errs:
            bad += 1
            print("REJECT %-28s %s" % (sid, "; ".join(errs)))
        else:
            print("ok     %-28s metric=%-19s bar=%d sha=%s"
                  % (sid, s["metric"], required_n(s), spec_sha(s)[:12]))
    print("\n%d spec(s), %d rejected" % (len(specs), bad))
    return 1 if bad else 0


def cmd_grade(args):
    specs = load_jsonl(REGISTRY)
    reads = load_jsonl(READS)
    now = parse_dt(args.now) if args.now else datetime.now().astimezone()
    con = connect()
    rows_out = []
    rejects = 0

    for s in specs:
        sid = s.get("id", "<no-id>")
        errs = validate_spec(s)
        if errs:
            rejects += 1
            s["state"] = "REJECTED"
            s["last_n"] = None
            rows_out.append({"id": sid, "state": "REJECTED", "reason": "; ".join(errs)})
            continue

        freeze = parse_dt(s["frozen_at"])
        obs = observation(con, s, freeze)
        streak = streak_for(reads, sid, obs["n_all"])
        ev = evaluate(s, obs, now=now, streak=streak)
        last_read = None
        for r in reads:
            if r.get("id") == sid:
                last_read = r
        sha = spec_sha(s)
        modified = bool(last_read and last_read.get("spec_sha") and
                        last_read["spec_sha"] != sha)

        read = {
            "ts": now.isoformat(),
            "id": sid,
            "metric": s["metric"],
            "venue": s["venue"],
            "frozen_at": s["frozen_at"],
            "op": s["op"],
            "threshold": s["threshold"],
            "required_n": ev["bar"],
            "state": ev["state"],
            "reason": ev["reason"],
            "n_all": obs["n_all"],
            "value_all": obs["value_all"],
            "n_pre": obs["n_pre"],
            "value_pre": obs["value_pre"],
            "n_post": obs["n_post"],
            "value_post": obs["value_post"],
            "streak": ev["streak"],
            "spec_sha": sha,
            "modified": modified,
            "source": "grader",
        }
        s["state"] = ev["state"]
        s["last_n"] = obs["n_post"]
        s["reads"] = sum(1 for r in reads if r.get("id") == sid) + 1
        s["spec_sha"] = sha
        rows_out.append(read)
        if not args.dry_run:
            append_jsonl(READS, read)
            reads.append(read)

    con.close()
    if not args.dry_run:
        write_registry(specs)

    if args.json:
        print(json.dumps(rows_out, indent=2))
    else:
        print("%-26s %-14s %12s %6s %6s %6s %12s %6s %8s"
              % ("id", "state", "post", "n", "need", "n_all", "all", "streak", "flags"))
        for r in rows_out:
            if r.get("state") == "REJECTED":
                print("%-26s %-14s  %s" % (r["id"], "REJECTED", r["reason"]))
                continue
            post = r["value_post"]
            allv = r["value_all"]
            print("%-26s %-14s %12s %6d %6d %6d %12s %6d %8s"
                  % (r["id"], r["state"],
                     ("%.4f" % post) if post is not None else "-",
                     r["n_post"], r["required_n"], r["n_all"],
                     ("%.4f" % allv) if allv is not None else "-",
                     r["streak"], "MODIFIED" if r["modified"] else ""))
            if r["state"] in ("UNGRADEABLE", "FROZEN", "NO_INFORMATION", "REJECTED_PRE_TRUE"):
                print("%26s   %s" % ("", r["reason"]))
        if args.dry_run:
            print("\n(dry run: registry and read log untouched)")
        else:
            print("\nappended %d read(s) to %s" % (len([r for r in rows_out
                                                        if r.get("state") != "REJECTED"]), READS))
    return 1 if rejects else 0


def cmd_adopt(args):
    specs = load_jsonl(REGISTRY)
    now = parse_dt(args.now) if args.now else datetime.now().astimezone()
    con = connect()
    results = []
    for s in specs:
        hr = s.get("hand_read")
        if not hr:
            continue
        errs = validate_spec(s)
        if errs:
            results.append({"id": s["id"], "reproduced": False,
                            "reason": "spec invalid: " + "; ".join(errs)})
            continue
        rows = fetch_rows(con, s)          # ALL rows in the slice, no freeze cut
        m = compute_metric(s["metric"], rows)
        tol = float(hr.get("tol", TOL[s["metric"]]))
        ok_val = m["value"] is not None and abs(m["value"] - float(hr["value"])) <= tol
        n_basis = hr.get("n_basis", "population")
        n_got = m["n"] if n_basis == "population" else m["numerator"]
        ok_n = True
        n_drift = None
        hand_n = None
        if "n" in hr:
            hand_n = int(hr["n"])
            n_drift = n_got - hand_n
            # A BOUNDED slice (since/until) is closed, so its n must match exactly.
            # A CUMULATIVE slice only grows: the hand read carries a DATE, not an
            # instant, so legs that settled later that same day are legitimately
            # absent from it. Requiring exact n there makes a correct engine fail
            # as the book moves -- the mirror of the defect this file grades against.
            bounded = ("since" in s["slice"] or "until" in s["slice"])
            ok_n = (n_got == hand_n) if bounded else (n_got >= hand_n)
        if not ok_n:
            reason = ("n %s < %s (cumulative population shrank)" % (n_got, hand_n)
                      if n_drift is not None and n_drift < 0
                      else "n %s != %s (bounded window)" % (n_got, hr.get("n")))
        elif not ok_val:
            reason = "value off by %s" % (m["value"] - float(hr["value"]))
        else:
            reason = ""
        results.append({
            "id": s["id"], "metric": s["metric"],
            "hand_value": float(hr["value"]), "grader_value": m["value"],
            "delta": (m["value"] - float(hr["value"])) if m["value"] is not None else None,
            "tol": tol,
            "hand_n": hr.get("n"), "grader_n": n_got, "n_drift": n_drift, "n_basis": n_basis,
            "hand_source": hr.get("source", ""),
            "reproduced": bool(ok_val and ok_n),
            "reason": reason,
        })
    con.close()

    need = 2
    total = len(results)
    reps = sum(1 for r in results if r["reproduced"])
    verdict = "ADOPT" if (total >= 3 and reps >= need) else "HOLD"
    payload = {"generated_at": now.isoformat(), "rule": "adopt iff >= 2 of 3 hand-read gates reproduce",
               "hand_read_gates": total, "reproduced": reps, "verdict": verdict,
               "gates": results}
    if not args.dry_run:
        ADOPTION.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print("%-26s %-19s %12s %12s %10s %6s %6s %s"
          % ("id", "metric", "hand", "grader", "delta", "n_hand", "n_got", "reproduced"))
    for r in results:
        if r.get("grader_value") is None:
            print("%-26s %-19s %12s %12s %10s %6s %6s %s   %s"
                  % (r["id"], r["metric"], r["hand_value"], "-", "-",
                     r.get("hand_n"), r.get("grader_n"), "NO", r.get("reason")))
            continue
        print("%-26s %-19s %12.4f %12.4f %+10.4f %6s %6s %s   %s"
              % (r["id"], r["metric"], r["hand_value"], r["grader_value"], r["delta"],
                 r.get("hand_n"), r.get("grader_n"), "YES" if r["reproduced"] else "NO",
                 r.get("reason")))
    print("\n%d of %d hand-read gates reproduce -> %s" % (reps, total, verdict))
    if not args.dry_run:
        print("wrote %s" % ADOPTION)
    return 0 if verdict == "ADOPT" else 1


def cmd_import_legacy(args):
    spec_id = args.id
    specs = [s for s in load_jsonl(REGISTRY) if s.get("id") == spec_id]
    if not specs:
        raise SystemExit("no spec %r in %s" % (spec_id, REGISTRY))
    legacy = load_jsonl(LEGACY_ENTRY_FLOOR)
    existing = {(r.get("id"), r.get("ts"), r.get("source")) for r in load_jsonl(READS)}
    added = 0
    for row in legacy:
        v = row.get("verdict") or {}
        n = (v.get("gateA_n") or {}).get("value")
        need = (v.get("gateA_n") or {}).get("need")
        roi = (v.get("gateA_roi") or {}).get("value")
        if n is None or roi is None:
            continue
        ts = row.get("ranAt")
        key = (spec_id, ts, "legacy:entry-floor-read.jsonl")
        if key in existing:
            continue
        state = "PENDING" if v.get("state") == "PENDING_DATE" else "UNGRADEABLE"
        out = {
            "ts": ts, "id": spec_id, "metric": specs[0]["metric"],
            "frozen_at": specs[0]["frozen_at"], "op": specs[0]["op"],
            "threshold": specs[0]["threshold"], "required_n": need or required_n(specs[0]),
            "state": state, "reason": "legacy bespoke read: %s" % v.get("note", ""),
            "n_all": n, "value_all": roi, "n_pre": None, "value_pre": None,
            "n_post": None, "value_post": None, "streak": None,
            "spec_sha": spec_sha(specs[0]), "modified": False,
            "source": "legacy:entry-floor-read.jsonl",
        }
        append_jsonl(READS, out)
        existing.add(key)
        added += 1
    print("imported %d legacy read(s) for %s from %s" % (added, spec_id, LEGACY_ENTRY_FLOOR))
    return 0


# ---------------------------------------------------------------- self-test
def cmd_self_test(args):
    fails = []
    checks = [0]

    def chk(name, cond, detail=""):
        checks[0] += 1
        if cond:
            print("PASS  %-52s %s" % (name, detail))
        else:
            print("FAIL  %-52s %s" % (name, detail))
            fails.append(name)

    base = {"id": "t-spec", "frozen_at": "2026-01-01", "metric": "roi", "venue": "all",
            "slice": {}, "op": "<=", "threshold": -0.2, "min_n": 5, "state": "UNGRADED",
            "last_n": None, "reads": 0}

    def mod(**kw):
        s = json.loads(json.dumps(base))
        for k, v in kw.items():
            if k == "slice":
                s["slice"].update(v)
            else:
                s[k] = v
        return s

    chk("valid base spec", validate_spec(base) == [], str(validate_spec(base)))
    chk("unknown metric rejected", bool(validate_spec(mod(metric="profit"))))
    chk("unknown spec key rejected", bool(validate_spec(mod(minN=5))))
    chk("unknown slice key rejected", bool(validate_spec(mod(slice={"slices": {}}))))
    chk("unknown op rejected", bool(validate_spec(mod(op="=>"))))
    chk("non-integer min_n rejected", bool(validate_spec(mod(min_n=5.5))))
    chk("bad hand_read key rejected", bool(validate_spec(mod(hand_read={"vals": 1}))))

    chk("floor raises the bar (roi min_n=5 -> 30)",
        required_n(mod(min_n=5)) == 30, "bar=%d" % required_n(mod(min_n=5)))
    chk("spec min_n above floor is kept (60)",
        required_n(mod(min_n=60)) == 60, "bar=%d" % required_n(mod(min_n=60)))

    obs_n = {"n_all": 40, "value_all": -0.5, "n_pre": 0, "value_pre": None,
             "n_post": 40, "value_post": -0.5}
    ev = evaluate(mod(min_n=60), obs_n, now=parse_dt("2026-02-01"), streak=1)
    chk("n below bar -> UNGRADEABLE", ev["state"] == "UNGRADEABLE", ev["state"])

    ev = evaluate(base, {"n_all": 40, "value_all": 0.1, "n_pre": 0, "value_pre": None,
                         "n_post": 40, "value_post": 0.1},
                  now=parse_dt("2026-02-01"), streak=1)
    chk("predicate false -> REFUTED", ev["state"] == "REFUTED", ev["state"])

    ev = evaluate(base, {"n_all": 40, "value_all": None, "n_pre": 0, "value_pre": None,
                         "n_post": 40, "value_post": None},
                  now=parse_dt("2026-02-01"), streak=1)
    chk("undefined metric -> UNGRADEABLE", ev["state"] == "UNGRADEABLE", ev["state"])

    ev = evaluate(base, {"n_all": 100, "value_all": -0.3, "n_pre": 100, "value_pre": -0.3,
                         "n_post": 100, "value_post": -0.3},
                  now=parse_dt("2026-02-01"), streak=1)
    chk("already true pre-freeze with n>=bar -> REJECTED_PRE_TRUE",
        ev["state"] == "REJECTED_PRE_TRUE", ev["state"])

    ev = evaluate(base, {"n_all": 100, "value_all": -0.3, "n_pre": 10, "value_pre": -0.3,
                         "n_post": 100, "value_post": -0.3},
                  now=parse_dt("2026-02-01"), streak=1)
    chk("supported but already true (pre n<bar) -> NO_INFORMATION",
        ev["state"] == "NO_INFORMATION", ev["state"])

    ev = evaluate(base, {"n_all": 40, "value_all": -0.3, "n_pre": 0, "value_pre": None,
                         "n_post": 40, "value_post": -0.3},
                  now=parse_dt("2026-02-01"), streak=7)
    chk("n unchanged 7 reads -> FROZEN", ev["state"] == "FROZEN", ev["state"])

    ev = evaluate(base, {"n_all": 40, "value_all": -0.3, "n_pre": 0, "value_pre": None,
                         "n_post": 40, "value_post": -0.3},
                  now=parse_dt("2026-02-01"), streak=6)
    chk("n unchanged 6 reads -> SUPPORTED (not yet frozen)",
        ev["state"] == "SUPPORTED", ev["state"])

    ev = evaluate(base, {"n_all": 40, "value_all": 0.5, "n_pre": 0, "value_pre": None,
                         "n_post": 40, "value_post": 0.5},
                  now=parse_dt("2026-02-01"), streak=9)
    chk("REFUTED is not frozen (frozen population is not the claim)",
        ev["state"] == "REFUTED", ev["state"])

    ev = evaluate(base, {"n_all": 0, "value_all": None, "n_pre": 0, "value_pre": None,
                         "n_post": 0, "value_post": 0.1},
                  now=parse_dt("2025-12-01"), streak=1)
    chk("now before frozen_at -> PENDING", ev["state"] == "PENDING", ev["state"])

    reads = [{"id": "x", "state": "UNGRADEABLE", "n_all": 31} for _ in range(6)]
    chk("streak reads the population history", streak_for(reads, "x", 31) == 7,
        "streak=%d" % streak_for(reads, "x", 31))
    reads2 = reads + [{"id": "x", "state": "UNGRADEABLE", "n_all": 32}]
    chk("streak resets when population moves", streak_for(reads2, "x", 32) == 2,
        "streak=%d" % streak_for(reads2, "x", 32))
    reads3 = [{"id": "x", "state": "PENDING", "n_all": 31} for _ in range(9)]
    chk("PENDING reads do not count toward FROZEN", streak_for(reads3, "x", 31) == 1,
        "streak=%d" % streak_for(reads3, "x", 31))

    # metric arithmetic on synthetic rows
    def row(b, w, ntl=10.0, pnl=1.0, fill=None):
        return {"entryPrice": b, "walletEntryPrice": w, "simulatedPositionSize": ntl,
                "realizedPnl": pnl, "fillStatus": fill}
    rows = [row(0.25, 0.75, 10.0, 5.0), row(0.50, 0.50, 10.0, -10.0)]
    chk("inverted_legs counts the mirrored leg", compute_metric("inverted_legs", rows)["value"] == 1.0)
    chk("inverted_pnl_share divides by total PnL",
        abs(compute_metric("inverted_pnl_share", rows)["value"] - (-1.0)) < 1e-9,
        str(compute_metric("inverted_pnl_share", rows)["value"]))
    chk("roi = pnl / notional",
        abs(compute_metric("roi", rows)["value"] - (-0.25)) < 1e-9)
    rows_fill = [row(0.2, 0.2, fill="filled"), row(0.3, 0.3, fill="unfilled"),
                 row(0.4, 0.4, fill=None)]
    chk("fill_reach uses stamped rows only",
        compute_metric("fill_reach", rows_fill)["value"] == 0.5 and
        compute_metric("fill_reach", rows_fill)["n"] == 2)

    print("\n%d/%d checks failed" % (len(fails), checks[0]))
    return 1 if fails else 0


# -------------------------------------------------------------------- main
def main(argv=None):
    global REGISTRY, READS
    ap = argparse.ArgumentParser(description="deterministic grader for pre-registered gates")
    ap.add_argument("--registry", default=None, help="override registry path (testing)")
    ap.add_argument("--reads", default=None, help="override read-log path (testing)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grade", help="grade every registry spec, append reads")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--json", action="store_true")
    g.add_argument("--now", default=None, help="ISO timestamp override (reproducibility)")
    g.set_defaults(func=cmd_grade)

    v = sub.add_parser("validate", help="schema/vocabulary check only")
    v.set_defaults(func=cmd_validate)

    a = sub.add_parser("adopt", help="reproduce hand-read gates and apply the adoption rule")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--now", default=None)
    a.set_defaults(func=cmd_adopt)

    i = sub.add_parser("import-legacy", help="seed read history from a legacy bespoke read log")
    i.add_argument("--id", default="entry-floor-a")
    i.set_defaults(func=cmd_import_legacy)

    t = sub.add_parser("self-test", help="exercise the guards on synthetic observations")
    t.set_defaults(func=cmd_self_test)

    args = ap.parse_args(argv)
    if args.registry:
        REGISTRY = Path(args.registry).expanduser().resolve()
    if args.reads:
        READS = Path(args.reads).expanduser().resolve()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
