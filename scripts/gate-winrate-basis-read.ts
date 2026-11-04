/**
 * gate-winrate-basis-read — the auto-rule-updater's `minCopyScore` gate, read back on the basis it
 * is printed on and on the basis it claims. Read-only. Card `ruleupdater-exit-labeled-winrate`.
 *
 * Run: npx tsx scripts/gate-winrate-basis-read.ts [--self-test]
 *
 * BASIS (printed on every run, never implied):
 *   level      = leg (one PaperTrade row)
 *   population = the rule updater's OWN query: status IN ('closed','resolved') AND realizedPnl NOT NULL
 *                (no isDemo scope — collectSamples has none; the count of demo rows is printed so a
 *                future demo insertion cannot hide inside the number)
 *   clock      = settlement: COALESCE(closedAt, resolvedAt); the window's bounds are printed
 *   EXIT win   = realizedPnl > 0            (the gate's live input)
 *   OUTCOME win= didOutcomeWin(trade.outcome, OutcomeReview.finalOutcome); undeterminable legs are
 *                excluded from the rate and reported as coverage
 *   settleBook = hold-to-settlement at OUR stake and OUR entry price, fees and slippage ZERO
 *                (counterfactual, labelled as such — it is not our book)
 *
 * The gate is NOT changed here. Both verdicts are computed; the live arm is what ships.
 */

import { prisma } from "../src/lib/db";
import { didOutcomeWin } from "../src/lib/resolution";
import { getActiveRules } from "../src/lib/rules";
import {
  compareGateBasis,
  GateLeg,
  BasisComparison,
  settlementPnl,
  exitBasisRead,
} from "../src/lib/gate-winrate-basis";

const pct = (r: number | null) => (r === null ? "n/a" : `${(100 * r).toFixed(1)}%`);
const usd = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`;

function verdictText(v: { tightens: boolean; relaxes: boolean; copyFloor: number } | null): string {
  if (!v) return "n/a (no judgeable legs)";
  if (v.tightens) return "TIGHTEN minCopyScore +3";
  if (v.relaxes) return "RELAX minCopyScore -2 (toward floor)";
  return `no move (floor ${v.copyFloor})`;
}

function selfTest(): number {
  // A population where the EXIT arm says "comfortable winner" and the SETTLEMENT arm says "loser":
  // 10 legs, 7 closed above entry (exit rate 70%), but 8 of the 10 settled LOSSES. If the detector
  // cannot see that flip, it is worthless — exit 1.
  const legs: GateLeg[] = [];
  for (let i = 0; i < 10; i++) {
    legs.push({ pnl: i < 7 ? 5 : -5, stake: 10, entryPrice: 0.5, at: new Date(), outcomeWin: i < 2 });
  }
  const c = compareGateBasis(legs, { minCopyScore: 65, highScoreCapMin: 80, sweetSpotMinScore: 70 });
  const errors: string[] = [];
  if (c.exit.rate !== 0.7) errors.push(`exit rate ${c.exit.rate} != 0.7`);
  if (c.outcomeOnExitBook.rate !== 0.2) errors.push(`outcome rate ${c.outcomeOnExitBook.rate} != 0.2`);
  if (c.disagreement.exitWinOutcomeLoss.n !== 5) errors.push(`win->loss legs ${c.disagreement.exitWinOutcomeLoss.n} != 5`);
  if (c.disagreement.exitLossOutcomeWin.n !== 0) errors.push(`loss->win legs ${c.disagreement.exitLossOutcomeWin.n} != 0`);
  // exit book: 7*5 - 3*5 = +20 -> no move; settlement book: 2 wins of 10 (p=0.5 pays +10) and 8
  // losses (-10) = 20 - 80 = -60, rate 20% -> TIGHTEN fires. The verdict MUST flip.
  if (c.verdictSettleBook?.tightens !== true) errors.push(`settlement verdict did not tighten: ${JSON.stringify(c.verdictSettleBook)}`);
  if (c.verdictFlips !== true) errors.push("verdictFlips false on a population built to flip");
  if (errors.length) {
    console.error("SELF-TEST FAILED — the detector cannot see the defect it exists for:");
    for (const e of errors) console.error(`  - ${e}`);
    return 1;
  }
  console.log("self-test OK: exit-basis 70.0% / outcome-basis 20.0%, verdict flips (no-move -> TIGHTEN), 5 legs mislabelled as wins.");
  return 0;
}

async function main() {
  if (process.argv.includes("--self-test")) {
    process.exitCode = selfTest();
    await prisma.$disconnect();
    return;
  }

  const { rules, version } = await getActiveRules();

  const trades = await prisma.paperTrade.findMany({
    where: { status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } },
    select: {
      id: true,
      marketId: true,
      botId: true,
      outcome: true,
      entryPrice: true,
      simulatedPositionSize: true,
      realizedPnl: true,
      status: true,
      isDemo: true,
      closedAt: true,
      resolvedAt: true,
      outcomeReviews: { select: { finalOutcome: true } },
      // The canonical label path: benchmarks.ts and decision-aggregates.ts resolve a decision's
      // outcome from the DECISION's reviews. 1,116 legs carry a decision-level review but no
      // paperTrade-linked one, so reading only `t.outcomeReviews` understates coverage by 8.9pt.
      decision: { select: { outcomeReviews: { select: { finalOutcome: true } } } },
    },
  });

  const toLeg = (t: (typeof trades)[number]): GateLeg => {
    const review =
      t.outcomeReviews.find((r) => r.finalOutcome !== null) ??
      t.decision.outcomeReviews.find((r) => r.finalOutcome !== null);
    return {
      pnl: t.realizedPnl,
      stake: t.simulatedPositionSize,
      entryPrice: t.entryPrice,
      at: t.closedAt ?? t.resolvedAt,
      outcomeWin: review ? didOutcomeWin(t.outcome, { winningLabel: review.finalOutcome }) : null,
    };
  };

  const legs = trades.map(toLeg);
  const demo = trades.filter((t) => t.isDemo).length;
  let since: Date | null = null;
  let until: Date | null = null;
  for (const t of trades) {
    const at = t.closedAt ?? t.resolvedAt;
    if (!at) continue;
    if (!since || at < since) since = at;
    if (!until || at > until) until = at;
  }

  const thresholds = {
    minCopyScore: rules.minCopyScore,
    highScoreCapMin: rules.highScoreCapMin,
    sweetSpotMinScore: rules.sweetSpotMinScore,
  };
  const all = compareGateBasis(legs, thresholds);

  console.log(
    `gate-winrate-basis-read | DB prisma/dev.db | level=leg | clock=COALESCE(closedAt,resolvedAt) | as of ${new Date().toISOString()}`
  );
  console.log(
    `population: the auto-tuner's own query (status IN closed,resolved AND realizedPnl NOT NULL) -> ${legs.length.toLocaleString("en-US")} legs` +
      `, demo rows ${demo}, window ${since ? since.toISOString() : "n/a"} .. ${until ? until.toISOString() : "n/a"}`
  );
  console.log(
    `rules in force: v${version} minCopyScore ${rules.minCopyScore}, floor max(highScoreCapMin ${rules.highScoreCapMin}, sweetSpotMinScore ${rules.sweetSpotMinScore}, 55) = ${all.verdictLive.copyFloor}`
  );

  const lanes = ["STANDARD", "BANKROLL_200"];
  const legSets: Record<string, GateLeg[]> = { ALL: legs };
  for (const lane of lanes) legSets[lane] = trades.filter((t) => t.botId === lane).map(toLeg);
  const reads: Record<string, BasisComparison> = { ALL: all };
  for (const lane of lanes) reads[lane] = compareGateBasis(legSets[lane], thresholds);

  for (const key of ["ALL", ...lanes]) {
    const c = reads[key];
    const o = c.outcomeOnExitBook;
    const s = c.settleBook;
    const judged = legSets[key].filter((l) => l.outcomeWin === true || l.outcomeWin === false);
    const judgedExit = exitBasisRead(judged);
    console.log(`\n[${key}] n=${c.exit.n.toLocaleString("en-US")}  exit PnL ${usd(c.exit.pnl)} on $${Math.round(c.exit.cost).toLocaleString("en-US")} cost`);
    console.log(
      `  EXIT basis      win rate ${pct(c.exit.rate)} (${c.exit.wins}/${c.exit.n}) — realizedPnl>0, the gate's live input`
    );
    console.log(
      `  OUTCOME basis   win rate ${pct(o.rate)} (${o.wins}/${o.n}) — same legs, same PnL book, settlement label; judgeable ${(100 * o.coverage).toFixed(1)}%, undetermined ${o.undetermined}`
    );
    console.log(
      `  LIKE-FOR-LIKE   on the ${judged.length.toLocaleString("en-US")} judgeable legs only: EXIT ${pct(judgedExit.rate)} vs OUTCOME ${pct(o.rate)} = ${o.rate !== null && judgedExit.rate !== null ? `${(100 * (o.rate - judgedExit.rate)).toFixed(1)}pt` : "n/a"}; exit book on those legs ${usd(judgedExit.pnl)} on $${Math.round(judgedExit.cost).toLocaleString("en-US")} cost`
    );
    if (s) {
      console.log(
        `  SETTLE book     win rate ${pct(s.rate)} (${s.wins}/${s.n}), PnL ${usd(s.pnl)} on $${Math.round(s.cost).toLocaleString("en-US")} cost — COUNTERFACTUAL hold-to-settlement at our stake, fees/slippage 0`
      );
    }
    const d = c.disagreement;
    console.log(
      `  label disagreement: exit-win/outcome-loss ${d.exitWinOutcomeLoss.n} legs, PnL ${usd(d.exitWinOutcomeLoss.pnl)} on $${Math.round(d.exitWinOutcomeLoss.cost).toLocaleString("en-US")} staked` +
        ` | exit-loss/outcome-win ${d.exitLossOutcomeWin.n} legs (PnL ${usd(d.exitLossOutcomeWin.pnl)}); agree ${d.bothWon + d.bothLost}, undetermined ${d.unknown}`
    );
    console.log(`  gate verdict — LIVE (exit rate):            ${verdictText(c.verdictLive)}`);
    console.log(`  gate verdict — rate swapped to OUTCOME:     ${verdictText(c.verdictOutcomeLabel)}`);
    console.log(`  gate verdict — SETTLE book (counterfactual): ${verdictText(c.verdictSettleBook)}`);
  }

  // WHY a leg is undeterminable — an exclusion this large is part of the answer, not a footnote.
  const reviewsOf = (t: (typeof trades)[number]) => [...t.outcomeReviews, ...t.decision.outcomeReviews];
  const noReview = trades.filter((t) => reviewsOf(t).length === 0).length;
  const nullOutcome = trades.filter(
    (t) => reviewsOf(t).length > 0 && !reviewsOf(t).some((r) => r.finalOutcome !== null)
  ).length;
  const labelMismatch = trades.filter((t) => toLeg(t).outcomeWin === null && reviewsOf(t).some((r) => r.finalOutcome !== null)).length;
  console.log(
    `\nundetermined ${all.outcomeOnExitBook.undetermined} of ${legs.length} legs: no outcome review ${noReview}, review with null finalOutcome ${nullOutcome}, review present but label families do not compare (YES/NO vs token name) ${labelMismatch}`
  );

  // Concentration guard: a win-rate gap that lives on a handful of legs is not a basis problem,
  // it is one market. Report the biggest single-market disagreement so it cannot be missed.
  const byMarket = new Map<string, { n: number; pnl: number }>();
  for (const t of trades) {
    const leg = toLeg(t);
    if (leg.outcomeWin === null) continue;
    const exitWin = (leg.pnl ?? 0) > 0;
    if (exitWin === leg.outcomeWin) continue;
    const cur = byMarket.get(t.marketId) ?? { n: 0, pnl: 0 };
    byMarket.set(t.marketId, { n: cur.n + 1, pnl: cur.pnl + (leg.pnl ?? 0) });
  }
  const disagreeing = [...byMarket.values()].sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
  const topN = disagreeing.slice(0, 5).reduce((a, m) => a + m.pnl, 0);
  if (disagreeing.length) {
    console.log(
      `\nconcentration: ${disagreeing.length} markets carry a disagreeing leg; top-5 markets hold ${usd(topN)} of the exit-win/outcome-loss PnL ${usd(all.disagreement.exitWinOutcomeLoss.pnl)}`
    );
  }

  const out = {
    generatedAt: new Date().toISOString(),
    basis: {
      level: "leg",
      population: "PaperTrade.status IN (closed,resolved) AND realizedPnl NOT NULL (rule-updater collectSamples query)",
      clock: "COALESCE(closedAt, resolvedAt)",
      exitWin: "realizedPnl > 0",
      outcomeWin: "didOutcomeWin(PaperTrade.outcome, OutcomeReview.finalOutcome), undeterminable excluded",
      settleBook: "hold-to-settlement at our stake and entry price, fees and slippage zero",
    },
    window: { since, until },
    rulesVersion: version,
    thresholds,
    demoRows: demo,
    reads,
    settlementPnlTotal: legs.reduce((a, l) => a + (settlementPnl(l) ?? 0), 0),
  };
  const { writeFileSync } = await import("node:fs");
  writeFileSync("data/gate-winrate-basis.json", JSON.stringify(out, null, 2) + "\n");
  console.log(`\nwrote data/gate-winrate-basis.json`);

  await prisma.$disconnect();
}

main().catch(async (e) => {
  console.error("gate-winrate-basis-read FAILED:", e);
  await prisma.$disconnect();
  process.exit(1);
});
