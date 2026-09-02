/**
 * apply:v37 — one-off activation of RuleSet v37 (2026-08-30 recommendations:
 * tuning review #10 + C-200 daily report 18:09). Versioned, audited path.
 *
 * Changes:
 *  - minCopyScore 70→80, NEW minConfidence 0.70        (report D2 quality gates)
 *  - NEW Kalshi gate + circuit breaker                  (report D1)
 *  - NEW entry-band sizing (dead zone ×0.5, long-shot ×1.5) (report D2)
 *  - maxOpenPositions 150→225, staleExitHours 48→24     (review R1 + report D3)
 *  - maxCopiesPerWalletPerDay 25→40                     (review R5)
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v37.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "minCopyScore" as const,
    newValue: 80,
    reason:
      "Raise minCopyScore 70→80: executed trades average 0.59 confidence / 75.4 copyScore — the 70 bar filters almost nothing; 80+ is the proven best bucket (30d +$0.57/trade)",
    evidence:
      "2026-08-30 18:09 report: 965 closed/resolved, 51.5% WR, −$138 realized, −$0.18/trade EV; avg executed conf 0.59 / score 75.4; bucket data: 80+ +$0.57/trade (256)",
  },
  {
    field: "minConfidence" as const,
    newValue: 0.7,
    reason:
      "Add hard minConfidence 0.70 gate: the score bar alone admits everything (avg executed conf 0.59); expect 40–60% fewer trades with positive expectancy",
    evidence: "2026-08-30 18:09 report: −$0.18/trade all-time EV; short-TTR lane exempt (own bar + fixed size)",
  },
  {
    field: "kalshiMinCopyScore" as const,
    newValue: 80,
    reason: "Gate Kalshi routing: only copies with copyScore ≥ 80 may route to Kalshi",
    evidence: "2026-08-30 report D1: recent Kalshi leg is the biggest loss center",
  },
  {
    field: "kalshiMinConfidence" as const,
    newValue: 0.75,
    reason: "Gate Kalshi routing: only copies with confidence ≥ 0.75 may route to Kalshi",
    evidence: "2026-08-30 report D1: recent Kalshi leg is the biggest loss center",
  },
  {
    field: "kalshiCircuitBreakerPnl" as const,
    newValue: -50,
    reason:
      "Kalshi venue circuit breaker: pause Kalshi routing once its realized PnL < −$50 (currently tripped at −$100.28 → Polymarket-only until the leg recovers)",
    evidence: "2026-08-30 report D1: Kalshi 41 closed −$58.37 + 32 open −$97.25 unrealized (−68% on ~$229); DB: realized −$100.28 all-time",
  },
  {
    field: "deadZoneMinPrice" as const,
    newValue: 0.2,
    reason: "Entry-band sizing: lower edge of the historically losing 0.2–0.6 entry band",
    evidence: "2026-08-30 report: $0.20–0.60 entries = 71% of volume, −$227 drain",
  },
  {
    field: "deadZoneMaxPrice" as const,
    newValue: 0.6,
    reason: "Entry-band sizing: upper edge of the historically losing 0.2–0.6 entry band",
    evidence: "2026-08-30 report: $0.20–0.60 entries = 71% of volume, −$227 drain",
  },
  {
    field: "deadZoneSizeFactor" as const,
    newValue: 0.5,
    reason: "Halve size inside the 0.2–0.6 entry band ($18 → $9 effective)",
    evidence: "2026-08-30 report D2: halve sweet-spot sizing in the 0.2–0.6 band",
  },
  {
    field: "longshotMaxPrice" as const,
    newValue: 0.2,
    reason:
      "Long-shot boost applies below $0.20 (the ONLY +EV bucket per the report's own data; <0.40 overlaps the losing middle so the data, not the report wording, sets the edge)",
    evidence: "2026-08-30 report: entry < $0.20 +$185.75 on 43 trades; $0.20–0.60 −$227",
  },
  {
    field: "longshotSizeFactor" as const,
    newValue: 1.5,
    reason: "Long-shot entries (< $0.20) carry 1.5× size — the only +EV entry bucket",
    evidence: "2026-08-30 report: entry < $0.20 +$185.75 on 43 trades",
  },
  {
    field: "maxOpenPositions" as const,
    newValue: 225,
    reason:
      "Raise open-position cap 150→225: 137 cap-skips/24h with $1,352 cash idle and proven turnover (EOD sweep 150→80, refilled by 06:51)",
    evidence: "2026-08-30 tuning review #10 rec 1 (range 225–250); daily report D3 asked 200 — 225 satisfies both",
  },
  {
    field: "staleExitHours" as const,
    newValue: 24,
    reason: "Tighten stale-exit tier-1 48→24h: slot-starved book needs faster turnover; hourly recycle already fires (5 in one run)",
    evidence: "2026-08-30 report D3 bonus; tuning review #10 rec 2 (hourly recycling)",
  },
  {
    field: "maxCopiesPerWalletPerDay" as const,
    newValue: 40,
    reason: "Raise wallet-daily copy cap 25→40: 304 downgrades ≈ 87% of executed copies were top-wallet signals hitting the cap",
    evidence: "2026-08-30 tuning review #10 rec 5",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v37-reports-0830");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (${PROPOSALS.length} proposals). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v37 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
