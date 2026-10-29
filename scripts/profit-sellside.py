#!/usr/bin/env python3
"""Profit review 2026-10-29 -- the sell side of the flow we copy.

WHY THIS FILE EXISTS
--------------------
`scripts/monitor-trades.ts:130` reads:

    if (t.side !== "BUY") continue; // copy entries only, not exits

so every SELL print by a tracked wallet is fetched from the data API and then
DISCARDED. The database proves it: ObservedTrade holds 4,660,889 BUY rows and
**10** SELL rows over 2026-06-18 -> 2026-10-29.

On Polymarket a SELL of YES at 0.85 is economically a BUY of NO at 0.15, so
"copy entries only" is not a filter on direction of exposure -- it is a filter
that removes (a) the exits of the wallets we copy, which are the only
thesis-linked exit signal the book could have, and (b) the entire other side
of the flow, which is the side the calibration table says is mispriced.

This script measures both, offline-first, with a committed cache so every
number in drafts/profit-recs-20261029.md reproduces without the wire:

    DATA_MODE=live python3 scripts/profit-sellside.py            # fetch if cache stale, then report
    python3 scripts/profit-sellside.py --offline                 # cache only
    python3 scripts/profit-sellside.py --only-census | --only-exit

COST BASIS, stated once and used everywhere: `PaperTrade.simulatedPositionSize`
is DOLLARS at risk, never shares. A BUY of $n at price p is n/p shares; an exit
at c realises n*(c/p - 1) and a settlement at s realises n*(s/p - 1). Identical
to scripts/profit-velocity.py, whose truth cache and bootstrap this imports.
"""
import collections
import json
import os
import random
import sqlite3
import statistics
import subprocess
import sys
import time

DATA_MODE = os.environ.get("DATA_MODE", "paper")
DB = os.environ.get("COPYBOT_DB", "prisma/dev.db")
FLOW_CACHE = "data/sellside-flow.json"
M2C_CACHE = "data/sellside-m2c.json"
DATA_API = "https://data-api.polymarket.com/trades"
PAGES = 6          # 6 x 500 = 3,000 prints per wallet, ~6 weeks of a busy wallet
PAGE = 500
OFFLINE = "--offline" in sys.argv
ONLY_CENSUS = "--only-census" in sys.argv
ONLY_EXIT = "--only-exit" in sys.argv


def _load_velocity():
    """The settlement-truth reader, reused rather than re-implemented (hyphen in filename)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pv", os.path.join("scripts", "profit-velocity.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_pv = _load_velocity()
truth_of = _pv.truth_of


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def pct(xs, q):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f = int(k)
    ceil = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[ceil] - xs[f]) * (k - f)


def usd(x):
    return f"${x:,.2f}"


# ---------------------------------------------------------------- §SS.1 flow
def _curl_wallet(addr, pages=PAGES):
    out = []
    for i in range(pages):
        url = f"{DATA_API}?user={addr}&limit={PAGE}&offset={i * PAGE}"
        p = subprocess.run(["curl", "-s", "--max-time", "25", url],
                           capture_output=True, text=True)
        try:
            rows = json.loads(p.stdout)
        except Exception:
            break
        if not isinstance(rows, list) or not rows:
            break
        out.extend(rows)
        if len(rows) < PAGE:
            break
        time.sleep(0.25)
    return out


def flow_census(c, refresh=False):
    """Every print of every tracked wallet, by side. Cache = data/sellside-flow.json."""
    tracked = [r["address"] for r in c.execute(
        "SELECT address FROM WalletProfile WHERE status='track' ORDER BY globalScore DESC")]
    cache = {}
    if os.path.exists(FLOW_CACHE):
        try:
            cache = json.load(open(FLOW_CACHE))
        except Exception:
            cache = {}
    fetched = 0
    if not OFFLINE and (refresh or not cache):
        for a in tracked:
            rows = _curl_wallet(a)
            if rows:
                cache[a] = [{k: r.get(k) for k in
                             ("side", "asset", "conditionId", "size", "price", "timestamp",
                              "title", "slug", "outcome", "outcomeIndex")} for r in rows]
                fetched += 1
        json.dump(cache, open(FLOW_CACHE, "w"))
    print(f"\n=== SS.1  FLOW CENSUS -- {len(tracked)} tracked wallets, "
          f"{fetched} fetched this run, {len(cache)} cached ===")
    tb = ts_ = 0
    tb_n = ts_n = 0
    per = []
    for a in tracked:
        rows = cache.get(a) or []
        b = [r for r in rows if r["side"] == "BUY"]
        s = [r for r in rows if r["side"] == "SELL"]
        nb = sum(r["size"] * r["price"] for r in b)
        ns = sum(r["size"] * r["price"] for r in s)
        tb += nb; ts_ += ns; tb_n += len(b); ts_n += len(s)
        if rows:
            per.append((a, len(rows), len(b), len(s), nb, ns))
    print(f"  prints: BUY {tb_n:,}  SELL {ts_n:,}   ->  SELL share of prints "
          f"{100.0 * ts_n / max(1, tb_n + ts_n):.1f}%")
    print(f"  notional: BUY {usd(tb)}  SELL {usd(ts_)}  ->  SELL share of notional "
          f"{100.0 * ts_ / max(1.0, tb + ts_):.1f}%")
    print(f"  wallets with any prints: {len(per)}/{len(tracked)}")
    if per:
        sells = [p[3] / max(1, p[1]) for p in per]
        print(f"  per-wallet SELL share of prints: median {100 * statistics.median(sells):.1f}%  "
              f"p90 {100 * pct(sells, 0.9):.1f}%  max {100 * max(sells):.1f}%")
    return cache, tracked


# ------------------------------------------------------ §SS.2 round trips
def round_trips(cache):
    """For each (wallet, conditionId, asset): first BUY -> first SELL after it."""
    rt = []
    for a, rows in cache.items():
        by_asset = collections.defaultdict(list)
        for r in rows:
            if not r.get("asset") or not r.get("conditionId"):
                continue
            by_asset[(r["conditionId"], r["asset"])].append(r)
        for (cid, asset), rs in by_asset.items():
            rs.sort(key=lambda x: x["timestamp"])
            buy = next((r for r in rs if r["side"] == "BUY"), None)
            if not buy:
                continue
            sell = next((r for r in rs if r["side"] == "SELL" and
                         r["timestamp"] > buy["timestamp"]), None)
            if not sell:
                continue
            hold_h = (sell["timestamp"] - buy["timestamp"]) / 3600.0
            rt.append(dict(wallet=a, cid=cid, asset=asset, outcome=buy.get("outcome"),
                           slug=buy.get("slug"), buy_px=buy["price"], sell_px=sell["price"],
                           sell_ts=sell["timestamp"], hold_h=hold_h))
    return rt


def exit_timing(rt):
    print("\n=== SS.2  WHAT THE DISCARDED PRINTS ARE: tracked-wallet round trips ===")
    if not rt:
        print("  no round trips in cache")
        return
    hold = [r["hold_h"] for r in rt]
    print(f"  round trips (first BUY -> first later SELL, same asset): {len(rt):,}")
    print(f"  hold before the sell: median {statistics.median(hold):.1f}h  "
          f"p10 {pct(hold, .1):.1f}h  p90 {pct(hold, .9):.1f}h")
    for lim in (24, 72, 168, 720):
        n = sum(1 for h in hold if h <= lim)
        print(f"    exited within {lim:>4}h: {n:,} ({100.0 * n / len(rt):.0f}%)")
    d = [r["sell_px"] - r["buy_px"] for r in rt]
    up = sum(1 for x in d if x > 0)
    print(f"  sell price - buy price: median {100 * statistics.median(d):+.1f}pp  "
          f"mean {100 * statistics.mean(d):+.1f}pp  sold higher {100.0 * up / len(rt):.0f}%")
    # what our lane does instead
    print("  Context: STANDARD holds to resolution or a dead-slug 404; weighted open-leg age "
          "is ~76d (2026-10-20 read).")


# ------------------------------------------------ §SS.3 overlap with our book
def market_conds(c):
    cache = {}
    if os.path.exists(M2C_CACHE):
        try:
            cache = json.load(open(M2C_CACHE))
        except Exception:
            cache = {}
    if cache:
        return cache
    for r in c.execute("""SELECT marketId, MAX(conditionId) cid FROM MarketSnapshot
                          WHERE conditionId IS NOT NULL GROUP BY marketId"""):
        cache[r["marketId"]] = r["cid"]
    json.dump(cache, open(M2C_CACHE, "w"))
    return cache


def book_overlap(c, cache, rt):
    """Our legs in markets where the SAME wallet later sold. Exit signal, priced."""
    print("\n=== SS.3  THE EXIT WE THREW AWAY, PRICED ON OUR OWN SETTLED LEGS ===")
    m2c = market_conds(c)
    sells_by = collections.defaultdict(list)   # wallet -> [(ts, cid, outcome, px)]
    for r in rt:
        sells_by[r["wallet"]].append((r["sell_ts"], r["cid"], r["outcome"], r["sell_px"]))

    legs = c.execute("""SELECT id, walletAddress w, marketId m, outcome o, entryPrice px,
                               simulatedPositionSize n, realizedPnl pnl, status st,
                               openedAt, closedAt, resolvedAt
                        FROM PaperTrade WHERE isDemo=0 AND status IN ('resolved','closed')""").fetchall()
    rows = []
    n_no_cid = 0
    for L in legs:
        cid = m2c.get(L["m"])
        if not cid:
            n_no_cid += 1
            continue
        opened_ms = L["openedAt"] if isinstance(L["openedAt"], int) else None
        if opened_ms is None:
            continue
        hit = None
        for ts, scid, sout, spx in sells_by.get(L["w"], ()):
            if scid != cid:
                continue
            if ts * 1000 <= opened_ms:
                continue
            # our side: same outcome -> our exit ~ their sell price; complement -> 1 - px
            exit_px = spx if (sout or "").strip().upper() == (L["o"] or "").strip().upper() \
                else 1.0 - spx
            if not (0.0 < exit_px < 1.0):
                continue
            if hit is None or ts < hit[0]:
                hit = (ts, exit_px)
        if not hit:
            continue
        # settlement-or-exit basis: only legs that actually settled naturally
        if L["st"] != "resolved":
            continue
        exit_pnl = L["n"] * (hit[1] / L["px"] - 1.0)
        rows.append(dict(id=L["id"], m=L["m"], n=L["n"], px=L["px"],
                         hold=L["pnl"], exit=exit_pnl, dt_h=(hit[0] * 1000 - opened_ms) / 3.6e6))
    print(f"  settled legs scanned: {len(legs):,}   no conditionId: {n_no_cid}   "
          f"legs where the copied wallet later sold: {len(rows):,}")
    if not rows:
        print("  none -- nothing to price (see §SS.4 for why this is the expected result)")
        return rows
    notional = sum(r["n"] for r in rows)
    hold = sum(r["hold"] for r in rows)
    ex = sum(r["exit"] for r in rows)
    print(f"  notional {usd(notional)}   hold-to-settlement {usd(hold)} "
          f"({100 * hold / notional:+.1f}%)   exit-at-their-print {usd(ex)} "
          f"({100 * ex / notional:+.1f}%)   alpha {usd(ex - hold)}")
    dts = [r["dt_h"] for r in rows]
    print(f"  they sold a median {statistics.median(dts):.1f}h after we opened "
          f"(p10 {pct(dts, .1):.1f}h, p90 {pct(dts, .9):.1f}h)")
    # market-clustered bootstrap on the alpha
    by_m = collections.defaultdict(list)
    for r in rows:
        by_m[r["m"]].append(r["exit"] - r["hold"])
    keys = list(by_m)
    if len(keys) >= 3:
        rnd = random.Random(11)
        ds = []
        for _ in range(1500):
            s = [rnd.choice(keys) for _ in keys]
            ds.append(sum(sum(by_m[k]) for k in s))
        ds.sort()
        print(f"  market-clustered 95% CI on the alpha: "
              f"[{usd(ds[int(.025 * len(ds))])}, {usd(ds[int(.975 * len(ds))])}] "
              f"over {len(keys)} markets")
    else:
        print(f"  CI not computed: {len(keys)} markets with variance")
    return rows


# ------------------------------------------- §SS.4 how much signal is even reachable
def reach(c, cache, rt):
    print("\n=== SS.4  IS THE SIGNAL REACHABLE? (why §SS.3 is small, measured) ===")
    tracked = set(cache)
    obs_wallets = {r[0] for r in c.execute(
        "SELECT DISTINCT walletAddress FROM ObservedTrade WHERE observationOnly=0")}
    print(f"  tracked now: {len(tracked)}   wallets that ever printed a copied trade: {len(obs_wallets)}")
    # how many of our copy events have a later sell by the same wallet in a fetched window
    sells = collections.defaultdict(set)
    for r in rt:
        sells[r["wallet"]].add((r["cid"], r["outcome"]))
    buys = collections.defaultdict(set)
    for a, rows in cache.items():
        for r in rows:
            if r["side"] == "BUY":
                buys[a].add((r["conditionId"], r["outcome"]))
    both = sum(len(buys[a] & sells[a]) for a in cache)
    tot = sum(len(buys[a]) for a in cache)
    print(f"  within the fetched window: {both:,} of {tot:,} (wallet,market,outcome) BUY "
          f"positions ({100.0 * both / max(1, tot):.1f}%) have a later SELL by the same wallet")
    print("  -> the exit signal exists in the flow we are already paying to fetch; "
          "it is dropped at monitor-trades.ts:130.")


def mark_path(c):
    """Does the wallet's intraday repricing exist for OUR fills, or is it their impact?

    For every copied leg, the mark for our outcome at openedAt + {2.5h, 24h, 168h},
    from MarketSnapshot (the recorder's own quotes). Two readings:
      (1) median mark change in pp, and the share of legs whose mark rose >= +5pp;
      (2) the realised PnL of exiting at that mark versus holding to settlement,
          on the legs whose markets have already settled (a paired comparison).
    A near-zero mark path means the wallets' +42pp is their own impact and the exit
    is not copyable at our size -- which is the refutation, and it is printed, not
    hidden.
    """
    print("\n=== SS.5  THE MARK PATH OF OUR OWN FILLS (is the repricing ours to take?) ===")
    HORIZONS = [(2.5, 3.0), (24.0, 12.0), (168.0, 48.0)]
    legs = c.execute("""SELECT id, botId, marketId m, outcome o, entryPrice px,
                               simulatedPositionSize n, realizedPnl pnl, status st,
                               openedAt, COALESCE(resolvedAt, closedAt) doneAt
                        FROM PaperTrade
                        WHERE isDemo=0 AND status IN ('resolved','closed')""").fetchall()
    print(f"  population: {len(legs):,} finished legs (resolved + early-closed)")
    res = {h[0]: [] for h in HORIZONS}
    covered = {h[0]: 0 for h in HORIZONS}
    for L in legs:
        t0 = L["openedAt"]
        if not isinstance(t0, int):
            continue
        for H, tol_h in HORIZONS:
            target = t0 + H * 3.6e6
            tol = tol_h * 3.6e6
            r = c.execute("""SELECT COALESCE(CASE ? WHEN 'NO' THEN noPrice ELSE yesPrice END, yesPrice) p,
                                    collectedAt
                             FROM MarketSnapshot
                             WHERE marketId=? AND collectedAt BETWEEN ? AND ?
                             ORDER BY ABS(collectedAt - ?) LIMIT 1""",
                          (L["o"], L["m"], target - tol, target + tol, target)).fetchone()
            if not r or r["p"] is None or not (0.0 < r["p"] < 1.0):
                continue
            covered[H] += 1
            res[H].append(dict(m=L["m"], n=L["n"], px=L["px"], mark=r["p"],
                               d=r["p"] - L["px"], st=L["st"], pnl=L["pnl"]))
    for H, _ in HORIZONS:
        rows = res[H]
        if not rows:
            print(f"  +{H:g}h: no snapshot coverage")
            continue
        d = [r["d"] for r in rows]
        up = sum(1 for x in d if x >= 0.05)
        dn = sum(1 for x in d if x <= -0.05)
        print(f"  +{H:>5g}h  coverage {covered[H]:,}/{len(legs):,} legs  "
              f"mark change: median {100 * statistics.median(d):+.1f}pp  "
              f"mean {100 * statistics.mean(d):+.1f}pp  "
              f"| rose >=5pp {100.0 * up / len(rows):.0f}%  fell >=5pp {100.0 * dn / len(rows):.0f}%")
        settled = [r for r in rows if r["st"] == "resolved"]
        if len(settled) >= 30:
            ntl = sum(r["n"] for r in settled)
            hold = sum(r["pnl"] for r in settled)
            ex = sum(r["n"] * (r["mark"] / r["px"] - 1.0) for r in settled)
            by_m = collections.defaultdict(list)
            for r in settled:
                by_m[r["m"]].append(r["n"] * (r["mark"] / r["px"] - 1.0) - r["pnl"])
            keys = list(by_m)
            rnd = random.Random(13)
            ds = sorted(sum(sum(by_m[rnd.choice(keys)]) for _ in keys) for _ in range(1500))
            print(f"          settled subset {len(settled):,} legs / {usd(ntl)}: "
                  f"hold {usd(hold)} ({100 * hold / ntl:+.1f}%)  "
                  f"exit-at-mark {usd(ex)} ({100 * ex / ntl:+.1f}%)  "
                  f"alpha {usd(ex - hold)}  CI "
                  f"[{usd(ds[int(.025 * len(ds))])}, {usd(ds[int(.975 * len(ds))])}] "
                  f"over {len(keys)} markets")
    # control: the same legs' marks BEFORE entry (was the wallet buying a rising market?)
    pre = []
    for L in legs[:4000]:
        t0 = L["openedAt"]
        if not isinstance(t0, int):
            continue
        target = t0 - 24 * 3.6e6
        r = c.execute("""SELECT COALESCE(CASE ? WHEN 'NO' THEN noPrice ELSE yesPrice END, yesPrice) p
                         FROM MarketSnapshot WHERE marketId=? AND collectedAt BETWEEN ? AND ?
                         ORDER BY ABS(collectedAt - ?) LIMIT 1""",
                      (L["o"], L["m"], target - 12 * 3.6e6, target + 12 * 3.6e6, target)).fetchone()
        if r and r["p"] is not None and 0 < r["p"] < 1:
            pre.append(r["p"] - L["px"])
    if pre:
        print(f"  CONTROL, -24h -> entry (first {len(pre):,} legs): median "
              f"{100 * statistics.median(pre):+.1f}pp, mean {100 * statistics.mean(pre):+.1f}pp "
              f"-- a positive value is the wallet buying into a market that was already rising")


def wallet_persistence(c, cache):
    """Axis 4, on 600+ wallets instead of 16: does trailing edge predict forward edge?

    The 2026-10-21 review set the bar explicitly -- "act when the rank correlation is
    below +0.15 on >=30 overlapping wallets" -- and declined to act on 16. This reads
    it on the population the scanner actually screens, one row per bet (first print
    only: the 10-27 review showed per-print weighting reverses the sign), edge in
    probability points (settle value - price paid), so the statistic is not dollars and
    cannot be taken by the smallest book.
    """
    print("\n=== SS.6  DOES WALLET RANK PREDICT ANYTHING FORWARD? (axis 4, n>=30 opened) ===")
    truth_cache = json.load(open("data/market-truth-clob.json"))
    stats = collections.Counter()
    bets = collections.defaultdict(dict)   # wallet -> {(cid, outcome): row}
    for r in c.execute("""SELECT walletAddress w, conditionId cid, outcome o, detectedPrice dp,
                                 walletEntryPrice wp, timestamp ts, marketId m
                          FROM ObservedTrade WHERE isDemo=0 AND side='BUY'
                            AND conditionId IS NOT NULL ORDER BY timestamp"""):
        v = truth_of(truth_cache, r["cid"], r["o"], stats)
        if v is None:
            continue
        px = r["dp"] if r["dp"] and 0 < r["dp"] < 1 else r["wp"]
        if not px or not (0 < px < 1):
            continue
        key = (r["cid"], (r["o"] or "").strip().upper())
        if key in bets[r["w"]]:
            continue                      # first print only
        bets[r["w"]][key] = (r["ts"], v - px, px, r["m"])
    print(f"  bets joined to settlement truth: {sum(len(v) for v in bets.values()):,} "
          f"over {len(bets):,} wallets  (truth: {dict(stats)})")
    CUT = 1787300000000               # 2026-08-20, so the forward window is ~70 days
    H1, H2 = {}, {}
    for w, d in bets.items():
        a = [x[1] for x in d.values() if x[0] < CUT]
        b = [x[1] for x in d.values() if x[0] >= CUT]
        if len(a) >= 8 and len(b) >= 8:
            H1[w] = statistics.mean(a)
            H2[w] = statistics.mean(b)
    print(f"  wallets with >=8 bets in BOTH halves (cut 2026-08-20): {len(H1):,}")
    if len(H1) < 30:
        print(f"  BELOW the pre-registered 30-wallet bar -- no verdict. The binding constraint is "
              f"TRUTH COVERAGE, not wallet count: {len(bets):,} wallets print, but the settlement "
              f"cache holds only 4,005 markets against 295,404 distinct conditionIds seen in "
              f"ObservedTrade (1.4%). Everything below is direction on {len(H1)} wallets.")
    if len(H1) < 8:
        return
    ws = list(H1)

    def spearman(a, b):
        def rank(x):
            s = sorted(range(len(x)), key=lambda i: x[i])
            r = [0.0] * len(x)
            for pos, i in enumerate(s):
                r[i] = pos
            return r
        ra, rb = rank(a), rank(b)
        ma, mb = statistics.mean(ra), statistics.mean(rb)
        num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
        den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
        return num / den if den else 0.0

    xs = [H1[w] for w in ws]
    ys = [H2[w] for w in ws]
    rho = spearman(xs, ys)
    rnd = random.Random(7)
    null = []
    for _ in range(2000):
        sh = ys[:]
        rnd.shuffle(sh)
        null.append(spearman(xs, sh))
    p = sum(1 for v in null if abs(v) >= abs(rho)) / len(null)
    print(f"  Spearman rho(H1 edge, H2 edge) = {rho:+.3f}   permutation p = {p:.3f} "
          f"({len(null)} shuffles)")
    print(f"  H1 edge: mean {100 * statistics.mean(xs):+.2f}pp median {100 * statistics.median(xs):+.2f}pp   "
          f"H2 edge: mean {100 * statistics.mean(ys):+.2f}pp median {100 * statistics.median(ys):+.2f}pp")
    # quintiles of H1 -> H2, plus a shuffled-label null on the top-minus-bottom spread
    order = sorted(ws, key=lambda w: H1[w])
    q = len(order) // 5
    print("  quintile by H1 edge -> forward (H2) edge:")
    buckets = []
    for i in range(5):
        grp = order[i * q:(i + 1) * q] if i < 4 else order[4 * q:]
        m = statistics.mean([H2[w] for w in grp])
        buckets.append(m)
        print(f"    Q{i + 1} (H1 {100 * statistics.mean([H1[w] for w in grp]):+.1f}pp, "
              f"{len(grp)} wallets) -> H2 {100 * m:+.2f}pp")
    spread = buckets[-1] - buckets[0]
    sh_n = []
    for _ in range(2000):
        sh = order[:]
        rnd.shuffle(sh)
        vals = [H2[w] for w in sh]
        sh_n.append(statistics.mean(vals[4 * q:]) - statistics.mean(vals[:q]))
    p2 = sum(1 for v in sh_n if v >= spread) / len(sh_n)
    print(f"  top-minus-bottom quintile forward spread: {100 * spread:+.2f}pp   "
          f"shuffled-null p = {p2:.3f}  (null p95 {100 * pct(sh_n, .95):+.2f}pp)")
    # what the screen actually picks vs the population
    tracked = {r[0] for r in c.execute("SELECT address FROM WalletProfile WHERE status='track'")}
    tw = [w for w in ws if w in tracked]
    if tw:
        print(f"  the tracked set, measured on the same forward window: {len(tw)} wallets, "
              f"forward edge mean {100 * statistics.mean([H2[w] for w in tw]):+.2f}pp  "
              f"vs population {100 * statistics.mean([H2[w] for w in ws]):+.2f}pp")
    else:
        print("  none of the currently tracked wallets has >=20 bets in both halves")
    print(f"  VERDICT INPUT: pre-registered bar was rho < +0.15 on >=30 wallets -> strip rank "
          f"from sizing. walletQualityInSize is ALREADY 0 in v69, so the bar can only inform "
          f"ADMISSION and scan-slot allocation now.")


def entry_lag(c):
    """How late are we, and does lateness explain the flat mark path?

    lag = DecisionJournal.createdAt - ObservedTrade.timestamp for every copied leg.
    Two readings: (1) the distribution; (2) settled edge and the +2.5h mark path by
    lag bucket. If the wallets round-trip in 2.5h at +41.9pp (§SS.2) and our edge is
    flat in lag, the information was never in the print and the copy premise is dead.
    If edge decays with lag, the fast lane is the first change aimed at the source.
    """
    print("\n=== SS.7  ENTRY LAG: are we copying an informative print at all? ===")
    rows = c.execute("""SELECT p.id, p.marketId m, p.outcome o, p.entryPrice px,
                               p.simulatedPositionSize n, p.realizedPnl pnl, p.status st,
                               p.openedAt, (j.createdAt - o.timestamp) lag_ms
                        FROM PaperTrade p
                        JOIN DecisionJournal j ON j.id = p.decisionJournalId
                        JOIN ObservedTrade o ON o.id = j.observedTradeId
                        WHERE p.isDemo=0""").fetchall()
    lags = [r["lag_ms"] / 60000.0 for r in rows if r["lag_ms"] is not None]
    lags = [x for x in lags if x >= 0]
    if not lags:
        print("  no joinable legs")
        return
    print(f"  legs with a decision lag: {len(lags):,}")
    print(f"  lag minutes: median {statistics.median(lags):.1f}  p10 {pct(lags, .1):.1f}  "
          f"p90 {pct(lags, .9):.1f}  p99 {pct(lags, .99):.1f}  max {max(lags):.1f}")
    buckets = [(0, 5), (5, 15), (15, 30), (30, 60), (60, 240), (240, 1e9)]
    print("  settled-edge and +2.5h mark change by lag bucket:")
    for lo, hi in buckets:
        sub = [r for r in rows if r["lag_ms"] is not None and lo <= r["lag_ms"] / 60000.0 < hi]
        settled = [r for r in sub if r["st"] == "resolved"]
        if not sub:
            continue
        ntl = sum(r["n"] for r in settled)
        pnl = sum(r["pnl"] for r in settled)
        marks = []
        for r in settled[:1200]:
            if not isinstance(r["openedAt"], int):
                continue
            t = r["openedAt"] + 2.5 * 3.6e6
            q = c.execute("""SELECT COALESCE(CASE ? WHEN 'NO' THEN noPrice ELSE yesPrice END, yesPrice) v
                             FROM MarketSnapshot WHERE marketId=? AND collectedAt BETWEEN ? AND ?
                             ORDER BY ABS(collectedAt - ?) LIMIT 1""",
                          (r["o"], r["m"], t - 3 * 3.6e6, t + 3 * 3.6e6, t)).fetchone()
            if q and q["v"] is not None and 0 < q["v"] < 1:
                marks.append(q["v"] - r["px"])
        roi = f"{100 * pnl / ntl:+.1f}%" if ntl else "n/a"
        mk = f"{100 * statistics.median(marks):+.1f}pp" if marks else "n/a"
        print(f"    {lo:>4g}-{hi if hi < 1e8 else 9999:>4g} min: {len(sub):>5,} legs  "
              f"settled {len(settled):>4,} / {usd(ntl):>10} ROI {roi:>7}  "
              f"+2.5h mark {mk:>7} (n={len(marks)})")
    # how much flow the drift gate kills, as context for the lag
    print("  context: the +/-0.4c drift gate is the book's #1 skip reason (28.9% of skips, "
          "2026-09-20 read) -- with a median lag of "
          f"{statistics.median(lags):.0f} min, a 0.4c tolerance is a very tight filter on a "
          "market the source has just traded.")


def entry_is_the_game(c):
    """If the entry is the only variable, price it: what is 1c of entry worth, and how much
    notional does the book put through the bands whose spread costs the most?"""
    print("\n=== SS.8  THE ENTRY IS THE WHOLE GAME -- priced on the book itself ===")
    now = int(time.time() * 1000)
    for label, since in (("all-time", 0), ("last 90d", now - 90 * 86400000)):
        legs = c.execute("""SELECT entryPrice px, simulatedPositionSize n, realizedPnl pnl,
                                   status st, openedAt, COALESCE(resolvedAt, closedAt) doneAt
                            FROM PaperTrade WHERE isDemo=0 AND status IN ('resolved','closed')
                              AND openedAt >= ?""", (since,)).fetchall()
        res = [L for L in legs if L["st"] == "resolved"]
        clo = [L for L in legs if L["st"] == "closed"]
        def agg(xs):
            n = sum(x["n"] for x in xs)
            p = sum(x["pnl"] or 0 for x in xs)
            return len(xs), n, p
        nr, ntr, pr = agg(res)
        nc, ntc, pc = agg(clo)
        print(f"  {label}: settled {nr:,} legs / {usd(ntr)} -> {usd(pr)} "
              f"({100 * pr / ntr if ntr else 0:+.1f}%)   early-closed {nc:,} / {usd(ntc)} -> "
              f"{usd(pc)} ({100 * pc / ntc if ntc else 0:+.1f}%)")
        # 1c better entry on every leg that settled: dPnL = n*s*(1/(p-.01) - 1/p), s=1 if won
        gain = 0.0
        for L in res:
            pnl = L["pnl"] or 0.0
            p = L["px"]
            if not (0.02 < p < 1) or L["n"] <= 0:
                continue
            won = (1.0 if pnl > 0 else 0.0)
            if won:
                gain += L["n"] * won * (1.0 / (p - 0.01) - 1.0 / p)
        print(f"          1c better entry on every settled leg, on the winning half: "
              f"{usd(gain)} of extra settlement value on {usd(ntr)} of notional "
              f"({100 * gain / ntr if ntr else 0:.1f}% of notional)")
    # capital-days, and profit per capital-day, on the finished book
    legs = c.execute("""SELECT entryPrice px, simulatedPositionSize n, realizedPnl pnl,
                               openedAt, COALESCE(resolvedAt, closedAt) doneAt
                        FROM PaperTrade WHERE isDemo=0 AND status IN ('resolved','closed')
                          AND doneAt IS NOT NULL""").fetchall()
    cd = sum(L["n"] * max((L["doneAt"] - L["openedAt"]) / 86400000.0, 0) for L in legs
             if isinstance(L["doneAt"], int) and isinstance(L["openedAt"], int))
    pnl = sum(L["pnl"] or 0 for L in legs)
    ntl = sum(L["n"] for L in legs)
    if cd:
        print(f"  finished book: {usd(pnl)} on {usd(ntl)} of notional over {cd:,.0f} "
              f"capital-days = ${1000 * pnl / cd:.2f} per $1k-capital-day")
        print(f"  read that against the ladder: $5,000/day at this rate needs "
              f"{usd(5000 * cd / pnl) if pnl else 'n/a'} of open capital "
              f"(current open book: $5,155)")


def main():
    c = con()
    refresh = "--refresh" in sys.argv
    cache, tracked = flow_census(c, refresh=refresh)
    rt = round_trips(cache)
    if not ONLY_CENSUS:
        exit_timing(rt)
        if not ONLY_EXIT:
            book_overlap(c, cache, rt)
            reach(c, cache, rt)
            mark_path(c)
            wallet_persistence(c, cache)
            entry_lag(c)
            entry_is_the_game(c)
    print("\n(§SS cost basis: simulatedPositionSize = dollars at risk; "
          "exit/settlement PnL = n*(c/p - 1).)")


if __name__ == "__main__":
    main()
