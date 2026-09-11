import Link from "next/link";
import { prisma } from "@/lib/db";
import { Card, Stat, Pnl, Badge, Empty } from "@/components/ui";
import { LineChart } from "@/components/chart";
import { getActiveRules } from "@/lib/rules";
import { effectiveExposureCap, exposureCapNote } from "@/lib/exposure-cap";
import { c200HourPolicy, etHourNow } from "@/lib/hour-policy";
import { summarizeDayPnl, combinedTodayPnl, dayWindow, rowsFinishedIn, finishedAt } from "@/lib/day-pnl";
import { researchCategoryFor } from "@/lib/research-categories";
import { readFileSync, readdirSync, statSync } from "fs";
import path from "path";

export const dynamic = "force-dynamic";

export default async function Overview() {
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);
  const asOfUtc = new Date().toISOString().slice(11, 16);

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
    closedTodayC200Rows,
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
      prisma.paperTrade.findMany({
        where: {
          botId: 'BANKROLL_200',
          status: { in: ['closed', 'resolved'] },
          // TR-15 (2026-09-03): include early exits (realized books at
          // closedAt; resolvedAt is NULL for those rows).
          OR: [{ resolvedAt: { gte: startOfDay } }, { closedAt: { gte: startOfDay } }],
        },
        // Rows rather than an aggregate: the Today's-PnL card needs today's
        // win/loss split, best/worst and per-venue realized. Totals are
        // unchanged — the daily-loss gate still reads sum(realizedPnl).
        select: { realizedPnl: true, unrealizedPnl: true, venue: true },
      }),
      prisma.paperTrade.aggregate({
        where: { botId: 'BANKROLL_200', status: 'open' },
        _sum: { unrealizedPnl: true, simulatedPositionSize: true }
      })
    ]);

  const activeRules = await getActiveRules();

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

  const c200Bankroll = bankrolls.find(b => b.botId === "BANKROLL_200") || { principal: 200, cashBalance: 0, realizedPnl: 0 };
  // Today's PnL (2026-09-11 card). c200OpenMtm + todayC200.realized are the two
  // distinct halves; todayC200Pnl keeps the historical Goal-Trajectory formula
  // (realized + residual unrealized on today's finishes + open book MTM).
  const c200OpenMtm = openTradesC200._sum.unrealizedPnl ?? 0;
  const todayC200 = summarizeDayPnl(closedTodayC200Rows);
  const todayC200Pnl = combinedTodayPnl(todayC200, c200OpenMtm);

  // v45 risk-gate live state — mirrors scripts/score-trades.ts gate math so the
  // dashboard shows the same numbers the scorer enforces on the next cycle.
  const riskRules = activeRules.rules;
  const c200OpenNotional = openTradesC200._sum.simulatedPositionSize ?? 0;
  const c200OpenCount = cmpOpen.length;
  const c200RealizedToday = todayC200.realized;
  const c200NetWorth =
    (c200Bankroll.principal ?? 0) + (c200Bankroll.realizedPnl ?? 0) + (openTradesC200._sum.unrealizedPnl ?? 0);
  let c200Peak = 0;
  try {
    c200Peak = JSON.parse(readFileSync(path.join(process.cwd(), "data", "c200-drawdown.json"), "utf-8")).peak ?? 0;
  } catch { /* not seeded yet */ }
  c200Peak = Math.max(c200Peak, c200Bankroll.principal ?? 0);
  const c200DrawdownPct = c200Peak > 0 ? Math.max(0, (c200Peak - c200NetWorth) / c200Peak) : 0;
  const ddCap = riskRules.maxDrawdownPct > 0 ? riskRules.maxDrawdownPct : 0.2;
  const c200ExposureCapEff = effectiveExposureCap(
    riskRules.maxGrossExposureUsd,
    c200NetWorth,
    c200Bankroll.principal ?? 0
  );
  const exposurePct = c200ExposureCapEff > 0 ? (c200OpenNotional / c200ExposureCapEff) * 100 : 0;
  const countPct = riskRules.maxOpenPositions > 0 ? (c200OpenCount / riskRules.maxOpenPositions) * 100 : 0;
  const ddPct = (c200DrawdownPct / ddCap) * 100;
  const gates = [
    { label: "Gross exposure", usage: exposurePct, note: `$${c200OpenNotional.toFixed(0)} / $${c200ExposureCapEff.toFixed(0)} eff` },
    { label: "Open positions", usage: countPct, note: `${c200OpenCount} / ${riskRules.maxOpenPositions}` },
    { label: "Drawdown", usage: ddPct, note: `${(c200DrawdownPct * 100).toFixed(1)}% / ${(ddCap * 100).toFixed(0)}%` },
  ];
  const nearestGate = gates.reduce((a, b) => (b.usage > a.usage ? b : a), gates[0]);

  // ── Circuit-breaker state — mirrors score-trades.ts gate logic per breaker ──
  const cooldownMs = (riskRules.tokenCircuitBreakerCooldownMin ?? 30) * 60_000;
  const [recentTokenTrips, kalshiAgg, c200OpenDetail] = await Promise.all([
    prisma.tokenCircuitTrip.count({ where: { trippedAt: { gte: new Date(Date.now() - cooldownMs) } } }),
    prisma.paperTrade.aggregate({
      where: { botId: "BANKROLL_200", venue: "Kalshi", status: { in: ["closed", "resolved"] } },
      _sum: { realizedPnl: true },
    }),
    prisma.paperTrade.findMany({
      where: { botId: "BANKROLL_200", status: "open" },
      select: {
        decision: { select: { observedTrade: { select: { marketQuestion: true, marketCategory: true } } } },
      },
    }),
  ]);
  const kalshiRealized = kalshiAgg._sum.realizedPnl ?? 0;
  const openCatCounts = new Map<string, number>();
  const openSlugCounts = new Map<string, number>();
  for (const row of c200OpenDetail) {
    const ot = row.decision?.observedTrade;
    const cat = researchCategoryFor(ot?.marketQuestion, ot?.marketCategory);
    if (cat) openCatCounts.set(cat, (openCatCounts.get(cat) ?? 0) + 1);
    if (ot?.marketCategory) openSlugCounts.set(ot.marketCategory, (openSlugCounts.get(ot.marketCategory) ?? 0) + 1);
  }
  const topCat = [...openCatCounts.entries()].sort((a, b) => b[1] - a[1])[0];
  const topSlug = [...openSlugCounts.entries()].sort((a, b) => b[1] - a[1])[0];
  const hourPol = c200HourPolicy(etHourNow());
  const etHourNowLabel = etHourNow();

  type Breaker = { key: string; label: string; tone: "pos" | "warn" | "neg"; state: string; title: string };
  const breakers: Breaker[] = [];
  const dailyFloor = riskRules.dailyLossLimitUsd ?? -150;
  const dailyTrip = c200RealizedToday < dailyFloor;
  breakers.push({
    key: "daily-loss",
    label: "Daily loss limit",
    tone: dailyTrip ? "neg" : c200RealizedToday < 0 ? "warn" : "pos",
    state: dailyTrip
      ? `TRIPPED ${c200RealizedToday >= 0 ? "+" : ""}$${c200RealizedToday.toFixed(2)} — halting new copies`
      : `${c200RealizedToday >= 0 ? "+" : ""}$${c200RealizedToday.toFixed(2)} vs −$${Math.abs(dailyFloor)}`,
    title: "Halts new C-200 copies when today's realized PnL (incl. early exits, TR-15) is below the floor",
  });
  const exposureTrip = c200OpenNotional >= c200ExposureCapEff;
  breakers.push({
    key: "exposure",
    label: "Gross exposure",
    tone: exposureTrip ? "neg" : c200ExposureCapEff > 0 && exposurePct >= 60 ? "warn" : "pos",
    state: exposureTrip
      ? `AT CAP $${c200OpenNotional.toFixed(0)} / $${c200ExposureCapEff.toFixed(0)}`
      : `$${c200OpenNotional.toFixed(0)} / $${c200ExposureCapEff.toFixed(0)} eff`,
    title: exposureCapNote(riskRules.maxGrossExposureUsd, c200NetWorth, c200Bankroll.principal ?? 0),
  });
  const posTrip = c200OpenCount >= riskRules.maxOpenPositions;
  breakers.push({
    key: "positions",
    label: "Position cap",
    tone: posTrip ? "neg" : countPct >= 60 ? "warn" : "pos",
    state: posTrip ? `AT CAP ${c200OpenCount} / ${riskRules.maxOpenPositions}` : `${c200OpenCount} / ${riskRules.maxOpenPositions}`,
    title: "Max open C-200 positions (v29 capital recycling)",
  });
  const ddTrip = c200DrawdownPct >= ddCap;
  breakers.push({
    key: "drawdown",
    label: "Drawdown gate",
    tone: ddTrip ? "neg" : ddPct >= 60 ? "warn" : "pos",
    state: ddTrip
      ? `TRIPPED ${(c200DrawdownPct * 100).toFixed(1)}% off peak`
      : `${(c200DrawdownPct * 100).toFixed(1)}% / ${(ddCap * 100).toFixed(0)}% off peak`,
    title: "Halts new copies when (peak − net worth)/peak exceeds the cap (peak tracked in data/c200-drawdown.json)",
  });
  const catCap = riskRules.maxCategoryPositions ?? 0;
  const catTrip = catCap > 0 && topCat ? topCat[1] >= catCap : false;
  breakers.push({
    key: "category",
    label: "Category cap",
    tone: catTrip ? "neg" : topCat && catCap > 0 && topCat[1] / catCap >= 0.75 ? "warn" : "pos",
    state: topCat ? `${topCat[1]} / ${catCap} · ${topCat[0]}` : "no mapped categories open",
    title: "Max open C-200 positions per research category (v41); unmapped 'Other' uncapped",
  });
  const slugCap = riskRules.maxMarketSlugPositions ?? 0;
  const slugTrip = slugCap > 0 && topSlug ? topSlug[1] >= slugCap : false;
  breakers.push({
    key: "slug",
    label: "Market-slug cap",
    tone: slugTrip ? "neg" : topSlug && slugCap > 0 && topSlug[1] / slugCap >= 0.75 ? "warn" : "pos",
    state: topSlug ? `${topSlug[1]} / ${slugCap} · ${topSlug[0]}` : "no slug-mapped positions",
    title: "Per raw marketCategory slug cap (v45 — closes the esports→'Other' hole)",
  });
  const tokenTrip = recentTokenTrips > 0;
  breakers.push({
    key: "token",
    label: "Token circuit breaker",
    tone: tokenTrip ? "warn" : "pos",
    state: tokenTrip
      ? `TRIPPED ×${recentTokenTrips} in last ${Math.round(cooldownMs / 60000)}m`
      : `clean — no flash moves in last ${Math.round(cooldownMs / 60000)}m`,
    title: "Per-market flash-move trip (15% in 5m); trips skip that market for the cooldown window",
  });
  breakers.push({
    key: "hour",
    label: "Hour policy",
    tone: hourPol.blackout ? "neg" : hourPol.sizeFactor !== 1 ? "warn" : "pos",
    state: hourPol.blackout
      ? `BLACKOUT — entries halted (${etHourNowLabel}:00 ET)`
      : hourPol.sizeFactor !== 1
        ? `HAIRCUT ×${hourPol.sizeFactor} (${etHourNowLabel}:00 ET)`
        : `clear (${etHourNowLabel}:00 ET)`,
    title: "20:00 ET blackout (v48: 23:00 un-gated — phantom-Kalshi artifact); 10:00 ET 50% size haircut (C-200)",
  });
  const kalshiFloor = riskRules.kalshiCircuitBreakerPnl ?? -50;
  const kalshiTrip = kalshiRealized < kalshiFloor;
  breakers.push({
    key: "kalshi",
    label: "Kalshi routing",
    tone: kalshiTrip ? "neg" : "pos",
    state: kalshiTrip
      ? `PAUSED — venue realized $${kalshiRealized.toFixed(0)} < −$${Math.abs(kalshiFloor)}`
      : `ok — $${kalshiRealized.toFixed(0)} vs −$${Math.abs(kalshiFloor)}`,
    title: "Kalshi execution pauses while the Kalshi leg's realized PnL is below the floor (phantom-0.50 era trades — see kalshi-reprice-92)",
  });

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
    select: { realizedPnl: true, unrealizedPnl: true, venue: true, closedAt: true, resolvedAt: true },
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

  // Yesterday's closed day (2026-09-11 card). Same definition as c200Daily[1]:
  // realized booked on the previous local calendar day, bucketed by
  // closedAt ?? resolvedAt (TR-15 early exits book at closedAt). Frozen at
  // midnight — src/lib/paper.ts stamps both timestamps with `new Date()` at run
  // time, so nothing writes into a past day. Reuses the 7-day ladder rows.
  const yesterdayWindow = dayWindow(-1);
  const yesterdayC200Rows = rowsFinishedIn(finishedC200, yesterdayWindow.start, yesterdayWindow.end);
  const yesterdayC200 = summarizeDayPnl(yesterdayC200Rows);
  const yesterdayStart = yesterdayWindow.start;
  const yesterdayLabel = `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][yesterdayStart.getDay()]} ${yesterdayStart.getFullYear()}-${String(yesterdayStart.getMonth() + 1).padStart(2, "0")}-${String(yesterdayStart.getDate()).padStart(2, "0")}`;
  const yesterdayLastBooking = yesterdayC200Rows
    .map((r) => finishedAt(r))
    .filter((d): d is Date => d != null)
    .sort((a, b) => b.getTime() - a.getTime())[0] ?? null;
  const yesterdayLastBookingLabel = yesterdayLastBooking
    ? `${String(yesterdayLastBooking.getHours()).padStart(2, "0")}:${String(yesterdayLastBooking.getMinutes()).padStart(2, "0")}`
    : "—";

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

  // Latest deliverables (audits / design docs) from the drafts dir, newest first
  const DRAFTS_DIR = path.join(process.cwd(), "drafts");
  let recentDrafts: { slug: string; title: string; mtime: string }[] = [];
  try {
    recentDrafts = readdirSync(DRAFTS_DIR)
      .filter((f) => f.endsWith(".md"))
      .map((f) => {
        const st = statSync(path.join(DRAFTS_DIR, f));
        return {
          slug: f.replace(/\.md$/i, ""),
          title: f
            .replace(/\.md$/i, "")
            .replace(/[-_]+/g, " ")
            .replace(/\b\w/g, (c) => c.toUpperCase()),
          mtime: new Date(st.mtimeMs).toISOString().slice(0, 10),
        };
      })
      .sort((a, b) => (a.mtime < b.mtime ? 1 : -1))
      .slice(0, 6);
  } catch {
    /* drafts dir missing — card shows empty state */
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
            <div className="text-dim">Today's PnL (realized + open MTM): <span className="text-ink font-mono font-medium">${todayC200Pnl.toFixed(2)}</span></div>
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

      {/* C-200 Today's PnL — realized vs open mark-to-market (2026-09-11) */}
      <Card title="C-200 — Today&apos;s PnL">
        <div className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-[10px] text-dim uppercase tracking-wide">
                Realized today — finished since 00:00 local (TR-15 early exits included)
              </div>
              <div
                className={`text-3xl font-bold font-mono mt-1 ${
                  todayC200.realized > 0 ? "text-pos" : todayC200.realized < 0 ? "text-neg" : "text-ink"
                }`}
              >
                {todayC200.realized >= 0 ? "+" : "-"}${Math.abs(todayC200.realized).toFixed(2)}
              </div>
              <div className="text-xs text-dim mt-1">
                {todayC200.closedCount} finished today · {todayC200.wins}W / {todayC200.losses}L
                {todayC200.scratch > 0 ? ` / ${todayC200.scratch} scratch` : ""} · best{" "}
                <span className="font-mono text-pos">+${todayC200.best.toFixed(2)}</span> / worst{" "}
                <span className="font-mono text-neg">-${Math.abs(todayC200.worst).toFixed(2)}</span>
              </div>
            </div>
            <div className="text-right text-xs text-dim">
              <div>as of <span className="font-mono">{asOfUtc}</span> UTC</div>
              <Link href="/paper-trades" className="text-accent hover:text-ink transition-colors">
                trade log →
              </Link>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="border border-edge rounded-lg p-3 bg-edge/10">
              <div className="text-[10px] text-dim uppercase tracking-wide">Open MTM (whole book)</div>
              <div className={`font-mono text-sm mt-1 ${c200OpenMtm > 0 ? "text-pos" : c200OpenMtm < 0 ? "text-neg" : "text-ink"}`}>
                {c200OpenMtm >= 0 ? "+" : "-"}${Math.abs(c200OpenMtm).toFixed(2)}
              </div>
              <div className="text-[10px] text-dim mt-0.5">
                {c200OpenCount} open · ${c200OpenNotional.toFixed(0)} notional
              </div>
            </div>

            <div className="border border-edge rounded-lg p-3 bg-edge/10">
              <div className="text-[10px] text-dim uppercase tracking-wide">Combined now</div>
              <div className={`font-mono text-sm mt-1 ${todayC200Pnl > 0 ? "text-pos" : todayC200Pnl < 0 ? "text-neg" : "text-ink"}`}>
                {todayC200Pnl >= 0 ? "+" : "-"}${Math.abs(todayC200Pnl).toFixed(2)}
              </div>
              <div className="text-[10px] text-dim mt-0.5">realized + open MTM</div>
            </div>

            <div className="border border-edge rounded-lg p-3 bg-edge/10">
              <div className="text-[10px] text-dim uppercase tracking-wide">Headroom to halt</div>
              <div
                className={`font-mono text-sm mt-1 ${
                  c200RealizedToday < (riskRules.dailyLossLimitUsd ?? -150) ? "text-neg" : "text-pos"
                }`}
              >
                ${(c200RealizedToday - (riskRules.dailyLossLimitUsd ?? -150)).toFixed(2)}
              </div>
              <div className="text-[10px] text-dim mt-0.5">floor -${Math.abs(riskRules.dailyLossLimitUsd ?? -150)}</div>
            </div>

            <div className="border border-edge rounded-lg p-3 bg-edge/10">
              <div className="text-[10px] text-dim uppercase tracking-wide">By venue today</div>
              <div className="mt-1 space-y-0.5">
                {todayC200.byVenue.length === 0 ? (
                  <div className="font-mono text-xs text-dim">nothing finished</div>
                ) : (
                  todayC200.byVenue.map((v) => (
                    <div key={v.venue} className="flex items-center justify-between gap-2 text-xs">
                      <span className="text-dim truncate">{v.venue}</span>
                      <span className={`font-mono ${v.realized > 0 ? "text-pos" : v.realized < 0 ? "text-neg" : "text-dim"}`}>
                        {v.realized >= 0 ? "+" : "-"}${Math.abs(v.realized).toFixed(2)}
                        <span className="text-dim"> ({v.count})</span>
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="text-[10px] text-dim pt-2 border-t border-edge">
            Realized = trades finished today; the daily-loss breaker and the phase ladder key off this figure. Open MTM is
            the whole open book&apos;s mark, not today&apos;s move — the Goal Trajectory card adds it to realized, which is
            why its heading now says so.
          </div>
        </div>
      </Card>

      {/* C-200 Yesterday's PnL — the previous closed day (2026-09-11) */}
      <Card title="C-200 — Yesterday&apos;s PnL">
        <div className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-[10px] text-dim uppercase tracking-wide">
                Realized on {yesterdayLabel} — booked before 00:00 local (TR-15 early exits included)
              </div>
              <div
                className={`text-3xl font-bold font-mono mt-1 ${
                  yesterdayC200.realized > 0 ? "text-pos" : yesterdayC200.realized < 0 ? "text-neg" : "text-ink"
                }`}
              >
                {yesterdayC200.realized >= 0 ? "+" : "-"}${Math.abs(yesterdayC200.realized).toFixed(2)}
              </div>
              <div className="text-xs text-dim mt-1">
                {yesterdayC200.closedCount} finished · {yesterdayC200.wins}W / {yesterdayC200.losses}L
                {yesterdayC200.scratch > 0 ? ` / ${yesterdayC200.scratch} scratch` : ""} · best{" "}
                <span className="font-mono text-pos">+${yesterdayC200.best.toFixed(2)}</span> / worst{" "}
                <span className="font-mono text-neg">-${Math.abs(yesterdayC200.worst).toFixed(2)}</span>
              </div>
            </div>
            <div className="text-right text-xs text-dim">
              <span className="inline-block border border-edge rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide">
                day closed
              </span>
              <div className="mt-1">frozen at 00:00 — no writes into a past day</div>
              <Link href="/paper-trades" className="text-accent hover:text-ink transition-colors">
                trade log →
              </Link>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="border border-edge rounded-lg p-3 bg-edge/10">
              <div className="text-[10px] text-dim uppercase tracking-wide">vs ${c200Goal.target.toLocaleString()}/day target</div>
              <div
                className={`font-mono text-sm mt-1 ${
                  yesterdayC200.realized - c200Goal.target >= 0 ? "text-pos" : "text-neg"
                }`}
              >
                {yesterdayC200.realized - c200Goal.target >= 0 ? "+" : "-"}$
                {Math.abs(yesterdayC200.realized - c200Goal.target).toFixed(2)}
              </div>
              <div className="text-[10px] text-dim mt-0.5">{c200Goal.name} · {c200Goal.target.toLocaleString()}/day</div>
            </div>

            <div className="border border-edge rounded-lg p-3 bg-edge/10">
              <div className="text-[10px] text-dim uppercase tracking-wide">Streak credit</div>
              <div
                className={`font-mono text-sm mt-1 ${
                  yesterdayC200.realized >= c200Goal.target ? "text-pos" : "text-neg"
                }`}
              >
                {yesterdayC200.realized >= c200Goal.target ? "counted" : "missed"}
              </div>
              <div className="text-[10px] text-dim mt-0.5">
                ladder bucket ${c200Daily[1].toFixed(2)} · needs ${c200Goal.target.toLocaleString()}
              </div>
            </div>

            <div className="border border-edge rounded-lg p-3 bg-edge/10">
              <div className="text-[10px] text-dim uppercase tracking-wide">Booked through</div>
              <div className="font-mono text-sm mt-1 text-ink">{yesterdayLastBookingLabel}</div>
              <div className="text-[10px] text-dim mt-0.5">latest finish that day</div>
            </div>

            <div className="border border-edge rounded-lg p-3 bg-edge/10">
              <div className="text-[10px] text-dim uppercase tracking-wide">By venue</div>
              <div className="mt-1 space-y-0.5">
                {yesterdayC200.byVenue.length === 0 ? (
                  <div className="font-mono text-xs text-dim">nothing finished</div>
                ) : (
                  yesterdayC200.byVenue.map((v) => (
                    <div key={v.venue} className="flex items-center justify-between gap-2 text-xs">
                      <span className="text-dim truncate">{v.venue}</span>
                      <span className={`font-mono ${v.realized > 0 ? "text-pos" : v.realized < 0 ? "text-neg" : "text-dim"}`}>
                        {v.realized >= 0 ? "+" : "-"}${Math.abs(v.realized).toFixed(2)}
                        <span className="text-dim"> ({v.count})</span>
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="text-[10px] text-dim pt-2 border-t border-edge">
            Settled figures: the window only advances at 00:00 local, and closedAt/resolvedAt are stamped at run time
            (src/lib/paper.ts), so a past day cannot change. Two honest caveats — a market that resolved late in the evening
            but is first picked up by the next hourly update-pnl run books on the following day, and the 22:00 EOD report
            sums a rolling window since the previous report, so its number can differ from this calendar day.
          </div>
        </div>
      </Card>

      {/* C-200 risk gates — live state vs enforced caps (mirrors score-trades.ts) */}
      <Card title={`C-200 risk gates — live (ruleset v${activeRules.version})`}>
        <div className="space-y-3">
          {gates.map((g) => {
            const pct = Math.min(100, Math.max(0, g.usage));
            const color = g.usage >= 95 ? "bg-neg" : g.usage >= 60 ? "bg-warn" : "bg-pos";
            const isNearest = g.label === nearestGate.label;
            return (
              <div key={g.label}>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-dim">
                    {g.label}
                    {isNearest && (
                      <span className="ml-2 text-[9px] uppercase tracking-wider border border-accent/30 bg-accent/10 text-accent px-1.5 py-0.5 rounded-full">
                        nearest binder
                      </span>
                    )}
                  </span>
                  <span className={`font-mono ${g.usage >= 100 ? "text-neg" : "text-ink"}`}>
                    {g.note}
                    {g.usage >= 100 ? " ⚠ at cap" : ""}
                  </span>
                </div>
                <div className="w-full h-1.5 bg-edge rounded-full overflow-hidden">
                  <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
          <div className="flex items-center justify-between text-xs pt-2 border-t border-edge">
            <span className="text-dim">Today realized PnL vs daily halt</span>
            <span
              className={`font-mono ${
                c200RealizedToday < (riskRules.dailyLossLimitUsd ?? -150)
                  ? "text-neg"
                  : c200RealizedToday < 0
                    ? "text-warn"
                    : "text-pos"
              }`}
            >
              {c200RealizedToday >= 0 ? "+" : ""}
              ${c200RealizedToday.toFixed(2)} vs −{Math.abs(riskRules.dailyLossLimitUsd ?? -150)}
              {c200RealizedToday < (riskRules.dailyLossLimitUsd ?? -150) ? " · new copies halted" : ""}
            </span>
          </div>
          <div className="text-[10px] text-dim pt-1">
            Equity-linked exposure cap (v46): {exposureCapNote(riskRules.maxGrossExposureUsd, c200NetWorth, c200Bankroll.principal ?? 0)}
          </div>
        </div>
      </Card>

      {/* Circuit breakers — per-breaker tripped/armed status */}
      <Card title={`Circuit breakers — status (ruleset v${activeRules.version})`}>
        <div className="flex flex-wrap gap-2">
          {breakers.map((b) => {
            const toneCls =
              b.tone === "neg"
                ? "border-neg/40 bg-neg/10 text-neg"
                : b.tone === "warn"
                  ? "border-warn/40 bg-warn/10 text-warn"
                  : "border-pos/30 bg-pos/10 text-pos";
            const dotCls =
              b.tone === "neg"
                ? "bg-neg live-dot-neg"
                : b.tone === "warn"
                  ? "bg-warn live-dot-warn"
                  : "bg-pos live-dot-pos";
            return (
              <span
                key={b.key}
                title={b.title}
                className={`inline-flex items-center gap-1.5 border rounded-full pl-2.5 pr-3 py-1 text-[11px] font-mono ${toneCls}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotCls}`} />
                <span className="opacity-80 uppercase tracking-wide text-[9px]">{b.label}</span>
                <span className="font-medium">{b.state}</span>
              </span>
            );
          })}
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

      {/* Deliverables — clickable audits & design docs */}
      <Card title="Deliverables — latest audits & design docs">
        {recentDrafts.length === 0 ? (
          <Empty message="No drafts yet." />
        ) : (
          <>
            <ul className="grid md:grid-cols-2 gap-x-6 gap-y-0.5">
              {recentDrafts.map((d) => (
                <li key={d.slug}>
                  <Link
                    href={`/drafts/${d.slug}`}
                    className="flex items-center justify-between gap-3 py-1.5 text-sm group"
                  >
                    <span className="text-ink group-hover:text-accent truncate transition-colors">
                      {d.title}
                    </span>
                    <span className="text-[10px] text-dim font-mono shrink-0">{d.mtime}</span>
                  </Link>
                </li>
              ))}
            </ul>
            <div className="text-xs mt-2 pt-2 border-t border-edge">
              <Link href="/drafts" className="text-accent hover:text-ink transition-colors">
                Browse all deliverables →
              </Link>
            </div>
          </>
        )}
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