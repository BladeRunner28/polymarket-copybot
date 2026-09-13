import { readFileSync } from "fs";
import path from "path";
import { Card, Stat, Empty, Badge } from "@/components/ui";
import { LineChart } from "@/components/chart";

/**
 * Venue shadow card (2026-09-13, user-approved) — FORWARD-ONLY.
 *
 * Answers a different question from the cards above it:
 *   KalshiShadowCards  = ATTRIBUTION of the existing (all-Polymarket) book at
 *                        Polymarket prices: "which venue rule would have routed what?"
 *   this card          = VENUE COMPARISON: the same C-200 copies booked at the
 *                        Polymarket entry AND at Kalshi's own top-of-book, each
 *                        venue's own taker fee, so the two books diverge for a real
 *                        reason (price) instead of a routing label.
 *
 * It cannot be backfilled: Kalshi order books are not archived, so a quote fetched
 * after the fact is not the entry a trade would have got. Collection starts the
 * first time scripts/kalshi-venue-shadow.ts runs and every row in the ledger is a
 * quote taken near the open. Target read: the post-Oct-8 Kelly-window decision.
 *
 * Data: scripts/kalshi-venue-shadow.ts (cron-able, idempotent) → data/kalshi-venue-shadow-summary.json
 */

interface Book {
  n: number;
  pnl: number;
  staked: number;
  roiPct: number;
}
interface Summary {
  asOf: string;
  kind: string;
  windowStart: string;
  note: string;
  caveats: string[];
  coverage: {
    copiesSeen: number;
    inWindow: number;
    withKalshiQuote: number;
    crossListRate: number;
    staleSkips: number;
    quoteFailures: number;
    unverifiedMatches?: number;
    rejectionReasons?: Record<string, number>;
  };
  matchAudit?: Array<{
    question: string;
    ticker?: string;
    matchedTitle?: string;
    score?: number;
    kalshiEntry?: number | null;
    pmEntry?: number;
    verified: boolean;
    reason?: string | null;
  }>;
  books: { pm: Book; kalshi: Book; delta: { pnl: number; perTrade: number } };
  series: { dates: string[]; pmCum: number[]; kalshiCum: number[] };
  perTrade: Array<{
    tradeId: string;
    question: string;
    pmEntry: number;
    kalshiEntry: number | null;
    pmPnl: number;
    kalshiPnl: number;
    delta: number;
  }>;
}

/** Kelly window (Sep 8 – Oct 8) closes this day; the card counts down to it. */
const KELLY_WINDOW_END = new Date("2026-10-08T00:00:00-05:00");

function load(): Summary | null {
  try {
    return JSON.parse(
      readFileSync(path.join(process.cwd(), "data", "kalshi-venue-shadow-summary.json"), "utf-8")
    ) as Summary;
  } catch {
    return null;
  }
}

function money(v: number): string {
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
}

export function KalshiVenueShadowCard() {
  const s = load();
  if (!s) {
    return (
      <Card title="Venue shadow — same trades, Kalshi's own prices (forward-only)">
        <Empty message="No venue shadow yet — run scripts/kalshi-venue-shadow.ts (needs the Rust sidecar's POST /quote)." />
      </Card>
    );
  }

  const daysLeft = Math.ceil((KELLY_WINDOW_END.getTime() - Date.now()) / 86_400_000);
  const settled = s.books.pm.n;
  const crossPct = (s.coverage.crossListRate * 100).toFixed(0);
  const series = (s.series?.dates ?? []).map((d, i) => ({
    d,
    pm: s.series.pmCum[i] ?? 0,
    kalshi: s.series.kalshiCum[i] ?? 0,
  }));
  const windowStart = s.windowStart ? s.windowStart.slice(0, 10) : "—";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Stat
          label="PM book (window, fee-adj)"
          value={money(s.books.pm.pnl)}
          tone={s.books.pm.pnl > 0 ? "pos" : "neg"}
          sub={`n=${settled} settled · staked $${s.books.pm.staked.toFixed(0)} · ROI ${s.books.pm.roiPct.toFixed(1)}%`}
        />
        <Stat
          label="Same trades on Kalshi"
          value={money(s.books.kalshi.pnl)}
          tone={s.books.kalshi.pnl > 0 ? "pos" : "neg"}
          sub={`n=${s.books.kalshi.n} · same size, Kalshi top-of-book + 0.07 fee · ROI ${s.books.kalshi.roiPct.toFixed(1)}%`}
        />
        <Stat
          label="Venue delta (Kalshi − PM)"
          value={money(s.books.delta.pnl)}
          tone={s.books.delta.pnl > 0 ? "pos" : "neg"}
          sub={`${s.books.delta.perTrade >= 0 ? "+" : "−"}$${Math.abs(s.books.delta.perTrade).toFixed(2)}/trade · this IS venue P&L, unlike the attribution cards`}
        />
      </div>

      <Card title="Venue shadow — window progress">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-xs text-dim uppercase tracking-wide">collecting since</div>
            <div className="font-mono">{windowStart}</div>
          </div>
          <div>
            <div className="text-xs text-dim uppercase tracking-wide">cross-listed coverage</div>
            <div className="font-mono">
              {s.coverage.withKalshiQuote}/{s.coverage.inWindow} ({crossPct}%)
            </div>
          </div>
          <div>
            <div className="text-xs text-dim uppercase tracking-wide">days to Kelly window close</div>
            <div className="font-mono">{daysLeft > 0 ? `${daysLeft} (Oct 8)` : "closed"}</div>
          </div>
          <div>
            <div className="text-xs text-dim uppercase tracking-wide">skipped / failed / unverified</div>
            <div className="font-mono">
              {s.coverage.staleSkips} stale · {s.coverage.quoteFailures} no-match ·{" "}
              {s.coverage.unverifiedMatches ?? 0} unverified
            </div>
          </div>
        </div>
        {settled === 0 && (
          <div className="text-xs text-dim mt-3">
            <Badge kind="venue" />{" "}
            No cross-listed trade has settled yet — both books read $0 because the window just opened, not because
            the venues agree. The first settled pair is the first real data point.
          </div>
        )}
        <div className="text-xs text-dim mt-2">{s.note}</div>
      </Card>

      {series.length >= 2 && (
        <Card title="Venue shadow — cumulative P&L, PM entry vs Kalshi top-of-book">
          <LineChart
            height={230}
            formatY={(v) => `$${v.toFixed(0)}`}
            series={[
              {
                name: "booked (Polymarket)",
                strokeColor: "#34d399",
                points: series.map((r) => ({ x: r.d, y: r.pm })),
              },
              {
                name: "same trades at Kalshi price",
                strokeColor: "#60a5fa",
                points: series.map((r) => ({ x: r.d, y: r.kalshi })),
              },
            ]}
          />
          <div className="text-xs text-dim mt-2">
            Both lines are fee-adjusted, same size, same trades — the only difference is which venue&apos;s price the
            entry is booked at. Forward-only: rows appear from {windowStart}, never backfilled.
          </div>
        </Card>
      )}

      <Card title="Match audit — what each Kalshi quote was matched to">
        {(s.matchAudit ?? []).length === 0 ? (
          <Empty message="No Kalshi quotes yet — coverage starts the first time the collector runs." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-dim uppercase tracking-wide">
                  <th className="text-left py-1">polymarket question</th>
                  <th className="text-left">matched kalshi event</th>
                  <th className="text-right">score</th>
                  <th className="text-right">PM</th>
                  <th className="text-right">Kalshi</th>
                  <th className="text-left">verdict</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {(s.matchAudit ?? []).slice(-10).reverse().map((m, i) => (
                  <tr key={i} className={m.verified ? "" : "text-neg"}>
                    <td className="py-1 pr-2 max-w-[16rem] truncate">{m.question}</td>
                    <td className="pr-2 max-w-[16rem] truncate">{m.matchedTitle ?? m.ticker ?? "—"}</td>
                    <td className="text-right">{m.score != null ? m.score.toFixed(2) : "—"}</td>
                    <td className="text-right">{m.pmEntry != null ? `$${m.pmEntry.toFixed(2)}` : "—"}</td>
                    <td className="text-right">{m.kalshiEntry != null ? `$${m.kalshiEntry.toFixed(2)}` : "—"}</td>
                    <td>{m.verified ? "priced" : `rejected: ${m.reason ?? "unverified"}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="text-xs text-dim mt-2">
              A rejected match is excluded from both books — a wrong ticker would otherwise manufacture a venue edge
              (the live example: a football question matched a Texas election market at 99.9¢ on the generic tokens
              <span className="font-mono"> win </span>+<span className="font-mono"> 2026</span>). Verification prefers
              dropping real matches over inventing a price.
            </div>
          </div>
        )}
      </Card>

      <Card title="Venue shadow — model card">
        <ul className="text-xs text-dim list-disc pl-5 space-y-0.5">
          {s.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
          <li>
            Coverage is the binding constraint: {s.coverage.withKalshiQuote} of {s.coverage.inWindow} in-window copies
            resolved to a Kalshi market, so a delta that reads &quot;no edge&quot; can equally mean &quot;too few
            cross-listings to see one&quot;.
          </li>
        </ul>
      </Card>
    </div>
  );
}
