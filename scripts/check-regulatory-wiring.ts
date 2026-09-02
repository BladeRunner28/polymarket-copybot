/* Read-only end-to-end check of Phase 8 wiring (no trades opened). */
import { prisma } from "../src/lib/db";
import { researchCategoryFor } from "../src/lib/research-categories";
import { scoreTrade } from "../src/lib/scoring/trade";
import { getActiveRules } from "../src/lib/rules";

async function main() {
  const sample = await prisma.observedTrade.findFirst({
    where: {
      OR: [
        { marketQuestion: { contains: "Senate" } },
        { marketQuestion: { contains: "election" } },
        { marketQuestion: { contains: "Fed" } },
        { marketQuestion: { contains: "crypto" } },
      ],
    },
    orderBy: { timestamp: "desc" },
  });
  if (!sample) { console.log("No political sample trade found"); return; }

  const cat = researchCategoryFor(sample.marketQuestion, sample.marketCategory);
  console.log(`Sample trade: "${sample.marketQuestion?.slice(0, 60)}" [${sample.marketCategory}] outcome=${sample.outcome} side=${sample.side}`);
  console.log(`Research category: ${cat ?? "none"}`);

  let agreement: number | undefined;
  if (cat) {
    const recent = await prisma.regulatorySignal.findFirst({
      where: {
        marketCategory: cat,
        processedAt: { gte: new Date(Date.now() - 7 * 86_400_000) },
        OR: [{ sentimentScore: { gte: 0.3 } }, { sentimentScore: { lte: -0.3 } }],
      },
      orderBy: { processedAt: "desc" },
    });
    if (recent) {
      const sideSign = sample.side === "SELL" ? -1 : 1;
      const outcomeSign = sample.outcome === "NO" ? -1 : 1;
      agreement = sideSign * outcomeSign * recent.sentimentScore;
      console.log(`Latest ${cat} signal: ${recent.sentimentScore} (${recent.source}) → signed agreement: ${agreement.toFixed(2)}`);
    } else {
      console.log(`No opinionated ${cat} signal in last 7 days — no boost`);
    }
  }

  const { rules } = await getActiveRules();
  const base = scoreTrade({
    walletGlobalScore: 75, walletCategoryWinRate: 0.6,
    walletEntryPrice: sample.walletEntryPrice, currentPrice: sample.detectedPrice,
    spread: 0.02, liquidity: 50000, timeToResolutionHours: 120,
    regulatoryAgreement: agreement,
  }, rules);
  console.log(`Decision: ${base.decision} | copyScore: ${base.copyScore}`);
  console.log(`Reasons: ${base.reasons.slice(0, 3).join(" | ") || "(none)"}`);
  console.log(`Risks: ${base.risks.slice(0, 3).join(" | ") || "(none)"}`);
}

main().finally(() => prisma.$disconnect());
