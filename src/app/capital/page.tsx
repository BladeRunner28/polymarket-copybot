/**
 * /capital — daily deposits into Total Capital (2026-09-20, user request).
 *
 * Two labels must stay distinct on this page:
 *   Total Capital (live)  = principal + realized + OPEN mark-to-market  ← the
 *                           Overview's own Total Capital stat (moves with marks)
 *   Booked capital        = principal + realized only                    ← what
 *                           this page's chart and table are built from
 *
 * The table in card 2 is the same series as the chart, so the page and
 * scripts/capital-deposits-report.ts (which writes drafts/capital-deposits-*.md)
 * cannot disagree.
 */

import { Card, Stat, Pnl, Empty } from "@/components/ui";
import { CapitalDepositsChart } from "@/components/capital-chart";
import { loadCapitalState } from "@/lib/capital-data";
import { positiveStreak, topDays } from "@/lib/capital";
import { readdirSync, statSync } from "fs";
import { join } from "path";
import Link from "next/link";

export const dynamic = "force-dynamic";

const DAYS = 30;

/** Newest drafts/capital-deposits-*.md, if the report has been written. */
function latestReport(): { slug: string; mtime: string } | null {
  try {
    const dir = join(process.cwd(), "drafts");
    const files = readdirSync(dir)
      .filter((f) => /^capital-deposits-.*\.md$/.test(f))
      .map((f) => ({ slug: f.replace(/\.md$/, ""), m: statSync(join(dir, f)).mtimeMs }))
      .sort((a, b) => b.m - a.m);
    if (!files.length) return null;
    return { slug: files[0].slug, mtime: new Date(files[0].m).toISOString().slice(0, 16).replace("T", " ") + "Z" };
  } catch {
    return null;
  }
}

const usd = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;

export default async function Capital() {
  // ONE loader for page, Overview card and the report/Discord script — the
  // chart, the table and the Discord message cannot drift (src/lib/capital-data.ts).
  const state = await loadCapitalState({ days: DAYS });
  const { series, ledger, principal, realized, openUnreal, openNotional } = state;
  const liveTotalCapital = state.liveTotalCapital;
  const bookedCapital = state.bookedCapital;
  const last7 = series.points.slice(-7).reduce((a, p) => a + p.deposit, 0);
  const streak = positiveStreak(series.points);
  const best = topDays(series.points, 3);
  const worst = topDays(series.points, 3).sort((a, b) => a.deposit - b.deposit).slice(0, 3);
  const report = latestReport();
  const reversed = [...series.points].reverse();

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-bold">Capital</h1>
        <span className="text-sm text-accent font-mono">daily deposits into Total Capital</span>
        <span className="text-xs text-dim">
          local-day boundary · booked at <span className="font-mono">closedAt ?? resolvedAt</span> · {series.points.length}d window
        </span>
      </div>

      <p className="text-sm text-dim">
        <strong className="text-ink">Total Capital (live)</strong> = principal + realized + open mark-to-market — the
        Overview&apos;s own stat, so it moves with marks and can fall without a trade closing.{" "}
        <strong className="text-ink">Daily deposit</strong> = the capital added on that day = booked PnL that day + any
        capital injection recorded in{" "}
        <span className="font-mono text-ink">data/capital-ledger.json</span>. Injections are the one input the DB never
        recorded (principal has no history), so the ledger owns them.
      </p>

      {series.warnings.length > 0 && (
        <div className="border border-warn/40 bg-warn/10 text-warn text-xs rounded-md px-3 py-2 space-y-0.5">
          {series.warnings.map((w) => (
            <div key={w}>⚠ {w}</div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat
          label="Total Capital (live)"
          value={usd(liveTotalCapital)}
          sub={`principal ${usd(principal)} + realized ${usd(realized)} + open MTM ${usd(openUnreal)}`}
          tone={liveTotalCapital >= principal ? "pos" : "neg"}
        />
        <Stat
          label={`Deposits (last 7d)`}
          value={`${last7 >= 0 ? "+" : ""}${usd(last7)}`}
          sub={`${series.points.slice(-7).filter((p) => p.deposit > 0).length}/7 up days · streak ${streak.current}`}
          tone={last7 > 0 ? "pos" : last7 < 0 ? "neg" : "neutral"}
        />
        <Stat
          label="Booked capital"
          value={usd(bookedCapital)}
          sub={`principal + realized (open notional ${usd(openNotional)} excluded)`}
        />
        <Stat
          label="Ledger gap"
          value={usd(series.ledgerGapUsd)}
          sub={Math.abs(series.ledgerGapUsd) < 0.01 ? "principal fully explained ✓" : "unexplained principal movement — add a ledger entry"}
          tone={Math.abs(series.ledgerGapUsd) < 0.01 ? "pos" : "neg"}
        />
      </div>

      <Card title={`Daily deposits into Total Capital — last ${series.points.length} days`}>
        <CapitalDepositsChart points={series.points} principal={principal} />
        <p className="text-xs text-dim mt-2">
          Bar = the day&apos;s deposit (green up / red down), dashed outline = the part funded by a ledger injection
          rather than trading. Line = booked capital at each day&apos;s close. A day with no bar had no finished trade
          and no ledger flow. Past days are immutable — a finished trade stamps its own booking time.
        </p>
      </Card>

      <Card title={`Report — the same numbers, as a table (last ${DAYS} days)`}>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <span className="text-xs text-dim">
            Window: <span className="font-mono text-ink">{series.points[0]?.day} → {series.points[series.points.length - 1]?.day}</span>{" "}
            · opening {usd(series.openingUsd)} → closing {usd(series.closingUsd)} · booked{" "}
            <span className="font-mono">{usd(series.bookedTotal)}</span> · injected{" "}
            <span className="font-mono">{usd(series.injectedTotal)}</span>
          </span>
          {report ? (
            <Link href={`/drafts/${report.slug}`} className="text-xs text-accent hover:text-ink font-mono">
              markdown report: {report.slug} ↗
            </Link>
          ) : (
            <span className="text-xs text-dim font-mono">
              markdown report not written yet — run: npx tsx scripts/capital-deposits-report.ts --write
            </span>
          )}
        </div>
        {reversed.length === 0 ? (
          <Empty message="No capital days to report yet." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead className="text-dim">
                <tr className="text-left">
                  <th className="py-1 pr-3 font-normal">day</th>
                  <th className="py-1 pr-3 font-normal text-right">deposit</th>
                  <th className="py-1 pr-3 font-normal text-right">booked</th>
                  <th className="py-1 pr-3 font-normal text-right">injected</th>
                  <th className="py-1 pr-3 font-normal text-right">closing capital</th>
                  <th className="py-1 pr-3 font-normal text-right">trades</th>
                  <th className="py-1 font-normal">note</th>
                </tr>
              </thead>
              <tbody>
                {reversed.map((p) => (
                  <tr key={p.day} className="border-t border-edge/60">
                    <td className="py-1 pr-3 text-ink">{p.day}</td>
                    <td className={`py-1 pr-3 text-right ${p.deposit > 0 ? "text-pos" : p.deposit < 0 ? "text-neg" : "text-dim"}`}>
                      {p.deposit === 0 ? "—" : <Pnl value={p.deposit} />}
                    </td>
                    <td className="py-1 pr-3 text-right text-dim">{p.booked === 0 ? "—" : usd(p.booked)}</td>
                    <td className="py-1 pr-3 text-right">{p.injected === 0 ? "—" : <span className="text-accent">{usd(p.injected)}</span>}</td>
                    <td className="py-1 pr-3 text-right text-ink">{usd(p.closing)}</td>
                    <td className="py-1 pr-3 text-right text-dim">{p.trades || "—"}</td>
                    <td className="py-1 text-dim">{p.injected !== 0 ? "ledger flow" : p.deposit === 0 ? "no finished trade" : ""}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="text-dim">
                <tr className="border-t border-edge">
                  <td className="py-1 pr-3">total</td>
                  <td className="py-1 pr-3 text-right text-ink">{usd(series.bookedTotal + series.injectedTotal)}</td>
                  <td className="py-1 pr-3 text-right">{usd(series.bookedTotal)}</td>
                  <td className="py-1 pr-3 text-right">{usd(series.injectedTotal)}</td>
                  <td className="py-1 pr-3 text-right text-ink">{usd(series.closingUsd)}</td>
                  <td className="py-1 pr-3 text-right">{series.points.reduce((a, p) => a + p.trades, 0)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
        <div className="text-xs text-dim mt-2 space-y-0.5">
          <div>
            Best days:{" "}
            {best.map((p) => (
              <span key={p.day} className="font-mono mr-3">
                {p.day} {usd(p.deposit)}
              </span>
            ))}
          </div>
          <div>
            Worst days:{" "}
            {worst.map((p) => (
              <span key={p.day} className="font-mono mr-3">
                {p.day} {usd(p.deposit)}
              </span>
            ))}
          </div>
          <div>
            Longest run of up days in window: <span className="font-mono">{streak.best}</span> · regenerate the table and
            the markdown report:{" "}
            <span className="font-mono text-ink">npx tsx scripts/capital-deposits-report.ts --write</span>
          </div>
        </div>
      </Card>

      <Card title={`Capital ledger — injections (${ledger.length} entr${ledger.length === 1 ? "y" : "ies"})`}>
        {ledger.length === 0 ? (
          <Empty message="No ledger entries." />
        ) : (
          <table className="w-full text-xs font-mono">
            <thead className="text-dim">
              <tr className="text-left">
                <th className="py-1 pr-3 font-normal">date</th>
                <th className="py-1 pr-3 font-normal">kind</th>
                <th className="py-1 pr-3 font-normal text-right">amount</th>
                <th className="py-1 font-normal">note</th>
              </tr>
            </thead>
            <tbody>
              {[...ledger]
                .sort((a, b) => (a.date < b.date ? 1 : -1))
                .map((e, i) => (
                  <tr key={`${e.date}-${i}`} className="border-t border-edge/60">
                    <td className="py-1 pr-3 text-ink">{e.date}</td>
                    <td className="py-1 pr-3">
                      <span
                        className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${
                          e.kind === "opening"
                            ? "bg-warn/15 text-warn border-warn/30"
                            : e.kind === "deposit"
                              ? "bg-pos/15 text-pos border-pos/30"
                              : "bg-edge text-dim border-edge"
                        }`}
                      >
                        {e.kind}
                      </span>
                    </td>
                    <td className="py-1 pr-3 text-right">{usd(e.amountUsd)}</td>
                    <td className="py-1 text-dim">{e.note}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
        <p className="text-xs text-dim mt-2">
          <span className="font-mono text-ink">opening</span> = baseline principal already in the book (drawn as the
          capital line&apos;s start, never as a daily bar). <span className="font-mono text-ink">deposit</span> /{" "}
          <span className="font-mono text-ink">withdrawal</span> = real flows. Pre-ledger funding is unrecoverable
          (<span className="font-mono">prisma/dev.db</span> is gitignored and principal has no history), so any principal
          movement the ledger does not explain shows as the Ledger gap above. When you change principal, add the matching
          entry in the same change.
        </p>
      </Card>
    </div>
  );
}
