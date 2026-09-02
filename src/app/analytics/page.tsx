import { prisma } from "@/lib/db";
import { Card, Empty } from "@/components/ui";
import { LineChart, BarChart, Heatmap, Scatter } from "@/components/chart";
import { Enlargeable } from "@/components/enlargeable";
import { researchCategoryFor } from "@/lib/research-categories";
import { readFileSync } from "fs";
import { join } from "path";

export const dynamic = "force-dynamic";

const dayKey = (d: Date) => d.toISOString().slice(0, 10);
const fmt$ = (v: number) => `${v >= 0 ? "+" : ""}$${v.toFixed(0)}`;
const ET = "America/New_York";

function etParts(ms: number): { hour: number; weekday: number } {
  // Server-side timezone conversion via Intl (no tz lib needed).
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: ET,
    hour: "numeric",
    weekday: "short",
    hour12: false,
  });
  const parts = fmt.formatToParts(new Date(ms));
  let hour = 0;
  let weekday = 0;
  const wdMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  for (const p of parts) {
    if (p.type === "hour") hour = parseInt(p.value, 10) % 24;
    if (p.type === "weekday") weekday = wdMap[p.value] ?? 0;
  }
  return { hour, weekday };
}

const PHASES = [500, 1000, 2000, 5000];

function activePhase(daily: { day: string; pnl: number }[]): { goal: number; streak: number; phaseName: string } {
  const sorted = [...daily].sort((a, b) => b.day.localeCompare(a.day));
  const names = ["Phase 1", "Phase 2", "Phase 3", "Ultimate"];
  for (let i = 0; i < PHASES.length; i++) {
    let streak = 0;
    for (const d of sorted) {
      if (d.pnl >= PHASES[i]) streak++;
      else break;
    }
    if (streak < 7) return { goal: PHASES[i], streak, phaseName: names[i] };
  }
  return { goal: PHASES[3], streak: 7, phaseName: "Ultimate" };
}

function parseBaselineCsv(text: string): { price: number; total: number; winRate: number }[] {
  return text
    .trim()
    .split("\n")
    .slice(1)
    .map((l) => {
      const [price, total, , wr] = l.split(",");
      return { price: parseFloat(price), total: parseFloat(total), winRate: parseFloat(wr) / 100 };
    });
}

export default async function Analytics() {
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);

  const [
    c200Resolved,
    snapshots,
    decisions,
    allResolved,
    trackedWallets,
    insiderScores,
    cal,
    baselineCsv,
  ] = await Promise.all([
    prisma.paperTrade.findMany({
      where: { botId: "BANKROLL_200", status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } },
      select: { realizedPnl: true, resolvedAt: true, openedAt: true },
    }),
    prisma.$queryRaw<Array<{ day: string; botId: string; total_pnl: number }>>`
      SELECT strftime('%Y-%m-%d', s.collectedAt / 1000, 'unixepoch') as day, t.botId, SUM(s.pnl) as total_pnl
      FROM PnlSnapshot s JOIN PaperTrade t ON s.paperTradeId = t.id
      GROUP BY day, t.botId ORDER BY day ASC
    `,
    prisma.decisionJournal.findMany({
      include: { observedTrade: true, paperTrades: true, outcomeReviews: true },
      orderBy: { createdAt: "asc" },
    }),
    prisma.paperTrade.findMany({
      where: { status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } },
      include: { decision: { include: { observedTrade: true } } },
    }),
    prisma.walletProfile.findMany({ where: { status: "track" }, select: { address: true, globalScore: true } }),
    prisma.walletInsiderScore.findMany({ select: { walletAddress: true, flagged: true, watch: true } }),
    (() => {
      try {
        return JSON.parse(readFileSync(join(process.cwd(), "data", "calibration-analysis.json"), "utf8")) as {
          bands?: Array<{ band: string; winRate: number; avgEntry: number; n: number }>;
        };
      } catch {
        return null;
      }
    })(),
    (() => {
      try {
        return readFileSync(join(process.cwd(), "data", "polymarket-calibration-baseline.csv"), "utf8");
      } catch {
        return null;
      }
    })(),
  ]);

  // ---------- 1. C-200 daily PnL bars vs goal ----------
  const dailyMap = new Map<string, number>();
  for (const t of c200Resolved) {
    const d = dayKey(t.resolvedAt ?? t.openedAt);
    dailyMap.set(d, (dailyMap.get(d) ?? 0) + (t.realizedPnl ?? 0));
  }
  const daily = [...dailyMap.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .slice(-21)
    .map(([day, pnl]) => ({ day: day.slice(5), pnl: Math.round(pnl * 100) / 100 }));
  const phase = activePhase(daily.map((d) => ({ day: d.day, pnl: d.pnl })));
  const streakFrom = Math.max(0, daily.length - phase.streak);
  const dailyBars = daily.map((d) => ({ x: d.day, y: d.pnl }));

  // ---------- 2. Equity curves + Oct-1 projection ----------
  const eqByBot = new Map<string, { day: string; cum: number }[]>();
  for (const s of snapshots) {
    const arr = eqByBot.get(s.botId) ?? [];
    const cum = arr.length ? arr[arr.length - 1].cum + s.total_pnl : s.total_pnl;
    arr.push({ day: s.day, cum: Math.round(cum * 100) / 100 });
    eqByBot.set(s.botId, arr);
  }
  const c200Eq = (eqByBot.get("BANKROLL_200") ?? []).map((p) => ({ x: p.day.slice(5), y: p.cum }));
  const stdEq = (eqByBot.get("STANDARD") ?? []).map((p) => ({ x: p.day.slice(5), y: p.cum }));
  // Projection: last-7d daily average realized -> linear to Oct 1.
  const last7 = daily.slice(-7);
  const avg7 = last7.length ? last7.reduce((a, d) => a + d.pnl, 0) / last7.length : 0;
  const projPoints: { x: string; y: number }[] = [];
  if (c200Eq.length > 0) {
    const start = c200Eq[c200Eq.length - 1];
    const oct1 = new Date("2026-10-01T00:00:00");
    const now = new Date();
    let cur = start.y;
    for (let d = new Date(now); d <= oct1; d.setDate(d.getDate() + 1)) {
      projPoints.push({ x: dayKey(d).slice(5), y: Math.round(cur * 100) / 100 });
      cur += avg7;
    }
  }

  // ---------- 3. Calibration curve (ours vs market-wide baseline) ----------
  let calPoints: { x: number; y: number }[] = [];
  let basePoints: { x: number; y: number }[] = [];
  if (cal?.bands && baselineCsv) {
    calPoints = cal.bands.map((b) => ({ x: b.avgEntry, y: b.winRate }));
    const rows = parseBaselineCsv(baselineCsv);
    const bandOf = (p: number) => (p < 20 ? 0 : p < 40 ? 1 : p < 60 ? 2 : p < 80 ? 3 : 4);
    const agg = new Map<number, { w: number; wt: number }>();
    for (const r of rows) {
      const b = bandOf(r.price);
      const cur = agg.get(b) ?? { w: 0, wt: 0 };
      cur.w += r.winRate * r.total;
      cur.wt += r.total;
      agg.set(b, cur);
    }
    const mids = [0.1, 0.3, 0.5, 0.7, 0.9];
    basePoints = [...agg.entries()].map(([b, v]) => ({ x: mids[b], y: v.wt ? v.w / v.wt : 0 }));
  }

  // ---------- 4. Hour x weekday heatmap ----------
  const heat = new Map<string, { v: number; n: number }>();
  for (const t of allResolved) {
    const ms = (t.resolvedAt ?? t.openedAt).getTime();
    const { hour, weekday } = etParts(ms);
    const k = `${weekday}-${hour}`;
    const cur = heat.get(k) ?? { v: 0, n: 0 };
    cur.v += t.realizedPnl ?? 0;
    cur.n++;
    heat.set(k, cur);
  }
  const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const heatCells = [...heat.entries()].map(([k, v]) => {
    const [wd, hr] = k.split("-").map(Number);
    return { x: hr, y: wd, v: Math.round(v.v * 100) / 100, n: v.n };
  });

  // ---------- 5. Decision funnel ----------
  const funnel = new Map<string, number>();
  for (const d of decisions) funnel.set(d.decision, (funnel.get(d.decision) ?? 0) + 1);
  const funnelMax = Math.max(...[...funnel.values(), 1]);
  const funnelOrder = ["paper_copy", "watchlist", "skip"];
  const funnelRows = funnelOrder.map((k) => ({ key: k, count: funnel.get(k) ?? 0 }));

  // ---------- 6. Benchmark cumulative curves ----------
  const HYP = 10;
  const benchSeries = new Map<string, { day: string; pnl: number }[]>();
  const pushB = (label: string, day: string, pnl: number) => {
    const arr = benchSeries.get(label) ?? [];
    arr.push({ day, pnl });
    benchSeries.set(label, arr);
  };
  for (const d of decisions) {
    const day = dayKey(d.createdAt);
    const review = d.outcomeReviews.find((r) => r.finalOutcome !== null);
    let hypo: number | null = null;
    if (review?.finalOutcome && d.observedTrade) {
      const won = review.finalOutcome === d.observedTrade.outcome;
      const entry = d.observedTrade.detectedPrice;
      hypo = HYP * (won ? 1 - entry : -entry);
    }
    if (hypo !== null) pushB("Blind copy", day, hypo);
    if (d.decision === "paper_copy") {
      const pnl = d.paperTrades[0]?.realizedPnl ?? null;
      if (pnl !== null) pushB("Bot (actual)", day, pnl);
    } else if (d.decision === "watchlist" && hypo !== null) {
      pushB("Watchlist (hypo)", day, hypo);
    } else if (d.decision === "skip" && hypo !== null) {
      pushB("Skipped (hypo)", day, hypo);
    }
  }
  const benchLines = [...benchSeries.entries()].map(([label, rows]) => {
    const sorted = rows.sort((a, b) => a.day.localeCompare(b.day));
    let cum = 0;
    const points = sorted.map((r) => {
      cum += r.pnl;
      return { x: r.day.slice(5), y: Math.round(cum * 100) / 100 };
    });
    const colors: Record<string, string> = {
      "Bot (actual)": "#34d399",
      "Blind copy": "#f87171",
      "Watchlist (hypo)": "#fbbf24",
      "Skipped (hypo)": "#8b93a7",
    };
    return { name: label, points, strokeColor: colors[label] ?? "#3b82f6" };
  });

  // ---------- 7. Category + venue bars ----------
  const byCat = new Map<string, number>();
  for (const t of allResolved) {
    const q = t.decision?.observedTrade?.marketQuestion;
    const cat = researchCategoryFor(q ?? null) ?? "uncategorized";
    byCat.set(cat, (byCat.get(cat) ?? 0) + (t.realizedPnl ?? 0));
  }
  const catBars = [...byCat.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([cat, pnl]) => ({ x: cat.length > 12 ? cat.slice(0, 12) + "…" : cat, y: Math.round(pnl) }));
  const byVenue = new Map<string, number>();
  for (const t of allResolved) {
    const v = t.venue ?? "Polymarket";
    byVenue.set(v, (byVenue.get(v) ?? 0) + (t.realizedPnl ?? 0));
  }
  const venueBars = [...byVenue.entries()].map(([v, pnl]) => ({ x: v, y: Math.round(pnl) }));

  // ---------- 8. Rule-version cohorts ----------
  const byVersion = new Map<string, number>();
  for (const t of allResolved) {
    const v = `v${t.decision?.ruleSetVersion ?? "?"}`;
    byVersion.set(v, (byVersion.get(v) ?? 0) + (t.realizedPnl ?? 0));
  }
  const versionBars = [...byVersion.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }))
    .map(([v, pnl]) => ({ x: v, y: Math.round(pnl) }));

  // ---------- 9. Wallet scatter ----------
  const walletStats = await prisma.paperTrade.groupBy({
    by: ["walletAddress"],
    where: { status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } },
    _sum: { realizedPnl: true },
    _count: true,
  });
  const winByWallet = new Map<string, number>();
  for (const t of allResolved) {
    const won = (t.realizedPnl ?? 0) > 0 ? 1 : 0;
    winByWallet.set(t.walletAddress, (winByWallet.get(t.walletAddress) ?? 0) + won);
  }
  const countByWallet = new Map<string, number>();
  for (const t of allResolved) {
    countByWallet.set(t.walletAddress, (countByWallet.get(t.walletAddress) ?? 0) + 1);
  }
  const insiderByAddr = new Map(insiderScores.map((s) => [s.walletAddress, s]));
  const scatterPoints = trackedWallets
    .map((w) => {
      const n = countByWallet.get(w.address) ?? 0;
      const wins = winByWallet.get(w.address) ?? 0;
      const ins = insiderByAddr.get(w.address);
      return {
        x: Math.round(w.globalScore * 10) / 10,
        y: n ? Math.round((wins / n) * 100) / 100 : 0,
        label: `${w.address.slice(0, 6)}… (n=${n})`,
        color: ins?.flagged ? "#f87171" : ins?.watch ? "#fbbf24" : n >= 15 ? "#34d399" : "#3b82f6",
        r: ins?.flagged ? 6 : 4,
      };
    })
    .filter((p) => p.y > 0 || p.x > 0);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Analytics</h1>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title={`C-200 Daily PnL vs ${phase.phaseName} Goal ($${phase.goal}/day)`}>
          <Enlargeable label={`C-200 Daily PnL vs ${phase.phaseName} Goal ($${phase.goal}/day)`}>
            <BarChart
              bars={dailyBars}
              goalLine={phase.goal}
              goalLabel={`$${phase.goal}/day`}
              highlight={phase.streak > 0 ? { label: `${phase.streak}-day streak`, from: streakFrom, to: daily.length - 1 } : undefined}
              formatY={fmt$}
            />
          </Enlargeable>
          <p className="text-xs text-dim mt-2">
            {phase.streak} consecutive day(s) ≥ ${phase.goal} — {7 - Math.min(phase.streak, 7)} more for the gate.
          </p>
        </Card>
        <Card title="Equity Curves + Oct-1 Projection">
          <Enlargeable label="Equity Curves + Oct-1 Projection">
            <LineChart
              series={[
                { name: "BANKROLL_200", points: c200Eq, strokeColor: "#3b82f6" },
                { name: "STANDARD", points: stdEq, strokeColor: "#34d399" },
                ...(projPoints.length > 1
                  ? [{ name: "Projection (7d avg)", points: projPoints, strokeColor: "#8b93a7", dash: "4 4" }]
                  : []),
              ]}
              formatY={fmt$}
            />
          </Enlargeable>
          <p className="text-xs text-dim mt-2">
            Dashed = linear extension of the last-7-day daily average ({fmt$(avg7)}/day) to Oct 1.
          </p>
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="Calibration: Our Entries vs Market-Wide (692M trades)">
          {calPoints.length > 0 ? (
            <Enlargeable label="Calibration: Our Entries vs Market-Wide (692M trades)">
            <svg viewBox="0 0 340 300" className="w-full">
              {[0.2, 0.4, 0.6, 0.8, 1].map((v) => (
                <g key={v}>
                  <line x1={30 + v * 280} y1={270} x2={30 + v * 280} y2={20} stroke="#1e2433" strokeWidth="0.5" />
                  <text x={30 + v * 280} y={285} fill="#8b93a7" fontSize="9" fontFamily="monospace" textAnchor="middle">
                    {v.toFixed(1)}
                  </text>
                  <line x1={30} y1={270 - v * 250} x2={310} y2={270 - v * 250} stroke="#1e2433" strokeWidth="0.5" />
                  <text x={24} y={270 - v * 250 + 3} fill="#8b93a7" fontSize="9" fontFamily="monospace" textAnchor="end">
                    {v.toFixed(1)}
                  </text>
                </g>
              ))}
              <line x1={30} y1={270} x2={310} y2={-10} stroke="#8b93a7" strokeWidth="1" strokeDasharray="4 4" />
              <text x={290} y={14} fill="#8b93a7" fontSize="9">perfect calibration</text>
              {basePoints.map((p, i) => (
                <circle key={`b${i}`} cx={30 + p.x * 280} cy={270 - p.y * 250} r={3.5} fill="#8b93a7" opacity={0.8}>
                  <title>{`market-wide @ ${p.x.toFixed(1)}: ${(p.y * 100).toFixed(1)}%`}</title>
                </circle>
              ))}
              {calPoints.map((p, i) => (
                <circle key={`c${i}`} cx={30 + p.x * 280} cy={270 - p.y * 250} r={5} fill="#34d399">
                  <title>{`ours @ ${p.x.toFixed(2)}: ${(p.y * 100).toFixed(1)}%`}</title>
                </circle>
              ))}
              <text x={30} y={18} fill="#8b93a7" fontSize="9">win rate →</text>
            </svg>
            </Enlargeable>
          ) : (
            <Empty message="Calibration data missing — run scripts/analyze-calibration.py." />
          )}
          <p className="text-xs text-dim mt-2">
            Green = our copied trades, gray = market-wide. Above the diagonal = edge over the crowd (the &lt;0.20 whale alpha).
          </p>
        </Card>
        <Card title="Returns Heatmap — Hour (ET) × Weekday">
          <Enlargeable label="Returns Heatmap — Hour (ET) × Weekday">
            <Heatmap xLabels={Array.from({ length: 24 }, (_, i) => `${i}`)} yLabels={WD} cells={heatCells} formatV={fmt$} />
          </Enlargeable>
          <p className="text-xs text-dim mt-2">Realized PnL of resolved trades; dim cells = n&lt;3 (noise).</p>
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="Decision Funnel">
          {funnelRows.map((r) => (
            <div key={r.key} className="flex items-center gap-3 py-1.5">
              <div className="w-24 text-xs text-dim">{r.key.replace("_", " ")}</div>
              <div className="flex-1 h-5 bg-edge/40 rounded overflow-hidden">
                <div
                  className={`h-full rounded ${r.key === "paper_copy" ? "bg-pos/70" : r.key === "watchlist" ? "bg-warn/70" : "bg-edge"}`}
                  style={{ width: `${(r.count / funnelMax) * 100}%` }}
                />
              </div>
              <div className="w-10 text-right font-mono text-xs">{r.count}</div>
            </div>
          ))}
          <p className="text-xs text-dim mt-2">
            Total decisions: {decisions.length} · observed signals feed the scorer, copies are the green slice.
          </p>
        </Card>
        <Card title="Benchmark Cumulative PnL (per $10 decision)">
          <Enlargeable label="Benchmark Cumulative PnL (per $10 decision)">
            <LineChart series={benchLines} formatY={fmt$} />
          </Enlargeable>
          <p className="text-xs text-dim mt-2">Bot actual vs blind copy / watchlist / skipped (hypothetical $10 flat).</p>
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="PnL by Category">
          <Enlargeable label="PnL by Category">
            <BarChart bars={catBars} formatY={fmt$} />
          </Enlargeable>
        </Card>
        <Card title="PnL by Venue">
          <Enlargeable label="PnL by Venue">
            <BarChart bars={venueBars} formatY={fmt$} />
          </Enlargeable>
          <p className="text-xs text-dim mt-2">The Kalshi leg story, visual.</p>
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="PnL by Rule Version (cohorts)">
          <Enlargeable label="PnL by Rule Version (cohorts)">
            <BarChart bars={versionBars} formatY={fmt$} />
          </Enlargeable>
          <p className="text-xs text-dim mt-2">Realized PnL of resolved trades journaled under each ruleset.</p>
        </Card>
        <Card title="Tracked Wallets — Score vs Win Rate">
          <Enlargeable label="Tracked Wallets — Score vs Win Rate">
            <Scatter
              points={scatterPoints}
              xLabel="wallet globalScore →"
              yLabel="win rate"
              formatX={(v) => v.toFixed(0)}
              formatY={(v) => `${(v * 100).toFixed(0)}%`}
            />
          </Enlargeable>
          <p className="text-xs text-dim mt-2">
            <span className="text-pos">green</span> = proven (≥15 trades) · <span className="text-warn">amber</span> = insider-watch ·{" "}
            <span className="text-neg">red</span> = insider-flagged.
          </p>
        </Card>
      </div>
    </div>
  );
}
