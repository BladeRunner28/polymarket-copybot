#!/usr/bin/env python3
"""Calibrate the Wang Transform risk-premium table (Phase A) and publish it.

Refits per-entry-price-band lambda (lambda_hat) from resolved BANKROLL_200
paper trades using the vendored oracle3 WangMLE (Apache-2.0, Yang 2026), then
writes data/premium-calibration.json for the scorer overlay and posts a
summary to Discord.

Model: p_mkt = Phi(Phi^-1(p*) + lambda). Positive lambda = overpriced entries
(premium drag); negative = entries beat the market (info edge).

Usage (project root):
    ./venv-calib/bin/python scripts/calibrate-premium.py
"""
import json
import os
import sqlite3
import sys
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore", category=RuntimeWarning)  # robust-SE Hessian noise on extreme λ̂

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "vendor", "oracle3"))
from wang_mle import WangMLE, LAMBDA_POLYMARKET, LAMBDA_KALSHI  # noqa: E402

DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "premium-calibration.json")
ENV = os.path.join(ROOT, ".env")
MIN_BAND_N = 20

BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def finished_trades(bot="BANKROLL_200"):
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT entryPrice, realizedPnl, venue FROM PaperTrade
           WHERE botId=? AND status IN ('resolved','closed')
             AND realizedPnl IS NOT NULL AND isDemo=0""",
        (bot,),
    ).fetchall()
    con.close()
    return [(p, 1 if pnl > 0 else 0, v) for p, pnl, v in rows]


def fit(prices, outcomes, warm):
    mle = WangMLE()
    r = mle.fit(prices=prices, outcomes=outcomes, initial_beta=[warm])
    se = r.se_robust[0] if r.se_robust else float("nan")
    return r.lambda_hat, se, r.n_obs, sum(outcomes) / r.n_obs


def main():
    trades = finished_trades()
    poly = [(p, o) for p, o, v in trades if v == "Polymarket"]
    kalshi = [(p, o) for p, o, v in trades if v == "Kalshi"]

    # Venue offset: Kalshi lambda minus Polymarket pooled lambda (same traders).
    lam_poly_all, _, n_poly, _ = fit([p for p, _ in poly], [o for _, o in poly], LAMBDA_POLYMARKET)
    venue_offset_kalshi = 0.0
    if len(kalshi) >= MIN_BAND_N:
        lam_kalshi, _, _, _ = fit([p for p, _ in kalshi], [o for _, o in kalshi], LAMBDA_KALSHI)
        venue_offset_kalshi = lam_kalshi - lam_poly_all

    bands = []
    lines = []
    for lo, hi in BANDS:
        sel = [(p, o) for p, o in poly if lo <= p < hi]
        if len(sel) < MIN_BAND_N:
            bands.append({"lo": lo, "hi": hi, "lambda": 0.0, "n": len(sel)})
            lines.append(f"  entry {lo:.2f}–{hi:.2f}: N={len(sel)} < {MIN_BAND_N} — λ̂ set to 0 (neutral)")
            continue
        ps, os_ = zip(*sel)
        lam, se, n, wr = fit(list(ps), list(os_), LAMBDA_POLYMARKET)
        bands.append({"lo": lo, "hi": hi, "lambda": round(lam, 4), "n": n})
        z = lam / se if se else 0.0
        lines.append(
            f"  entry {lo:.2f}–{hi:.2f}: N={n:>4}  λ̂={lam:+.4f} ± {se:.4f}  (z={z:+.2f})  win%={wr*100:5.1f}"
        )

    cal = {
        "calibratedAt": datetime.now(timezone.utc).isoformat(),
        "source": "wang-mle (vendored oracle3, Apache-2.0)",
        "venueOffsetKalshi": round(venue_offset_kalshi, 4),
        "bands": bands,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(cal, f, indent=2)

    summary = (
        f"**🧮 C-200 Premium Calibration (Wang Transform)**\n"
        f"Refit {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC from {len(trades)} finished trades "
        f"(Poly N={n_poly}, Kalshi N={len(kalshi)}).\n"
        f"Model: p_mkt = Φ(Φ⁻¹(p*) + λ̂) — positive λ̂ = overpriced entries (premium drag).\n"
        f"Kalshi offset: {venue_offset_kalshi:+.3f}\n"
        + "\n".join(lines)
    )
    print(summary)

    # Discord delivery (same pattern as other stack scripts).
    try:
        with open(ENV) as f:
            env = {k.strip(): v.strip().strip('"') for k, v in (ln.split("=", 1) for ln in f if "=" in ln and not ln.strip().startswith("#"))}
        url = env.get("DISCORD_WEBHOOK_URL", "")
        if url:
            import urllib.request

            payload = json.dumps({"content": summary[:1990]}).encode()
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "content-type": "application/json",
                    "user-agent": "Medusa-CopyBot/1.0 (Hermes cron)",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"Discord HTTP {resp.status}")
    except Exception as e:  # noqa: BLE001
        print(f"Discord delivery failed (non-fatal): {e}")


if __name__ == "__main__":
    main()
