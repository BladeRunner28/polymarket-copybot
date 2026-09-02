import { readFileSync } from "fs";

/**
 * Phase A premium overlay (Wang Transform calibration, 2026-08-31).
 *
 * oracle3 / Yang (2026) pricing model: p_mkt = Φ(Φ⁻¹(p*) + λ). A positive λ̂
 * means entries are systematically OVERPRICED (premium drag); negative λ̂
 * means entries beat the market (info edge). The calibration table is refit
 * biweekly (1st & 15th) from resolved C-200 paper trades by
 * scripts/calibrate-premium.py into data/premium-calibration.json.
 *
 * Overlay semantics (measurement-first):
 *   - size factor = clamp(1 − k·λ̂, minFactor, maxFactor)
 *     λ̂=−1.20 (long-shot edge)  → 1 + 0.5·1.20 = 1.60× boost
 *     λ̂= 0.00 (dead zone)       → 1.00× unchanged
 *     λ̂=+0.35 (overpriced)      → 1 − 0.5·0.35 = 0.825× shrink
 *   - Every C-200 copy gets a `premium λ̂=…` risk tag (journaled, reportable).
 */

export interface PremiumBand {
  lo: number;
  hi: number;
  lambda: number;
  n: number;
}

export interface PremiumCalibration {
  calibratedAt: string;
  source: string;
  /** Kalshi entries carry an additive premium offset vs Polymarket. */
  venueOffsetKalshi: number;
  bands: PremiumBand[];
}

/** λ̂ for an entry price: first band whose [lo, hi) contains the price. */
export function getBandLambda(price: number, bands: PremiumBand[]): number {
  for (const b of bands) {
    if (price >= b.lo && price < b.hi) return b.lambda;
  }
  // Price above the last band's hi: use the top band's value.
  const last = bands[bands.length - 1];
  return last ? last.lambda : 0;
}

/** Overlay size factor: clamp(1 − k·λ̂, min, max). */
export function computePremiumFactor(
  lambda: number,
  k: number,
  minFactor: number,
  maxFactor: number
): number {
  const f = 1 - k * lambda;
  return Math.min(maxFactor, Math.max(minFactor, f));
}

/** Human-readable risk tag for the journal. */
export function premiumRiskTag(lambda: number, venue: string): string {
  const label =
    lambda <= -0.15 ? "info edge (underpriced)" : lambda >= 0.15 ? "overpriced entry (premium drag)" : "fair";
  return `premium λ̂=${lambda.toFixed(2)} ${label} (${venue})`;
}

/** Load the calibration table (missing/corrupt → null, overlay off). */
export function loadPremiumCalibration(path: string): PremiumCalibration | null {
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as PremiumCalibration;
    if (!Array.isArray(parsed.bands) || parsed.bands.length === 0) return null;
    return parsed;
  } catch {
    return null;
  }
}
