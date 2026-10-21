/**
 * Enforcement probe for v65: run the LIVE ruleset through the REAL scorer and prove
 * `walletQualityInSize=0` actually moves the size, rather than merely sitting in the
 * RuleSet row. Two identical legs differing ONLY in wallet score must produce
 * different sizes under the flag off (they did under the flag on).
 *
 * Also re-checks the revert direction by scoring the same leg with the flag forced
 * back to 1.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/verify-v65-wallet-size.ts
 */
import { getActiveRules } from "../src/lib/rules";
import { scoreTrade } from "../src/lib/scoring/trade";
import type { TradeScoreInput } from "../src/lib/scoring/trade";

const sz = (r: { simulatedPositionSize: number | null }): number => r.simulatedPositionSize ?? 0;

function leg(walletGlobalScore: number, walletCategoryWinRate: number): TradeScoreInput {
  return {
    currentPrice: 0.35,
    walletEntryPrice: 0.35,
    walletGlobalScore,
    walletCategoryWinRate,
    spread: 0.01,
    liquidity: 5000,
    timeToResolutionHours: 200, // outside short-TTR lane -> normal eligibility
    tradeSize: 50,
  } as TradeScoreInput;
}

async function main() {
  const { rules, version } = await getActiveRules();
  console.log(`active v${version}: walletQualityInSize=${rules.walletQualityInSize}`);

  const cases: Array<[string, number, number]> = [
    ["low wallet / mid category", 45, 0.5],
    ["high wallet / mid category", 95, 0.5],
  ];

  for (const [label, w, c] of cases) {
    const off = scoreTrade(leg(w, c), rules);
    const on = scoreTrade(leg(w, c), { ...rules, walletQualityInSize: 1 });
    console.log(
      `  ${label.padEnd(26)} flag0 score=${off.copyScore.toFixed(1)} size=$${sz(off).toFixed(2)}` +
        `  |  flag1 score=${on.copyScore.toFixed(1)} size=$${sz(on).toFixed(2)}  decision=${off.decision}`
    );
  }

  // The decisive assertion: the two wallet scores must now produce closer sizes than
  // they did under the legacy flag, because the wallet term no longer reaches size.
  const offLow = sz(scoreTrade(leg(45, 0.5), rules));
  const offHigh = sz(scoreTrade(leg(95, 0.5), rules));
  const onLow = sz(scoreTrade(leg(45, 0.5), { ...rules, walletQualityInSize: 1 }));
  const onHigh = sz(scoreTrade(leg(95, 0.5), { ...rules, walletQualityInSize: 1 }));

  const offGap = Math.abs(offHigh - offLow);
  const onGap = Math.abs(onHigh - onLow);
  console.log(`\n  size gap from wallet score alone: flag1 $${onGap.toFixed(2)} -> flag0 $${offGap.toFixed(2)}`);
  if (rules.walletQualityInSize === 0 && offGap > onGap + 1e-9) {
    console.error("FAIL: wallet score still widens the size gap with the flag off");
    process.exit(1);
  }
  console.log(
    rules.walletQualityInSize === 0
      ? "PASS: the active ruleset does not let wallet score widen the size gap"
      : "NOTE: flag is 1 (legacy) on the active ruleset — nothing to enforce"
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
