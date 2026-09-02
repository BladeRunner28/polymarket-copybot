const { PrismaClient } = require('@prisma/client');
const prisma = new PrismaClient();

// C-200 phase goals — each phase requires STABILITY_DAYS consecutive days at
// target before advancing to the next (user policy, 2026-08-31).
const PHASES = [
  { name: "Phase 1", target: 500 },
  { name: "Phase 2", target: 1000 },
  { name: "Phase 3", target: 2000 },
  { name: "Ultimate", target: 5000 },
];
const STABILITY_DAYS = 7;

function dayKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function main() {
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);

  const bankroll = await prisma.botBankroll.findUnique({
    where: { botId: 'BANKROLL_200' }
  });

  if (!bankroll) {
    console.log("BANKROLL_200 not found");
    process.exit(0);
  }

  // All closed/resolved C-200 trades in the last 14 days. Use the actual close
  // timestamp (closedAt for early exits, resolvedAt for resolved; Unix-ms
  // ints) so daily PnL history and the stability streak are accurate.
  const since14 = new Date(startOfDay.getTime() - 13 * 86400000);
  const finished = await prisma.paperTrade.findMany({
    where: {
      botId: 'BANKROLL_200',
      status: { in: ['closed', 'resolved'] },
      OR: [{ closedAt: { gte: since14 } }, { resolvedAt: { gte: since14 } }],
    },
    select: { realizedPnl: true, closedAt: true, resolvedAt: true },
  });

  const byDay = new Map();
  for (const t of finished) {
    const ts = t.closedAt ?? t.resolvedAt;
    if (!ts) continue;
    const k = dayKey(new Date(ts));
    byDay.set(k, (byDay.get(k) ?? 0) + (t.realizedPnl ?? 0));
  }

  // Last 14 days of realized PnL, most recent first (days with no closes = $0).
  const dailyPnl = [];
  for (let i = 0; i < 14; i++) {
    const d = new Date(startOfDay.getTime() - i * 86400000);
    dailyPnl.push(byDay.get(dayKey(d)) ?? 0);
  }

  // Current goal: a phase is CLEARED only after its target held for
  // STABILITY_DAYS consecutive days; the goal advances accordingly.
  let goalIdx = 0;
  const last7 = dailyPnl.slice(0, STABILITY_DAYS);
  for (let i = 0; i < PHASES.length; i++) {
    if (last7.length === STABILITY_DAYS && last7.every((d) => d >= PHASES[i].target)) goalIdx = i + 1;
    else break;
  }
  goalIdx = Math.min(goalIdx, PHASES.length - 1);
  const goal = PHASES[goalIdx];

  // Stability streak: consecutive days (from today back) meeting the CURRENT
  // goal's target.
  let streak = 0;
  for (const d of dailyPnl) {
    if (d >= goal.target) streak++;
    else break;
  }

  const realizedToday = byDay.get(dayKey(startOfDay)) ?? 0;
  const openTrades = await prisma.paperTrade.aggregate({
    where: {
      botId: 'BANKROLL_200',
      status: 'open'
    },
    _sum: { unrealizedPnl: true }
  });

  const totalPnl = realizedToday + (openTrades._sum.unrealizedPnl || 0);

  console.log(`**C-200 Daily Progress Report**
- **Goal:** $${goal.target}/day (${goal.name}${goalIdx > 0 ? " — CLEARED" : ""})
- **Today's PnL:** $${totalPnl.toFixed(2)}
- **Status:** ${totalPnl >= goal.target ? '[✅ ON TRACK]' : '[❌ BEHIND]'}
- **Phase stability:** ${streak}/${STABILITY_DAYS} consecutive days at $${goal.target}/day (advance requires ${STABILITY_DAYS} days stable)
- **Current Bankroll:** $${(bankroll.cashBalance + realizedToday).toFixed(2)}`);
}

main().finally(() => prisma.$disconnect());
