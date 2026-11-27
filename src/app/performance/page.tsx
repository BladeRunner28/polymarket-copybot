import { prisma } from "@/lib/db";
import { hourlyPnlSeries } from "@/lib/pnl-rollup";
import { computeBenchmarks } from "@/lib/benchmarks";
import { Card, Stat, Empty, Pnl, Addr } from "@/components/ui";
import { LineChart } from "@/components/chart";
import Link from "next/link";
import { readFileSync } from "fs";
import { join } from "path";

export const dynamic = "force-dynamic";

export default async function Performance() {
  const [snapshots, resolved, bench] = await Promise.all([
    // Rollup-backed (scripts/rollup-pnl-hourly.ts): was a full PnlSnapshot
    // GROUP BY scan per request.
    hourlyPnlSeries(),
    // SETTLED, not "resolved" (2026-11-26 self-audit). `status: "resolved"` is
    // only the NATURAL settlements; early exits are `status: "closed"` and were
    // silently dropped, so every figure below read a different population than
    // the book it claims to describe: 4,095 natural legs vs 13,153 settled
    // (closed|resolved). STANDARD alone went +$7,580.23 (2,698) -> +$9,147.09
    // (10,067) — the page understated it by $1,567. Ordered in JS below on
    // (closedAt ?? resolvedAt) because Prisma cannot coalesce a sort key and
    // ordering by resolvedAt alone would put every early exit at the front
    // (SQLite sorts NULL first ascending), i.e. a false chronology.
    prisma.paperTrade.findMany({
      where: { status: { in: ["closed", "resolved"] }, isDemo: false },
      select: { id: true, botId: true, walletAddress: true, realizedPnl: true, openedAt: true, closedAt: true, resolvedAt: true, status: true },
    }),
    computeBenchmarks(),
  ]);
  const settledAt = (t: { closedAt: Date | null; resolvedAt: Date | null }) => (t.closedAt ?? t.resolvedAt ?? new Date(0)).getTime();
  resolved.sort((a, b) => settledAt(a) - settledAt(b));

  // Cumulative PnL chart from database-aggregated snapshots
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
    { name: "BANKROLL_200 ($0.10 - $10)", points: compoundingSeries.length ? compoundingSeries : [{ x: "Now", y: 0 }], strokeColor: "#3b82f6" }, // blue
  ];

  // Rolling win rate chart
  const wrPoints: { x: string; y: number }[] = [];
  let wins = 0;
  resolved.forEach((t, i) => {
    if ((t.realizedPnl ?? 0) > 0) wins++;
    wrPoints.push({ x: (t.closedAt ?? t.resolvedAt ?? t.openedAt).toISOString().slice(5, 10), y: Math.round((wins / (i + 1)) * 1000) / 10 });
  });
  // Per-lane finals for the basis line: the pooled curve above is a BLEND of two
  // lanes that are 78% STANDARD by leg count, so the pooled number is neither
  // lane's win rate. Printed so the chart cannot be read as "the bot's win rate".
  const laneWr = new Map<string, { n: number; wins: number }>();
  for (const t of resolved) {
    const cur = laneWr.get(t.botId) ?? { n: 0, wins: 0 };
    cur.n++;
    if ((t.realizedPnl ?? 0) > 0) cur.wins++;
    laneWr.set(t.botId, cur);
  }
  const pooledWr = resolved.length ? (wins / resolved.length) * 100 : null;

  // Per-wallet and per-category performance
  const byWallet = new Map<string, { pnl: number; n: number }>();
  for (const t of resolved) {
    if (t.botId !== "STANDARD") continue; // only show standard for benchmarks
    const cur = byWallet.get(t.walletAddress) ?? { pnl: 0, n: 0 };
    cur.pnl += t.realizedPnl ?? 0;
    cur.n++;
    byWallet.set(t.walletAddress, cur);
  }
  const walletRows = [...byWallet.entries()].sort((a, b) => b[1].pnl - a[1].pnl);

  const decisions = await prisma.decisionJournal.findMany({
    // Settled = closed|resolved (an early exit is a closed leg, not a loss of
    // data) and the leg is picked explicitly by lane below rather than as
    // `paperTrades[0]`, which was an unordered arbitrary pick from a decision
    // that can hold both a STANDARD and a C-200 leg. Measured 2026-11-26 on the
    // 2,698 decisions in this loop: the first leg was already the STANDARD one
    // in 2,698/2,698 cases, so this is prevention, not a changed number.
    where: { paperTrades: { some: { status: { in: ["closed", "resolved"] }, botId: "STANDARD" } } },
    include: { observedTrade: true, paperTrades: true },
  });
  const byCat = new Map<string, { pnl: number; n: number }>();
  for (const d of decisions) {
    // The REAL category. `observedTrade.marketCategory` is the venue field that
    // the schema documents as not a category (it holds slug first-tokens like
    // "world"/"highest"/"elon"); marketCategoryClass is the coarse bucket written
    // at ingest by src/lib/market-category.ts. Grouping on the junk field made
    // the card read "world +$7,372.53" over 923 legs where the graded truth is
    // sports +$6,254.76 over 1,326.
    const cat = d.observedTrade.marketCategoryClass ?? "uncategorized";
    const leg = d.paperTrades.find((t) => t.botId === "STANDARD" && (t.status === "closed" || t.status === "resolved"));
    const pnl = leg?.realizedPnl ?? 0;
    const cur = byCat.get(cat) ?? { pnl: 0, n: 0 };
    cur.pnl += pnl;
    cur.n++;
    byCat.set(cat, cur);
  }

  const buckets = [bench.botFiltered, bench.blindCopy, bench.watchlist, bench.skipped];

  // Calibration significance (data/calibration-analysis.json — refreshed
  // nightly by the EOD job via scripts/analyze-calibration.py). Missing or
  // corrupt file → section hidden, page still renders.
  let cal: {
    total?: { n: number; excessReturn: number; z: number; realizedPnl: number };
    bands?: Array<{ band: string; n: number; winRate: number; excessReturn: number; z: number; p: number; significant: boolean; realizedPnl: number }>;
    hours?: Array<{ hour: number; n: number; winRate: number; excessReturn: number; z: number; p: number; significant: boolean; realizedPnl: number }>;
  } | null = null;
  try {
    cal = JSON.parse(readFileSync(join(process.cwd(), "data", "calibration-analysis.json"), "utf8"));
  } catch {
    cal = null;
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Performance</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Missed Winners" value={String(bench.missedWinners)} sub="skipped/watched, would have won" tone="neg" />
        <Stat label="Avoided Losers" value={String(bench.avoidedLosers)} sub="skipped/watched, would have lost" tone="pos" />
        <Stat label="Bad Copies" value={String(bench.badCopies)} sub="copies that lost" tone={bench.badCopies > 0 ? "neg" : "neutral"} />
        <Stat label="Good Skips" value={String(bench.goodSkips)} sub="skips that dodged losses" tone="pos" />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="Paper PnL (hourly snapshots)">
          <LineChart series={chartData} formatY={(v) => `$${v.toFixed(0)}`} />
        </Card>
        <Card title="Rolling Win Rate %">
          <LineChart points={wrPoints} formatY={(v) => `${v.toFixed(0)}%`} />
          <p className="text-xs text-dim mt-2">
            Basis: BOTH lanes pooled, level=leg, population = settled legs (closed|resolved), isDemo=0,
            clock = closedAt ?? resolvedAt, win = realizedPnl &gt; 0 (our exit sign, not the market outcome).
            {pooledWr !== null && ` Pooled final ${pooledWr.toFixed(1)}% over ${resolved.length.toLocaleString()} legs — a blend, not either lane:`}
            {[...laneWr.entries()].map(([bot, v]) => ` ${bot} ${((v.wins / Math.max(1, v.n)) * 100).toFixed(1)}% (n=${v.n.toLocaleString()})`).join(" ·")}
            . Per-lane lifetime win rates on the EOD report are the same query, split.
          </p>
        </Card>
      </div>

      <Card title="Strategy Benchmark: Bot vs Blind Copy vs Watchlist vs Skips">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-dim uppercase border-b border-edge">
                <th className="py-2 pr-3">Strategy</th>
                <th className="py-2 pr-3">Signals</th>
                <th className="py-2 pr-3">Resolved</th>
                <th className="py-2 pr-3">Total PnL</th>
                <th className="py-2 pr-3">Avg PnL/trade</th>
                <th className="py-2">Win Rate</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => (
                <tr key={b.label} className={`border-b border-edge/40 ${b.label.startsWith("Bot") ? "bg-accent/5" : ""}`}>
                  <td className="py-2 pr-3">{b.label}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{b.count}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{b.resolvedCount}</td>
                  <td className="py-2 pr-3"><Pnl value={b.totalPnl} /></td>
                  <td className="py-2 pr-3"><Pnl value={b.avgPnl} /></td>
                  <td className="py-2 font-mono text-xs">{(b.winRate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-dim mt-2">
          Watchlist/skipped/blind PnL is hypothetical ($10 flat positions at detection price). Bot-filtered uses actual simulated sizes.
          Level differs per row: the Bot row counts LEGS (a copied signal books one leg per lane, so its Resolved can exceed a
          per-signal count), every other row counts SIGNALS.
        </p>
      </Card>

      <div className="grid md:grid-cols-2 gap-4">
        <Card title="Per-Wallet Paper PnL (STANDARD, settled legs)">
          {walletRows.length === 0 ? (
            <Empty message="No resolved paper trades yet." />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {walletRows.slice(0, 12).map(([addr, v]) => (
                  <tr key={addr} className="border-b border-edge/40">
                    <td className="py-1.5">
                      <Link href={`/wallets/${addr}`} className="hover:text-accent"><Addr address={addr} /></Link>
                    </td>
                    <td className="py-1.5 text-xs text-dim font-mono">{v.n} trades</td>
                    <td className="py-1.5 text-right"><Pnl value={v.pnl} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Per-Category Paper PnL (STANDARD, settled legs)">
          {byCat.size === 0 ? (
            <Empty message="No resolved paper trades yet." />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {[...byCat.entries()].sort((a, b) => b[1].pnl - a[1].pnl).map(([cat, v]) => (
                  <tr key={cat} className="border-b border-edge/40">
                    <td className="py-1.5">{cat}</td>
                    <td className="py-1.5 text-xs text-dim font-mono">{v.n} trades</td>
                    <td className="py-1.5 text-right"><Pnl value={v.pnl} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="text-xs text-dim mt-2">
            Category = ObservedTrade.marketCategoryClass (coarse bucket from the slug/question classifier), settled
            legs, clock = closedAt ?? resolvedAt. NOT the venue&apos;s marketCategory field — the schema documents that
            one as slug fragments, not a category.
          </p>
        </Card>
      </div>

      {cal && (
        <div className="grid md:grid-cols-2 gap-4">
          <Card title={`Calibration Significance — Price Bands${cal.total ? ` (N=${cal.total.n})` : ""}`}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-dim uppercase border-b border-edge">
                    <th className="py-2 pr-3">Entry</th>
                    <th className="py-2 pr-3">N</th>
                    <th className="py-2 pr-3">Win %</th>
                    <th className="py-2 pr-3">Excess</th>
                    <th className="py-2 pr-3">z</th>
                    <th className="py-2">PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {(cal.bands ?? []).map((b) => (
                    <tr key={b.band} className={`border-b border-edge/40 ${b.significant ? "bg-warn/5" : ""}`}>
                      <td className="py-2 pr-3 font-mono text-xs">
                        {b.band}
                        {b.significant && <span className="text-warn ml-1" title="|z|≥2 significant">**</span>}
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs">{b.n}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{(b.winRate * 100).toFixed(1)}%</td>
                      <td className={`py-2 pr-3 font-mono text-xs ${b.excessReturn > 0 ? "text-pos" : "text-neg"}`}>
                        {b.excessReturn >= 0 ? "+" : ""}
                        {b.excessReturn.toFixed(4)}
                      </td>
                      <td className={`py-2 pr-3 font-mono text-xs ${b.significant ? "text-ink font-bold" : "text-dim"}`}>
                        {b.z >= 0 ? "+" : ""}
                        {b.z.toFixed(2)}
                      </td>
                      <td className="py-2 font-mono text-xs"><Pnl value={b.realizedPnl} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-dim mt-2">
              Excess return = win rate − mean entry price; ** = |z|≥2 significant. Refreshed nightly by the EOD job
              (scripts/analyze-calibration.py, port of jon-becker/prediction-market-analysis).
            </p>
          </Card>
          <Card title="Returns by Hour (ET)">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-dim uppercase border-b border-edge">
                    <th className="py-2 pr-3">Hour</th>
                    <th className="py-2 pr-3">N</th>
                    <th className="py-2 pr-3">Win %</th>
                    <th className="py-2 pr-3">Excess</th>
                    <th className="py-2 pr-3">z</th>
                    <th className="py-2">PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {(cal.hours ?? []).map((h) => (
                    <tr key={h.hour} className={`border-b border-edge/40 ${h.significant ? "bg-warn/5" : ""}`}>
                      <td className="py-1.5 pr-3 font-mono text-xs">
                        {String(h.hour).padStart(2, "0")}:00
                        {h.significant && <span className="text-warn ml-1" title="|z|≥2 significant">**</span>}
                      </td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{h.n}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{(h.winRate * 100).toFixed(1)}%</td>
                      <td className={`py-1.5 pr-3 font-mono text-xs ${h.excessReturn > 0 ? "text-pos" : "text-neg"}`}>
                        {h.excessReturn >= 0 ? "+" : ""}
                        {h.excessReturn.toFixed(4)}
                      </td>
                      <td className={`py-1.5 pr-3 font-mono text-xs ${h.significant ? "text-ink font-bold" : "text-dim"}`}>
                        {h.z >= 0 ? "+" : ""}
                        {h.z.toFixed(2)}
                      </td>
                      <td className="py-1.5 font-mono text-xs"><Pnl value={h.realizedPnl} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
