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

CST = timezone(timedelta(hours=-5))
UA = {"User-Agent": "polyhydra-research/1.0"}
TIMEOUT = 20


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


def fetch_json(url: str) -> tuple[Any | None, str]:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode()), "ok"
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 - any network/parse failure is a source failure
        return None, f"{type(e).__name__}: {e}"


def fetch_text(url: str) -> tuple[str | None, str]:
    """Fetch a non-JSON body (Reddit's Atom feeds). Same fail-loud contract as fetch_json."""
    try:
        req = urllib.request.Request(
            url, headers={**UA, "Accept": "application/atom+xml, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", "replace"), "ok"
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------- our bot
def bot_facts(db: str, days: int) -> list[str]:
    out: list[str] = []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return [f"**SOURCE FAILED — dev.db**: {e}"]
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
            else:
                out.append("- active RuleSet: **none active**")
        except Exception as e:  # noqa: BLE001
            out.append(f"- RuleSet read FAILED: {e}")

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
            if tcol:
                for d in (1, 7, 30):
                    r = cur.execute(
                        f"SELECT COUNT(*), ROUND(SUM(realizedPnl),2) FROM PaperTrade "
                        f"WHERE {status_ok} AND realizedPnl IS NOT NULL AND {tcol} >= ?",
                        (ms(now - timedelta(days=d)),)).fetchone()
                    out.append(f"  - last {d}d: n={r[0]}, realized ${r[1] or 0:,.2f}")
            scols = [c for c in ("simulatedPositionSize", "size", "stakeUsd") if c in cols]
            sizecol = scols[0] if scols else None
            op = cur.execute(
                f"SELECT COUNT(*), ROUND(SUM(COALESCE({sizecol},0)),2) FROM PaperTrade "
                f"WHERE status='open'" if sizecol else
                "SELECT COUNT(*), 0 FROM PaperTrade WHERE status='open'").fetchone()
            out.append(f"- open positions: {op[0]}, at risk ${op[1] or 0:,.2f}")
            if "botId" in cols:
                for bot, in cur.execute("SELECT DISTINCT botId FROM PaperTrade WHERE botId IS NOT NULL").fetchall():
                    r = cur.execute(
                        f"SELECT COUNT(*), ROUND(SUM(realizedPnl),2), "
                        f"ROUND(1.0*SUM(CASE WHEN realizedPnl>0 THEN 1 ELSE 0 END)/COUNT(*),3) "
                        f"FROM PaperTrade WHERE {status_ok} AND realizedPnl IS NOT NULL AND botId=?",
                        (bot,)).fetchone()
                    out.append(f"  - {bot}: n={r[0]} realized ${r[1] or 0:,.2f} win={r[2]}")
        except Exception as e:  # noqa: BLE001
            out.append(f"- PaperTrade read FAILED: {e}")

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
                    blob = cur.execute(
                        f"SELECT {', '.join(sel)} FROM DecisionJournal WHERE {wcol} >= ? "
                        f"AND decision='skip' LIMIT 400", (since,)).fetchall()
                    cnt: Counter = Counter()
                    bare = 0
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
                        for tag in items:
                            cnt[str(tag)[:70]] += 1
                    out.append(
                        f"- skip reasons (every entry of risksJson, reasonsJson fallback; "
                        f"{len(blob)} rows, {bare} empty): "
                        + (", ".join(f"{k} x{v}" for k, v in cnt.most_common(5)) or "(none parsed)"))
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

    # daily report history
    if has(cur, "DailyReport"):
        cols = table_cols(cur, "DailyReport")
        try:
            cols_sel = [c for c in ("date", "paperPnl", "compoundingPnl", "totalCapital") if c in cols]
            rows = cur.execute(
                f"SELECT {', '.join(cols_sel)} FROM DailyReport ORDER BY date DESC LIMIT 5").fetchall()
            out.append("- last daily reports: " + "; ".join(
                " ".join(str(x) for x in r) for r in rows))
        except Exception as e:  # noqa: BLE001
            out.append(f"- DailyReport read FAILED: {e}")

    con.close()
    return out


# ---------------------------------------------------------------- venue snapshots
def polymarket_snapshot() -> list[str]:
    out: list[str] = []
    data, err = fetch_json(
        "https://gamma-api.polymarket.com/markets?closed=false&limit=60"
        "&order=volume24hr&ascending=false")
    if data is None:
        return [f"- **SOURCE FAILED — Polymarket gamma**: {err}"]
    markets = data if isinstance(data, list) else data.get("data", [])
    open_n = len(markets)
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


def kalshi_snapshot() -> list[str]:
    data, err = fetch_json(
        "https://api.elections.kalshi.com/trade-api/v2/markets?limit=200&status=open")
    if data is None:
        return [f"- **SOURCE FAILED — Kalshi**: {err}"]
    mk = data.get("markets", data if isinstance(data, list) else [])

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
    out = [f"- Kalshi: {len(mk)} open markets on the first page, summed volume/OI {vol:,.0f} "
           f"(fixed-point fields)"]
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
REDDIT_PAUSE_S = 3.0     # between feeds: the 429s here are self-inflicted, not a block
REDDIT_RETRY_S = 30.0    # one backoff retry before declaring a feed failed
REDDIT_TTL_H = 26.0      # fetch each feed at most once per day, regardless of run cadence
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "research-recon"
YIELD_LOG = Path(__file__).resolve().parent.parent / "data" / "radar-yield.jsonl"

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


def github_recon() -> list[str]:
    out: list[str] = []
    for label, q, sort in GH_QUERIES:
        qs = urllib.parse.quote(q, safe="")
        data, note = gh_api(f"search/repositories?q={qs}&sort={sort}&order=desc&per_page=5")
        if data is None or "items" not in data:
            out.append(f"- **SOURCE FAILED — GitHub '{label}'**: {note}")
            GH_STATS.append({"query": label, "sort": sort, "total_count": None, "slots": 0,
                             "usable": 0, "no_licence": 0, "zero_star": 0, "failed": note})
            continue
        items = data.get("items", [])[:5]
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


def reddit_recon() -> list[str]:
    out: list[str] = []
    rate_limited = False
    for i, (label, url) in enumerate(reddit_feeds()):
        if rate_limited:
            out.append(f"- (not attempted — {label}: backing off after a 429 rather than making it worse)")
            continue
        if i:
            time.sleep(REDDIT_PAUSE_S)
        slug = re.sub(r"\W+", "-", label.lower()).strip("-")
        body, err = cached_text(slug, url, REDDIT_TTL_H)
        if body is None and "429" in err:
            time.sleep(REDDIT_RETRY_S)
            body, err = cached_text(slug, url, REDDIT_TTL_H)
            if body is not None:
                err = f"recovered after {REDDIT_RETRY_S:.0f}s backoff"
        if body is None:
            out.append(f"- **SOURCE FAILED — {label}**: {err}"
                       + ("  ← rate-limited; leaving the remaining feeds to the next run"
                          if "429" in err else ""))
            REDDIT_STATS.append({"label": label, "state": "429" if "429" in err else "error",
                                 "note": err, "entries": 0, "relevant": 0})
            if "429" in err:
                rate_limited = True
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            out.append(f"- **SOURCE FAILED — {label}**: XML parse error: {e}")
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
        out.append(f"**{label}** [{err}] — {len(rel)} relevant of {len(hits)} entries:")
        for title, when, link in rel[:4]:
            out.append(f"  - {when} · {title[:96]} · {link.split('?')[0][:96]}")
    return out


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="prisma/dev.db")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--skip-venues", action="store_true")
    ap.add_argument("--skip-recon", action="store_true",
                    help="skip the GitHub/Reddit reconnaissance blocks")
    a = ap.parse_args()

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
    lines.append("## Venue snapshots (keyless, best-effort)")
    if a.skip_venues:
        lines.append("- (skipped by flag)")
    else:
        lines += polymarket_snapshot()
        lines += kalshi_snapshot()
    lines.append("")
    lines.append("## Reusable assets radar — GitHub (search results are facts; `gh` authenticated)")
    lines += (["- (skipped by flag)"] if a.skip_recon else github_recon())
    lines.append("")
    lines.append("## Practitioner signal — Reddit (Atom feeds; .json endpoints 403 from this host)")
    lines += (["- (skipped by flag)"] if a.skip_recon else reddit_recon())
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
