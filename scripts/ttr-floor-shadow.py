#!/usr/bin/env python3
"""Forward shadow for the time-to-resolution floor: 2h -> 24h.

APPROVED 2026-10-23 (Lane A). This script does NOT change any rule. It measures the
population the new floor WOULD block, so the flip decision is made on forward data
instead of the in-sample read that proposed it.

BASIS CORRECTION 2026-11-23 (Lane B, approvals id apr-profit-floor-ttr-all-lane-basis)
-------------------------------------------------------------------------------
Through 2026-11-23 this shadow measured STANDARD ONLY (`BOT = "STANDARD"`), while the
gate it shadows is GLOBAL: `minTimeToResolutionHours` is one hard skip in
src/lib/scoring/trade.ts:124 inside the single `scoreTrade(..., rules)` call every lane
makes (scripts/score-trades.ts:592). The decision population is now EVERY lane the gate
binds, with each lane reported as a sub-arm, and the pre-registered verdict is read on
the COMBINED 2-24h population.

The correction also had to answer a second question the STANDARD-only arm could not:
WHAT DOES THE FLIP REACH? Counting band rows assumes every 2-24h leg dies at the floor.
It does not. The short-TTR lane rescue (trade.ts:266-272) clears a
`resolves in ... < min ...h` skip whenever the leg is `laneEligible` -- ttr inside
[shortTtrMinHours, shortTtrMaxHours] and adverse drift <= shortTtrMaxDrift -- and
scores >= shortTtrMinCopyScore. The live RuleSet carries 2 / 72 / 0.05 / 35, so the
ENTIRE 2-24h band sits inside the lane window: raising the floor to 24h adds a skip the
rescue immediately clears, and the leg then takes the main path (score >= minCopyScore)
or the $10 lane path (score below it) exactly as it does today. Measured by running the
scorer itself on a 22,464-case grid: 0 decisions, lane flags or sizes change, with three
controls armed (lane disabled -> 75 cases move; lane window 2-12h -> 15; lane score bar
999 -> 1,115). scripts/ttr-floor-reach-probe.ts is that probe; this shadow reports its
conclusion as `reach` and prints it beside the verdict, so a FLIP message never reads
as "this will block the band" when it blocks nothing.

THE DECISION -- n-DRIVEN (user chose option A, 2026-10-23):
  At n >= 150 settled legs in the at-risk band, FLIP LIVE unless the band's net ROI
  is >= +3.0%. A band that returns +3% or better is profitable work we would be
  throwing away, so "shadow >= +3%" is the REFUTATION, not the pass.

  THERE IS NO CALENDAR DEADLINE. The rule as first drafted said "shadow 14 days, flip
  unless >= +3% on >=150 blocked legs", and that was internally inconsistent: measured
  at 4.29 band openings/day, fourteen days yields ~60 settled legs, not 150. The two
  halves could never both be satisfied, so a day-14 run would have recorded a NULL
  where a decision had been promised. The day-14 clause is RETIRED, not reinterpreted:
  n is the sole trigger and the ETA printed below is information, not a deadline.

  REFUTATION (any one):
    (a) band net ROI >= +3.0% at n >= 150 settled legs          -> do not flip
    (b) flat 0.6-1.0 cells widen to >= +10% on 150 forward legs  -> do not flip
    (c) 3-7d ex-top-10 falls below 0% on a 60d read              -> do not flip
  (b) and (c) are reported here as not-yet-evaluable; they are manual reads at day 14
  so this script cannot quietly declare a pass on a clause it never tested.

WHY THE BAND IS [2, 24): the live RuleSet floor is 2h, so a leg with 2-24h left is
copied TODAY and would carry an added skip under the proposed floor. TTR below 2h should
not exist (the current floor blocks it) -- if any appear, that is itself a finding and is
reported separately rather than folded into the band.

TTR SOURCE: identical to scripts/profit-velocity.py -- the last MarketSnapshot at or
before entry+15min, timeToResolution in HOURS, re-based onto the entry instant. Reused
deliberately: a shadow that derives its own axis can disagree with the study that
motivated it and the argument becomes about the instrument instead of the rule.

SETTLEMENT: PaperTrade.realizedPnl ORs early exits (closed) and natural resolutions
(resolved). Both are reported, and the headline is the OR because that is how the lane
books PnL -- but resolved-only is shown beside it, because an exit-rule change during
the window can move the OR without the floor having anything to do with it. If the two
disagree in SIGN, the verdict refuses to flip.

POPULATION: isDemo=0, every botId, settled, openedAt >= approval date, deduped to the
first leg per bot|wallet|market|outcome (the basis scripts/profit-tenor.py §S15 and
drafts/profit-recs-20261121.md R1 were measured on). The undeduped count is reported
beside it; the two agree in sign and verdict.

Read-only. Writes data/ttr-floor-shadow.json only.
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "ttr-floor-shadow.json")
# A calibration replay (--since older than approval, or a different --band-lo) must NOT
# overwrite the forward-shadow artifact: the replay reports an IN-SAMPLE verdict (e.g.
# "FLIP" on 3,386 historical legs) which is exactly what the forward artifact is supposed
# to stay ignorant of until n=150 is reached out of sample. Calibration writes its own file.
CAL_OUT = os.path.join(ROOT, "data", "ttr-floor-shadow-calibration.json")

APPROVAL_DATE = "2026-10-23"
BASIS_CORRECTED_AT = "2026-11-23"       # the all-lane basis correction (Lane B)
CANONICAL_APPROVAL_DATE = "2026-10-23"   # the forward shadow's true start
CANONICAL_BAND_LO_H = 2.0                # the live floor at approval
# A calibration replay must reproduce the study it shadows, which was measured on
# STANDARD alone -- so calibration stays single-lane unless told otherwise.
CALIBRATION_BOT = "STANDARD"
# Retired as a decision trigger on 2026-10-23 (option A): kept only so the reason is
# legible next to the number that killed it.
SHADOW_DAYS_SUPERSEDED = 14
# Throughput is measured over a fixed TRAILING window, not over days-since-approval.
RATE_WINDOW_DAYS = 14
BAND_LO_H = 2.0        # live floor today
BAND_HI_H = 24.0       # proposed floor
MIN_LEGS = 150         # pre-registered n
REFUTE_ROI = 0.03      # band ROI at or above this = refuted (do not flip)

# The live RuleSet values this shadow reads to answer "what would the flip reach".
SHORT_TTR_MIN_SCORE = 35.0
SHORT_TTR_MAX_DRIFT = 0.05
# Sanity bound for the lane window when the DB row is unreadable; the live value is read.
FALLBACK_SHORT_TTR_MIN_H = 2.0
FALLBACK_SHORT_TTR_MAX_H = 72.0


def ms(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def live_lane_window(c):
    """The short-TTR lane window the rescue actually uses, from the active RuleSet."""
    try:
        row = c.execute("SELECT rulesJson, version FROM RuleSet ORDER BY version DESC LIMIT 1").fetchone()
        j = json.loads(row[0])
        return (float(j.get("shortTtrMinHours", FALLBACK_SHORT_TTR_MIN_H)),
                float(j.get("shortTtrMaxHours", FALLBACK_SHORT_TTR_MAX_H)),
                int(row[1]))
    except Exception:
        return FALLBACK_SHORT_TTR_MIN_H, FALLBACK_SHORT_TTR_MAX_H, None


def main():
    global APPROVAL_DATE, BAND_LO_H
    only_bot = None
    quiet = "--quiet" in sys.argv
    since_arg = None
    for i, a in enumerate(sys.argv):
        if a == "--since" and i + 1 < len(sys.argv):
            since_arg = sys.argv[i + 1]
        elif a == "--band-lo" and i + 1 < len(sys.argv):
            BAND_LO_H = float(sys.argv[i + 1])
        elif a == "--only-bot" and i + 1 < len(sys.argv):
            only_bot = sys.argv[i + 1]
    if since_arg is not None:
        APPROVAL_DATE = since_arg

    if not os.path.exists(DB):
        sys.exit("no database at %s" % DB)
    calibration = (APPROVAL_DATE != CANONICAL_APPROVAL_DATE) or (BAND_LO_H != CANONICAL_BAND_LO_H)
    if calibration and only_bot is None:
        # the historical study was STANDARD-only; a calibration that silently widened
        # the population could not reproduce it and would look like a broken instrument.
        only_bot = CALIBRATION_BOT
    out_path = CAL_OUT if calibration else OUT
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    c.row_factory = sqlite3.Row
    since = ms(APPROVAL_DATE)
    lane_lo_h, lane_hi_h, rules_version = live_lane_window(c)

    # Previous run's verdict, read BEFORE the artifact is overwritten. The watchdog speaks
    # on a VERDICT TRANSITION, not on every run: once the read is actionable it stays
    # actionable, and a daily re-post of the same settled line is noise the reader learns to
    # ignore (the class that makes an alert path worthless). A verdict that flips back
    # REFUTED -> FLIP still speaks, because that IS a transition.
    prev_verdict = None
    prev_basis = None
    if not calibration:
        try:
            with open(OUT) as pf:
                _prev = json.load(pf)
            prev_verdict = _prev.get("verdict")
            prev_basis = _prev.get("basis_corrected_at")
        except Exception:
            prev_verdict = None

    # --- the settled cohort ---------------------------------------------------
    sql = """SELECT p.status, p.botId AS bot, p.marketId AS market, p.walletAddress AS wallet,
                    p.outcome AS outcome, p.entryPrice AS px,
                    p.simulatedPositionSize AS ntl, p.realizedPnl AS pnl, p.openedAt,
                    j.reasonsJson AS rj, j.adjustedCopyScore AS sc,
                    o.walletEntryPrice AS wep, o.detectedPrice AS dp
             FROM PaperTrade p
             LEFT JOIN DecisionJournal j ON j.id = p.decisionJournalId
             LEFT JOIN ObservedTrade o ON o.id = j.observedTradeId
             WHERE p.isDemo=0 AND p.status IN ('closed','resolved')
               AND p.realizedPnl IS NOT NULL AND p.openedAt >= ?"""
    args = [since]
    if only_bot:
        sql += " AND p.botId = ?"
        args.append(only_bot)
    rows = c.execute(sql, args).fetchall()

    # EVERY leg opened since approval, whatever its status. This is the throughput
    # denominator, and it must be openings rather than settlements: a cohort one day
    # old has barely begun to settle, so dividing SETTLED legs by elapsed days reads
    # as ~0.9/day and projects a fantasy ETA.
    sql_open = """SELECT p.marketId AS market, p.botId AS bot, p.entryPrice AS px, p.openedAt
                  FROM PaperTrade p
                  WHERE p.isDemo=0 AND p.openedAt >= ?"""
    open_args = [since]
    if only_bot:
        sql_open += " AND p.botId = ?"
        open_args.append(only_bot)
    opened_rows = c.execute(sql_open, open_args).fetchall()

    cache = {}

    def ttr_at_entry(market_id, opened_at):
        """Last MarketSnapshot at or before entry+15min -- same snapshot as profit-velocity.py,
        but its TTR is re-based onto the ENTRY instant.

        The snapshot is taken at or before entry+15min, so its timeToResolution is already
        0-15 minutes STALE, and time-to-resolution only falls. A leg entered with 2.05h left
        reads 1.80h at the snapshot. The floor is evaluated at entry, so the elapsed
        snapshot->entry lag is added back.
        """
        key = (market_id, opened_at // 3_600_000)
        if key in cache:
            return cache[key]
        s = c.execute(
            """SELECT timeToResolution, collectedAt FROM MarketSnapshot
               WHERE marketId=? AND collectedAt<=? AND timeToResolution IS NOT NULL
               ORDER BY collectedAt DESC LIMIT 1""",
            (market_id, opened_at + 900_000),
        ).fetchone()
        if s is None:
            cache[key] = None
        else:
            lag_h = (s[1] - opened_at) / 3_600_000.0
            cache[key] = s[0] + lag_h
        return cache[key]

    def classify_rows(raw_rows, dedupe):
        band, under, over, unknown = [], [], [], 0
        seen = set()
        for r in raw_rows:
            if not r["px"] or r["px"] <= 0 or not r["ntl"] or r["ntl"] <= 0:
                continue
            if dedupe:
                key = (r["bot"], r["wallet"], r["market"], r["outcome"])
                if key in seen:
                    continue
                seen.add(key)
            ttl = ttr_at_entry(r["market"], r["openedAt"])
            if ttl is None or ttl < 0:
                unknown += 1
                continue
            drift = None
            if r["dp"] is not None and r["wep"] is not None:
                drift = max(0.0, float(r["dp"]) - float(r["wep"]))
            rec = {
                "bot": r["bot"],
                "market": r["market"],
                "ttl": ttl,
                "ntl": r["ntl"],
                "pnl": r["pnl"],
                "resolved": r["status"] == "resolved",
                # the admission path the leg actually took, from the journal's own reasons
                "lane": bool(r["rj"] and "Short-TTR lane" in r["rj"]),
                "score": r["sc"],
                "adverse_drift": drift,
            }
            if ttl < BAND_LO_H:
                under.append(rec)
            elif ttl < BAND_HI_H:
                band.append(rec)
            else:
                over.append(rec)
        return {"band": band, "over": over, "under": under, "unknown": unknown}

    def stats(recs):
        n = len(recs)
        if n == 0:
            return {"legs": 0, "markets": 0, "notional": 0.0, "pnl": 0.0, "roi": None,
                    "resolved_legs": 0, "resolved_roi": None}
        ntl = sum(x["ntl"] for x in recs)
        pnl = sum(x["pnl"] for x in recs)
        res = [x for x in recs if x["resolved"]]
        r_ntl = sum(x["ntl"] for x in res)
        r_pnl = sum(x["pnl"] for x in res)
        return {
            "legs": n,
            "markets": len({x["market"] for x in recs}),
            "notional": round(ntl, 2),
            "pnl": round(pnl, 2),
            "roi": (pnl / ntl) if ntl else None,
            "resolved_legs": len(res),
            "resolved_roi": (r_pnl / r_ntl) if r_ntl else None,
        }

    def bands_of(recs):
        return {
            "at_risk_2_24h": stats([x for x in recs["band"]]),
            "kept_24h_plus": stats([x for x in recs["over"]]),
            "under_live_floor_lt_2h": stats([x for x in recs["under"]]),
        }

    dedup = classify_rows(rows, True)
    raw = classify_rows(rows, False)

    lanes = sorted({r["bot"] for r in rows})
    by_lane = {}
    by_lane_raw = {}
    for bot in lanes:
        sub = {
            "band": [x for x in dedup["band"] if x["bot"] == bot],
            "over": [x for x in dedup["over"] if x["bot"] == bot],
            "under": [x for x in dedup["under"] if x["bot"] == bot],
        }
        by_lane[bot] = bands_of(sub)
        raw_sub = {
            "band": [x for x in raw["band"] if x["bot"] == bot],
            "over": [x for x in raw["over"] if x["bot"] == bot],
            "under": [x for x in raw["under"] if x["bot"] == bot],
        }
        by_lane_raw[bot] = bands_of(raw_sub)

    # admission path inside the band: lane copies vs main-funnel copies. These are the
    # two populations the flip treats differently -- and neither is blocked (see `reach`).
    lane_band = [x for x in dedup["band"] if x["lane"]]
    main_band = [x for x in dedup["band"] if not x["lane"]]

    def lane_eligible(rec):
        """Would the short-TTR rescue clear a newly-added `resolves in ... < 24h` skip?"""
        if not (lane_lo_h <= rec["ttl"] <= lane_hi_h):
            return False
        if rec["score"] is not None and rec["score"] < SHORT_TTR_MIN_SCORE:
            return False
        return rec["adverse_drift"] is not None and rec["adverse_drift"] <= SHORT_TTR_MAX_DRIFT

    reachable = [x for x in dedup["band"] if not lane_eligible(x)]
    unresolved = [x for x in dedup["band"] if x["adverse_drift"] is None]
    blocked = [x for x in reachable if x["adverse_drift"] is not None]

    # Trailing-window throughput: how fast the band accrues, measured on a window wide
    # enough not to be a handful of legs. Deliberately independent of APPROVAL_DATE.
    rate_since = int((time.time() - RATE_WINDOW_DAYS * 86_400) * 1000)
    rate_sql = """SELECT marketId AS market, openedAt FROM PaperTrade
                  WHERE isDemo=0 AND entryPrice > 0 AND openedAt >= ?"""
    rate_args = [rate_since]
    if only_bot:
        rate_sql += " AND botId = ?"
        rate_args.append(only_bot)
    trailing_band = 0
    for r in c.execute(rate_sql, rate_args).fetchall():
        ttl = ttr_at_entry(r["market"], r["openedAt"])
        if ttl is not None and BAND_LO_H <= ttl < BAND_HI_H:
            trailing_band += 1
    trailing_rate = trailing_band / float(RATE_WINDOW_DAYS)

    opened_band = 0
    for r in opened_rows:
        if not r["px"] or r["px"] <= 0:
            continue
        ttl = ttr_at_entry(r["market"], r["openedAt"])
        if ttl is not None and BAND_LO_H <= ttl < BAND_HI_H:
            opened_band += 1

    b = stats(dedup["band"])
    decision_population = only_bot if only_bot else "ALL"

    # --- the pre-registered decision -----------------------------------------
    days_elapsed = (int(time.time() * 1000) - since) / 86_400_000.0
    verdict, why = "ACCUMULATING", ""
    if b["legs"] >= MIN_LEGS:
        roi = b["roi"]
        r_roi = b["resolved_roi"]
        if roi is None:
            verdict, why = "INSUFFICIENT", "band has legs but no notional"
        elif roi >= REFUTE_ROI:
            verdict = "REFUTED"
            why = ("band net ROI %+.2f%% >= +3.0%% at n=%d -- this is profitable work the "
                   "floor would throw away, so do NOT flip" % (roi * 100, b["legs"]))
        elif r_roi is not None and roi > 0 and r_roi < 0:
            verdict = "INSUFFICIENT"
            why = ("headline %+.2f%% and resolved-only %+.2f%% disagree in SIGN -- an exit-rule "
                   "change can move the OR without the floor being involved; refuse to flip on "
                   "a split result" % (roi * 100, r_roi * 100))
        else:
            verdict = "FLIP"
            why = "band net ROI %+.2f%% < +3.0%% at n=%d" % (roi * 100, b["legs"])
    else:
        need = MIN_LEGS - b["legs"]
        rate = trailing_rate
        eta = (need / rate) if rate > 0 else None
        why = ("%d of %d settled band legs (from %d opened); %d to go"
               % (b["legs"], MIN_LEGS, opened_band, need))
        if eta is not None:
            why += (" (~%.0f days at the trailing-%dd rate of %.2f band openings/day; "
                    "settlement lag not included)" % (eta, RATE_WINDOW_DAYS, rate))
        if days_elapsed >= SHADOW_DAYS_SUPERSEDED:
            why += ("; the originally-drafted %d-day deadline has elapsed but is RETIRED -- n is "
                    "the only trigger" % SHADOW_DAYS_SUPERSEDED)

    flip_effect = (
        "INERT: %d of %d settled band legs would change admission under the live ruleset "
        "(%d already take the short-TTR lane path; %d are main-path legs whose only added skip "
        "is the floor's and are rescued back onto the same path). Measure with "
        "`npx tsx scripts/ttr-floor-reach-probe.ts` (0 of 22,464 grid cases move; controls armed)."
        % (len(reachable), b["legs"], len(lane_band), len(main_band))
    ) if not reachable else (
        "%d of %d settled band legs are NOT rescued by the lane window and would be BLOCKED"
        "%s."
        % (len(blocked), b["legs"],
           "; %d more have no drift join so their eligibility is unresolved" % len(unresolved)
           if unresolved else "")
    )

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "calibration-replay" if calibration else "forward",
        "approval_date": APPROVAL_DATE,
        "basis_corrected_at": BASIS_CORRECTED_AT,
        "basis_correction": (
            "measured STANDARD only through 2026-11-23; the gate is global. Decision "
            "population is now every lane, each reported as a sub-arm. See "
            "drafts/ttr-floor-all-lane-basis-20261123.md (approvals apr-profit-floor-ttr-all-lane-basis)."
        ),
        "decision_population": decision_population,
        "window": "n-driven (no calendar deadline)",
        "superseded_shadow_days": SHADOW_DAYS_SUPERSEDED,
        "days_elapsed": round(days_elapsed, 2),
        "bot": decision_population,
        "lanes_reported": lanes,
        "rule": {
            "proposed": "minTimeToResolutionHours 2 -> 24 -- GLOBAL, binds every lane",
            "live_floor_h": BAND_LO_H,
            "proposed_floor_h": BAND_HI_H,
            "at_risk_band_h": [BAND_LO_H, BAND_HI_H],
            "min_settled_legs": MIN_LEGS,
            "refute_if_band_roi_at_or_above": REFUTE_ROI,
            "decision": "n-driven: flip live unless the at-risk band returns >= +3.0% at n >= 150 settled legs",
            "decision_population": "COMBINED (all lanes) -- the population the gate binds",
            "calendar_deadline": "none -- the original 14-day clause was unmeetable at 4.29 band openings/day and is retired, not reinterpreted",
        },
        "population_basis": (
            "PaperTrade isDemo=0, every botId unless --only-bot, settled (closed|resolved, "
            "realizedPnl not null), openedAt >= approval, deduped to one leg per "
            "bot|wallet|market|outcome"
        ),
        "bands": bands_of(dedup),
        "by_lane": by_lane,
        "by_lane_undeduped": by_lane_raw,
        "band_admission_path": {
            "short_ttr_lane": stats(lane_band),
            "main_funnel": stats(main_band),
            "note": (
                "Admission path is read from DecisionJournal.reasonsJson ('Short-TTR lane: ...'), "
                "not inferred from price or size. Both paths are inside the lane window "
                "[%g, %g]h, so a floor raise is cleared by the rescue on either."
                % (lane_lo_h, lane_hi_h)
            ),
        },
        "reach": {
            "mechanism": (
                "short-TTR lane rescue (src/lib/scoring/trade.ts laneRescuesGateFailures) clears a "
                "'resolves in ... < min ...h' skip when ttr in [shortTtrMinHours, shortTtrMaxHours], "
                "adverse drift <= shortTtrMaxDrift and copyScore >= shortTtrMinCopyScore"
            ),
            "lane_window_h": [lane_lo_h, lane_hi_h],
            "lane_min_copy_score": SHORT_TTR_MIN_SCORE,
            "lane_max_drift": SHORT_TTR_MAX_DRIFT,
            "ruleset_version_read": rules_version,
            "reachable_band_legs": len(reachable),
            "band_legs": b["legs"],
            "unresolved_eligibility": len(unresolved),
            "probe": "npx tsx scripts/ttr-floor-reach-probe.ts",
            "probe_result": "0 of 22464 grid cases change under the live ruleset; controls A/B/C reach 75/15/1115",
            "note": (
                "reachable_band_legs counts settled band legs the rescue would NOT clear, i.e. the "
                "legs a 2->24h raise would actually block. A band-removal counterfactual over ALL "
                "band legs (scripts/profit-tenor.py §S15) is NOT this number -- it prices a block "
                "that cannot happen."
            ),
        },
        "raw_undeduped_band_legs": stats(raw["band"])["legs"],
        "bands_undeduped": bands_of(raw),
        "dedupe_note": (
            "bands/by_lane are the decision basis (one leg per bot|wallet|market|outcome, the "
            "basis of the S15 measurement and the 2026-11-21 profit review). bands_undeduped is "
            "the pre-2026-11-23 basis and the one the historical calibration reproduces; it is "
            "reported so a reader can see what the dedupe moves rather than having to trust it."
        ),
        "opened_legs_in_band": opened_band,
        "trailing_rate_window_days": RATE_WINDOW_DAYS,
        "trailing_openings_per_day": round(trailing_rate, 2),
        "projected_days_to_n": (round((MIN_LEGS - b["legs"]) / trailing_rate) if trailing_rate > 0 else None),
        "unclassified_ttr": dedup["unknown"],
        "verdict": verdict,
        "verdict_population": decision_population,
        "action": (
            "DO NOT APPLY: the raise is INERT under the live ruleset (0 of %d band legs change "
            "admission). A floor raise cannot block a band the short-TTR lane window [%g, %g]h "
            "already rescues; to block it, move shortTtrMaxHours below 24 (Lane A), or size the "
            "main-path band legs instead (Lane A)." % (b["legs"], lane_lo_h, lane_hi_h)
            if not reachable else
            "Lane A: the raise reaches %d band legs; the operator approves the RuleSet write."
            % len(blocked)
        ),
        "reason": why,
        "flip_effect": flip_effect,
        "not_yet_evaluable": [
            "refutation (b): flat 0.6-1.0 cells widening to >= +10% on 150 forward legs",
            "refutation (c): 3-7d ex-top-10 below 0% on a 60d read",
        ],
        "note": "Read-only shadow. Changing the floor is Lane A and still needs the user.",
    }

    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    # --- report ---------------------------------------------------------------
    # --quiet (the cron mode): stay SILENT while the verdict is still accumulating, and on
    # every run whose verdict repeats the previous one. An empty stdout sends no message, so
    # the watchdog speaks on a transition only. The JSON is written either way, so the
    # dashboard stays fresh.
    if quiet and (
        verdict == "ACCUMULATING"
        or (not calibration and verdict == prev_verdict and prev_basis == BASIS_CORRECTED_AT)
    ):
        return

    print("TTR floor shadow -- population %s, %.2f days since approval (%s)"
          % (decision_population, days_elapsed, APPROVAL_DATE))
    if calibration:
        print()
        print("  *** CALIBRATION REPLAY (--since %s, --band-lo %.2f): this is an IN-SAMPLE read,"
              % (APPROVAL_DATE, BAND_LO_H))
        print("  *** not the forward shadow. Written to %s;" % os.path.basename(out_path))
        print("  *** the live artifact %s was NOT touched." % os.path.basename(OUT))
    print()

    def line(label, s):
        print("  %-18s: %4d legs / %3d mkts  ntl $%9.2f  pnl $%9.2f  ROI %s"
              % (label, s["legs"], s["markets"], s["notional"], s["pnl"],
                 ("%+.2f%%" % (s["roi"] * 100)) if s["roi"] is not None else "n/a"))

    line("at risk [2,24)h", b)
    for bot in lanes:
        line("  " + bot, by_lane[bot]["at_risk_2_24h"])
    line("kept    [24,inf)", stats(dedup["over"]))
    u = stats(dedup["under"])
    if u["legs"]:
        print("  BELOW LIVE FLOOR : %4d legs  <-- should be impossible under a %gh floor; investigate"
              % (u["legs"], BAND_LO_H))
    print()
    print("  ---- what the raise would actually change (admission path) ----")
    line("lane copies", stats(lane_band))
    line("main-funnel", stats(main_band))
    print("  reachable (would be blocked by 2->24h): %d of %d band legs%s"
          % (len(reachable), b["legs"],
             "  [%d legs have no drift join, eligibility unresolved]" % len(unresolved) if unresolved else ""))
    print("  opened in band   : %4d legs (settled + still open) -> %.2f openings/day (trailing %dd)"
          % (opened_band, trailing_rate, RATE_WINDOW_DAYS))
    if dedup["unknown"]:
        print("  unclassified TTR : %4d legs (no snapshot at entry+15m)" % dedup["unknown"])
    print()
    print("  VERDICT: %s -- %s" % (verdict, why))
    print("  FLIP EFFECT: %s" % flip_effect)
    print("  ACTION: %s" % out["action"])
    print()
    print("  not yet evaluable: refutation (b) flat 0.6-1.0 cells >= +10%; (c) 3-7d ex-top-10 < 0%")
    print("  wrote %s" % out_path)


if __name__ == "__main__":
    main()
