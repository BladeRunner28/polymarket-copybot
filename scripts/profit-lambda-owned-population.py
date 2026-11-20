#!/usr/bin/env python3
"""
LAMBDA ON THE OWNED POPULATION — is the cheap band's lambda_hat fitted on the legs we own?

WHY THIS EXISTS
---------------
`data/premium-calibration.json` (refit 2026-11-15) carries lambda_hat = -0.5308 for 0.00-0.20,
which prices q ~= 28% at a 13.5c ask. That q is the sizing input that funds C-200's cheapest clips
to kellyMaxSizeUsd = $100, and the band receiving them loses money. The card asks whether that
lambda_hat describes the population the book OWNS (legs the venue tape says filled) or a wider
population (every leg the book BOOKED, including the ones the market never brought to our price).

WHAT THE LIVE TABLE IS ACTUALLY FITTED ON (verified here, not assumed)
----------------------------------------------------------------------
`scripts/calibrate-premium.py :: finished_trades()` reads
    SELECT entryPrice, realizedPnl, venue FROM PaperTrade
     WHERE botId='BANKROLL_200' AND status IN ('resolved','closed')
       AND realizedPnl IS NOT NULL AND isDemo=0
and labels each row `1 if realizedPnl > 0 else 0`. So the fit is on OUR OWN booked rows — not on
the copied wallet's prints — but on three things that are not the live question:

  * POPULATION : every SETTLED leg, whether or not the market ever came to our price. A leg we never
                 owned contributes a price and a label to the fit even though no dollars were ever
                 at risk at that price.
  * PRICE      : `entryPrice`, which for C-200 is the detection MID minus the maker credit — a level
                 we may never have been able to buy at.
  * LABEL      : `realizedPnl > 0`, i.e. "did our exit policy make money on this leg", not "did the
                 token we hold resolve as the winner". 73.9% of finished legs exit early, so this
                 label credits an early exit on a losing token and debits a held loss on a winner.

ARMS PRINTED
------------
    A1  RAW book rows x realizedPnl>0 x entryPrice  == the LIVE table (reproduction check)
    A2  book population x market-outcome label      (isolates the LABEL defect)
    A3  OWNED population x market-outcome label     (the arm the card asks for)
    A4  OWNED population x realizedPnl>0 label      (isolates the POPULATION defect)
plus the card's OWN statistic (owned cheap legs profitable-or-not, 7/54) so a reader can see which
label that number carries, and what each lambda_hat would buy under the LIVE RuleSet knobs.

BASIS
-----
population : PaperTrade isDemo=0, deduped to the first leg per bot|wallet|market|outcome (except A1,
             which is raw and un-deduped so it matches the live script), BANKROLL_200 only. Two
             windows: ALL history (what the live table fits) and the REGIME (ruleSetVersion >= 68 and
             opened >= 2026-09-01, the population the card measured).
price      : A1/A2 `entryPrice` (byte-identical to the live fit). A3/A4 `trueP` (the price we actually
             paid; ppi reprices only INVERTED legs whose booked price is the sibling token's).
ownership  : clob.polymarket.com minute tape, touch = min(p) <= paid + 0.001 inside 3600s of
             dispatch -> `filled_tape` (positively owned). `near_miss` (+1c) and `unfilled_tape` are
             NOT owned; `no_tape` is unadjudicated and excluded from the owned arm (counted).
label      : the venue archive's `tokens[].winner`, compared with the same normalisation and the same
             YES/NO-vs-named guard as `didOutcomeWin()` in src/lib/resolution.ts. Undeterminable rows
             are EXCLUDED and counted, never booked as losses. NOTE the coverage limit: a market
             only carries a winner once it has RESOLVED, and most C-200 legs exit early, so the
             outcome-labelled population is a fraction of the book — printed on every arm.
sizing     : scripts/score-trades.ts Kelly block re-implemented from the live RuleSet row
             (kellyFraction, kellyMaxBankrollPct, kellyMaxSizeUsd, kellyMinBetUsd, kellyMinEdgePct)
             with availableBankroll = BotBankroll.cashBalance, plus the `applyKellyBandRails` floor
             (`entryPrice < 0.20 -> max(kelly, legacyEquiv)`), which a lambda_hat change cannot move.

READ-ONLY. DB opened mode=ro. Writes no file, no RuleSet, no premium-calibration.json.

RUN
  ./venv-calib/bin/python scripts/profit-lambda-owned-population.py
  ./venv-calib/bin/python scripts/profit-lambda-owned-population.py --selftest
"""
import argparse
import importlib.util
import json
import os
import random
import sqlite3
import sys
from statistics import NormalDist

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "prisma", "dev.db")
CAL = os.path.join(ROOT, "data", "premium-calibration.json")
TRUTH = os.path.join(ROOT, "data", "market-truth-clob.json")
FUNNEL_CACHE = os.path.join(ROOT, "data", "cheap-funnel-cache")

sys.path.insert(0, os.path.join(HERE, "vendor", "oracle3"))
from wang_mle import WangMLE, LAMBDA_POLYMARKET  # noqa: E402

BANDS = ((0.0, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 1.01))
NAMES = ("0.00-0.20", "0.20-0.40", "0.40-0.60", "0.60-0.80", "0.80-1.01")
ND = NormalDist()


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def _con():
    c = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


# ------------------------------------------------------------------ labels

def norm_label(s):
    return str(s or "").strip().upper()


def outcome_win(leg_outcome, winner):
    """Mirror of didOutcomeWin(): True/False/None (None = undeterminable, never booked)."""
    want = norm_label(leg_outcome)
    if not want:
        return None
    w = norm_label(winner)
    if w:
        if w == want:
            return True
        binary = lambda s: s in ("YES", "NO")  # noqa: E731
        if binary(w) != binary(want):
            return None
        return False
    return None


def load_truth():
    """conditionId -> winning label, from the venue archive caches. Never fetched here."""
    out = {}
    if os.path.exists(TRUTH):
        with open(TRUTH) as f:
            j = json.load(f)
        for cid, m in (j.get("markets") or {}).items():
            win = None
            for tok in m.get("tokens") or []:
                try:
                    name, won = tok[0], tok[1]
                except Exception:
                    continue
                if won:
                    win = name
            if win is not None:
                out[cid] = win
    if os.path.isdir(FUNNEL_CACHE):
        for fn in os.listdir(FUNNEL_CACHE):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(FUNNEL_CACHE, fn)) as f:
                    j = json.load(f)
            except Exception:
                continue
            if isinstance(j, dict) and j.get("winner"):
                out.setdefault(fn[:-5], j["winner"])
    return out


def load_review_labels():
    """paperTradeId -> OutcomeReview.finalOutcome. The DB-resident market-outcome label.

    PREFERRED over the archive cache: it covers the resolver's whole corpus, including markets the
    2026-11-15 archive snapshot never saw. It is still a VENUE-ORIGIN label (the resolver reads the
    venue's winning token), and `outcome_win()` applies the same didOutcomeWin guard to it, so a
    named-outcome market our YES/NO label cannot name comes back None instead of a guess.
    """
    c = _con()
    out = {r["paperTradeId"]: r["finalOutcome"] for r in c.execute(
        "SELECT paperTradeId, finalOutcome FROM OutcomeReview WHERE paperTradeId IS NOT NULL")}
    c.close()
    return out


# ------------------------------------------------------------------ fit + sizing

def fit(prices, ys, warm=LAMBDA_POLYMARKET):
    mle = WangMLE()
    r = mle.fit(prices=list(prices), outcomes=list(ys), initial_beta=[warm])
    se = r.se_robust[0] if r.se_robust else float("nan")
    return r.lambda_hat, se, r.n_obs


def fair_q(p, lam):
    """q = Phi(Phi^-1(p) - lambda) — the consumer in src/lib/kelly.ts."""
    return ND.cdf(ND.inv_cdf(p) - lam)


def kelly_size(p, lam, avail, knobs, base_size=None):
    """Re-implementation of kellySizeForCopy + applyKellyBandRails on the LIVE knobs."""
    if not (p > 0 and p < 1):
        return {"size": 0.0, "q": None, "fstar": 0.0, "skip": "price out of range"}
    if p <= 0.005 or p >= 0.995:
        return {"size": 0.0, "q": None, "fstar": 0.0, "skip": "extreme price"}
    if not avail > 0:
        return {"size": 0.0, "q": None, "fstar": 0.0, "skip": "no bankroll"}
    q = fair_q(p, lam)
    f = (q - p) / (1 - p)
    if f <= 0:
        return {"size": 0.0, "q": q, "fstar": 0.0, "skip": "no edge (q<=p)"}
    if f < knobs["minEdgePct"]:
        return {"size": 0.0, "q": q, "fstar": f, "skip": "edge < minEdgePct"}
    size = min(f * knobs["fraction"] * avail, knobs["maxBankrollPct"] * avail, knobs["maxSizeUsd"])
    if size < knobs["minBetUsd"]:
        return {"size": 0.0, "q": q, "fstar": f, "skip": "below minBetUsd"}
    railed = size
    if base_size is not None:
        # mapBankroll200Size band map (v54/v67 fields) then applyKellyBandRails:
        #   [0.20, 0.60) -> MIN(kelly, legacyEquiv)   (v57-B dead-zone/mid-band cap)
        #   < 0.20       -> MAX(kelly, legacyEquiv)   (long-shot floor)
        pct = (base_size - 0.25) / (20.0 - 0.25)
        leg = 0.2 + pct * (20.0 - 0.2)
        if p < 0.20:
            if p >= knobs.get("longshotFloor", 0.0):
                leg *= knobs.get("longshotFactor", 1.0)
            railed = max(size, leg)
        elif p < 0.60:
            if p >= 0.40:
                leg *= knobs.get("deadZoneFactor", 1.0)
            railed = min(size, leg)
    return {"size": round(railed, 2), "q": q, "fstar": f, "skip": None, "raw": round(size, 2)}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    ph = k / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    m = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5)
    return (ph, (c - m) / d, (c + m) / d)


def boot_lambda(legs, price_key, label_key, reps=400, seed=13):
    by = {}
    for l in legs:
        by.setdefault(l["marketId"], []).append(l)
    keys = list(by)
    if len(keys) < 8:
        return (None, None)
    rnd = random.Random(seed)
    xs = []
    for _ in range(reps):
        samp = []
        for _k in range(len(keys)):
            samp.extend(by[keys[rnd.randrange(len(keys))]])
        ps = [price_key(l) for l in samp if label_key(l) is not None]
        ys = [label_key(l) for l in samp if label_key(l) is not None]
        if len(ps) < 15 or len(set(ys)) < 2:
            continue
        try:
            lam, _se, _n = fit(ps, ys)
        except Exception:
            continue
        if lam == lam:
            xs.append(lam)
    if len(xs) < 50:
        return (None, None)
    xs.sort()
    return (xs[int(0.025 * len(xs))], xs[int(0.975 * len(xs)) - 1])


def live_knobs():
    c = _con()
    row = c.execute("SELECT version, rulesJson FROM RuleSet WHERE active=1").fetchone()
    d = json.loads(row["rulesJson"])
    cash = c.execute("SELECT cashBalance FROM BotBankroll WHERE botId='BANKROLL_200'").fetchone()[0]
    c.close()
    return {
        "version": row["version"],
        "fraction": d["kellyFraction"],
        "maxBankrollPct": d["kellyMaxBankrollPct"],
        "maxSizeUsd": d["kellyMaxSizeUsd"],
        "minBetUsd": d["kellyMinBetUsd"],
        "minEdgePct": d["kellyMinEdgePct"],
        "longshotFactor": d["c200LongshotBandFactor"],
        "longshotFloor": d["c200LongshotBandFloor"],
        "deadZoneFactor": d["c200DeadZoneBandFactor"],
        "avail": cash,
    }


def band_of(p):
    for (lo, hi), nm in zip(BANDS, NAMES):
        if p is not None and lo <= p < hi:
            return nm
    return None


def cap_threshold_lambda(knobs, p, base_size=None):
    """The least-negative lambda that still funds the full per-position cap at price p.

    size = min(fraction*f*avail, pct*avail, maxSize). The cap binds while
    fraction*f*avail >= maxSize, i.e. f >= maxSize/(fraction*avail); solve for lambda.
    """
    need_f = knobs["maxSizeUsd"] / (knobs["fraction"] * knobs["avail"])
    if need_f >= 1.0:
        return None
    need_q = p + need_f * (1 - p)
    if not (0 < need_q < 1):
        return None
    return ND.inv_cdf(p) - ND.inv_cdf(need_q)


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--min-rule", type=int, default=68)
    ap.add_argument("--window", type=int, default=3600)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--bootstrap", type=int, default=400)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    ppi = _mod("ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
    ft = _mod("ft", os.path.join(HERE, "profit-fill-tape.py"))

    knobs = live_knobs()
    cal = json.load(open(CAL))
    live = {round(b["lo"], 2): b["lambda"] for b in cal["bands"]}
    truth = load_truth()
    rev = load_review_labels()

    print("=" * 104)
    print("LAMBDA ON THE OWNED POPULATION — the cheap band's sizing input, refitted on the legs we own")
    print("=" * 104)
    print(f"\n  live table : data/premium-calibration.json  calibratedAt={cal['calibratedAt']}")
    print(f"  live knobs : RuleSet v{knobs['version']}  kellyFraction={knobs['fraction']}"
          f"  maxSize=${knobs['maxSizeUsd']:.0f}  maxBankrollPct={knobs['maxBankrollPct']}"
          f"  minEdgePct={knobs['minEdgePct']}  longshotFactor={knobs['longshotFactor']}x")
    print(f"  bankroll   : BotBankroll.cashBalance = ${knobs['avail']:,.2f} (Kelly `availableBankroll`)")
    print(f"  truth cache: {len(truth):,} conditionIds carrying a winning label (venue archive)")

    # ---------------------------------------------------------------- populations
    legs = ppi.dedupe(ppi.load_legs())
    legs = [l for l in legs if l["botId"] == "BANKROLL_200"]
    c = _con()
    cond = {r["id"]: r["conditionId"] for r in c.execute(
        "SELECT p.id AS id, o.conditionId AS conditionId FROM PaperTrade p "
        "JOIN DecisionJournal d ON d.id = p.decisionJournalId "
        "LEFT JOIN ObservedTrade o ON o.id = d.observedTradeId")}
    # A1 must be byte-identical to the live script: raw rows, venue Polymarket, no dedupe.
    raw = c.execute(
        "SELECT entryPrice, realizedPnl FROM PaperTrade WHERE botId='BANKROLL_200'"
        " AND status IN ('resolved','closed') AND realizedPnl IS NOT NULL AND isDemo=0"
        " AND venue='Polymarket'").fetchall()
    c.close()

    for l in legs:
        l["cid"] = cond.get(l["id"])
        w_arch = truth.get(l["cid"]) if l["cid"] else None
        w_rev = rev.get(l["id"])
        l["win_arch"] = outcome_win(l["outcome"], w_arch) if w_arch else None
        l["win_rev"] = outcome_win(l["outcome"], w_rev) if w_rev else None
        l["win"] = l["win_rev"] if l["win_rev"] is not None else l["win_arch"]
        l["pnl_lab"] = 1 if (l.get("realizedPnl") or 0) > 0 else 0
        l["band"] = band_of(l["entryPrice"])

    # label-source validation: where BOTH sources speak, do they agree?
    both = [l for l in legs if l["win_rev"] is not None and l["win_arch"] is not None]
    agree = sum(1 for l in both if l["win_rev"] == l["win_arch"])
    print(f"\n  label sources: OutcomeReview.finalOutcome on {sum(1 for l in legs if l['win_rev'] is not None):,}"
          f"  venue archive on {sum(1 for l in legs if l['win_arch'] is not None):,}"
          f"  agreement where both speak: {agree}/{len(both)}"
          + (f" ({100 * agree / len(both):.1f}%)" if both else ""))

    book = [l for l in legs if l["status"] != "open"]
    regime = [l for l in book if (l.get("rv") or 0) >= a.min_rule
              and (l.get("openedTs") or 0) >= ppi._ms(a.since)]
    print(f"\n  A1 raw rows (live script's exact query)      : {len(raw):,}")
    print(f"  book population (B200, deduped, settled)     : {len(book):,}"
          f"   with a venue winning label: {sum(1 for l in book if l['win'] is not None):,}")
    print(f"  regime subset (rv>={a.min_rule}, opened>={a.since}) : {len(regime):,}")

    # ---------------------------------------------------------------- A1
    print("\n" + "-" * 104)
    print("A1. REPRODUCTION — the fit exactly as `calibrate-premium.py` runs it today")
    print("-" * 104)
    print(f"  {'band':<11}{'n':>6}{'win%(pnl>0)':>13}{'lambda':>10}{'live':>10}{'delta':>10}")
    for (lo, hi), nm in zip(BANDS, NAMES):
        sel = [(p, 1 if pnl > 0 else 0) for p, pnl in raw if p is not None and lo <= p < hi]
        if len(sel) < 20:
            print(f"  {nm:<11}{len(sel):>6}   n<20 — the live script sets lambda=0 (neutral)")
            continue
        lam, _se, _n = fit([s[0] for s in sel], [s[1] for s in sel])
        print(f"  {nm:<11}{len(sel):>6}{100 * sum(s[1] for s in sel) / len(sel):>12.1f}%"
              f"{lam:>+10.4f}{live.get(round(lo, 2), 0.0):>+10.4f}{lam - live.get(round(lo, 2), 0.0):>+10.4f}")
    print("  (delta = today's data vs the 2026-11-15 table: it moves with five days of new settlements,")
    print("   so a few hundredths is expected. A LARGE delta means the population drifted.)")

    # ---------------------------------------------------------------- tape ownership
    print("\n" + "-" * 104)
    print("A2. OWNERSHIP — the regime book adjudicated against the venue minute tape (cached)")
    print("-" * 104)
    rl = [l for l in regime if l["cid"]]
    ft.classify(rl, workers=a.workers)
    for l in rl:
        l["tv"] = ft.verdict_at(l, a.window)
    owned_r = [l for l in rl if l.get("tv") == "filled_tape"]
    cov = {}
    for l in rl:
        cov[l["tv"]] = cov.get(l["tv"], 0) + 1
    for k in sorted(cov, key=lambda x: -cov[x]):
        print(f"    {k:<16}{cov[k]:>5}")
    print(f"  positively owned (filled_tape): {len(owned_r):,} of {len(rl):,}"
          f" ({100 * len(owned_r) / max(1, len(rl)):.1f}%)")
    print(f"  owned AND carrying a venue winning label: {sum(1 for l in owned_r if l['win'] is not None):,}"
          f"  <- the outcome label needs a RESOLVED market; early exits do not have one")

    # ---------------------------------------------------------------- four arms
    print("\n" + "-" * 104)
    print("A3. THE FOUR ARMS — same bands, four population/label conventions")
    print("-" * 104)
    print(f"  {'band':<11}" + "".join(f"{h:>23}" for h in
                                     ("A2 book / outcome", "A3 OWNED / outcome", "A4 OWNED / pnl>0")))
    print(f"  {'':<11}" + "".join(f"{'n':>5}{'win%':>7}{'lambda':>11}" for _ in range(3)))
    arms = {}
    for (lo, hi), nm in zip(BANDS, NAMES):
        cells = []
        for pop, key_price in ((book, "entryPrice"), (owned_r, "trueP"), (owned_r, "trueP")):
            lab = "win" if len(cells) < 2 else "pnl_lab"
            sel = [l for l in pop if lo <= (l.get(key_price) or 0) < hi and l.get(lab) is not None]
            if len(sel) >= 20 and len({l[lab] for l in sel}) > 1:
                lam, se, n = fit([l[key_price] for l in sel], [l[lab] for l in sel])
                cells.append((n, sum(l[lab] for l in sel) / n, lam, se))
            else:
                cells.append((len(sel), None, None, None))
        arms[nm] = cells
        line = f"  {nm:<11}"
        for n, wr, lam, _se in cells:
            line += f"{n:>5}" + (f"{100 * wr:>6.1f}%" if wr is not None else f"{'—':>7}")
            line += (f"{lam:>+11.3f}" if lam is not None else f"{'—':>11}")
        print(line)
    print("  (n counts LABELLED legs only; the label's coverage limit is printed in A2. A cell under 20")
    print("   labelled legs is not fitted — an unlabelled population is not a measurement.)")

    # ---------------------------------------------------------------- cheap band
    print("\n" + "-" * 104)
    print("A4. THE CHEAP BAND IN DETAIL — which label does the card's 13.0% (7/54) actually carry?")
    print("-" * 104)
    lo, hi = BANDS[0]
    cheap_regime = [l for l in regime if lo <= (l.get("trueP") or 0) < hi]
    cheap_owned = [l for l in owned_r if lo <= (l.get("trueP") or 0) < hi]
    te = _mod("te", os.path.join(HERE, "profit-taker-entry.py"))
    for l in cheap_owned:
        l["exit_px"] = te.exit_of(l)
    print(f"  regime C-200 cheap legs: {len(cheap_regime)}   tape-owned: {len(cheap_owned)}")
    masked = sum(1 for l in cheap_owned
                 if l.get("fillStatus") == "unfilled" and (l.get("realizedPnl") or 0.0) == 0.0)
    k_booked = sum(1 for l in cheap_owned if l["pnl_lab"])
    k_exit = sum(1 for l in cheap_owned if (te.pnl_at(l, l["trueP"]) or 0) > 0)
    k_out = sum(1 for l in cheap_owned if l["win"] is not None and l["win"])
    n_out = sum(1 for l in cheap_owned if l["win"] is not None)
    ph, wlo, whi = wilson(k_booked, len(cheap_owned))
    print(f"  three ways to score the SAME {len(cheap_owned)} owned cheap legs:")
    print(f"    booked PnL sign (realizedPnl>0)      : {k_booked}/{len(cheap_owned)} ="
          f" {100 * k_booked / max(1, len(cheap_owned)):.1f}%  <- {masked} legs are booked at ZERO PnL"
          f" by the unfilled-stamp convention, so this understates the arm")
    print(f"    reconstructed exit sign (pnl_at)     : {k_exit}/{len(cheap_owned)} ="
          f" {100 * k_exit / max(1, len(cheap_owned)):.1f}%  <- this is the card's 13.0% (7/54) family")
    if n_out:
        q2, qlo, qhi = wilson(k_out, n_out)
        print(f"    market outcome (venue winner)        : {k_out}/{n_out} ="
              f" {100 * q2:.1f}%   Wilson 95% [{100 * qlo:.1f}%, {100 * qhi:.1f}%]"
              f"  <- the probability target; {len(cheap_owned) - n_out} owned legs have no resolved market")
        print("    -> the outcome-labelled owned sample is the only one that can carry a lambda_hat, and")
        print(f"       it is {n_out} legs wide. A rate over {len(cheap_owned)} legs with a proxy label is not a")
        print("       probability and must not be compared to q.")
    cheap_book = [l for l in book if lo <= l["entryPrice"] < hi and l["win"] is not None]
    if cheap_book:
        lam_b, se_b, n_b = fit([l["entryPrice"] for l in cheap_book], [l["win"] for l in cheap_book])
        blo, bhi = boot_lambda(cheap_book, lambda l: l["entryPrice"], lambda l: l["win"],
                               reps=a.bootstrap)
        kh = sum(l["win"] for l in cheap_book)
        mh, mlo, mhi = wilson(kh, n_b)
        med_p = sorted(l["entryPrice"] for l in cheap_book)[n_b // 2]
        print(f"\n  BOOK x market outcome (the arm with power): n={n_b}  hit {100 * mh:.1f}%"
              f"  Wilson 95% [{100 * mlo:.1f}%, {100 * mhi:.1f}%]")
        print(f"    lambda = {lam_b:+.4f} (se {se_b:.4f})"
              + (f"   market-clustered 95% CI [{blo:+.3f}, {bhi:+.3f}]" if blo is not None else ""))
        print(f"    at the band's median booked price {med_p:.3f}: q={fair_q(med_p, lam_b):.3f}"
              f"   (live lambda {live[0.0]:+.4f} -> q={fair_q(med_p, live[0.0]):.3f})")
        zeros = sum(1 for l in book if lo <= l["entryPrice"] < hi and l["win"] is None)
        print(f"    {zeros} further book legs in this band are unlabelled (market not resolved / named")
        print("    outcome our YES-NO label cannot name) — a coverage bias, not a random exclusion.")

    # ---------------------------------------------------------------- owned arm with intervals
    print("\n" + "-" * 104)
    print("A4b. THE OWNED ARM WITH INTERVALS — the numbers a rule would actually read")
    print("-" * 104)
    print(f"  {'band':<11}{'owned n':>8}{'hit':>7}{'wilson 95%':>18}{'lambda':>10}{'se':>7}{'clustered 95%':>18}")
    owned_fits = {}
    for (lo_, hi_), nm in zip(BANDS, NAMES):
        sel = [l for l in owned_r if lo_ <= (l.get("trueP") or 0) < hi_ and l["win"] is not None]
        if len(sel) < 20 or len({l["win"] for l in sel}) < 2:
            print(f"  {nm:<11}{len(sel):>8}   — not fittable (needs >=20 labelled legs)")
            continue
        lam, se, n = fit([l["trueP"] for l in sel], [l["win"] for l in sel])
        owned_fits[nm] = (lam, se, n)
        k = sum(l["win"] for l in sel)
        _ph, wlo, whi = wilson(k, n)
        blo, bhi = boot_lambda(sel, lambda l: l["trueP"], lambda l: l["win"], reps=a.bootstrap)
        print(f"  {nm:<11}{n:>8}{100 * k / n:>6.1f}%"
              f"{f'[{100 * wlo:.0f}%,{100 * whi:.0f}%]':>18}{lam:>+10.3f}{se:>7.3f}"
              f"{(f'[{blo:+.3f},{bhi:+.3f}]' if blo is not None else '—'):>18}")
    print("  own x outcome is the arm the card names; its width is the answer's precision.")

    # ---------------------------------------------------------------- sizing
    print("\n" + "-" * 104)
    print("A5. WHAT EACH LAMBDA BUYS — the clip under the LIVE knobs, at several paid prices")
    print("-" * 104)
    base = None
    cheap_book_all = [l for l in book if lo <= l["entryPrice"] < hi]
    if cheap_book_all:
        base = sorted(l["simulatedPositionSize"] for l in cheap_book_all)[len(cheap_book_all) // 2]
    sizes = sorted(l["simulatedPositionSize"] for l in cheap_owned) if cheap_owned else []
    if sizes:
        print(f"  owned cheap clips: median ${sizes[len(sizes) // 2]:.0f}"
              f"  min ${sizes[0]:.0f}  max ${sizes[-1]:.0f}")
        print(f"  share of owned cheap clips at the ${knobs['maxSizeUsd']:.0f} cap:"
              f" {100 * sum(1 for s in sizes if s >= knobs['maxSizeUsd'] - 0.01) / len(sizes):.0f}%")
    print(f"  median standard-scale base size in the band: ${base:.2f}" if base else "")
    cand = [(live[0.0], "LIVE table")]
    for nm in NAMES:
        c2 = arms.get(nm) or []
        if len(c2) > 1 and c2[1][2] is not None:
            cand.append((c2[1][2], f"A3 owned/outcome ({nm})"))
    cheap_book_arm = None
    if cheap_book:
        cheap_book_arm = fit([l["entryPrice"] for l in cheap_book], [l["win"] for l in cheap_book])[0]
        cand.append((cheap_book_arm, "A2 book/outcome (cheap)"))
    print(f"\n  prices probed: {', '.join(f'{p:.3f}' for p in (0.05, 0.104, 0.135, 0.19))}")
    for p in (0.05, 0.104, 0.135, 0.19):
        thr = cap_threshold_lambda(knobs, p)
        print(f"\n    p={p:.3f}   the ${knobs['maxSizeUsd']:.0f} cap binds for any lambda <= {thr:+.3f}")
        print(f"    {'lambda':>9}{'q':>8}{'f*':>9}{'kelly$':>9}{'railed$':>9}  basis")
        for lam, why in cand:
            r = kelly_size(p, lam, knobs["avail"], knobs, base_size=base)
            q = r["q"]
            print(f"    {lam:>+9.3f}{(q if q is not None else float('nan')):>8.3f}"
                  f"{r['fstar']:>9.4f}{(r.get('raw', r['size'])):>9.2f}{r['size']:>9.2f}  {why}"
                  + (f"  [{r['skip']}]" if r["skip"] else ""))
    print("\n  -> the clip is min(fraction*f*avail, pct*avail, cap). At avail ="
          f" ${knobs['avail']:,.0f} the")
    print("     cap binds across the whole plausible lambda range, and applyKellyBandRails then")
    print("     FLOORS the cheap band at the legacy-equivalent size. A lambda refit alone cannot")
    print("     shrink this clip; only a lambda that reaches 'no edge' (a skip) or a cap/knob change can.")

    # ---------------------------------------------------------------- swap diff
    print("\n" + "-" * 104)
    print("A6. IF THE LIVE TABLE WERE REPLACED BY THE OUTCOME-CONVENTION TABLE — what each band would do")
    print("-" * 104)
    print("  (band median BOOKED price, live RuleSet knobs; 'live' = today's table, 'A2' = book x venue")
    print("   outcome. This is the blast radius of the label change, not just the cheap band.)")
    print(f"  {'band':<11}{'med p':>7}{'live lam':>10}{'q':>7}{'size':>8}   ->{'A2 lam':>9}{'q':>7}{'size':>8}  read")
    for (lo, hi), nm in zip(BANDS, NAMES):
        ls = [l for l in book if lo <= l["entryPrice"] < hi]
        labelled = [l for l in book if lo <= l["entryPrice"] < hi and l["win"] is not None]
        if not ls:
            continue
        ps = sorted(l["entryPrice"] for l in ls)
        med = ps[len(ps) // 2]
        lr = kelly_size(med, live.get(round(lo, 2), 0.0), knobs["avail"], knobs, base_size=base)
        if len(labelled) < 20:
            print(f"  {nm:<11}{med:>7.3f}{live.get(round(lo, 2), 0.0):>+10.3f}{(lr['q'] or 0):>7.3f}"
                  f"{lr['size']:>8.2f}   ->   (n={len(labelled)} labelled: not fittable)")
            continue
        lam2 = fit([l["entryPrice"] for l in labelled], [l["win"] for l in labelled])[0]
        r2 = kelly_size(med, lam2, knobs["avail"], knobs, base_size=base)
        read = "no change"
        if lr["size"] == 0 and r2.get("raw", 0) > 0:
            read = "BAND RE-ADMITTED"
        elif lr["size"] > 0 and r2["size"] == 0:
            read = "band would SKIP"
        elif abs(r2["size"] - lr["size"]) > 1.0:
            read = "size moves"
        print(f"  {nm:<11}{med:>7.3f}{live.get(round(lo, 2), 0.0):>+10.3f}{(lr['q'] or 0):>7.3f}"
              f"{lr['size']:>8.2f}   ->{lam2:>+9.3f}{(r2['q'] or 0):>7.3f}{r2['size']:>8.2f}  {read}")
    print("\n  -> a convention swap is NOT cheap-band-local. Its largest effect is on the bands the")
    print("     current table's POSITIVE lambda is keeping out of the book.")

    # ---------------------------------------------------------------- stability
    print("\n" + "-" * 104)
    print("A7. STABILITY — is the cheap band's corrected lambda a level, or a drift?")
    print("-" * 104)
    lo, hi = BANDS[0]  # A6's loop leaks its last band into the names above — reset explicitly
    if cheap_book:
        ts = sorted((l.get("openedTs") or 0) for l in cheap_book)
        mid = ts[len(ts) // 2]
        import datetime as _dt
        halves = [("first half", [l for l in cheap_book if (l.get("openedTs") or 0) < mid]),
                  ("second half", [l for l in cheap_book if (l.get("openedTs") or 0) >= mid])]
        print(f"  split at {_dt.datetime.utcfromtimestamp(mid / 1000):%Y-%m-%d %H:%M} UTC (median decision time)")
        print(f"  {'half':<13}{'n':>5}{'hit':>7}{'lambda':>10}{'median t':>13}")
        for tag, sub in halves:
            if len(sub) < 30 or len({l["win"] for l in sub}) < 2:
                print(f"  {tag:<13}{len(sub):>5}   —        —   (too thin to fit)")
                continue
            lam, _se, n = fit([l["entryPrice"] for l in sub], [l["win"] for l in sub])
            t = sorted(l["openedTs"] for l in sub)[len(sub) // 2]
            print(f"  {tag:<13}{n:>5}{100 * sum(l['win'] for l in sub) / n:>6.1f}%{lam:>+10.3f}"
                  f"  {_dt.datetime.utcfromtimestamp(t / 1000):%Y-%m-%d}")
        # price basis: paid price instead of the booked mid, on the same arms
        sub = [l for l in book if lo <= l["entryPrice"] < hi and l["win"] is not None
               and l.get("trueP")]
        if len(sub) >= 30:
            lam_t = fit([l["trueP"] for l in sub], [l["win"] for l in sub])[0]
            print(f"  price basis  : booked entry -> {lam_b:+.3f}   paid price (trueP) -> {lam_t:+.3f}"
                  f"  on the same n={len(sub)}")

    # ---------------------------------------------------------------- verdict
    print("\n" + "-" * 104)
    print("A8. VERDICT AGAINST THE CARD'S DECISION RULE")
    print("-" * 104)
    print("  rule (card R3): owned cheap lambda >= -0.20 -> the Kelly input over-bets, re-derive size")
    a3 = arms.get(NAMES[0], [None] * 3)[1]
    if a3 and a3[2] is not None:
        print(f"  measured A3 (private): lambda = {a3[2]:+.4f} on {a3[0]} legs"
              f" -> {'PASSES' if a3[2] >= -0.20 else 'FAILS'} the rule")
    else:
        print(f"  measured A3 (private): n={a3[0] if a3 else 0} labelled owned cheap legs"
              " -> UNTESTABLE at this sample")
    if cheap_book:
        print(f"  but the arm with power (A2 book/outcome, n={n_b}): lambda = {cheap_book_arm:+.4f}"
              f" -> {'PASSES' if cheap_book_arm >= -0.20 else 'FAILS'} the rule")
    print("\n  READ-ONLY: nothing written. The proposed table lives in the draft, not in data/.")


def selftest():
    """Prove the instrument can fail: a known-lambda synthetic sample must recover it."""
    ok = True
    rnd = random.Random(3)
    for true_lam in (-0.53, -0.10, 0.20):
        ps, ys = [], []
        for _ in range(3000):
            p = rnd.uniform(0.05, 0.19)
            q = ND.cdf(ND.inv_cdf(p) - true_lam)  # outcome prob = Phi(Phi^-1(p_mkt) - lam)
            ys.append(1 if rnd.random() < q else 0)
            ps.append(p)
        lam, se, n = fit(ps, ys)
        good = abs(lam - true_lam) < 0.07 and n == 3000
        ok &= bool(good)
        print(f"  [{'PASS' if good else 'FAIL'}] synthetic lambda={true_lam:+.2f} -> {lam:+.4f}"
              f" (se {se:.3f}, n={n})")
    knobs = {"fraction": 0.5, "maxBankrollPct": 0.1, "maxSizeUsd": 100, "minBetUsd": 2,
             "minEdgePct": 0.02, "longshotFactor": 3.5, "longshotFloor": 0.05, "avail": 6721.88}
    r0 = kelly_size(0.135, 0.0, 6721.88, knobs, base_size=10.0)
    r1 = kelly_size(0.135, -0.53, 6721.88, knobs, base_size=10.0)
    r2 = kelly_size(0.135, -0.20, 6721.88, knobs, base_size=10.0)
    g0 = r0["size"] == 0.0 and r0["skip"] is not None
    g1 = r1["size"] == 100.0
    g2 = r2["size"] == 100.0  # the cap binds even at the rule's own threshold
    thr = cap_threshold_lambda(knobs, 0.135)
    g3 = -0.12 < thr < -0.10
    for g, msg in ((g0, "lambda=0.00 at 13.5c -> 0 (skip: no edge)"),
                   (g1, "lambda=-0.53 at 13.5c -> $100 (saturates the cap)"),
                   (g2, "lambda=-0.20 at 13.5c -> $100 (the cap still binds)"),
                   (g3, f"cap threshold at 13.5c = {thr:+.3f} (expected ~-0.11)")):
        ok &= bool(g)
        print(f"  [{'PASS' if g else 'FAIL'}] {msg}")
    print(f"  SELFTEST {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
