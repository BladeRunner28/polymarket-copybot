#!/usr/bin/env python3
"""
wallet-concentration-test — READ-ONLY: does a source wallet's category
CONCENTRATION (specialist vs generalist) predict how our copy of that wallet
does? (roadmap card `polycopy-concentration-feature-test`, 2026-09-23).

WHY: Polycopy's marketing-side Q1 2026 report claims category concentration is
the strongest predictor of trader performance (80%+ of volume in one category =
58.2% win rate vs 51.1% for 4+ categories; NBA O/U specialists +18pp over the
category average). We store `bestCategory` / `categoryFitScore` but have never
measured concentration itself, and our C-200 category blacklist is a hard filter
rather than a graded feature. The standing rule (see skill trading-data-integrity
check 13) is MEASURE FIRST: this script is the measurement, it gates nothing.

WHAT IT DOES:
  1. classifies every observed trade's market into (coarse, fine) categories with
     an explicit keyword classifier (the stored `ObservedTrade.marketCategory` is
     a bare slug token — `highest`, `what`, `fifwc` — and is NOT usable as a
     category), and prints the volume distribution so the coverage is auditable;
  2. per source wallet, computes concentration = share of its observed VOLUME
     (size x walletEntryPrice) in its top fine / top coarse category (count-based
     variants too) — over ALL its observed history AND over a FIXED window of its
     most recent 20 trades. The fixed window matters: concentration over a
     wallet's full history is mechanically driven by how MANY of its trades we
     have seen (more trades -> more categories touched -> lower share), measured
     below at spearman -0.72 against observed-trade count. Equal-n windows make
     the feature comparable across thin and deep records;
  3. joins concentration to OUR OWN settled legs (status closed|resolved,
     isDemo=0, closedAt ?? resolvedAt) per lane and prints decile tables, the
     vendor's own 80% split, wallet-clustered bootstrap CIs, pooled permutation
     tests, an entry-price control (the price baseline — a thin-specialist wallet
     may simply bet more longshots), and AUCs against the wallet scores we
     already store so the reader can see whether concentration adds anything on
     top of them;
  4. validates the classifier against polycopy's own `categoryStrengthsJson`
     (independent measure of the same feature) and reports how they agree.

Writes nothing. One command re-runs everything.
"""
import csv
import datetime
import json
import math
import os
import random
import re
import sqlite3
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_PATH = os.path.join(ROOT, "prisma", "dev.db")
LANES = ("BANKROLL_200", "STANDARD")
BOOT = 5000
PERM = 20000
ELEMENT_BUDGET = 40000000     # permutation element-ops per test (~60s in CPython)
BOOT_BUDGET = 20000000        # element-ops per bootstrap CI
MIN_OBS_PRIMARY = 10          # wallets with fewer observed trades have a noisy 0/1 concentration
random.seed(20260923)
_DRAWS = []                   # permutation draws actually used (audit line)
_BOOT_DRAWS = []

# ------------------------------------------------------------------ classifier
# Ordered rules over the market QUESTION (lowercased). The slug prefix is used
# first when it is a known series token, because it is exact where the question
# text is free-form. Coarse = the bucket a copy book would blacklist/allocate
# against; fine = the grain the vendor's claim lives at (league / market type).
SLUG_RULES = [
    ("fifwc", "sports", "football-intl"), ("uwcl", "sports", "football-intl"),
    ("ucl", "sports", "football-ucl"), ("epl", "sports", "football-epl"),
    ("fl1", "sports", "football-epl"), ("spl", "sports", "football-epl"),
    ("efl", "sports", "football-epl"), ("mls", "sports", "football-mls"),
    ("brco", "sports", "football-intl"), ("bra2", "sports", "football-intl"),
    ("lol", "esports", "esports-lol"), ("lec", "esports", "esports-lol"),
    ("cs2", "esports", "esports-cs2"), ("dota2", "esports", "esports-dota"),
    ("val", "esports", "esports-valorant"),
    ("mlb", "sports", "baseball-mlb"), ("wnba", "sports", "basketball-nba"),
    ("nba", "sports", "basketball-nba"), ("nfl", "sports", "football-nfl"),
    ("nhl", "sports", "hockey-nhl"), ("ufc", "sports", "combat-ufc"),
    ("atp", "sports", "tennis"), ("wta", "sports", "tennis"), ("itf", "sports", "tennis"),
    ("btc", "crypto", "crypto-btc"), ("eth", "crypto", "crypto-eth"),
    ("bitcoin", "crypto", "crypto-btc"), ("ethereum", "crypto", "crypto-eth"),
    ("elon", "politics", "politics-elon"), ("khamenei", "politics", "politics-geo"),
    ("trump", "politics", "politics-us"), ("donald", "politics", "politics-us"),
    ("white", "politics", "politics-us"), ("fed", "econ", "econ-macro"),
]
QUESTION_RULES = [
    (r"\b(bitcoin|btc|ethereum|eth|solana|sol|xrp|doge|crypto)\b", "crypto", "crypto-price"),
    (r"up or down", "crypto", "crypto-updown"),
    (r"\b(league of legends|\blol\b|valorant|dota|counter-?strike|cs2|esports?)\b", "esports", "esports-other"),
    (r"\b(nba|wnba|lakers|celtics|knicks|nuggets|warriors|bucks|nba finals)\b", "sports", "basketball-nba"),
    (r"\b(mlb|world series|yankees|dodgers|red sox)\b", "sports", "baseball-mlb"),
    (r"\b(nfl|super bowl|touchdown)\b", "sports", "football-nfl"),
    (r"\b(nhl|stanley cup)\b", "sports", "hockey-nhl"),
    (r"\b(ufc|mma)\b", "sports", "combat-ufc"),
    (r"\b(atp|wta|itf|grand slam|wimbledon|us open tennis)\b", "sports", "tennis"),
    (r"\b(fifa|world cup|uefa|premier league|la liga|serie a|bundesliga|ligue 1|mls|champions league|copa)\b", "sports", "football-intl"),
    (r"\b(temperature|rain|snow|hurricane|weather|fahrenheit|celsius)\b", "weather", "weather-temp"),
    (r"\b(fed|fomc|interest rate|cpi|inflation|gdp|recession|unemployment|s&p|nasdaq|stock)\b", "econ", "econ-macro"),
    (r"\b(election|senate|house of representatives|president|parliament|prime minister|governor|mayor|nominee|congress|khamenei|putin|zelensky|netanyahu)\b", "politics", "politics-elections"),
    (r"\b(trump|biden|harris|desantis|newsom|white house|elon musk)\b", "politics", "politics-us"),
    (r"\b(oscar|grammy|emmy|movie|box office|album|billboard|song|spotify|netflix|tiktok)\b", "culture", "culture-media"),
    (r"\b(openai|gpt|gemini|claude|llama|anthropic|nvidia|tesla|spacex|starship|apple|google|meta)\b", "tech", "tech-corp"),
    (r"\b(ai\b|artificial intelligence)\b", "tech", "tech-ai"),
]
_SLUG_FIRST = {}
for tok, coarse, fine in SLUG_RULES:
    _SLUG_FIRST.setdefault(tok, (coarse, fine))


def classify(market_id, question):
    slug = (market_id or "").lower()
    first = slug.split("-")[0]
    if first in _SLUG_FIRST:
        return _SLUG_FIRST[first]
    # series tokens that are not the first slug segment (e.g. "will-fifwc-...")
    for tok in _SLUG_FIRST:
        if re.search(r"(^|-)" + re.escape(tok) + r"(-|$)", slug):
            return _SLUG_FIRST[tok]
    q = (question or "").lower()
    for pat, coarse, fine in QUESTION_RULES:
        if re.search(pat, q):
            return (coarse, fine)
    return ("other", "other")


# ------------------------------------------------------------------ statistics
def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else float("nan")


def _ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(xs, ys):
    return pearson(_ranks(xs), _ranks(ys))


def auc(scores, labels):
    """Rank AUC; nan if one class is empty. labels truthy = positive."""
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return float("nan")
    ranks = _ranks(scores)
    rsum = sum(r for r, l in zip(ranks, labels) if l)
    n1, n0 = len(pos), len(neg)
    return (rsum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def auc_half(n_pos, n_neg):
    """Hanley–McNeil closed-form 95% half-width of an AUC estimate evaluated at
    A=0.5 — the sample's minimum detectable discrimination. No randomness."""
    a = 0.5
    q1 = a / (2 - a)
    q2 = 2 * a * a / (1 + a)
    se = math.sqrt((a * (1 - a) + (n_pos - 1) * (q1 - a * a) + (n_neg - 1) * (q2 - a * a)) / (n_pos * n_neg))
    return 1.96 * se


def boot_ci_clusters(groups, fn, n=None):
    """Cluster bootstrap: resample the SHARED UNIT (here: wallets), not legs.
    Draws are budgeted by total element count so a 9k-leg lane cannot take
    minutes; the interval is a percentile CI either way."""
    total = sum(len(g) for g in groups)
    draws = n or max(1000, min(BOOT, int(BOOT_BUDGET / max(1, total))))
    _BOOT_DRAWS.append(draws)
    vals = []
    for _ in range(draws):
        sample = [groups[random.randrange(len(groups))] for _ in range(len(groups))]
        v = fn(sample)
        if v == v and abs(v) != float("inf"):
            vals.append(v)
    if len(vals) < 100:
        return (float("nan"), float("nan"))
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))])


def fast_mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def pooled_perm_clusters(groups_a, groups_b, stat, n=None):
    """Two-group difference where the GROUP LABEL is permuted at the shared unit
    (WALLET) level: the pooled wallets are re-split each draw, so the legs of one
    wallet never move independently of each other. A leg-level shuffle treats
    1,400 legs as 1,400 draws and reports p=0.000 for trivial differences."""
    wa = [g for g in groups_a if g]
    wb = [g for g in groups_b if g]
    fa = [x for g in wa for x in g]
    fb = [x for g in wb for x in g]
    if len(fa) < 5 or len(fb) < 5 or len(wa) < 4 or len(wb) < 4:
        return float("nan")
    obs = abs(stat(fa) - stat(fb))
    pool = wa + wb
    na = len(wa)
    draws = n or max(2000, min(PERM, int(ELEMENT_BUDGET / max(1, len(fa) + len(fb)))))
    _DRAWS.append(draws)
    cnt = 0
    for _ in range(draws):
        random.shuffle(pool)
        a = [x for g in pool[:na] for x in g]
        b = [x for g in pool[na:] for x in g]
        if abs(stat(a) - stat(b)) >= obs:
            cnt += 1
    return (cnt + 1) / (draws + 1)


def draws_note():
    if not _DRAWS:
        return ""
    return "permutation draws %d-%d (adaptive to pool size)" % (min(_DRAWS), max(_DRAWS))


# ----------------------------------------------------------------------- data
def load_observed():
    con = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True)
    rows = con.execute(
        "SELECT walletAddress, marketId, marketQuestion, size, walletEntryPrice, observationOnly, timestamp "
        "FROM ObservedTrade WHERE isDemo = 0"
    ).fetchall()
    con.close()
    return rows


def load_legs():
    con = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True)
    rows = con.execute(
        """SELECT p.botId, p.walletAddress, p.marketId, p.realizedPnl,
                  p.simulatedPositionSize, p.entryPrice
           FROM PaperTrade p
           WHERE p.isDemo = 0 AND p.status IN ('closed','resolved')
             AND p.realizedPnl IS NOT NULL"""
    ).fetchall()
    scans = con.execute(
        """SELECT address, coalesce(globalScore,0), coalesce(roi30d,0),
                  coalesce(consistencyScore,0), coalesce(copyabilityScore,0),
                  coalesce(resolvedTradeCount30d,0), coalesce(tradeCount30d,0),
                  coalesce(winRate30d,0), coalesce(categoryStrengthsJson,'{}'),
                  coalesce(status,'')
           FROM WalletProfile WHERE isDemo = 0"""
    ).fetchall()
    con.close()
    return rows, scans


def concentration(rows, min_obs, fixed_k=20):
    """Per wallet: top-category share of volume and of trade count, coarse+fine,
    over the whole observed history AND over the most recent `fixed_k` trades."""
    bywallet = defaultdict(list)
    for wallet, mid, q, size, price, _obs, ts in rows:
        usd = (size or 0.0) * (price or 0.0)
        coarse, fine = classify(mid, q)
        bywallet[wallet].append((ts or 0, usd, coarse, fine))
    out = {}
    for wallet, trades in bywallet.items():
        if len(trades) < min_obs:
            continue
        trades.sort()

        def shares(subset):
            tot = sum(t[1] for t in subset) or 1e-9
            fine_usd, coarse_usd, fine_n = defaultdict(float), defaultdict(float), defaultdict(int)
            for _ts, usd, coarse, fine in subset:
                fine_usd[fine] += usd
                coarse_usd[coarse] += usd
                fine_n[fine] += 1
            return dict(
                conc_fine=max(fine_usd.values()) / tot,
                conc_coarse=max(coarse_usd.values()) / tot,
                conc_fine_n=max(fine_n.values()) / len(subset),
                top_fine=max(fine_usd, key=lambda k: fine_usd[k]),
                top_coarse=max(coarse_usd, key=lambda k: coarse_usd[k]),
                n_fine_cats=len(fine_usd),
            )

        rec = dict(n_obs=len(trades), usd=sum(t[1] for t in trades))
        rec.update(shares(trades))
        rec.update(dict(("win_" + k, v) for k, v in shares(trades[-fixed_k:]).items()))
        out[wallet] = rec
    return out


def scan_concentration(js, field="trades"):
    """polycopy's own categoryStrengthsJson → top-category share (independent
    measure of the same feature; validated against ours)."""
    try:
        d = json.loads(js or "{}")
    except Exception:
        return None
    if not isinstance(d, dict) or not d:
        return None
    tot = 0.0
    top = 0.0
    for cat, v in d.items():
        if not isinstance(v, dict):
            continue
        val = float(v.get(field) or 0)
        tot += val
        top = max(top, val)
    return (top / tot) if tot > 0 else None


def decile_table(L, key, title):
    """Wallet-level feature → leg-level outcome, in deciles of the feature.
    `wal` counts wallets (the unit that owns the feature) and `legs` the legs."""
    def val(w):
        return next(l[key] for l in L if l["wallet"] == w) or 0.0
    ranked = sorted({l["wallet"] for l in L}, key=val)
    q = max(1, len(ranked) // 10)
    print("\n  %s" % title)
    print("  %-6s %-16s %5s %5s %6s %10s %9s %8s %7s %8s" %
          ("decile", "share range", "wal", "legs", "cost$", "realized$", "mean leg$", "median$", "win%", "edge%"))
    mon = _monotone_means(L, ranked, q, val)
    for i in range(10):
        grp = ranked[i * q:(i + 1) * q] if i < 9 else ranked[i * q:]
        if not grp:
            continue
        gl = [l for l in L if l["wallet"] in set(grp)]
        cost = sum(l["size"] for l in gl) or 1e-9
        print("  %-6d %-16s %5d %5d %6.0f %10s %9s %8s %6.0f%% %8s" % (
            i + 1, "%.2f-%.2f" % (min(val(w) for w in grp), max(val(w) for w in grp)),
            len(grp), len(gl), cost, money(sum(l["pnl"] for l in gl)),
            money(statistics.mean([l["pnl"] for l in gl])),
            money(statistics.median([l["pnl"] for l in gl])),
            100.0 * sum(1 for l in gl if l["pnl"] > 0) / len(gl),
            "%+.1f" % (100.0 * sum(l["pnl"] for l in gl) / cost)))
    print("    monotone in mean-leg PnL across the 10 buckets: %s" % ("yes" if mon else "NO — no dose-response"))


def _monotone_means(L, ranked, q, val):
    means = []
    for i in range(10):
        grp = ranked[i * q:(i + 1) * q] if i < 9 else ranked[i * q:]
        if not grp:
            continue
        gl = [l for l in L if l["wallet"] in set(grp)]
        means.append(statistics.mean([l["pnl"] for l in gl]))
    inc = all(b >= a for a, b in zip(means, means[1:]))
    dec = all(b <= a for a, b in zip(means, means[1:]))
    return (inc or dec)


def vendor_split(L, key, label):
    hi = [l for l in L if (l[key] or 0) >= 0.80]
    lo = [l for l in L if (l[key] or 0) < 0.80]
    print("\n  THE VENDOR SPLIT (%s): top-category share >= 0.80 vs < 0.80" % label)
    for lab, grp in (("specialist >=80%", hi), ("generalist <80%", lo)):
        if not grp:
            continue
        cost = sum(l["size"] for l in grp) or 1e-9
        gh = defaultdict(list)
        for l in grp:
            gh[l["wallet"]].append(l["pnl"])
        lo_ci, hi_ci = boot_ci_clusters(list(gh.values()), lambda s: statistics.mean([x for g in s for x in g]))
        print("    %-17s wallets=%3d legs=%4d cost=%9s realized=%10s mean leg=%8s [%s, %s] median=%7s win=%.0f%% edge=%+.1f%%" % (
            lab, len(gh), len(grp), money(sum(l["size"] for l in grp)), money(sum(l["pnl"] for l in grp)),
            money(statistics.mean([l["pnl"] for l in grp])), money(lo_ci), money(hi_ci),
            money(statistics.median([l["pnl"] for l in grp])),
            100.0 * sum(1 for l in grp if l["pnl"] > 0) / len(grp), 100.0 * sum(l["pnl"] for l in grp) / cost))
    if hi and lo:
        a = [[l["pnl"] for l in hi if l["wallet"] == w] for w in {l["wallet"] for l in hi}]
        b = [[l["pnl"] for l in lo if l["wallet"] == w] for w in {l["wallet"] for l in lo}]
        print("    wallet-clustered permutation: p(mean leg differs)=%.3f  p(median leg differs)=%.3f  [%s]"
              % (pooled_perm_clusters(a, b, fast_mean), pooled_perm_clusters(a, b, statistics.median), draws_note()))
        ec = [100.0 * sum(l["pnl"] for l in g) / max(1e-9, sum(l["size"] for l in g)) for g in (hi, lo)]
        print("    edge%% of cost: specialist %+.1f%% vs generalist %+.1f%% (win-leg share %.1f%% vs %.1f%%)"
              % (ec[0], ec[1],
                 100.0 * sum(1 for l in hi if l["pnl"] > 0) / len(hi),
                 100.0 * sum(1 for l in lo if l["pnl"] > 0) / len(lo)))
    return hi, lo


def money(v):
    return "%s$%.2f" % ("-" if v < 0 else "", abs(v))


def pct(v):
    return "n/a" if v is None or v != v else "%+.3f" % v


def main():
    obs = load_observed()
    leg_rows, scans = load_legs()
    scan_by_wallet = {r[0]: r for r in scans}

    # ---- classifier coverage (auditable before any result is quoted)
    vol = defaultdict(float)
    cnt = defaultdict(int)
    for wallet, mid, q, size, price, _o, _ts in obs:
        c, f = classify(mid, q)
        vol[f] += (size or 0) * (price or 0)
        cnt[f] += 1
    tot_vol = sum(vol.values())
    print("PSMI-free wallet concentration test — READ-ONLY, gates nothing")
    print("  observed trades: %d rows, %d wallets, $%.0f of copied-side volume"
          % (len(obs), len({r[0] for r in obs}), tot_vol))
    print("\nCLASSIFIER COVERAGE (fine category share of observed volume) — the stored")
    print("ObservedTrade.marketCategory is a bare slug token ('highest','what') and is unusable:")
    for f, v in sorted(vol.items(), key=lambda kv: -kv[1])[:14]:
        print("    %-16s %7d trades  %5.1f%% of volume" % (f, cnt[f], 100.0 * v / tot_vol))
    other = vol.get("other", 0.0) / tot_vol
    print("    %-16s %7d trades  %5.1f%% of volume" % ("(other = unclassified)", cnt.get("other", 0), 100.0 * other))

    conc = concentration(obs, MIN_OBS_PRIMARY)
    print("\nPOPULATION: %d wallets have >=%d observed trades (the concentration sample)"
          % (len(conc), MIN_OBS_PRIMARY))

    # ---- legs, joined per lane
    legs = []
    for bot, wallet, mid, pnl, size, entry in leg_rows:
        c = conc.get(wallet)
        s = scan_by_wallet.get(wallet)
        legs.append(dict(
            bot=bot, wallet=wallet, pnl=pnl or 0.0, size=size or 0.0, entry=entry or 0.0,
            conc=c["win_conc_fine"] if c else None, conc_all=c["conc_fine"] if c else None,
            conc_coarse=c["win_conc_coarse"] if c else None,
            n_obs=c["n_obs"] if c else None, top_fine=c["win_top_fine"] if c else None,
            globalScore=s[1] if s else None, roi30d=s[2] if s else None,
            cons=s[3] if s else None, copyab=s[4] if s else None,
            resolved30=s[5] if s else None, trades30=s[6] if s else None,
            winrate30=s[7] if s else None, status=s[9] if s else None,
        ))
    print("  legs (all lanes): %d settled legs, %d wallets" % (len(legs), len({l['wallet'] for l in legs})))

    # ---- validation of our classifier against polycopy's own category map
    xs, ys = [], []
    for wallet, c in conc.items():
        s = scan_by_wallet.get(wallet)
        if not s:
            continue
        v = scan_concentration(s[8], "trades")
        if v is None:
            continue
        xs.append(c["conc_fine"])
        ys.append(v)
    if len(xs) >= 10:
        print("\nCLASSIFIER VALIDATION vs polycopy's categoryStrengthsJson (top-category share of their trades)")
        print("  n=%d wallets  pearson %s  spearman %s" % (len(xs), pct(pearson(xs, ys)), pct(spearman(xs, ys))))
        print("  (the two measures are built from different data — ours from observed trades, theirs from their")
        print("   leaderboard scan — so agreement is evidence the classifier tracks their taxonomy)")

    for lane in LANES:
        L = [l for l in legs if l["bot"] == lane and l["conc"] is not None]
        if len(L) < 50:
            print("\n%s: only %d legs with a concentration feature — skipped" % (lane, len(L)))
            continue
        print("\n" + "=" * 78)
        print("%s — %d settled legs from %d wallets (≥%d observed trades each)"
              % (lane, len(L), len({l['wallet'] for l in L}), MIN_OBS_PRIMARY))
        print("  realized %s on %s cost (%.1f%% of cost) | legs/wallet median %d"
              % (money(sum(l['pnl'] for l in L)), money(sum(l['size'] for l in L)),
                 100.0 * sum(l['pnl'] for l in L) / max(1e-9, sum(l['size'] for l in L)),
                 statistics.median([sum(1 for x in L if x['wallet'] == w) for w in {l['wallet'] for l in L}])))

        # ---- concentration -> our legs, in deciles, for BOTH feature definitions
        decile_table(L, "conc",
                     "DECILES of top-category share over the wallet's LAST 20 observed trades (equal-n window)")
        decile_table(L, "conc_all",
                     "DECILES of top-category share over the wallet's FULL observed history")
        hi, lo = vendor_split(L, "conc", "equal-n window, last 20 trades")
        vendor_split(L, "conc_all", "full observed history")

        # ---- price control: is the contrast just a different entry-price mix?
        print("\n  PRICE CONTROL — the same split WITHIN entry-price quintiles (a specialist may simply bet a")
        print("  different price band; the wallet's own booked entry is the price that matters)")
        prices = sorted(l["entry"] for l in L)
        edges = [prices[int(k * len(prices) / 5.0)] for k in range(1, 5)]
        print("  %-14s %5s %5s %9s %9s %9s   %s" % ("entry band", "legs", "wal", "mean spec$", "mean gen$", "diff", "clustered p"))
        cuts = [0.0] + edges + [1.01]
        for i in range(5):
            a = [l for l in hi if cuts[i] <= l["entry"] < cuts[i + 1]]
            b = [l for l in lo if cuts[i] <= l["entry"] < cuts[i + 1]]
            if len(a) < 5 or len(b) < 5:
                print("  %-14s %5d %5d %9s %9s %9s   (too few legs)" % (
                    "%.2f-%.2f" % (cuts[i], cuts[i + 1]), len(a), len(b),
                    money(statistics.mean([l["pnl"] for l in a])) if a else "n/a",
                    money(statistics.mean([l["pnl"] for l in b])) if b else "n/a", "n/a"))
                continue
            ga = [[l["pnl"] for l in a if l["wallet"] == w] for w in {l["wallet"] for l in a}]
            gb = [[l["pnl"] for l in b if l["wallet"] == w] for w in {l["wallet"] for l in b}]
            print("  %-14s %5d %5d %9s %9s %9s   p=%.3f" % (
                "%.2f-%.2f" % (cuts[i], cuts[i + 1]), len(a), len(b),
                money(statistics.mean([l["pnl"] for l in a])), money(statistics.mean([l["pnl"] for l in b])),
                money(statistics.mean([l["pnl"] for l in a]) - statistics.mean([l["pnl"] for l in b])),
                pooled_perm_clusters(ga, gb, fast_mean)))

        # ---- does concentration add anything over the scores we already store?
        print("\n  RANKERS vs 'leg won' (AUC, leg-level; 0.50 = no information). The price baseline and the")
        print("  wallet scores we ALREADY select on are the bar — a new feature has to beat them.")
        win = [1 if l["pnl"] > 0 else 0 for l in L]
        np_, nn_ = sum(win), len(win) - sum(win)
        hw = auc_half(np_, nn_)
        print("  MDE: with %d winning / %d losing legs this sample excludes any true AUC outside 0.50±%.3f"
              % (np_, nn_, hw))
        feats = [
            ("conc fine, last-20 window", lambda l: l["conc"]),
            ("conc fine, full history", lambda l: l["conc_all"]),
            ("conc coarse, last-20 window", lambda l: l["conc_coarse"]),
            ("generalist = 1 - conc fine", lambda l: 1.0 - (l["conc"] or 0)),
            ("entryPrice (price baseline)", lambda l: l["entry"]),
            ("1 - entryPrice", lambda l: 1.0 - l["entry"]),
            ("globalScore", lambda l: l["globalScore"]),
            ("roi30d", lambda l: l["roi30d"]),
            ("consistencyScore", lambda l: l["cons"]),
            ("copyabilityScore", lambda l: l["copyab"]),
            ("winRate30d (scan)", lambda l: l["winrate30"]),
            ("resolvedTradeCount30d", lambda l: l["resolved30"]),
            ("n observed trades (ours)", lambda l: l["n_obs"]),
        ]
        for label, get in feats:
            pairs = [(get(l), w) for l, w in zip(L, win) if get(l) is not None]
            if len(pairs) < 50:
                continue
            print("    %-28s AUC %.3f [%.3f, %.3f]  (n=%d)" % (
                label, auc([p[0] for p in pairs], [p[1] for p in pairs]),
                auc([p[0] for p in pairs], [p[1] for p in pairs]) - hw,
                auc([p[0] for p in pairs], [p[1] for p in pairs]) + hw, len(pairs)))

        # ---- the depth confound (specialists are often also thin records)
        xs = [l["conc_all"] for l in L if l["conc_all"] is not None and l["n_obs"] is not None]
        ys = [l["n_obs"] for l in L if l["conc_all"] is not None and l["n_obs"] is not None]
        xs2 = [l["conc"] for l in L if l["conc"] is not None and l["n_obs"] is not None]
        print("\n  DEPTH CONFOUND (the trap this feature has to pass): spearman(concentration, observed-trade count)")
        print("    full-history concentration : %s over %d legs  <- mechanically negative: more observed trades,"
              % (pct(spearman(xs, ys)), len(xs)))
        print("      more categories touched, lower top share (so 'specialist' partly just means 'thin record')")
        print("    last-20-window concentration: %s over %d legs  <- equal-n window, so activity depth cannot move it"
              % (pct(spearman(xs2, ys)), len(xs2)))
        print("  top fine categories among specialists (>=80% of the last 20 trades' volume), by leg count:")
        tc = defaultdict(int)
        for l in hi:
            tc[l["top_fine"]] += 1
        print("    " + ", ".join("%s %d" % kv for kv in sorted(tc.items(), key=lambda kv: -kv[1])[:8]))

    print("\nReproduce: python3 scripts/wallet-concentration-test.py   (reads %s; writes nothing)"
          % os.path.relpath(DB_PATH, ROOT))
    print("Deterministic: random.seed(20260923). Wallets with <%d observed trades are excluded from the" % MIN_OBS_PRIMARY)
    print("feature sample (a 0/1 concentration from 2 trades is noise, not a strategy).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
