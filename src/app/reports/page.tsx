import { prisma } from "@/lib/db";
import { Card, Badge, Empty, Pnl } from "@/components/ui";
import { bucketByDayAndBot, dayPayoff } from "@/lib/day-pnl";

export const dynamic = "force-dynamic";

/**
 * 2026-11-17 self-audit — two figures on this page named neither their lane nor
 * their basis, and one of them was not a day figure at all:
 *
 *   "Day PnL"  = `paperPnl`  = the STANDARD lane only. The C-200 row was stored in
 *                the same record (`compoundingPnl`) and rendered NOWHERE, so a
 *                reader took a one-lane number as the bot's day.
 *   "Win rate" = `winRate`   = the LIFETIME rate as of the run that wrote the row,
 *                printed bare beside the day's PnL. Measured on the live table:
 *                the column reads 0.633 → 0.635 across 2026-11-06..11-16 while the
 *                day's own STANDARD rate on those days ran 0.0% (11-15, n=6) to
 *                50.0% (11-16, n=4) and C-200's ran 0.0% (11-15, n=9) to 6.7%
 *                (11-16, n=15). A lifetime rate cannot show a daily trend, so a
 *                "win rate trend" read off these rows is arithmetically dead.
 *
 * Now: each lane's day PnL, each lane's DAY win rate (computed from the same rows
 * the day's PnL is summed from — closedAt ?? resolvedAt, local calendar day,
 * level=leg, isDemo=0), and the stored lifetime value on a line that says what it
 * is. Nothing stored changed.
 */

const LANES = [
  { botId: "STANDARD", label: "STANDARD" },
  { botId: "BANKROLL_200", label: "C-200" },
];

export default async function Reports() {
  const reports = await prisma.dailyReport.findMany({ orderBy: { date: "desc" }, take: 30 });

  // Weekly rollup from daily reports
  const weeks = new Map<string, { pnl: number; days: number; signals: number }>();
  for (const r of reports) {
    const d = new Date(r.date + "T00:00:00Z");
    const weekStart = new Date(d);
    weekStart.setUTCDate(d.getUTCDate() - d.getUTCDay());
    const key = weekStart.toISOString().slice(0, 10);
    const cur = weeks.get(key) ?? { pnl: 0, days: 0, signals: 0 };
    cur.pnl += r.paperPnl;
    cur.days++;
    cur.signals += r.newSignals;
    weeks.set(key, cur);
  }

  // ONE query for the whole page: every settled leg since the oldest report date,
  // bucketed by (local day, lane). Same basis as the day PnL the card prints.
  const byDayLane = new Map<string, ReturnType<typeof dayPayoff>>();
  if (reports.length > 0) {
    const oldest = reports[reports.length - 1].date;
    const [y, m, d] = oldest.split("-").map(Number);
    const since = new Date(y, m - 1, d, 0, 0, 0, 0); // local midnight of the oldest report
    const settled = await prisma.paperTrade.findMany({
      where: {
        isDemo: false,
        status: { in: ["closed", "resolved"] },
        // TR-15: early exits book at closedAt (resolvedAt NULL).
        OR: [{ closedAt: { gte: since } }, { resolvedAt: { gte: since } }],
      },
      select: { botId: true, realizedPnl: true, simulatedPositionSize: true, closedAt: true, resolvedAt: true },
    });
    const buckets = bucketByDayAndBot(settled);
    for (const [key, rows] of buckets) byDayLane.set(key, dayPayoff(rows));
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Reports</h1>
      <p className="text-xs text-dim">
        Day figures are per lane, level=leg, isDemo=0, clock=<code>closedAt ?? resolvedAt</code> on the LOCAL
        calendar day. A row is a snapshot written by the 22:00 run, which cannot contain the day&apos;s last two
        hours — legs that settle after it land in the next day&apos;s report. The stored lifetime rate beside each
        day rate is a running total of everything since go-live, so it is NOT a daily series.
      </p>

      <Card title="Weekly Summary">
        {weeks.size === 0 ? (
          <Empty message="No reports yet. Run `npm run report:daily`." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-dim uppercase border-b border-edge">
                <th className="py-2 pr-3">Week of</th>
                <th className="py-2 pr-3">Paper PnL (STANDARD)</th>
                <th className="py-2 pr-3">Reported Days</th>
                <th className="py-2">Signals</th>
              </tr>
            </thead>
            <tbody>
              {[...weeks.entries()].map(([week, v]) => (
                <tr key={week} className="border-b border-edge/40">
                  <td className="py-2 pr-3 font-mono text-xs">{week}</td>
                  <td className="py-2 pr-3"><Pnl value={v.pnl} /></td>
                  <td className="py-2 pr-3 font-mono text-xs">{v.days}</td>
                  <td className="py-2 font-mono text-xs">{v.signals}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {reports.map((r) => {
        const bestWallets = JSON.parse(r.bestWalletsJson) as { address: string; pnl: number }[];
        const worstWallets = JSON.parse(r.worstWalletsJson) as { address: string; pnl: number }[];
        const ruleChanges = JSON.parse(r.ruleChangesJson) as { version: number; reason: string }[];
        const dayRates = LANES.map((l) => {
          const p = byDayLane.get(`${r.date}|${l.botId}`);
          return { ...l, p };
        });
        return (
          <Card key={r.id} title={`End of Day — ${r.date}`}>
            <div className="flex items-center gap-2 mb-3">
              <Badge kind={r.sentToDiscord ? "resolved" : "watch"} />
              <span className="text-xs text-dim">{r.sentToDiscord ? "delivered to Discord" : "stored locally"}</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm mb-2">
              <div>
                <span className="text-dim block text-xs">Day PnL · STANDARD</span>
                <Pnl value={r.paperPnl} />
              </div>
              <div>
                <span className="text-dim block text-xs">Day PnL · C-200</span>
                <Pnl value={r.compoundingPnl} />
              </div>
              <div>
                <span className="text-dim block text-xs">Win rate · day (level=leg)</span>
                {dayRates.map((d) => (
                  <div key={d.botId} className="font-mono text-xs">
                    {d.label} {d.p && d.p.n > 0 ? `${(d.p.winRate * 100).toFixed(1)}% (n=${d.p.n})` : "no settled leg"}
                  </div>
                ))}
              </div>
              <div>
                <span className="text-dim block text-xs">Win rate · lifetime (stored, NOT the day)</span>
                <div className="font-mono text-xs">STANDARD {(r.winRate * 100).toFixed(1)}%</div>
                <div className="font-mono text-xs">C-200 {(r.compoundingWinRate * 100).toFixed(1)}%</div>
              </div>
            </div>
            <div className="text-xs text-dim mb-3">
              Open positions {r.openPositions} · Signals (copy/near-miss/skip) {r.copiedSignals}/{r.watchedSignals}/{r.skippedSignals}
              {/* 2026-11-23 self-audit (Lane B, label only): the middle bucket read "w" (watched
                  signals) and stored `watchedSignals`, but it is the journal's `watchlist`
                  DECISION — a score band (copyScore at/above the watchlist bar, under the copy
                  bar) plus copy-intended rows a cap/risk gate refused. It is NOT the count of
                  watch-status wallets: 2026-11-22 stored 2 watchlist rows while wallets whose
                  status is `watch` produced decisions journaled `skip`. The EOD text was renamed
                  to "near-miss" on 2026-11-22; this page kept the ambiguous letter. */}
              {" "}· as written by the 22:00 run, so the day&apos;s last hours are not in these counts
            </div>
            {(bestWallets.length > 0 || worstWallets.length > 0) && (
              <div className="text-xs text-dim mb-3">
                {bestWallets[0] && <span>Best wallet: <span className="text-pos font-mono">{bestWallets[0].address.slice(0, 10)}… (+${bestWallets[0].pnl.toFixed(2)})</span></span>}
                {worstWallets[0] && worstWallets[0].pnl < 0 && (
                  <span className="ml-4">Worst wallet: <span className="text-neg font-mono">{worstWallets[0].address.slice(0, 10)}… (${worstWallets[0].pnl.toFixed(2)})</span></span>
                )}
              </div>
            )}
            {ruleChanges.length > 0 && (
              <div className="text-xs mb-3">
                <span className="text-dim uppercase">Rule updates: </span>
                {ruleChanges.map((c, i) => (
                  <span key={i} className="text-accent">v{c.version}: {c.reason}{i < ruleChanges.length - 1 ? "; " : ""}</span>
                ))}
              </div>
            )}
            <pre className="text-xs text-dim whitespace-pre-wrap bg-base rounded-lg border border-edge p-3 font-mono">{r.summary}</pre>
          </Card>
        );
      })}
    </div>
  );
}
