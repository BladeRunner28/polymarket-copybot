import Link from "next/link";
import { prisma } from "@/lib/db";
import { Card, Stat, Pnl, Badge, Empty } from "@/components/ui";
import { LineChart } from "@/components/chart";
import { readFileSync } from "fs";
import path from "path";

export const dynamic = "force-dynamic";

export default async function Overview() {
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);

  const [
    openTrades, 
    resolvedTrades, 
    tracked, 
    today, 
    latestReport, 
    latestChanges, 
    snapshots, 
    demoCount, 
    bankrolls,
    regulatorySignals,
    recentC200Trades,
    closedTodayC200,
    openTradesC200
  ] = await Promise.all([
      prisma.paperTrade.findMany({ where: { status: "open" } }),
      prisma.paperTrade.findMany({ where: { status: "resolved" } }),
      prisma.walletProfile.count({ where: { status: "track" } }),
      prisma.decisionJournal.count({
        where: {
          decision: "paper_copy",
          createdAt: { gte: new Date(new Date().toISOString().slice(0, 10)) },
        },
      }),
      prisma.dailyReport.findFirst({ orderBy: { date: "desc" } }),
      prisma.ruleChange.findMany({
        orderBy: { createdAt: "desc" },
        take: 3,
        include: { newRuleSet: true },
      }),
      prisma.$queryRaw<Array<{ hour: string; botId: string; total_pnl: number }>>`
        SELECT strftime('%Y-%m-%d %H:00:00', s.collectedAt / 1000, 'unixepoch') as hour, t.botId, SUM(s.pnl) as total_pnl
        FROM PnlSnapshot s
        JOIN PaperTrade t ON s.paperTradeId = t.id
        GROUP BY hour, t.botId
        ORDER BY hour ASC
      `,
      prisma.paperTrade.count({ where: { isDemo: true } }),
      prisma.botBankroll.findMany(),
      prisma.regulatorySignal.findMany({ orderBy: { processedAt: "desc" }, take: 5 }),
      prisma.paperTrade.findMany({ 
        where: { botId: "BANKROLL_200" }, 
        include: { decision: true },
        orderBy: { openedAt: "desc" },
        take: 100 
      }),
      prisma.paperTrade.aggregate({
        where: { botId: 'BANKROLL_200', status: { in: ['closed', 'resolved'] }, resolvedAt: { gte: startOfDay } },
        _sum: { realizedPnl: true, unrealizedPnl: true }
      }),
      prisma.paperTrade.aggregate({
        where: { botId: 'BANKROLL_200', status: 'open' },
        _sum: { unrealizedPnl: true }
      })
    ]);

  const stdOpen = openTrades.filter(t => t.botId === "STANDARD");
  const cmpOpen = openTrades.filter(t => t.botId === "BANKROLL_200");
  const stdResolved = resolvedTrades.filter(t => t.botId === "STANDARD");
  const cmpResolved = resolvedTrades.filter(t => t.botId === "BANKROLL_200");

  const stdRealizedPnl = stdResolved.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const stdUnrealizedPnl = stdOpen.reduce((a, t) => a + t.unrealizedPnl, 0);
  const stdTotalPnl = stdRealizedPnl + stdUnrealizedPnl;
  const stdWinRate = stdResolved.length
    ? stdResolved.filter((t) => (t.realizedPnl ?? 0) > 0).length / stdResolved.length
    : 0;

  const cmpRealizedPnl = cmpResolved.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const cmpUnrealizedPnl = cmpOpen.reduce((a, t) => a + t.unrealizedPnl, 0);
  const cmpTotalPnl = cmpRealizedPnl + cmpUnrealizedPnl;
  const cmpWinRate = cmpResolved.length
    ? cmpResolved.filter((t) => (t.realizedPnl ?? 0) > 0).length / cmpResolved.length
    : 0;

  const c200Bankroll = bankrolls.find(b => b.botId === "BANKROLL_200") || { principal: 200, cashBalance: 0 };
  const todayC200Pnl = (closedTodayC200._sum.realizedPnl || 0) + (closedTodayC200._sum.unrealizedPnl || 0) + (openTradesC200._sum.unrealizedPnl || 0);

  // C-200 phase goals — each phase requires 7 consecutive days at target
  // before advancing to the next (user policy, 2026-08-31).
  const C200_PHASES = [
    { name: "Phase 1", target: 500 },
    { name: "Phase 2", target: 1000 },
    { name: "Phase 3", target: 2000 },
    { name: "Ultimate", target: 5000 },
  ];
  const STABILITY_DAYS = 7;
  const c200DayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const c200Since = new Date(startOfDay.getTime() - (STABILITY_DAYS - 1) * 86400000);
  const finishedC200 = await prisma.paperTrade.findMany({
    where: {
      botId: "BANKROLL_200",
      status: { in: ["closed", "resolved"] },
      OR: [{ closedAt: { gte: c200Since } }, { resolvedAt: { gte: c200Since } }],
    },
    select: { realizedPnl: true, closedAt: true, resolvedAt: true },
  });
  const c200ByDay = new Map<string, number>();
  for (const t of finishedC200) {
    const ts = t.closedAt ?? t.resolvedAt;
    if (!ts) continue;
    const k = c200DayKey(new Date(ts));
    c200ByDay.set(k, (c200ByDay.get(k) ?? 0) + (t.realizedPnl ?? 0));
  }
  const c200Daily: number[] = [];
  for (let i = 0; i < STABILITY_DAYS; i++) {
    c200Daily.push(c200ByDay.get(c200DayKey(new Date(startOfDay.getTime() - i * 86400000))) ?? 0);
  }
  let c200GoalIdx = 0;
  for (let i = 0; i < C200_PHASES.length; i++) {
    if (c200Daily.every((d) => d >= C200_PHASES[i].target)) c200GoalIdx = i + 1;
    else break;
  }
  c200GoalIdx = Math.min(c200GoalIdx, C200_PHASES.length - 1);
  const c200Goal = C200_PHASES[c200GoalIdx];
  let c200Streak = 0;
  for (const d of c200Daily) {
    if (d >= c200Goal.target) c200Streak++;
    else break;
  }

  // Cumulative PnL over time from database-aggregated snapshots
  const standardSeries = snapshots
    .filter((s) => s.botId === "STANDARD")
    .map((s) => ({ x: s.hour ? s.hour.slice(5, 13) : "", y: Math.round((s.total_pnl ?? 0) * 100) / 100 }))
    .filter((p) => p.x !== "");

  const compoundingSeries = snapshots
    .filter((s) => s.botId === "BANKROLL_200")
    .map((s) => ({ x: s.hour ? s.hour.slice(5, 13) : "", y: Math.round((s.total_pnl ?? 0) * 100) / 100 }))
    .filter((p) => p.x !== "");

  const chartData = [
    { name: "STANDARD ($0.25 - $20)", points: standardSeries.length ? standardSeries : [{ x: "Now", y: 0 }], strokeColor: "#34d399" }, // green
    { name: "BANKROLL_200 ($0.10 - $45)", points: compoundingSeries.length ? compoundingSeries : [{ x: "Now", y: 0 }], strokeColor: "#3b82f6" }, // blue
  ];

  // GDELT Atlas static snapshot stats (public/atlas.html, served at /atlas.html)
  let atlasStats: { stories?: number; countries?: number; generated?: string } | null = null;
  try {
    const atlasPath = path.join(process.cwd(), "public", "atlas.html");
    const html = readFileSync(atlasPath, "utf8");
    const m = html.match(/const SNAPSHOT = (\{[\s\S]*?\});\n/);
    if (m) {
      const snap = JSON.parse(m[1]);
      atlasStats = {
        stories: snap.total_stories,
        countries: snap.covered,
        generated: snap.generated,
      };
    }
  } catch {
    /* atlas not built yet — card renders with "not yet generated" state */
  }

  // Calculate breakdown of C-200 reasons
  let swarmCount = 0;
  let whaleWakeCount = 0;
  let trendCount = 0;
  let meanReversionCount = 0;
  let kalshiCount = 0;

  recentC200Trades.forEach(t => {
    if (t.venue === "Kalshi") kalshiCount++;
    try {
      const reasons = JSON.parse(t.decision.reasonsJson) as string[];
      const risks = JSON.parse(t.decision.risksJson) as string[];
      
      if (reasons.some(r => r.includes("Swarm"))) swarmCount++;
      if (reasons.some(r => r.includes("Whale-Wake"))) whaleWakeCount++;
      if (reasons.some(r => r.includes("Trend Following"))) trendCount++;
      if (risks.some(r => r.includes("Mean Reversion"))) meanReversionCount++;
    } catch { /* old format or corrupted json */ }
  });

  return (
    <div className="space-y-4">
      {demoCount > 0 && (
        <div className="bg-warn/10 border border-warn/30 text-warn text-sm rounded-xl px-4 py-2">
          ⚠️ Demo data present: some rows below are seeded <strong>[DEMO]</strong> data, not live market research.
        </div>
      )}

      {/* Goal Trajectory Tracker for C-200 */}
      <Card title="C-200 Bot Goal Trajectory (Dec 1st target: $5k/day)">
        <div className="space-y-4 mt-2">
          <div className="flex items-center justify-between text-sm">
            <div className="text-dim">Today's PnL: <span className="text-ink font-mono font-medium">${todayC200Pnl.toFixed(2)}</span></div>
            <div className="text-dim text-right">Current Goal: <span className="text-ink font-mono font-medium">${c200Goal.target.toLocaleString()}/day ({c200Goal.name})</span></div>
          </div>
          
          <div className="w-full bg-edge/30 rounded-full h-3 mb-1 overflow-hidden relative">
            <div 
              className={`h-3 rounded-full ${todayC200Pnl >= c200Goal.target ? 'bg-pos' : todayC200Pnl > 0 ? 'bg-accent' : 'bg-neg'}`} 
              style={{ width: `${Math.min(Math.max((todayC200Pnl / c200Goal.target) * 100, 0), 100)}%` }}
            ></div>
            {/* Phase markers */}
            <div className="absolute left-[10%] top-0 h-3 border-l border-ink/20" title="$500 (Phase 1)"></div>
            <div className="absolute left-[20%] top-0 h-3 border-l border-ink/20" title="$1,000 (Phase 2)"></div>
            <div className="absolute left-[40%] top-0 h-3 border-l border-ink/20" title="$2,000 (Phase 3)"></div>
            <div className="absolute left-[100%] top-0 h-3 border-l border-ink/20" title="$5,000 (Ultimate)"></div>
          </div>
          <div className="flex justify-between text-xs text-dim">
            <span>$0</span>
            <span>${c200Goal.target.toLocaleString()}/day</span>
          </div>

          <div className={`text-xs rounded-lg px-3 py-2 ${c200Streak >= 7 ? 'bg-pos/10 text-pos border border-pos/30' : 'bg-edge/10 border border-edge text-dim'}`}>
            ⏳ Phase stability: <span className="font-mono">{c200Streak}/{STABILITY_DAYS}</span> consecutive days at ${c200Goal.target.toLocaleString()}/day — each phase must be stable for {STABILITY_DAYS} days before advancing
            {c200GoalIdx > 0 && <span className="block mt-0.5">✅ {C200_PHASES[c200GoalIdx - 1].name} cleared ({C200_PHASES[c200GoalIdx - 1].target.toLocaleString()}/day stable for {STABILITY_DAYS} days)</span>}
          </div>

          <div className="grid grid-cols-4 gap-2 mt-2 text-center">
            <div className={`p-2 border rounded bg-edge/10 ${c200GoalIdx >= 1 ? 'border-pos/40' : 'border-edge'}`}>
              <div className="text-xs text-dim mb-1">Phase 1</div>
              <div className="font-mono text-sm">$500/day</div>
            </div>
            <div className={`p-2 border rounded bg-edge/10 ${c200GoalIdx >= 2 ? 'border-pos/40' : 'border-edge'}`}>
              <div className="text-xs text-dim mb-1">Phase 2</div>
              <div className="font-mono text-sm">$1,000/day</div>
            </div>
            <div className={`p-2 border rounded bg-edge/10 ${c200GoalIdx >= 3 ? 'border-pos/40' : 'border-edge'}`}>
              <div className="text-xs text-dim mb-1">Phase 3</div>
              <div className="font-mono text-sm">$2,000/day</div>
            </div>
            <div className={`p-2 border rounded bg-edge/10 ${c200GoalIdx >= 4 ? 'border-pos/40' : 'border-edge'}`}>
              <div className="text-xs text-dim mb-1">Ultimate</div>
              <div className="font-mono text-sm">$5,000/day</div>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat
          label="Total Paper PnL (Standard)"
          value={`${stdTotalPnl >= 0 ? "+" : ""}$${stdTotalPnl.toFixed(2)}`}
          sub={`realized ${stdRealizedPnl >= 0 ? "+" : ""}$${stdRealizedPnl.toFixed(2)} / open ${stdUnrealizedPnl >= 0 ? "+" : ""}$${stdUnrealizedPnl.toFixed(2)}`}
          tone={stdTotalPnl > 0 ? "pos" : stdTotalPnl < 0 ? "neg" : "neutral"}
        />
        <Stat label="Win Rate" value={`${(stdWinRate * 100).toFixed(1)}%`} sub={`${stdResolved.length} resolved trades`} tone={stdWinRate >= 0.5 ? "pos" : "neg"} />
        <Stat label="Open Positions" value={String(stdOpen.length)} sub="standard bot ($0.25 - $20)" />
        <Stat label="Tracked Wallets" value={String(tracked)} sub={`${today} copy candidates today`} />
        
        <Stat
          label="Total PnL (C-200)"
          value={`${cmpTotalPnl >= 0 ? "+" : ""}$${cmpTotalPnl.toFixed(2)}`}
          sub={`realized ${cmpRealizedPnl >= 0 ? "+" : ""}$${cmpRealizedPnl.toFixed(2)} / open ${cmpUnrealizedPnl >= 0 ? "+" : ""}$${cmpUnrealizedPnl.toFixed(2)}`}
          tone={cmpTotalPnl > 0 ? "pos" : cmpTotalPnl < 0 ? "neg" : "neutral"}
        />
        <Stat label="Win Rate (C-200)" value={`${(cmpWinRate * 100).toFixed(1)}%`} sub={`${cmpResolved.length} resolved trades`} tone={cmpWinRate >= 0.5 ? "pos" : "neg"} />
        <Stat label="Open Positions" value={String(cmpOpen.length)} sub="compounding bot ($0.10 - $45)" />
        <Stat label="Total Capital" value={`$${(c200Bankroll.principal + cmpTotalPnl).toFixed(2)}`} sub={`starting principal: $${c200Bankroll.principal.toFixed(2)}`} tone="neutral" />
      </div>

      <Card title="Paper PnL Over Time">
        <LineChart series={chartData} formatY={(v) => `$${v.toFixed(0)}`} />
      </Card>

      {/* GDELT Atlas — global news signal map */}
      <a
        href="/atlas.html"
        className="block bg-panel border border-accent/25 rounded-xl p-4 hover:border-accent/60 transition-colors group"
      >
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent font-bold text-lg">
              🌐
            </div>
            <div>
              <h2 className="text-sm font-semibold text-ink">
                GDELT Atlas <span className="text-accent">→</span>
              </h2>
              <p className="text-xs text-dim mt-0.5">
                Interactive world map of news coverage intensity &amp; significance (GDELT OSINT feed, dark mode)
              </p>
            </div>
          </div>
          <div className="flex items-center gap-5 text-right">
            {atlasStats ? (
              <>
                <div>
                  <div className="text-xs text-dim uppercase tracking-wide">stories</div>
                  <div className="font-mono text-sm text-ink">{atlasStats.stories}</div>
                </div>
                <div>
                  <div className="text-xs text-dim uppercase tracking-wide">countries</div>
                  <div className="font-mono text-sm text-ink">{atlasStats.countries}</div>
                </div>
                <div className="hidden md:block">
                  <div className="text-xs text-dim uppercase tracking-wide">snapshot</div>
                  <div className="font-mono text-xs text-dim">
                    {atlasStats.generated ? atlasStats.generated.slice(0, 10) : "—"}
                  </div>
                </div>
              </>
            ) : (
              <span className="text-xs text-dim">not generated yet — weekly rebuild pending</span>
            )}
          </div>
        </div>
      </a>

      <div className="grid md:grid-cols-2 gap-4">
        {/* Research Bot Sentiment Data */}
        <Card title="Political & Regulatory Sentiment Bot">
          {regulatorySignals.length === 0 ? (
            <Empty message="No research signals ingested yet via /api/webhooks/research-signal." />
          ) : (
            <ul className="space-y-3 text-sm">
              {regulatorySignals.map((s) => (
                <li key={s.id} className="border-l-2 pl-3" style={{ borderColor: s.sentimentScore > 0 ? '#34d399' : s.sentimentScore < 0 ? '#f87171' : '#9ca3af' }}>
                  <div className="flex justify-between">
                    <span className="font-medium text-ink">{s.marketCategory}</span>
                    <span className={`font-mono ${s.sentimentScore > 0 ? 'text-pos' : s.sentimentScore < 0 ? 'text-neg' : 'text-dim'}`}>
                      {s.sentimentScore > 0 ? '+' : ''}{s.sentimentScore.toFixed(2)}
                    </span>
                  </div>
                  <div className="text-dim text-xs mt-0.5 break-words">
                    {s.source} — {s.processedAt.toISOString().slice(5, 16).replace("T", " ")}
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="text-xs text-dim mt-3 pt-3 border-t border-edge">
            Connects to Quiver Quant & GovInfo APIs to extract off-chain political alpha.
          </div>
        </Card>

        {/* C-200 Predictive Signals Summary */}
        <Card title="C-200 Predictive Signals (Last 100 Trades)">
          {recentC200Trades.length === 0 ? (
            <Empty message="No trades available to analyze." />
          ) : (
             <div className="space-y-4 mt-2">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-dim">Swarm Signaled</span>
                  <span className="font-mono font-medium">{swarmCount}</span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-dim">Whale-Wake Maker Limits</span>
                  <span className="font-mono font-medium">{whaleWakeCount}</span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-dim">Trend Following</span>
                  <span className="font-mono font-medium">{trendCount}</span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-dim">Mean Reversion Aversions</span>
                  <span className="font-mono font-medium">{meanReversionCount}</span>
                </div>
                <div className="mt-4 pt-3 border-t border-edge flex justify-between items-center text-sm">
                  <span className="text-dim">Kalshi Arbitrage Routes</span>
                  <span className="font-mono font-medium text-accent">{kalshiCount} / {recentC200Trades.length}</span>
                </div>
             </div>
          )}
        </Card>
      </div>

    </div>
  );
}