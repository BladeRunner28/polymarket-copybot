# Phase Astro-1 — Astrological Sentiment Shadow Feed (SPEC)

**Status:** SHIPPED in shadow mode — 2026-08-31. **Gate:** measurement before any promotion (D-tier cap applies).
**Origin:** human recommendation to add an astrological sentiment feed. This spec settles the question empirically.

---

## 1. Position

Astrology has **no causal mechanism** for market movement. The only defensible channel is
*behavioral*: if a meaningful slice of retail traders acts on astrological belief, their flows
can move short-TTR prediction-market prices short-term. The feed therefore models
**belief-crowd sentiment**, not celestial truth — the same family as whale-flow following,
but a much weaker cousin.

**Prior: low probability of durable edge (~10% or less).** The published evidence base is
essentially empty (weak, contested lunar-return findings; the Mercury-retrograde literature
found a *behavioral volatility* effect, not directional prediction).

## 2. Design principles

1. **Shadow-only** — the feed never touches the live pipeline. It logs to
   `data/astro-shadow.jsonl`; promotion requires the comparison to demonstrate signal.
2. **Deterministic & keyless** — real JPL ephemeris (DE440s via skyfield), no API keys,
   no scraping. Fully reproducible/backfillable.
3. **Tiny magnitudes, D-tier cap** — scores are clamped to [-0.3, +0.3]; if ever promoted it
   enters the Bayesian evidence aggregation as a D-tier source (0.2 cap), so even a
   misbehaving feed cannot move a decision materially.
4. **Measurement-first** — the comparison joins astro windows against the actual paper book
   (`PaperTrade` realized PnL), not against vibes.

## 3. Data source & signals

`~/political-research-bot/src/astro_shadow.py` (Python 3.9, skyfield 1.55, ephemeris cached
in `~/.skyfield/de440s.bsp` — note: the downloaded kernel exposes only barycenters for
outer planets; the script falls back to `name barycenter` automatically, which is
astronomically negligible for zodiac longitude).

| Signal | Weight | Basis |
|---|---|---|
| mercury retrograde | −0.15 | tradition: comms/contracts/trade disruption |
| mars retrograde | −0.10 | tradition: action/energy disruption |
| venus/jupiter/saturn retrograde | −0.05 each | soft caution |
| new moon window (±1 d) | +0.10 | 'beginnings' optimism; weak lunar-effect lit. |
| full moon window (±1 d) | −0.10 | culmination/volatility caution |
| solar eclipse window | −0.10 | disruption (geometric proxy: new moon within 1.5° of ecliptic) |
| lunar eclipse window | −0.05 | soft caution (proxy: full moon within 1.5° of ecliptic) |
| sun sign ingress | 0.00 | logged only, no score |

Composite = sum, clamped to [−0.3, +0.3]. `confidence: 0.2` fixed (low).

**Verified against real 2026 events:** total solar eclipse Aug 12 ✓, partial lunar eclipse
Aug 28 ✓, Mercury retrograde early July ✓, Saturn retrograde (Mar–Aug) ✓, full moon Aug 28 ✓.

## 4. Logging & backfill

```bash
cd ~/political-research-bot
venv/bin/python src/astro_shadow.py                 # append row for now (idempotent per day)
venv/bin/python src/astro_shadow.py --backfill 60   # deterministic daily backfill, idempotent
```

Row: `{ts, day, source: "astro", version, confidence: 0.2, retrogrades, moonPhase,
moonPhaseDeg, sunSign, events, score, components, ephemeris}`.

61 rows backfilled (2026-07-02 → 08-31), covering the full paper-trading history.

## 5. Comparison — `~/polymarket-copybot/scripts/compare-astro.py`

Joins daily astro scores against daily realized PnL from `PaperTrade` (closed trades →
`closedAt`, resolved trades → `resolvedAt`; read-only SQLite) and reports:

- daily score vs PnL Pearson correlation + sign agreement + correlation t-statistic
- retrograde vs non-retrograde days (Welch t)
- new/full-moon windows vs other days
- eclipse windows vs other days
- verdict: promotion decision gate (|t| ≥ 2 required for "notable")

## 6. First results (n=47 days, Jul 14 → Aug 31 — full paper history)

| Test | Result |
|---|---|
| corr(astro score, daily PnL) | **−0.168, \|t\| = 1.1 → NOT significant** (p ≈ 0.27) |
| sign agreement | 47.7% — coin flip |
| new/full moon days (14) vs other (33) | mean −$61.6 vs +$253.6, t = −0.97 → not significant; direction matches the caution tilt but within noise |
| retrograde vs non-retrograde | **degenerate: 44 of 47 days retrograde** (Saturn station covers nearly the whole window) — structurally weak discriminator over this span; only Mercury's shorter retrogrades add contrast |
| eclipse windows (8 days) | insufficient for a bucket test yet (need ≥10); directionally neutral |

**Verdict: NO SIGNIFICANT SIGNAL — do not promote.** The feed stays in shadow; the daily
logger (if scheduled) keeps accumulating so the test strengthens over time.

## 7. Promotion criteria (if ever)

1. |t| ≥ 2 on the daily correlation AND a replication window (e.g., the next 4–6 weeks
   independently) showing the same sign.
2. A window-effect (moon/eclipse/retrograde bucket) with |t| ≥ 2 that survives removal of
   outlier days (median checks).
3. Promotion is **D-tier only** (0.2 cap) — never above the RegulatorySignal B/C tiers.
4. Revertible by flag, consistent with the sentiment-evidence pattern.

## 8. Non-goals & honesty notes

- **No causal claim.** If it ever works, it works because traders *believe*, not because
  planets move prices.
- Eclipse flags are a geometric proxy (eclipse-season alignment), not precise umbra
  prediction — acceptable at D-tier magnitude.
- One structural caveat: daily *realized* PnL is noisy and regime-dependent (the paper book
  switched rule regimes v36→v38 mid-window); the negative correlation is likely regime
  drift, not astro flow. Longer accumulation + per-ruleset segmentation would be needed
  before any real conclusion.

## 9. Files

- `~/political-research-bot/src/astro_shadow.py` — logger (skyfield DE440s, moon-phase
  fallback if skyfield missing)
- `~/polymarket-copybot/scripts/compare-astro.py` — comparison + verdict
- `~/polymarket-copybot/data/astro-shadow.jsonl` — accumulated rows
- `~/polymarket-copybot/data/astro-shadow-summary.json` — latest summary
- `~/polymarket-copybot/drafts/astro-shadow-feed.md` — this spec
