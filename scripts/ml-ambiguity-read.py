#!/usr/bin/env python3
"""
ml-ambiguity-read.py — PRICE the resolution-ambiguity filter before building anything.

PRE-REGISTERED (written before the run, so the result can fail):
  H   Ambiguous resolution criteria make YES overpriced: markets whose rules are unclear, contingent
      or sourced from nowhere specific resolve to YES LESS often than their price implies, because
      the exotic case usually does not happen.
  Test residual = y_yes - implied_yes_p, for markets an LLM judge flags ambiguous vs clean, with a
      CI bootstrapped over MARKETS (one label per market, so markets are the cluster).
  Tradeable  buy NO at the quoted ask on ambiguous markets; report net ROI after fee + premium.
  FALSIFIED IF  ambiguous residual CI includes 0, or the NO-buy net ROI does not clear 0.

WHY THE DATA HAD TO BE ACQUIRED
0 of 15,889,482 MarketSnapshot rows carry resolution text -- `rawMarketJson` is '{}' in 100% of them
and only the ~63-char question title is stored ("Jets vs. Stars"). The filter's entire premise is
reading the rules, so descriptions are fetched from Gamma by conditionId (200 OK, 683-3556 chars,
and they genuinely carry the contingency clauses the filter is meant to catch).

THE JUDGE'S RUBRIC IS THE RISK. An LLM told to find ambiguity will find it everywhere, which would
make every market "ambiguous" and the measurement vacuous. So the rubric is narrow, the judge must
answer in JSON, and the script ABORTS if the flag rate lands outside a sane range -- a judge that
flags almost everything is measuring its own agreeableness, not the markets.

Usage:
  .venv-ml/bin/python scripts/ml-ambiguity-read.py --limit 240 --concurrency 4
  .venv-ml/bin/python scripts/ml-ambiguity-read.py --limit 40 --dry-run     # eyeball the judge
"""

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com/markets"
OLLAMA = "http://localhost:11434/api/generate"
# NOT qwen3.5:9b: it is a THINKING model and spends its whole num_predict budget in the `thinking`
# field, returning response '' with done_reason 'length'. Measured: 200/200 tokens thinking, 0 output.
# qwen2.5:7b-instruct answers the same prompt in 6 tokens with clean JSON. A reasoning model is the
# wrong tool for a 240-item labelled judgement; revisit only if the effect proves marginal.
# qwen3.5:9b IS the judge: it is a thinking model, so num_predict must be large enough for the
# reasoning pass or it returns '' with done_reason 'length' (measured: 200/200 tokens thinking, 0
# output). qwen2.5:7b-instruct is faster but was measured to flip 95% -> 0% on a prompt reword.
DEFAULT_MODEL = "qwen3.5:9b"
OUT = "data/ml/ambiguity-report.json"

# A holistic "is this ambiguous?" question is SUGGESTIBLE and was measured to be worthless: the same
# judge on the same 20 markets returned 95% ambiguous, then 0% ambiguous at confidence 1.00, purely
# from re-wording the prompt. So the judgement is decomposed into four auditable yes/no checks, each
# answered from the rules TEXT alone. Ambiguity is then DERIVED here, not asserted by the model, and
# the per-criterion breakdown is reported so we can see which check drives any flag.
RUBRIC = """Audit this prediction market's RESOLUTION RULES. Answer four yes/no checks about the
RULES TEXT ONLY. Do not consider whether the outcome is likely, only whether the rules are decidable.

1. named_source: do the rules name WHERE the outcome is determined from (an official body, a named
   site, a specific published figure)? If the text says "per the official MLB box score" or "per the
   National Weather Service", that is YES. If it says only "the winner will be determined" with no
   provenance, that is NO.
2. measurable_condition: is the winning condition stated as something checkable (a team wins, a value
   exceeds a number, a party controls a chamber)? Vague standards like "widely considered", "is
   successful", "is popular" are NO.
3. alternatives: could two honest traders read these exact rules and reach DIFFERENT answers about
   how a real edge case resolves (postponement, tie, disqualification, a value exactly on the
   boundary)? YES if the text leaves such a case genuinely open.
4. contingencies: does the text address what happens if the event is postponed, cancelled or void?

A missing structured metadata field is NOT evidence for any of these -- judge only the words.

Answer with JSON only:
{"named_source": true|false, "measurable_condition": true|false, "alternatives": true|false,
 "contingencies": true|false, "reason": "<=14 words"}"""


def fetch_one_clob(condition_id, attempts=3):
    """
    Fetch one market record from CLOB by conditionId.

    measured 2026-10-21: this is the ONLY reliable route for these markets. Gamma's `condition_ids`
    filter returns ZERO rows even with closed=true, and `slug=<marketId>` only resolves markets that
    are still listed -- on a random sample of archived candidates Gamma found 3 of 20 (15%). CLOB
    /markets/<conditionId> returned full descriptions for 8 of 8 archived markets (773-2569 chars).
    One request per market, so this is slower than a batch, but a batch that misses 85% is worthless.
    """
    url = "{}/{}".format(CLOB, condition_id)
    req = urllib.request.Request(url, headers={"User-Agent": "copybot-research/1.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                m = json.loads(r.read().decode())
            return {
                "description": m.get("description") or "",
                "resolutionSource": m.get("resolutionSource") or m.get("resolution_source") or "",
                "question": m.get("question") or "",
            }
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            return None
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    return None


def fetch_descriptions(condition_ids, concurrency=5):
    """Concurrent CLOB fetch keyed by conditionId."""
    found = {}
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        results = list(ex.map(fetch_one_clob, condition_ids))
    for cid, rec in zip(condition_ids, results):
        if rec and rec.get("description"):
            found[cid] = rec
    return found


# DETERMINISTIC PROXY JUDGE.
# The LLM judge could not be made reproducible: qwen3.5:9b (thinking) never terminates its reasoning
# pass (1600/1600 tokens, done_reason=length, empty response, 42.5s/market) and qwen2.5:7b-instruct
# flips 95% -> 0% ambiguous on the same 20 markets from a prompt reword alone. A filter whose
# classification step is not reproducible cannot be priced. This proxy is boring, free, auditable and
# identical on every run, so the ECONOMIC question can be answered even while the semantic judge is
# unsolved. It detects STRUCTURAL ambiguity markers only: no named provenance, or a vague standard, or
# unaddressed contingencies. It cannot see semantic vagueness -- that is the limitation to state.
RE_NAMED = re.compile(
    r"per the official|according to|official (league|site|website|source|results|box score|statistics)|"
    r"as reported by|per the (national|associated|reuters|associated press)|"
    r"published (by|on)|official (nba|nfl|mlb|nhl|fifa|uefa|fec|congress|white house)")
RE_CONTING = re.compile(
    r"postpon|cancel|second round|overturn|disqualif|reschedul|"
    r"if the (game|event|match|election|vote) is|if .{0,30}(is not|isn't) (known|held|completed)")
RE_VAGUE = re.compile(
    r"\bconsidered\b|\bwidely\b|\bgenerally\b|at (its|their|the) discretion|\breasonable\b|"
    r"may be deemed|is successful|is popular|sufficiently|\bsignificant\b|\bsubstantial\b|"
    r"as (they|it) see fit|in the (sole )?opinion")


def judge_regex(row, min_desc=120):
    """Deterministic structural-ambiguity proxy. Returns the same shape as the LLM judge."""
    t = (row.get("description") or "").lower()
    if len(t) < min_desc:
        return {"ambiguous": None, "confidence": 1.0, "reason": "TOO_SHORT"}
    named = bool(RE_NAMED.search(t))
    conting = bool(RE_CONTING.search(t))
    vague = bool(RE_VAGUE.search(t))
    return {
        "ambiguous": (not named) or vague, "confidence": 1.0,
        "named_source": named, "measurable_condition": not vague,
        "alternatives": vague, "contingencies": conting,
        "reason": "no-provenance" if not named else ("vague-standard" if vague else "clean"),
    }


def judge_one(model, row):
    # Do NOT render an empty resolutionSource as "(not stated)" -- the judge reads that as missing
    # provenance and flags 95% of markets ambiguous, which is a rubric artefact rather than a
    # property of the markets. The rules text governs; the metadata field is mostly empty upstream.
    text = "TITLE: {}\n\nRULES:\n{}".format(row["question"], row["description"][:3500])
    if row["resolutionSource"]:
        text += "\n\n(resolution source field: {})".format(row["resolutionSource"][:200])
    payload = json.dumps({
        "model": model, "prompt": RUBRIC + "\n\n---\n" + text, "stream": False,
        "format": "json", "options": {"temperature": 0.0, "num_predict": 1600},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode())
        raw = d.get("response") or ""
        if not raw.strip():
            return {"ambiguous": None, "confidence": 0.0,
                    "reason": "EMPTY_RESPONSE (done_reason={})".format(d.get("done_reason"))}
        j = json.loads(raw)
        ns = bool(j.get("named_source"))
        mc = bool(j.get("measurable_condition"))
        al = bool(j.get("alternatives"))
        co = bool(j.get("contingencies"))
        # Ambiguity is DERIVED from the checks, never asserted by the judge.
        ambiguous = (not ns) or (not mc) or al
        return {"ambiguous": ambiguous, "confidence": 1.0,
                "named_source": ns, "measurable_condition": mc,
                "alternatives": al, "contingencies": co,
                "reason": str(j.get("reason") or "")[:80]}
    except Exception as e:
        return {"ambiguous": None, "confidence": 0.0, "reason": "JUDGE_ERROR: {}".format(str(e)[:60])}


def cluster_ci(values, clusters, B=600, seed=11):
    values = np.asarray(values, dtype=float)
    clusters = np.asarray(clusters)
    if len(pd.unique(clusters)) < 3 or len(values) == 0:
        return (None, None)
    idx_by = pd.Series(range(len(clusters)), index=clusters).groupby(level=0).apply(
        lambda s: s.to_numpy())
    rng = np.random.default_rng(seed)
    means = [values[np.concatenate([idx_by.iloc[i] for i in rng.choice(len(idx_by), len(idx_by))])].mean()
             for _ in range(B)]
    return (round(float(np.percentile(means, 2.5)), 3), round(float(np.percentile(means, 97.5)), 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/ml/market-candidates.parquet")
    ap.add_argument("--db", default="prisma/dev.db")
    ap.add_argument("--limit", type=int, default=240)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--judge", default="llm", choices=["llm", "regex"],
                    help="regex = deterministic structural proxy; the only reproducible option measured")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    d = pd.read_parquet(args.parquet)
    d = d[d["y_yes"].notna() & d["passes_gate"].astype(bool)]
    # One row per market: the T-24h candidate if present, else the earliest.
    d = d.sort_values("horizon_h", ascending=False).drop_duplicates("market_id")
    markets = d["market_id"].drop_duplicates().tolist()
    random.Random(args.seed).shuffle(markets)
    markets = markets[: args.limit]
    print("candidate markets with labels: {:,} | sampling {:,}".format(len(d), len(markets)))

    # Need conditionIds: CLOB is keyed by conditionId, and marketId is a slug.
    con = sqlite3.connect("file:{}?mode=ro".format(args.db), uri=True)
    ph = ",".join("?" * len(markets))
    cid_by_market = dict(con.execute(
        "SELECT marketId, MAX(conditionId) FROM MarketSnapshot WHERE isDemo=0 AND marketId IN ({}) "
        "GROUP BY marketId".format(ph), markets).fetchall())
    con.close()
    want = [c for c in cid_by_market.values() if c]
    print("conditionIds to fetch: {:,}".format(len(want)))

    desc = fetch_descriptions(want, concurrency=args.concurrency)
    print("descriptions fetched: {:,} ({:.1f}%)".format(len(desc), 100.0 * len(desc) / max(len(want), 1)))
    if not desc:
        print("FATAL: no descriptions -- cannot price the filter")
        sys.exit(1)

    rows = []
    for m in markets:
        c = cid_by_market.get(m)
        if not c or c not in desc:
            continue
        r = desc[c]
        sub = d[d["market_id"] == m].iloc[0]
        rows.append({
            "market_id": m, "question": r["question"] or sub["question"],
            "description": r["description"], "resolutionSource": r["resolutionSource"],
            "yesPrice": float(sub["yesPrice"]), "y_yes": float(sub["y_yes"]),
            "band": str(sub["band"]), "side": sub["side"],
            "ask": float(sub["ask"]), "fee_ps": float(sub["fee_ps"]), "cost_ps": float(sub["cost_ps"]),
        })
    print("joinable rows: {:,}".format(len(rows)))

    if args.judge == "regex":
        print("judge: deterministic regex proxy (no LLM)")
        verdicts = [judge_regex(r) for r in rows]
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            verdicts = list(ex.map(lambda r: judge_one(args.model, r), rows))
    for r, v in zip(rows, verdicts):
        r.update(v)
    ok = [r for r in rows if r["ambiguous"] is not None]
    errs = len(rows) - len(ok)
    print("judged: {:,} | judge errors: {}".format(len(ok), errs))
    if not ok:
        print("FATAL: judge produced no valid answers")
        sys.exit(1)

    flag_rate = 100.0 * sum(1 for r in ok if r["ambiguous"]) / len(ok)
    print("\njudge flag rate: {:.1f}% ambiguous".format(flag_rate))
    # Which check drives any flag? Without this the flag rate is unattributable.
    ok_df = pd.DataFrame(ok)
    for crit in ["named_source", "measurable_condition", "alternatives", "contingencies"]:
        if crit in ok_df.columns:
            pct = 100.0 * float(ok_df[crit].mean())
            print("  check {:<22} YES {:5.1f}%".format(crit, pct))
    if args.dry_run:
        print("\n--- sample judgements (eyeball these) ---")
        for r in ok[:10]:
            print("  [{:<3}] src={} meas={} alt={} cont={} {:.30}".format(
                "AMB" if r["ambiguous"] else "ok",
                int(bool(r.get("named_source"))), int(bool(r.get("measurable_condition"))),
                int(bool(r.get("alternatives"))), int(bool(r.get("contingencies"))),
                r["question"]))
        print("\nDRY RUN — no verdict, no report.")
        return

    # The guard exists because an LLM told to find ambiguity finds it everywhere. A DETERMINISTIC
    # proxy is expected to flag more (most markets genuinely omit explicit provenance), so it gets a
    # wider band -- but it still aborts if it flags essentially everything, which would leave no
    # comparison group at all.
    hi_cap = 95.0 if args.judge == "regex" else 70.0
    if flag_rate < 3.0 or flag_rate > hi_cap:
        print("\nABORT: flag rate {:.1f}% is outside 3-{:.0f}%. A judge outside that range is".format(flag_rate, hi_cap))
        print("measuring its own strictness, not the markets, and any difference it finds is an artefact.")
        sys.exit(2)

    ok = pd.DataFrame(ok)
    ok["gross_yes"] = ok["y_yes"]
    # Buy NO at the ask: cost_ps, pays 1 - y_yes.
    ok["roi_no_pct"] = ((1.0 - ok["y_yes"]) / ok["cost_ps"] - 1.0) * 100.0

    print("\n=== RESIDUAL: does ambiguity leave YES overpriced? (y_yes - implied yesPrice) ===")
    out = {}
    for label, grp in [("AMBIGUOUS", ok[ok["ambiguous"]]), ("CLEAN", ok[~ok["ambiguous"]])]:
        if len(grp) < 5:
            print("  {:<10} n={:<4} (too few)".format(label, len(grp)))
            continue
        resid = (grp["y_yes"] - grp["yesPrice"]).values * 100.0
        lo, hi = cluster_ci(resid, grp["market_id"].values)
        roi_no = grp["roi_no_pct"].values
        nlo, nhi = cluster_ci(roi_no, grp["market_id"].values)
        print("  {:<10} n={:<4} mean residual {:>+7.2f}pp  CI [{:+.2f}, {:+.2f}]   "
              "buy-NO net ROI {:>+7.2f}%  CI [{:+.2f}, {:+.2f}]".format(
                  label, len(grp), resid.mean(), lo if lo is not None else 0.0,
                  hi if hi is not None else 0.0, roi_no.mean(),
                  nlo if nlo is not None else 0.0, nhi if nhi is not None else 0.0))
        out[label] = {
            "n": int(len(grp)), "mean_residual_pp": round(float(resid.mean()), 3),
            "residual_ci": [lo, hi], "buy_no_roi_pct": round(float(roi_no.mean()), 3),
            "buy_no_ci": [nlo, nhi],
            "win_rate_yes": round(float(grp["y_yes"].mean()) * 100.0, 2),
            "implied_yes_pct": round(float(grp["yesPrice"].mean()) * 100.0, 2),
        }

    amb = out.get("AMBIGUOUS")
    established = bool(
        amb and amb["residual_ci"][0] is not None and amb["residual_ci"][0] > 0
    )
    print("\n=== VERDICT (pre-registered) ===")
    if not amb:
        print("  NOT ESTABLISHED: too few ambiguous markets to test.")
        verdict = "NOT_ESTABLISHED"
    elif established:
        print("  CANDIDATE: ambiguous markets resolve YES MORE often than implied -- that is the")
        print("  OPPOSITE of the pre-registered direction, so the tradeable form would be buy YES,")
        print("  not buy NO. Direction and mechanism need re-deriving before any build.")
        verdict = "OPPOSITE_DIRECTION"
    elif amb["residual_ci"][1] is not None and amb["residual_ci"][1] < 0:
        print("  CANDIDATE: ambiguous markets resolve YES LESS often than implied, as pre-registered.")
        print("  Now check the buy-NO economic arm before proposing anything.")
        verdict = "CANDIDATE"
    else:
        print("  NOT ESTABLISHED: the ambiguous residual CI spans zero. Ambiguity, as judged here,")
        print("  is not priced wrong in either direction.")
        verdict = "NOT_ESTABLISHED"

    with open(OUT, "w") as f:
        json.dump({
            "built_at": pd.Timestamp.utcnow().isoformat(),
            "pre_registration": {
                "hypothesis": "ambiguous rules make YES overpriced (resolves YES less than implied)",
                "metric": "mean(y_yes - implied yesPrice) for ambiguous vs clean, CI clustered by market",
                "falsifier": "ambiguous residual CI includes 0, or buy-NO ROI does not clear 0",
            },
            "sample": len(ok), "judge": args.model, "flag_rate_pct": round(flag_rate, 2),
            "judge_errors": errs, "groups": out, "verdict": verdict,
        }, f, indent=2, default=str)
    print("\nwrote {}".format(OUT))


if __name__ == "__main__":
    main()
