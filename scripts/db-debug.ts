import { prisma } from "../src/lib/db";

async function main() {
  const date = new Date().toISOString().slice(0, 10);
  const dayStart = new Date(`${date}T00:00:00Z`);

  console.log("Analyzing BANKROLL_200 for date:", date);
  console.log("Day start (UTC):", dayStart.toISOString());

  const bankroll = await prisma.botBankroll.findUnique({
    where: { botId: "BANKROLL_200" }
  });
  console.log("BANKROLL_200 Bankroll Record:", bankroll);

  const openTrades = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", status: "open" }
  });
  console.log(`Open Trades count: ${openTrades.length}`);
  const totalOpenUnrealizedPnl = openTrades.reduce((a, t) => a + (t.unrealizedPnl ?? 0), 0);
  console.log(`Total Open Unrealized Pnl: $${totalOpenUnrealizedPnl.toFixed(2)}`);

  const resolvedToday = await prisma.paperTrade.findMany({
    where: {
      botId: "BANKROLL_200",
      status: "resolved",
      resolvedAt: { gte: dayStart }
    }
  });
  console.log(`Resolved Today count: ${resolvedToday.length}`);
  const totalResolvedRealizedPnl = resolvedToday.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  console.log(`Total Resolved Realized Pnl Today: $${totalResolvedRealizedPnl.toFixed(2)}`);

  const allResolved = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", status: "resolved" }
  });
  console.log(`All Resolved count: ${allResolved.length}`);
  const totalRealizedPnlAllTime = allResolved.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  console.log(`Total Realized Pnl All-Time: $${totalRealizedPnlAllTime.toFixed(2)}`);

  // Let's print out the open trades and resolved trades details
  console.log("\n--- Open Trades ---");
  for (const t of openTrades) {
    console.log(`ID: ${t.id}, Market: ${t.marketId}, Size: ${t.simulatedPositionSize}, Entry: ${t.entryPrice}, Current: ${t.currentPrice}, Unrealized PnL: ${t.unrealizedPnl}, OpenedAt: ${t.openedAt.toISOString()}`);
  }

  console.log("\n--- Resolved Today ---");
  for (const t of resolvedToday) {
    console.log(`ID: ${t.id}, Market: ${t.marketId}, Size: ${t.simulatedPositionSize}, Realized PnL: ${t.realizedPnl}, ResolvedAt: ${t.resolvedAt?.toISOString()}`);
  }
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect());
