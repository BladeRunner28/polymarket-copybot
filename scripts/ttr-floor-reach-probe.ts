/**
 * TTR-floor REACH probe — does raising `minTimeToResolutionHours` 2 -> 24 actually
 * change any admission under the LIVE ruleset?
 *
 * WHY THIS EXISTS
 * ---------------
 * The approved 2->24h floor was priced as "blocking the 2-24h band" (a pure TTR-band
 * counterfactual, scripts/profit-tenor.py §S15). But the gate at
 * src/lib/scoring/trade.ts:124 is not evaluated alone: the short-TTR lane rescue
 * (trade.ts:266-272) clears a `resolves in ... < min ...h` skip whenever the leg is
 * `laneEligible` — ttr within [shortTtrMinHours, shortTtrMaxHours] and adverse drift
 * <= shortTtrMaxDrift — and scores >= shortTtrMinCopyScore. The live RuleSet (v73)
 * carries shortTtrMinHours=2, shortTtrMaxHours=72, shortTtrMinCopyScore=35, so the
 * ENTIRE 2-24h band is inside the lane window. A band-row counterfactual therefore
 * measures a population the gate may not be able to reach at all.
 *
 * So this probe does not count rows. It runs the scorer ITSELF — the same
 * scoreTrade(..., rules) call the loop makes, with rules loaded from the active
 * RuleSet — twice per case: once with the live floor, once with 24h. A case counts
 * as REACHED only if the decision, the lane flag or the booked size differs.
 *
 * CONTROLS (a probe that cannot fail is not a probe):
 *   control A: shortTtrMaxHours = 0  (lane disabled)   -> the flip MUST reach
 *   control B: shortTtrMaxHours = 12 (lane window short) -> must reach ttr in (12,24)
 *   control C: shortTtrMinCopyScore = 999              -> lane cannot rescue -> reaches
 * If a control reports zero reached cases, the probe is broken, not the finding.
 *
 * Read-only: loads the active RuleSet, writes nothing.
 *
 * RUN
 *   npx tsx scripts/ttr-floor-reach-probe.ts
 *   npx tsx scripts/ttr-floor-reach-probe.ts --verbose
 */

import { getActiveRules } from "../src/lib/rules";
import { scoreTrade, TradeScoreInput } from "../src/lib/scoring/trade";
import type { Rules } from "../src/lib/rules";

const VERBOSE = process.argv.includes("--verbose");

const TTRS = [1.5, 2.0, 2.5, 5, 12, 23.9, 24.0, 30, 48, 71.9, 72.0, 73, 120];
// adverse drift = currentPrice - walletEntryPrice (only the adverse half matters)
const DRIFTS = [0, 0.002, 0.004, 0.01, 0.03, 0.049, 0.051, 0.08];
const PRICES = [0.05, 0.12, 0.3, 0.55, 0.7, 0.85];
const WALLET_SCORES = [45, 60, 75, 90];
const SPREADS = [0.02, 0.05, 0.07];
const LIQUIDITIES = [500, 1000, 5000];

interface Case {
  ttr: number;
  drift: number;
  px: number;
  wscore: number;
  spread: number;
  liq: number;
}

function buildCases(): Case[] {
  const out: Case[] = [];
  for (const ttr of TTRS)
    for (const drift of DRIFTS)
      for (const px of PRICES)
        for (const wscore of WALLET_SCORES)
          for (const spread of SPREADS)
            for (const liq of LIQUIDITIES) out.push({ ttr, drift, px, wscore, spread, liq });
  return out;
}

function input(c: Case): TradeScoreInput {
  return {
    walletGlobalScore: c.wscore,
    walletEntryPrice: c.px,
    currentPrice: Math.min(0.99, c.px + c.drift),
    spread: c.spread,
    liquidity: c.liq,
    timeToResolutionHours: c.ttr,
  };
}

function sig(r: ReturnType<typeof scoreTrade>): string {
  return `${r.decision}/${r.lane ?? "main"}/${r.simulatedPositionSize ?? "-"}`;
}

function sweep(rules: Rules, label: string) {
  const raised: Rules = { ...rules, minTimeToResolutionHours: 24 };
  let reached = 0;
  const byTtr = new Map<string, number>();
  const examples: string[] = [];
  for (const c of buildCases()) {
    const a = scoreTrade(input(c), rules);
    const b = scoreTrade(input(c), raised);
    if (sig(a) === sig(b)) continue;
    reached++;
    const k = c.ttr < 2 ? "<2h" : c.ttr < 24 ? "2-24h" : ">=24h";
    byTtr.set(k, (byTtr.get(k) ?? 0) + 1);
    if (examples.length < (VERBOSE ? 40 : 6))
      examples.push(
        `ttr=${c.ttr}h drift=${c.drift} px=${c.px} score=${c.wscore} ` +
          `spread=${c.spread} liq=${c.liq}: ${sig(a)} -> ${sig(b)}`
      );
  }
  const total = buildCases().length;
  const split = [...byTtr.entries()].map(([k, v]) => `${k} ${v}`).join(", ") || "none";
  console.log(`  ${label.padEnd(38)} reached ${String(reached).padStart(5)} / ${total}   [${split}]`);
  for (const e of examples) console.log(`      ${e}`);
  return reached;
}

async function main() {
  const { rules, version } = await getActiveRules();
  console.log(`TTR-floor reach probe — active RuleSet v${version}`);
  console.log(
    `  live floor minTimeToResolutionHours=${rules.minTimeToResolutionHours}h  ` +
      `shortTtr lane: [${rules.shortTtrMinHours}, ${rules.shortTtrMaxHours}]h, ` +
      `minCopyScore=${rules.shortTtrMinCopyScore}, maxDrift=${rules.shortTtrMaxDrift}`
  );
  console.log(
    `  drift gate maxPriceDrift=${rules.maxPriceDrift} longshotDriftPct=${rules.longshotDriftPct} ` +
      `longshotMaxPrice=${rules.longshotMaxPrice}`
  );
  console.log("");

  const live = sweep(rules, "LIVE ruleset, floor 2 -> 24");
  const cA = sweep({ ...rules, shortTtrMaxHours: 0 }, "control A: lane disabled");
  const cB = sweep({ ...rules, shortTtrMaxHours: 12 }, "control B: lane window 2-12h");
  const cC = sweep({ ...rules, shortTtrMinCopyScore: 999 }, "control C: lane score bar 999");

  console.log("");
  const controlsOk = cA > 0 && cB > 0 && cC > 0;
  console.log(
    `  controls: A=${cA} B=${cB} C=${cC} -> ${controlsOk ? "ARMED (each control reaches >0, so the probe can fail)" : "BROKEN — a control reached 0; do not read the live number"}`
  );
  if (!controlsOk) process.exitCode = 2;

  console.log("");
  if (live === 0) {
    console.log("  FINDING: the 2->24h floor is INERT under this ruleset — it changes no decision,");
    console.log("  no lane flag and no size, because every 2-24h leg is already inside the short-TTR");
    console.log("  lane window and is rescued from the very skip the floor would add.");
    console.log("  To make the floor bind, the LANE WINDOW must move first (shortTtrMaxHours < 24),");
    console.log("  not the floor. Control B prices that boundary.");
  } else {
    console.log(`  FINDING: the floor reaches ${live} grid cases. Non-zero reach — read the rows above.`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
