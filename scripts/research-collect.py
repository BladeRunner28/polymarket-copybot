#!/usr/bin/env python3
"""
research-collect.py — deterministic fact sheet for the CopyBot research agent.

Prints ONE markdown fact sheet to stdout: our bot's measured state (read-only, from
prisma/dev.db), plus cheap keyless venue snapshots. The research agent adds judgment and
external research; it must never invent a number that belongs here.

Contract (deliberate, see ~/.hermes/skills/autonomous-ai-agents/cronjob-patterns on
"a keep-the-previous exit 0 makes a dead source invisible"):
    0  wrote the fact sheet (individual sources may still be marked FAILED inside it)
    1  hard failure (could not write anything)
Sources that fail are printed as `SOURCE FAILED` with the reason — never silently omitted.

Usage: python3 scripts/research-collect.py [--db prisma/dev.db] [--days 7]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Typed per-block input-health sidecar (2026-11-09, approved in thread; candidate
# xyonium/reach-mcp, whose only transferable asset was its status taxonomy). Sibling module, same
# directory, so it resolves the same way whether this file is run or loaded by a test.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import factsheet_status  # noqa: E402

REC = factsheet_status.Recorder()

CST = timezone(timedelta(hours=-5))
UA = {"User-Agent": "polyhydra-research/1.0"}
TIMEOUT = 20

# A day carrying >= 100 closures is a STOCK CLEAR, not a trading day: one forced-exit rail empties a
# backlog in one pass, so it dominates any window it lands in and can invert the per-leg read. The
# list is DERIVED from the book on every run (2026-11-04 self-audit), never a named date.
#
# It used to be the single hardcoded constant STOCK_CLEAR_DATE = "2026-10-24". Measured on the live
# book at the fix: only one day in the trailing 45 clears the bar (10-24: 708 closures; next is
# 10-25 with 74), so the hardcode was still ACCURATE — but by construction it could never notice a
# NEW clear, and once 10-24 rolled out of the 7d window the "EX-STOCK-CLEAR (2026-10-24 excluded)"
# line printed a date that was not in the window at all, with numbers identical to the blended line,
# and no way for a reader to tell "nothing to exclude" from "the exclusion is working".
#
# WHICH LANE that 10-24 clear belongs to: the 701 early exits are STANDARD (booked -$350.52, opened
# mostly 07-15/07-16); C-200 contributed 4 rows that day. Both comments here said "closed 701 C-200
# legs", which is the wrong lane — v66 added the STANDARD stale-exit rail, and that is what fired.
BULK_CLOSE_MIN_LEGS = 100


# ---------------------------------------------------------------- helpers
def now_cst() -> datetime:
    return datetime.now(CST)


def table_cols(cur: sqlite3.Cursor, table: str) -> set[str]:
    try:
        return {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def has(cur: sqlite3.Cursor, table: str) -> bool:
    return bool(cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _http_error_note(e: urllib.error.HTTPError) -> str:
    """`HTTP <code>` plus a short body hint when the source says WHY.

    A 403 is a different animal depending on its body: GitHub's keyless REST says "API rate limit
    exceeded" (a 60 req/h allowance, i.e. rate_limited) while a plan/permission refusal is
    gated_off. Dropping the body made those indistinguishable, so the sidecar classifier would
    file a rate limit as a gate.
    """
    hint = ""
    try:
        raw = e.read().decode("utf-8", "replace")
        m = re.search(r'"message"\s*:\s*"([^"]{1,120})"', raw) or re.search(r"\S.{0,120}", raw)
        if m:
            hint = " " + re.sub(r"\s+", " ", m.group(0))[:120]
    except Exception:  # noqa: BLE001 - a body we cannot read is not worth a second failure
        pass
    return f"HTTP {e.code}{hint}"


def fetch_json(url: str) -> tuple[Any | None, str]:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode()), "ok"
    except urllib.error.HTTPError as e:
        return None, _http_error_note(e)
    except Exception as e:  # noqa: BLE001 - any network/parse failure is a source failure
        return None, f"{type(e).__name__}: {e}"


def fetch_text(url: str) -> tuple[str | None, str]:
    """Fetch a non-JSON body (Reddit's Atom feeds). Same fail-loud contract as fetch_json.

    Records Reddit's own rate-limit reset (`x-ratelimit-reset`, seconds) in REDDIT_RESET_S so the
    caller waits the window the venue states instead of a guessed pause. Measured 2026-11-11: a
    burst leaves `x-ratelimit-remaining: 0.0` and a 48 s reset, so a 3 s spacing guarantees 429s.
    """
    global REDDIT_RESET_S
    try:
        req = urllib.request.Request(
            url, headers={**UA, "Accept": "application/atom+xml, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            _note_reset(r.headers)
            return r.read().decode("utf-8", "replace"), "ok"
    except urllib.error.HTTPError as e:
        _note_reset(e.headers)
        return None, _http_error_note(e)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


REDDIT_RESET_S = 0.0  # seconds Reddit said to wait; 0 = it told us nothing


def _note_reset(headers) -> None:
    """Keep the longest reset seen in this call — a 429 body can carry one too."""
    global REDDIT_RESET_S
    try:
        reset = float(headers.get("x-ratelimit-reset") or 0)
        remaining = float(headers.get("x-ratelimit-remaining") or 1)
    except (TypeError, ValueError):
        return
    if remaining <= 0 and reset > 0:
        REDDIT_RESET_S = max(REDDIT_RESET_S, reset)


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def bulk_close_days(cur, scol: str, status_ok: str, demo_ok: str, since_ms: int, bot: str | None = None):
    """Local days in the window carrying >= BULK_CLOSE_MIN_LEGS closures -> [(day, n, pnl)].

    Derived from the book on every run (2026-11-04 self-audit), per lane when `bot` is given: a
    stock clear is one lane's rail emptying a backlog, so a day that is a clear for STANDARD (708
    closures on 2026-10-24) is an ordinary day for C-200 (4 closures) and must not be excluded from
    C-200's window. Empty list means "nothing to exclude" and every caller must SAY so rather than
    print a number that happens to equal the blended one.
    """
    bot_ok = " AND botId=?" if bot else ""
    args = (bot, since_ms) if bot else (since_ms,)
    rows = cur.execute(
        f"SELECT date({scol}/1000,'unixepoch','-5 hours') d, COUNT(*), ROUND(SUM(realizedPnl),2) "
        f"FROM PaperTrade WHERE {status_ok} AND realizedPnl IS NOT NULL{demo_ok}{bot_ok} "
        f"AND {scol} >= ? GROUP BY d HAVING COUNT(*) >= ? ORDER BY d",
        (*args, BULK_CLOSE_MIN_LEGS)).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def per_leg(n: int | None, pnl: float | None) -> str:
    """Per-settlement PnL, the figure a window read has to compare across samples of
    different size (a 708-leg stock clear and a 154-leg week are not the same population).
    n=0 prints 'n/a' rather than a division by zero that would poison the fact sheet."""
    if not n:
        return "$n/a"
    return f"${(pnl or 0) / n:,.2f}"


# ---------------------------------------------------------------- our bot
def bot_facts(db: str, days: int) -> list[str]:
    out: list[str] = []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as e:
        # One failed open means every db block below was never measured: say so per block rather
        # than letting four silent no-rows read as four healthy reads.
        REC.mark("db.open", "void", str(e)[:200])
        for b in ("db.ruleset", "db.papertrade", "db.decision_journal", "db.daily_report"):
            REC.mark(b, "void", "not attempted: dev.db open failed")
        return [f"**SOURCE FAILED — dev.db**: {e}"]
    REC.mark("db.open", "ok")
    cur = con.cursor()
    now = now_cst()

    # active rule set
    if has(cur, "RuleSet"):
        cols = table_cols(cur, "RuleSet")
        vcol = "version" if "version" in cols else "id"
        try:
            row = cur.execute(
                f"SELECT {vcol}, rulesJson FROM RuleSet WHERE active=1 ORDER BY {vcol} DESC LIMIT 1"
            ).fetchone()
            if row:
                rules = json.loads(row[1] or "{}")
                keep = [k for k in sorted(rules) if any(s in k.lower() for s in (
                    "kelly", "max", "min", "cap", "thresh", "band", "gate", "fraction",
                    "longshot", "shortttr", "ttr", "size"))]
                knobs = ", ".join(f"{k}={rules[k]}" for k in keep[:14])
                out.append(f"- active RuleSet **v{row[0]}**: {knobs or '(no matching keys)'}")
                REC.mark("db.ruleset", "ok")
            else:
                out.append("- active RuleSet: **none active**")
                REC.mark("db.ruleset", "no_results", "no active RuleSet row")
        except Exception as e:  # noqa: BLE001
            out.append(f"- RuleSet read FAILED: {e}")
            REC.mark("db.ruleset", "void", f"{type(e).__name__}: {e}")
    else:
        out.append("- RuleSet read FAILED: table missing")
        REC.mark("db.ruleset", "void", "table RuleSet is missing")

    # trades: realized + open, per lane, over rolling windows
    if has(cur, "PaperTrade"):
        cols = table_cols(cur, "PaperTrade")
        tcol = "openedAt" if "openedAt" in cols else ("createdAt" if "createdAt" in cols else None)
        status_ok = "status IN ('closed','resolved')"
        try:
            tot = cur.execute(
                f"SELECT COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade "
                f"WHERE {status_ok} AND realizedPnl IS NOT NULL").fetchone()
            out.append(f"- settled trades (all time): {tot[0]}, realized **${tot[1] or 0:,.2f}**")
            # 2026-10-25 REC 1 (user-approved): these windows were anchored on the OPEN clock
            # with no isDemo filter, under a label that says "realized". A trade opened 6 days
            # ago and settled today is NOT in an opened-window read of the last 24h, and a trade
            # opened 40 days ago and closed today is in no window at all -- so the line measured
            # cohort OPENINGS while claiming settlement. Measured at the fix: the opened basis
            # read n=44 / -$110.93 for 7d where the settled basis read n=768 / +$174.81. The sign
            # differs, so this was not a rounding issue. Basis is now printed on every line.
            scol = None
            if "closedAt" in cols and "resolvedAt" in cols:
                scol = "COALESCE(closedAt, resolvedAt)"
            elif "closedAt" in cols:
                scol = "closedAt"
            elif "resolvedAt" in cols:
                scol = "resolvedAt"
            demo_ok = " AND isDemo=0" if "isDemo" in cols else ""
            if scol:
                out.append(f"  basis: SETTLED clock ({scol}), isDemo=0 -- realized in the window")
                for d in (1, 7, 30):
                    r = cur.execute(
                        f"SELECT COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade "
                        f"WHERE {status_ok} AND realizedPnl IS NOT NULL{demo_ok} AND {scol} >= ?",
                        (ms(now - timedelta(days=d)),)).fetchone()
                    out.append(f"  - last {d}d: n={r[0]}, realized ${r[1] or 0:,.2f}")
                    # Companion line on the same clock/basis, stock-clear days excluded --
                    # deliberately alongside the blended line, not replacing it: the blended
                    # figure is what actually settled, the ex-clear figure is what trading did.
                    if d in (7, 30):
                        since = ms(now - timedelta(days=d))
                        clears = bulk_close_days(cur, scol, status_ok, demo_ok, since)
                        if clears:
                            ph = ",".join("?" * len(clears))
                            ex = cur.execute(
                                f"SELECT COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade "
                                f"WHERE {status_ok} AND realizedPnl IS NOT NULL{demo_ok} "
                                f"AND {scol} >= ? "
                                f"AND date({scol}/1000,'unixepoch','-5 hours') NOT IN ({ph})",
                                (since, *[c[0] for c in clears])).fetchone()
                            excl = ", ".join(f"{day} n={n:,}" for day, n, _ in clears)
                            out.append(
                                f"    last {d}d EX-BULK-CLOSE ({excl} excluded): "
                                f"n={ex[0]}, realized ${ex[1] or 0:,.2f}, "
                                f"{per_leg(ex[0], ex[1])}/leg "
                                f"[blended {per_leg(r[0], r[1])}/leg]")
                        else:
                            out.append(
                                f"    last {d}d EX-BULK-CLOSE: none -- no day in this window has "
                                f">= {BULK_CLOSE_MIN_LEGS} closures, so it IS the blended figure")
                    # 2026-11-01: a per-leg mean summarises a window a handful of legs can set.
                    # Measured at the fix: the 7d window read +$265.45 net while its top-3 legs
                    # alone carried +$1,161.20, so the other 201 legs were -$895.75 -- the sign of
                    # the window and the sign of the flow DISAGREE. Same shape on 10-30 and 10-31
                    # (ex-top-3 -$956). Print the tail beside the mean so a "how is trading doing"
                    # answer cannot silently be a tail artifact. Reporting only, no decision path.
                    legs = cur.execute(
                        f"SELECT realizedPnl FROM PaperTrade WHERE {status_ok} "
                        f"AND realizedPnl IS NOT NULL{demo_ok} AND {scol} >= ? "
                        f"ORDER BY ABS(realizedPnl) DESC", (ms(now - timedelta(days=d)),)).fetchall()
                    vals = [v[0] or 0 for v in legs]
                    if vals:
                        top3 = sum(vals[:3])
                        abs_sum = sum(abs(v) for v in vals)
                        ex3 = sum(vals) - top3
                        share = (100.0 * abs(top3) / abs_sum) if abs_sum else 0.0
                        agree = "agrees" if (ex3 >= 0) == (sum(vals) >= 0) else "DISAGREES"
                        out.append(
                            f"    top-3 legs by |PnL|: ${top3:,.2f} of sum(|leg|) "
                            f"${abs_sum:,.2f} ({share:.0f}%), ex-top-3 net ${ex3:,.2f} "
                            f"-- sign {agree} with the window net")
                # A single day carrying >=100 closures is a STOCK CLEAR, not trading, and it
                # dominates any window it lands in. 2026-10-24: 708 closures / -$487.04 -- the 701
                # early exits are STANDARD (v66's new stale-exit rail, booked -$350.52, legs opened
                # mostly 07-15/07-16); C-200 contributed 4 resolutions. The settled clock lands 708
                # because it also picks up that date's 7 natural resolutions. When it sat inside the
                # 7d window the window read n=768 / +$174.81 WITH it and n=60 / +$661.85 WITHOUT --
                # quote the ex-bulk-close figure when the question is "how is trading doing".
                # Same derived read the exclusion uses, so the list a reader sees and the days the
                # arithmetic removes cannot drift apart.
                for d_, n_, pnl_ in bulk_close_days(
                        cur, scol, status_ok, demo_ok, ms(now - timedelta(days=30))):
                    out.append(
                        f"    [bulk-close day {d_}: n={n_}, ${pnl_ or 0:,.2f} -- stock clear, not "
                        f"flow; exclude it when reading a window as trading]")
            if tcol:
                out.append(
                    f"  basis: OPENED clock ({tcol}), LEGACY -- cohort openings, "
                    f"not a settlement read; kept so the change is diffable")
                for d in (1, 7, 30):
                    r = cur.execute(
                        f"SELECT COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade "
                        f"WHERE {status_ok} AND realizedPnl IS NOT NULL AND {tcol} >= ?",
                        (ms(now - timedelta(days=d)),)).fetchone()
                    out.append(f"  - last {d}d opened: n={r[0]}, realized ${r[1] or 0:,.2f}")
            scols = [c for c in ("simulatedPositionSize", "size", "stakeUsd") if c in cols]
            sizecol = scols[0] if scols else None
            # 2026-10-31: the open-position line was the ONE quoted figure with no isDemo
            # filter. At the fix, 487 open / $5,285.98 included 18 demo STANDARD legs /
            # $165.60, so the line overstated the real book against every other line here
            # (which are all isDemo=0). Demo rows never settle, so they inflate "at risk"
            # permanently and can never wash out of the read.
            op = cur.execute(
                f"SELECT COUNT(*), ROUND(SUM(COALESCE({sizecol},0)),2) FROM PaperTrade "
                f"WHERE status='open'{demo_ok}" if sizecol else
                "SELECT COUNT(*), 0 FROM PaperTrade WHERE status='open'").fetchone()
            out.append(f"- open positions (isDemo=0): {op[0]}, at risk ${op[1] or 0:,.2f}")
            # 2026-11-01 (fact-sheet-collector-truth item 3): every line above is a BLEND of two
            # books run by different rules, and the blend answers the wrong question for the
            # lane that carries the ladder. Measured at the fix (SETTLED clock, isDemo=0): the
            # 7d blended +$269.87 IS C-200 +$611.85 MINUS STANDARD $341.98, so the blended sign
            # is positive while one of its own lanes is negative; the 30d blend (+$2,590.27) is
            # 96% C-200; and the open line (450 legs / $4,981.64) is 97.5% STANDARD book while
            # the C-200 cap is the number the ladder reads. Print each lane BESIDE the blend --
            # never instead of it, because what settled really is the sum.
            if "botId" in cols and scol and sizecol:
                out.append(
                    "  per LANE (same settled clock, isDemo=0, booked realizedPnl; the lanes run"
                    " different rules, so a blended line answers neither):")
                lane_nets = {}
                for bot, in cur.execute(
                        "SELECT DISTINCT botId FROM PaperTrade WHERE botId IS NOT NULL "
                        "ORDER BY botId").fetchall():
                    ob = cur.execute(
                        f"SELECT COUNT(*), ROUND(SUM(COALESCE({sizecol},0)),2) FROM PaperTrade "
                        f"WHERE status='open'{demo_ok} AND botId=?", (bot,)).fetchone()
                    parts, nets = [], {}
                    for d in (1, 7, 30):
                        rb = cur.execute(
                            f"SELECT COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade "
                            f"WHERE {status_ok} AND realizedPnl IS NOT NULL{demo_ok} "
                            f"AND botId=? AND {scol} >= ?",
                            (bot, ms(now - timedelta(days=d)))).fetchone()
                        nets[d] = rb[1] or 0
                        seg = f"{d}d n={rb[0]} ${rb[1] or 0:,.2f}"
                        if d in (7, 30):
                            since = ms(now - timedelta(days=d))
                            # Per-lane: a clear is THIS lane's rail emptying a backlog, so a day
                            # that is a clear for STANDARD is an ordinary C-200 day.
                            lane_clears = bulk_close_days(cur, scol, status_ok, demo_ok, since, bot=bot)
                            if lane_clears:
                                ph = ",".join("?" * len(lane_clears))
                                exb = cur.execute(
                                    f"SELECT COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade "
                                    f"WHERE {status_ok} AND realizedPnl IS NOT NULL{demo_ok} "
                                    f"AND botId=? AND {scol} >= ? "
                                    f"AND date({scol}/1000,'unixepoch','-5 hours') NOT IN ({ph})",
                                    (bot, since, *[c[0] for c in lane_clears])).fetchone()
                                seg += f", ex-bulk-close n={exb[0]} ${exb[1] or 0:,.2f}"
                            else:
                                seg += ", ex-bulk-close: no clear day in window"
                        parts.append(seg)
                    lane_nets[bot] = nets
                    out.append(
                        f"  - {bot}: open {ob[0]} legs / ${ob[1] or 0:,.2f} at risk | settled "
                        + " | ".join(parts))
                for d in (7, 30):
                    bl = cur.execute(
                        f"SELECT ROUND(SUM(realizedPnl),2) FROM PaperTrade "
                        f"WHERE {status_ok} AND realizedPnl IS NOT NULL{demo_ok} "
                        f"AND {scol} >= ?", (ms(now - timedelta(days=d)),)).fetchone()
                    bnet = bl[0] or 0
                    opposing = [b for b, n in lane_nets.items() if n[d] * bnet < 0 and n[d] != 0]
                    if opposing:
                        out.append(
                            f"    ! LANE SIGN DISAGREES at {d}d: blended ${bnet:,.2f} vs "
                            + ", ".join(f"{b} ${lane_nets[b][d]:,.2f}" for b in sorted(lane_nets))
                            + " -- do not read the blend as the flow")
                # Each lane spends a DIFFERENT rail, so open-legs counts are not comparable
                # between them: C-200 has an equity-linked notional ceiling, STANDARD has a leg
                # count and no notional ceiling at all. Quote each against its own rail.
                try:
                    rules_row = cur.execute(
                        "SELECT version, rulesJson FROM RuleSet WHERE active=1").fetchone()
                    rules = json.loads(rules_row[1] or "{}") if rules_row else {}
                    base = float(rules.get("maxGrossExposureUsd") or 0)
                    bals = {}
                    if has(cur, "BotBankroll"):
                        for b, pr, rp in cur.execute(
                                "SELECT botId, principal, realizedPnl FROM BotBankroll").fetchall():
                            bals[b] = (float(pr or 0), float(rp or 0))
                    pr, rp = bals.get("BANKROLL_200", (0.0, 0.0))
                    c200_open = cur.execute(
                        f"SELECT ROUND(SUM(COALESCE({sizecol},0)),2) FROM PaperTrade "
                        f"WHERE status='open'{demo_ok} AND botId='BANKROLL_200'").fetchone()[0] or 0
                    if base > 0 and pr > 0:
                        nw = pr + rp
                        cap = base + 0.5 * max(0.0, nw - pr)
                        out.append(
                            f"  - rail C-200: gross-exposure cap on the REALIZED basis = "
                            f"${base:,.0f} base + 50% x (net worth ${nw:,.2f} - principal "
                            f"${pr:,.2f}) = ${cap:,.2f}; open ${c200_open:,.2f} = "
                            f"{100.0 * c200_open / cap:.1f}%. The ENFORCED ceiling also adds "
                            f"open MTM (score-trades.ts recomputes it each cycle), so this "
                            f"figure omits that term.")
                    else:
                        out.append(
                            "  - rail C-200: NOT COMPUTED -- base cap or principal unreadable "
                            f"(base ${base:,.0f}, principal ${pr:,.2f}); no figure is printed "
                            "rather than a guessed one")
                    legs_rail = float(rules.get("standardMaxOpenPositions") or 0)
                    st_open = cur.execute(
                        f"SELECT COUNT(*) FROM PaperTrade WHERE status='open'{demo_ok} "
                        f"AND botId='STANDARD'").fetchone()[0]
                    if legs_rail > 0:
                        out.append(
                            f"  - rail STANDARD: standardMaxOpenPositions={legs_rail:,.0f} legs "
                            f"(v{rules_row[0]}); open {st_open} = "
                            f"{100.0 * st_open / legs_rail:.1f}%. STANDARD has no notional cap, "
                            f"so its at-risk dollars have no ceiling to divide by.")
                except Exception as e:  # noqa: BLE001
                    out.append(f"  - rail read FAILED: {e}")
            if "botId" in cols:
                for bot, in cur.execute("SELECT DISTINCT botId FROM PaperTrade WHERE botId IS NOT NULL").fetchall():
                    # 2026-11-03 (card winrate-payoff-companion-reporting): this line printed a
                    # LIFETIME win rate with no clock and NO payoff companions -- "win=0.47" sitting
                    # under a block of rolling windows, with nothing to say which population it was,
                    # and nothing to separate a payoff shift from a collapse. Same rows, same level
                    # (the leg), same clock (settled) now carry average win, average loss and ROI,
                    # and the population is named on the line. Arithmetic matches
                    # src/lib/payoff.ts, which the EOD report and the dashboard use.
                    stake_col = "simulatedPositionSize" if "simulatedPositionSize" in cols else None
                    stake_sel = f"SUM({stake_col})" if stake_col else "NULL"
                    r = cur.execute(
                        f"SELECT COUNT(*), ROUND(SUM(realizedPnl),2), "
                        f"ROUND(1.0*SUM(CASE WHEN realizedPnl>0 THEN 1 ELSE 0 END)/COUNT(*),3), "
                        f"SUM(CASE WHEN realizedPnl>0 THEN 1 ELSE 0 END), "
                        f"ROUND(SUM(CASE WHEN realizedPnl>0 THEN realizedPnl ELSE 0 END),2), "
                        f"ROUND(SUM(CASE WHEN realizedPnl<=0 THEN realizedPnl ELSE 0 END),2), "
                        f"{stake_sel}, MIN({scol}) "
                        f"FROM PaperTrade WHERE {status_ok} AND realizedPnl IS NOT NULL{demo_ok} AND botId=?",
                        (bot,)).fetchone()
                    n, realized, wr, wins, win_sum, loss_sum, cost, first = r
                    wins = wins or 0
                    win_sum, loss_sum = win_sum or 0.0, loss_sum or 0.0
                    losses = (n or 0) - wins
                    avg_win = win_sum / wins if wins else 0.0
                    avg_loss = loss_sum / losses if losses else 0.0
                    roi = (100.0 * (realized or 0) / cost) if cost else None
                    since = (datetime.fromtimestamp(first / 1000, timezone.utc).date().isoformat()
                             if first else "n/a")
                    roi_txt = (f"ROI {roi:+.1f}% on ${cost:,.0f} cost" if roi is not None
                               else "ROI n/a (no stake recorded)")
                    # The companions are built as ONE fragment so they live on the same printed
                    # line as the rate (scripts/winrate-companion-census.py enforces that).
                    companion = (
                        f"avg win {'+' if avg_win >= 0 else '-'}${abs(avg_win):,.2f} / "
                        f"avg loss {'+' if avg_loss >= 0 else '-'}${abs(avg_loss):,.2f} / {roi_txt} "
                        f"-- win rate alone cannot separate payoff from decay")
                    out.append(
                        f"  - {bot}: n={n} (LIFETIME settled, isDemo=0, level=leg, since {since}) "
                        f"realized ${realized or 0:,.2f} | win {100.0 * (wr or 0):.1f}% | {companion}")
            REC.mark("db.papertrade", "ok", n=int(tot[0] or 0))
        except Exception as e:  # noqa: BLE001
            out.append(f"- PaperTrade read FAILED: {e}")
            REC.mark("db.papertrade", "void", f"{type(e).__name__}: {e}")
    else:
        out.append("- PaperTrade read FAILED: table missing")
        REC.mark("db.papertrade", "void", "table PaperTrade is missing")

    # decision funnel (what the scorer actually decided)
    if has(cur, "DecisionJournal"):
        cols = table_cols(cur, "DecisionJournal")
        wcol = "createdAt" if "createdAt" in cols else ("ts" if "ts" in cols else None)
        if wcol:
            try:
                since = ms(now - timedelta(hours=24))
                dcol = "decision" if "decision" in cols else None
                if dcol:
                    rows = cur.execute(
                        f"SELECT {dcol}, COUNT(*) FROM DecisionJournal WHERE {wcol} >= ? "
                        f"GROUP BY {dcol} ORDER BY 2 DESC LIMIT 8", (since,)).fetchall()
                    out.append("- decisions last 24h: " + ", ".join(
                        f"{r or '?'}={c}" for r, c in rows))
                if "reasonsJson" in cols or "risksJson" in cols:
                    # 2026-10-17 fix: the true skip reasons live in risksJson; reasonsJson is the
                    # BOOST field and is '[]' on the overwhelming majority of skips, so the old
                    # "first entry of reasonsJson" line reported a boost tag as a skip mix (void).
                    # Now: count EVERY entry of risksJson, fall back to reasonsJson when empty.
                    from collections import Counter
                    sel = [c for c in ("risksJson", "reasonsJson") if c in cols]
                    # 2026-10-25 REC 1: two defects in one query. (1) No ORDER BY, so
                    # LIMIT 400 took an ARBITRARY slice of the window -- not reproducible
                    # between runs. (2) It counted every risksJson ENTRY, and one decision can
                    # carry several, so the sums could be entry-level while the row count was
                    # decision-level. HONEST NOTE: the entry-vs-decision inflation did NOT
                    # reproduce on 2026-10-25 -- the top five tags came out identical at both
                    # levels (139/92/92/92/81), i.e. no decision in the slice carried a tag
                    # twice. What IS real is that this is a 400-row slice of 1,817 skips with
                    # per-VALUE tags ("confidence 0.45 ..." vs "confidence 0.52 ..."), so its
                    # counts are slice-local and must never be read as a gate census. Both
                    # levels are printed and labelled so neither can be mistaken for one.
                    blob = cur.execute(
                        f"SELECT {', '.join(sel)} FROM DecisionJournal WHERE {wcol} >= ? "
                        f"AND decision='skip' ORDER BY {wcol} DESC LIMIT 400", (since,)).fetchall()
                    cnt: Counter = Counter()
                    dec_cnt: Counter = Counter()
                    bare = 0
                    # 2026-11-02 (Lane B): both levels were printed under a caption that ASSERTED a
                    # relationship instead of measuring it. Measured on this slice: 916 tag entries
                    # over 400 skips, 353/400 carry more than one entry -> the ENTRY-level totals do
                    # exceed the row count, but no tag ever repeats INSIDE one decision, so the
                    # DECISION-level (dedupe-within-row) view agrees tag-for-tag and the two lines
                    # read as one population printed twice. Both facts now print from the data; the
                    # ONLY thing that can make the lists differ is a within-row duplicate, and that
                    # count prints too. Full-window independent read: scripts/skip-reason-level-read.py.
                    n_entries = 0
                    n_dups = 0
                    for row in blob:
                        items = []
                        for raw in row:  # risksJson is first when present
                            try:
                                j = json.loads(raw or "[]")
                            except Exception:  # noqa: BLE001
                                continue
                            cand = j if isinstance(j, list) else (
                                list(j.values()) if isinstance(j, dict) else [])
                            if cand:
                                items = cand
                                break
                        if not items:
                            bare += 1
                            continue
                        seen_here = set()
                        n_entries += len(items)
                        for tag in items:
                            key = str(tag)[:70]
                            cnt[key] += 1
                            if key not in seen_here:
                                dec_cnt[key] += 1
                                seen_here.add(key)
                        n_dups += len(items) - len(seen_here)
                    tagged = len(blob) - bare
                    out.append(
                        f"- skip reasons DECISION-level (one count per skipped decision PER TAG, so "
                        f"these counts sum to {sum(dec_cnt.values())} entries, NOT to the "
                        f"{len(blob)} rows; {len(blob)} rows newest-first, {bare} empty, "
                        f"{n_dups} within-row duplicate entries): "
                        + (", ".join(f"{k} x{v}" for k, v in dec_cnt.most_common(5)) or "(none parsed)"))
                    out.append(
                        f"- skip reasons ENTRY-level (every risksJson entry: {n_entries} entries over "
                        f"{tagged} tagged rows, "
                        f"{'above' if n_entries > tagged else 'not above'} the row count; the two "
                        f"lines differ ONLY where a decision repeats a tag, measured {n_dups} times): "
                        + (", ".join(f"{k} x{v}" for k, v in cnt.most_common(5)) or "(none parsed)"))
                    out.append(
                        "- skip reasons by GATE FAMILY (the readable rollup; per-tag keys are "
                        "per-VALUE, so the lists above mix strength buckets with gates): "
                        "python3 scripts/skip-reason-level-read.py")
                    # `outcome` lives on ObservedTrade, NOT on DecisionJournal — querying it bare
                    # raised `no such column: outcome` on every run and the except below swallowed
                    # it into a report line, so this counter read "FAILED" for three days (tuning
                    # review 2026-10-20). Keying on observedTradeId instead would run but silently
                    # count distinct *trades* under a label that says market/outcome, so join for
                    # the real pair. MarketId is identical on both rows, so only the outcome needs
                    # the join.
                    if "risksJson" in cols and "observedTradeId" in cols:
                        dedup = cur.execute(
                            "SELECT COUNT(DISTINCT dj.marketId || '|' || ot.outcome) "
                            "FROM DecisionJournal dj "
                            "JOIN ObservedTrade ot ON ot.id = dj.observedTradeId "
                            f"WHERE dj.{wcol} >= ? AND dj.decision='skip'", (since,)).fetchone()
                        out.append(f"- distinct skipped market/outcome last 24h: {dedup[0] if dedup else '?'}")
            except Exception as e:  # noqa: BLE001
                out.append(f"- DecisionJournal read FAILED: {e}")
                REC.mark("db.decision_journal", "void", f"{type(e).__name__}: {e}")
            else:
                REC.mark("db.decision_journal", "ok")
        else:
            out.append("- DecisionJournal read FAILED: no time column")
            REC.mark("db.decision_journal", "void", "no createdAt/ts column")
    else:
        out.append("- DecisionJournal read FAILED: table missing")
        REC.mark("db.decision_journal", "void", "table DecisionJournal is missing")

    # daily report history
    if has(cur, "DailyReport"):
        cols = table_cols(cur, "DailyReport")
        try:
            cols_sel = [c for c in ("date", "paperPnl", "compoundingPnl", "totalCapital") if c in cols]
            rows = cur.execute(
                f"SELECT {', '.join(cols_sel)} FROM DailyReport ORDER BY date DESC LIMIT 5").fetchall()

            def _labelled(r: tuple) -> str:
                """Label every value: paperPnl is the STANDARD lane, compoundingPnl is C-200.

                Printed bare (2026-10-21 27.44 -12.06) the two PnL columns are
                indistinguishable, and a reader cannot tell which lane moved or which
                number is which -- a silent ambiguity in a fact sheet the agent is told
                to trust. src/lib/report.ts:411-414 writes stdPnlToday -> paperPnl and
                cmpPnlToday -> compoundingPnl, so the labels are the lane names.
                """
                labels = {"date": "", "paperPnl": "STANDARD", "compoundingPnl": "C-200",
                          "totalCapital": "capital"}
                return " ".join(
                    str(v) if name == "date" else f"{labels.get(name, name)} {v}"
                    for name, v in zip(cols_sel, r))

            out.append("- last daily reports (lane-labelled, date STANDARD$ C-200$): " + "; ".join(
                _labelled(r) for r in rows))
            REC.mark("db.daily_report", "ok" if rows else "no_results",
                     "" if rows else "no DailyReport rows")
        except Exception as e:  # noqa: BLE001
            out.append(f"- DailyReport read FAILED: {e}")
            REC.mark("db.daily_report", "void", f"{type(e).__name__}: {e}")
    else:
        out.append("- DailyReport read FAILED: table missing")
        REC.mark("db.daily_report", "void", "table DailyReport is missing")

    con.close()
    return out


# ---------------------------------------------------------------- venue snapshots
def polymarket_snapshot(skipped: bool = False) -> list[str]:
    out: list[str] = []
    if skipped:
        REC.mark("polymarket.gamma", "gated_off", "skipped by --skip-venues")
        return ["- (skipped by flag)"]
    data, err = fetch_json(
        "https://gamma-api.polymarket.com/markets?closed=false&limit=60"
        "&order=volume24hr&ascending=false")
    if data is None:
        REC.mark("polymarket.gamma", factsheet_status.classify_fetch_note(err), err)
        return [f"- **SOURCE FAILED — Polymarket gamma**: {err}"]
    if not isinstance(data, (list, dict)):
        REC.mark("polymarket.gamma", "void", f"unexpected JSON shape: {type(data).__name__}")
        return [f"- **SOURCE FAILED — Polymarket gamma**: unexpected JSON shape "
                f"({type(data).__name__}, not a list or object)"]
    markets = data if isinstance(data, list) else data.get("data", [])
    open_n = len(markets)
    if not markets:
        REC.mark("polymarket.gamma", "no_results", "the top-60 page returned 0 markets")
        return ["- Polymarket: 0 markets in the top-60 page — the venue was asked and answered "
                "EMPTY (not a failure, but no venue read is available from it)"]
    REC.mark("polymarket.gamma", "ok", n=open_n)

    vol = 0.0
    for m in markets:
        try:
            vol += float(m.get("volume24hr") or 0)
        except (TypeError, ValueError):
            pass
    out.append(f"- Polymarket: {open_n} markets in the top-60 page, "
               f"summed 24h volume **${vol:,.0f}** (sampled, not the whole venue)")
    top = sorted(markets, key=lambda m: float(m.get("volume24hr") or 0), reverse=True)[:8]
    for m in top:
        q = (m.get("question") or "")[:78]
        v = float(m.get("volume24hr") or 0)
        lp = m.get("liquidityNum") or m.get("liquidity")
        end = (m.get("endDate") or "")[:10]
        out.append(f"  - ${v:,.0f} 24h | liq {lp} | ends {end} | {q}")
    return out


KALSHI_CLOSE_WINDOW_S = 2 * 86400


def kalshi_snapshot(skipped: bool = False) -> list[str]:
    """The closing-soon board, NOT the newest listings.

    `?limit=200&status=open` with no close filter returns the newest 200 LISTINGS — parlay
    legs and freshly-created templates — where every volume field reads 0. That is a silent
    zero that reads like a quiet venue: measured 2026-10-22, 200/200 rows at 0, while the
    same endpoint under a 2-day close window returned $267,000 of summed volume on 18/200
    nonzero rows. So this block asks the close window and prints how many rows are nonzero,
    which makes a genuine zero visible as `0/200` instead of an unexplained `0`.
    """
    if skipped:
        REC.mark("kalshi.markets", "gated_off", "skipped by --skip-venues")
        return ["- (skipped by flag)"]
    now = int(time.time())
    data, err = fetch_json(
        "https://api.elections.kalshi.com/trade-api/v2/markets?limit=200&status=open"
        f"&min_close_ts={now}&max_close_ts={now + KALSHI_CLOSE_WINDOW_S}")
    if data is None:
        REC.mark("kalshi.markets", factsheet_status.classify_fetch_note(err), err)
        return [f"- **SOURCE FAILED — Kalshi**: {err}"]
    if not isinstance(data, (list, dict)):
        REC.mark("kalshi.markets", "void", f"unexpected JSON shape: {type(data).__name__}")
        return [f"- **SOURCE FAILED — Kalshi**: unexpected JSON shape "
                f"({type(data).__name__}, not a list or object)"]
    # `data.get(...)` in the default slot would be EVALUATED FIRST, so a list body raised
    # AttributeError before the ternary could pick it (a crash on the very shape it meant to
    # accept). Branch on the type, then read.
    mk = data if isinstance(data, list) else (data.get("markets") or [])
    if not mk:
        # 0 rows in a 48h close window is a measurement of a quiet venue -- but only because the
        # request succeeded. Say which of the two zeroes this is.
        REC.mark("kalshi.markets", "no_results", "0 markets closing within 48h")
        return ["- Kalshi: 0 open markets closing within 48h — the close window was asked and "
                "answered EMPTY (not a failed request)"]
    REC.mark("kalshi.markets", "ok", n=len(mk))

    def vol_of(m: dict) -> float:
        """Kalshi's plain `volume` is deprecated in favour of fixed-point *_fp strings."""
        for k in ("volume_24h_fp", "volume_24h", "volume_fp", "volume",
                  "open_interest_fp", "open_interest"):
            if m.get(k) not in (None, ""):
                try:
                    return float(m[k])
                except (TypeError, ValueError):
                    continue
        return 0.0

    vol = sum(vol_of(m) for m in mk)
    nonzero = sum(1 for m in mk if vol_of(m) > 0)
    out = [f"- Kalshi: {len(mk)} open markets closing within 48h, summed 24h volume/OI "
           f"{vol:,.0f} on {nonzero}/{len(mk)} nonzero rows (close-window, not newest-listing)"]
    top = sorted(mk, key=vol_of, reverse=True)[:6]
    for m in top:
        t = (m.get("title") or m.get("ticker") or "")[:76]
        out.append(f"  - {vol_of(m):,.0f} | {(m.get('close_time') or '')[:10]} | {t}")
    return out


# ---------------------------------------------------------------- code & community recon
# GitHub is the deterministic half of "find us reusable assets": search results (name, stars, push
# date, licence, archived flag) are FACTS, so the agent never has to recall a repo. Uses `gh api`
# when the CLI is authenticated (5000 req/h) and falls back to keyless REST (60 req/h).
GH_QUERIES = [
    ("newest Polymarket tooling", 'polymarket in:name,description', "updated"),
    ("newest Kalshi tooling", 'kalshi in:name,description', "updated"),
    ("strategies / bots / arb", '"prediction market" (arbitrage OR bot OR strategy) in:name,description', "updated"),
    ("MCP servers — Polymarket", 'polymarket mcp in:name,description', "updated"),
    ("MCP servers — Kalshi", 'kalshi mcp in:name,description', "updated"),
    ("datasets / historical", '"prediction market" (dataset OR broker OR api) in:name,description', "stars"),
    ("established topic index", "topic:prediction-markets", "stars"),
]

# Reddit's .json endpoints 403 from this host; the Atom feeds (top/.rss, search.rss) are served.
REDDIT_FIXED = [
    ("r/Polymarket top/day", "https://www.reddit.com/r/Polymarket/top/.rss?t=day"),
    ("r/predictionmarkets top/week", "https://www.reddit.com/r/predictionmarkets/top/.rss?t=week"),
]
REDDIT_ROTATION = [
    ("r/Kalshi top/week", "https://www.reddit.com/r/Kalshi/top/.rss?t=week"),
    ("search: polymarket api", "https://www.reddit.com/search.rss?q=polymarket%20api&sort=new&t=month"),
    ("r/algotrading top/week", "https://www.reddit.com/r/algotrading/top/.rss?t=week"),
    ("search: kalshi bot", "https://www.reddit.com/search.rss?q=kalshi%20bot&sort=new&t=month"),
]
REDDIT_PAUSE_S = 25.0    # between feeds: the 429s here are self-inflicted, not a block.
                         # 3.0 s was measured too tight on 2026-11-11 (a 2nd request 8 s after a
                         # 200 still returned 429), which left 2 of 3 feeds on 45-72 h old caches.
REDDIT_RETRY_S = 75.0    # one backoff retry before declaring a feed failed (was 30 s: not enough)
REDDIT_TTL_H = 26.0      # fetch each feed at most once per day, regardless of run cadence
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "research-recon"
YIELD_LOG = Path(__file__).resolve().parent.parent / "data" / "radar-yield.jsonl"
REPO_DIR = Path(__file__).resolve().parent.parent
ENTRY_FLOOR_SERIES = REPO_DIR / "data" / "entry-floor-read.jsonl"

# The one definition of "usable" (REC 1's decision rule depends on it being stable, so it is defined
# here and never re-defined in the analysis script).
USABLE_MIN_STARS = 5
USABLE_MAX_AGE_D = 90
GH_STATS: list[dict] = []
REDDIT_STATS: list[dict] = []


def usable(r: dict) -> bool:
    lic = (r.get("license") or {}).get("spdx_id") or "no-licence"
    if lic == "no-licence" or r.get("archived"):
        return False
    if (r.get("stargazers_count") or 0) < USABLE_MIN_STARS:
        return False
    try:
        pushed = datetime.strptime((r.get("pushed_at") or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return (datetime.now(timezone.utc).date() - pushed).days <= USABLE_MAX_AGE_D


def reddit_feeds() -> list[tuple[str, str]]:
    """3 requests per run — Reddit 429'd the 4th in a burst on two consecutive runs.

    The third slot rotates by weekday, so all six sources are still covered across the week
    without ever exceeding the observed burst limit.
    """
    wd = datetime.now().weekday()
    return REDDIT_FIXED + [REDDIT_ROTATION[wd % len(REDDIT_ROTATION)]]


def reddit_feeds_stalest_first() -> list[tuple[str, str]]:
    """The run's feeds, oldest cache first (never-fetched ahead of everything).

    Why order matters: Reddit's burst limit lands on request #2, and a fixed order puts the same
    feed in that slot every run. On 2026-11-11 the two fixed feeds were fetched 3 s apart, #2
    429'd, and the tail slot went three days without a refresh. Sorting by cache age makes slot
    #1 rotate by staleness, so a feed cannot be starved by its position in the list.
    """
    def age(item: tuple[str, str]) -> float:
        f = CACHE_DIR / f"{factsheet_status.slug(item[0])}.xml"
        return (time.time() - f.stat().st_mtime) if f.exists() else float("inf")

    return sorted(reddit_feeds(), key=age, reverse=True)


RELEVANT = re.compile(
    r"api|bot|arb|strategy|fee|rebate|sdk|mcp|dataset|data set|code|github|tool|agent|scrap|"
    r"market.?mak|liquidit|latenc|backtest|kelly|calibrat|copy.?trad", re.I)


def gh_api(path: str) -> tuple[Any | None, str]:
    """Prefer the authenticated CLI; fall back to keyless REST. Returns (json, note)."""
    try:
        p = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30)
        if p.returncode == 0 and p.stdout.strip():
            return json.loads(p.stdout), "gh (authenticated)"
    except Exception:  # noqa: BLE001 - fall through to keyless
        pass
    body, err = fetch_json("https://api.github.com/" + path)
    return body, err if body is None else "keyless REST"


def github_recon(skipped: bool = False) -> list[str]:
    out: list[str] = []
    for label, q, sort in GH_QUERIES:
        block = "github." + factsheet_status.slug(label)
        if skipped:
            REC.mark(block, "gated_off", "skipped by --skip-recon")
            continue
        qs = urllib.parse.quote(q, safe="")
        data, note = gh_api(f"search/repositories?q={qs}&sort={sort}&order=desc&per_page=5")
        if not isinstance(data, dict) or "items" not in data:
            # Per QUERY, not per block: one rate-limited query used to hide behind six healthy
            # ones. The state names which failure it was; the note carries the reason.
            state = factsheet_status.classify_fetch_note(note)
            REC.mark(block, state, note)
            out.append(f"- **SOURCE FAILED — GitHub '{label}'**: {note}")
            GH_STATS.append({"query": label, "sort": sort, "total_count": None, "slots": 0,
                             "usable": 0, "no_licence": 0, "zero_star": 0, "failed": note})
            continue
        items = (data.get("items") or [])[:5]
        REC.mark(block, "ok" if items else "no_results",
                 "" if items else "the search matched 0 repositories", n=len(items))
        GH_STATS.append({
            "query": label, "sort": sort, "total_count": data.get("total_count"),
            "slots": len(items), "usable": sum(1 for r in items if usable(r)),
            "no_licence": sum(1 for r in items
                              if ((r.get("license") or {}).get("spdx_id") or "no-licence") == "no-licence"),
            "zero_star": sum(1 for r in items if not (r.get("stargazers_count") or 0)),
            "repos": [r.get("full_name") for r in items],
        })
        out.append(f"**{label}** ({sort}) via {note} — {data.get('total_count', '?')} matches, top {len(items)}:")
        for r in items:
            lic = (r.get("license") or {}).get("spdx_id") or "no-licence"
            flag = " · ARCHIVED" if r.get("archived") else ""
            out.append(f"  - `{r['full_name']}` ★{r.get('stargazers_count', 0)} · pushed "
                       f"{(r.get('pushed_at') or '')[:10]} · {lic}{flag} · "
                       f"{(r.get('description') or '')[:88]} · {r.get('html_url')}")
    if skipped:
        return ["- (skipped by flag)"]
    return out


def cached_text(slug: str, url: str, ttl_h: float) -> tuple[str | None, str]:
    """Fetch with an on-disk TTL cache. A stale cache beats an error: label it so nothing hides."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{slug}.xml"
    age = (time.time() - f.stat().st_mtime) / 3600 if f.exists() else None
    if age is not None and age < ttl_h:
        return f.read_text(encoding="utf-8", errors="replace"), f"cache ({age:.1f}h old)"
    body, err = fetch_text(url)
    if body is None:
        if f.exists():
            return f.read_text(encoding="utf-8", errors="replace"), f"STALE cache ({age:.1f}h old) after {err}"
        return None, err
    f.write_text(body, encoding="utf-8")
    return body, "fresh"


def _reddit_wait() -> None:
    """Wait Reddit's own stated reset (plus 2 s) when it gave one, else the floor pause.

    `x-ratelimit-remaining: 0.0` with `x-ratelimit-reset: 48` is what a burst looks like; sleeping
    a fixed 3 s into that window is a guaranteed 429, which is how two feeds sat 45-72 h stale.
    """
    global REDDIT_RESET_S
    wait = max(REDDIT_PAUSE_S, REDDIT_RESET_S + 2.0) if REDDIT_RESET_S else REDDIT_PAUSE_S
    REDDIT_RESET_S = 0.0
    time.sleep(wait)


def reddit_recon(skipped: bool = False) -> list[str]:
    out: list[str] = []
    # Consecutive 429s with no cached copy: two in a row means the host is throttled.
    hard_429s = 0
    for i, (label, url) in enumerate(reddit_feeds_stalest_first()):
        block = "reddit." + factsheet_status.slug(label)
        if skipped:
            REC.mark(block, "gated_off", "skipped by --skip-recon")
            continue
        if hard_429s >= 2:
            REC.mark(block, "rate_limited", "not attempted: backing off after two consecutive 429s")
            out.append(f"- (not attempted — {label}: backing off after two consecutive 429s rather than making it worse)")
            continue
        if i:
            _reddit_wait()
        slug = factsheet_status.slug(label)
        body, err = cached_text(slug, url, REDDIT_TTL_H)
        if body is None and "429" in err:
            time.sleep(max(REDDIT_RETRY_S, REDDIT_RESET_S + 2))
            body, err = cached_text(slug, url, REDDIT_TTL_H)
            if body is not None:
                err = f"recovered after {REDDIT_RETRY_S:.0f}s backoff"
        if body is None:
            state = factsheet_status.classify_fetch_note(err)
            REC.mark(block, state, err)
            out.append(f"- **SOURCE FAILED — {label}**: {err}"
                       + ("  ← rate-limited with no cached copy" if "429" in err else ""))
            REDDIT_STATS.append({"label": label, "state": "429" if "429" in err else "error",
                                 "note": err, "entries": 0, "relevant": 0})
            if "429" in err:
                hard_429s += 1
            else:
                hard_429s = 0
            continue
        hard_429s = 0
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            REC.mark(block, "void", f"XML parse error: {e}")
            out.append(f"- **SOURCE FAILED — {label}**: XML parse error: {e}")
            REDDIT_STATS.append({"label": label, "state": "error", "note": f"XML parse error: {e}",
                                 "entries": 0, "relevant": 0})
            continue
        ns = {"a": "http://www.w3.org/2005/Atom"}
        hits = []
        for e in root.findall("a:entry", ns):
            title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
            link = ""
            le = e.find("a:link", ns)
            if le is not None:
                link = le.get("href", "")
            when = (e.findtext("a:updated", default="", namespaces=ns) or "")[:10]
            hits.append((title, when, link))
        rel = [h for h in hits if RELEVANT.search(h[0])] or hits[:3]
        state = ("recovered" if err.startswith("recovered") else
                 "cache" if err.startswith("cache") else
                 "stale" if err.startswith("STALE") else "fresh")
        REDDIT_STATS.append({"label": label, "state": state, "note": err,
                             "entries": len(hits), "relevant": len(rel)})
        # A STALE cache is the one case where rows EXIST but the input failed: state names the
        # failure, `n` records that the numbers came from it. That is the void/rate_limited-with-
        # rows shape the gate looks for -- a stale copy must never read as a fresh feed.
        if factsheet_status.is_stale_cache(err):
            REC.mark(block, factsheet_status.classify_fetch_note(err), err, n=len(hits))
        elif not hits:
            REC.mark(block, "no_results", err, n=0)
        else:
            REC.mark(block, "ok", err, n=len(hits))
        out.append(f"**{label}** [{err}] — {len(rel)} relevant of {len(hits)} entries:")
        for title, when, link in rel[:4]:
            out.append(f"  - {when} · {title[:96]} · {link.split('?')[0][:96]}")
    if skipped:
        return ["- (skipped by flag)"]
    return out


# ---------------------------------------------------------------- main
def prereg_reads(skipped: bool = False) -> list[str]:
    """Status of the pre-registered reads whose gate dates are already in the past.

    WHY THIS EXISTS (2026-10-26, self-audit Lane B). `scripts/entry-floor-replay.py` was
    pre-registered 2026-10-17 with a hard gate date (2026-10-24) and its draft promised that
    "2026-10-24 is answered by a series, not an impression". No job ran it: the series held
    exactly ONE line, written on registration day with state PENDING_DATE, and the gate date
    passed two days earlier with nothing reading it. An unread gate is indistinguishable from
    a pending one, so the read is now taken here — the daily research run is the job that
    approved it (REC 1) and its fact sheet is where the gate has to be visible.
    """
    out: list[str] = []
    if skipped:
        REC.mark("prereg.entry_floor", "gated_off", "skipped by --skip-prereg")
        return ["- (skipped by flag)"]
    try:
        p = subprocess.run(
            [sys.executable, str(REPO_DIR / "scripts" / "entry-floor-replay.py"),
             "--if-stale-hours", "12"],
            cwd=str(REPO_DIR), capture_output=True, text=True, timeout=180,
        )
        note = (p.stdout or p.stderr or "").strip().splitlines()
        if p.returncode != 0:
            REC.mark("prereg.entry_floor", "void",
                     f"exit {p.returncode} {(note[-1] if note else 'no output')[:160]}")
            return [f"- **SOURCE FAILED — entry-floor prereg read**: exit {p.returncode} "
                    f"{(note[-1] if note else 'no output')[:200]}"]
    except (OSError, subprocess.SubprocessError) as e:
        REC.mark("prereg.entry_floor", "void", f"{type(e).__name__}: {e}")
        return [f"- **SOURCE FAILED — entry-floor prereg read**: {type(e).__name__}: {e}"]

    # Always report the state from the SERIES (not from this run's stdout), so a skipped
    # append still shows the gate. State, gate date, n-vs-needed and the age of the read are
    # all that is printed: the numbers belong to the instrument, not to a summary of it.
    try:
        last = None
        if ENTRY_FLOOR_SERIES.exists():
            for line in ENTRY_FLOOR_SERIES.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip():
                    last = line
        rec = json.loads(last) if last else None
    except (OSError, json.JSONDecodeError) as e:
        REC.mark("prereg.entry_floor", "void", f"{type(e).__name__}: {e}")
        return [f"- **SOURCE FAILED — entry-floor prereg series**: {type(e).__name__}: {e}"]
    if rec is None:
        REC.mark("prereg.entry_floor", "no_results", "series is empty: the read has never run")
        return ["- entry-floor prereg: series is EMPTY — the read has never run (no gate can be read)"]

    v = rec.get("verdict", {})
    ran = str(rec.get("ranAt") or "")
    age_d = ""
    try:
        at = datetime.fromisoformat(ran.replace("Z", "+00:00"))
        age_d = f", read {(datetime.now(timezone.utc) - at).total_seconds() / 86400:.1f}d ago"
    except ValueError:
        pass
    gate = str(rec.get("gateDate") or "?")
    gate_days = rec.get("daysSinceGate")
    gate_txt = f"gate {gate}" + (f" = {gate_days}d ago" if isinstance(gate_days, int) else "")
    ga, gb = v.get("gateA_n", {}), v.get("gateB_net", {})
    out.append(
        f"- **Entry-floor prereg** ({gate_txt}{age_d}): **{v.get('state', '?')}** — "
        f"gate A n={ga.get('value')}/{ga.get('need')} "
        f"ROI={v.get('gateA_roi', {}).get('value')} (need {v.get('gateA_roi', {}).get('need')}) · "
        f"gate B net=${gb.get('value')} across {v.get('gateB_resolved', {}).get('value')} resolved "
        f"(need >= $25 / 30). Series: `data/entry-floor-read.jsonl`."
    )
    out.append(
        "- A `PENDING_DATE` line older than the gate date is NOT a pending gate — it is an "
        "unread one. Quote the newest state with its `gateDate` and `ranAt`, never the state alone."
    )
    REC.mark("prereg.entry_floor", "ok")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="prisma/dev.db")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--skip-venues", action="store_true")
    ap.add_argument("--skip-recon", action="store_true",
                    help="skip the GitHub/Reddit reconnaissance blocks")
    ap.add_argument("--skip-prereg", action="store_true",
                    help="skip the pre-registered-read status block (does not take the read)")
    a = ap.parse_args()

    # Every block this run must emit a typed row for. `--skip-*` blocks are recorded as
    # gated_off (blocked on US, not broken), so a flag cannot masquerade as a healthy run.
    REC.expect(factsheet_status.expected_blocks(
        [q[0] for q in GH_QUERIES], [f[0] for f in reddit_feeds()]))

    lines: list[str] = []
    lines.append(f"# CopyBot fact sheet — {now_cst():%Y-%m-%d %H:%M} CDT")
    lines.append("")
    lines.append(f"Generated by `scripts/research-collect.py` at "
                 f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} (freshness stamp — if this is "
                 f"stale, the collector is broken, not the market).")
    lines.append("")
    lines.append("## Our measured state")
    lines += bot_facts(a.db, a.days)
    lines.append("")
    lines.append("## Pre-registered reads (gate status)")
    lines += prereg_reads(skipped=a.skip_prereg)
    lines.append("")
    lines.append("## Venue snapshots (keyless, best-effort)")
    lines += polymarket_snapshot(skipped=a.skip_venues)
    lines += kalshi_snapshot(skipped=a.skip_venues)
    lines.append("")
    lines.append("## Reusable assets radar — GitHub (search results are facts; `gh` authenticated)")
    lines += github_recon(skipped=a.skip_recon)
    lines.append("")
    lines.append("## Practitioner signal — Reddit (Atom feeds; .json endpoints 403 from this host)")
    lines += reddit_recon(skipped=a.skip_recon)
    # Log this run's yield (one JSON line per run) — the pre-registered read in REC 1 is a lookup
    # over this file, not a re-parse of prose after the fact.
    try:
        with YIELD_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z"),
                "usable_rule": f"licence!=none AND stars>={USABLE_MIN_STARS} AND pushed<= {USABLE_MAX_AGE_D}d",
                "github": GH_STATS, "reddit": REDDIT_STATS,
            }) + "\n")
    except OSError as e:
        lines.append(f"- **SOURCE FAILED — radar yield log not written**: {e}")

    # Append this run's typed rows, ONE PER BLOCK, then show the audit count in the sheet itself.
    # Order matters: the write happens before the sheet is persisted so a refused/failed write is
    # printed inside the sheet that the agent is told to trust.
    try:
        factsheet_status.write_rows(REC.rows())
    except (OSError, factsheet_status.StatusSchemaError) as e:
        lines.append(f"- **SOURCE FAILED — input-health sidecar not written**: "
                     f"{type(e).__name__}: {e}")
    health = REC.sheet_block(factsheet_status.display_path())
    at = lines.index("## Our measured state")
    lines[at:at] = health + [""]

    # Persist the sheet: the audit worker's seeder parses the radar block straight out of this file,
    # and it doubles as the audit trail of what the agent was actually shown on a given run.
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / "factsheet-latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as e:
        lines.append(f"- **SOURCE FAILED — fact sheet not persisted**: {e}")

    lines.append("")
    lines.append("## Reminders for the agent")
    lines.append("- Nothing above is a recommendation; it is the baseline the research must beat.")
    lines.append("- `SOURCE FAILED` lines are part of the report — say so, never paper over them.")
    lines.append("- `## Input health` is the typed per-block record: `no_results` means the source "
                 "answered EMPTY, `void`/`rate_limited`/`gated_off` mean it did NOT answer. A "
                 "zero under a block that is not `ok` is not a measurement.")
    lines.append("- Our own numbers come from here; external claims need a cited URL.")
    lines.append("- A repo in the radar is a CANDIDATE, not an endorsement: read its licence, last push, "
                 "issues and tests before proposing to adopt anything (load `github-repo-audit`).")
    lines.append("- Reddit entries are SIGNAL DETECTION only (a fee change, a new API, a widely-reported "
                 "bug); never source a strategy claim from a thread — find the primary source.")

    text = "\n".join(lines)
    sys.stdout.write(text + "\n")
    return 0 if text else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"research-collect hard failure: {type(e).__name__}: {e}\n")
        raise SystemExit(1)
