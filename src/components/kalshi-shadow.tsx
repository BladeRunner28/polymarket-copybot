import { readFileSync } from "fs";
import path from "path";
import { Card, Stat, Empty, Badge } from "@/components/ui";
import { LineChart } from "@/components/chart";

/**
 * Kalshi shadow cards (2026-09-13, user-approved).
 *
 * Live Kalshi routing is retired, so the C-200 book is all Polymarket. This
 * surface answers the two questions that decision left open, side by side with
 * the live PnL:
 *   1. ATTRIBUTION — which slice of the realized book would each candidate
 *      venue rule have routed to Kalshi? (priced at the Polymarket reference:
 *      an attribution, not venue P&L)
 *   2. SCORING — what does the shadow expectancy model say about the book,
 *      next to the live copyScore?
 *
 * Data comes from scripts/kalshi-shadow.py (idempotent rebuild, run by cron).
 */

interface Stats {
  n: number;
  n_settled: number;
  n_open: number;
  pnl: number;
  staked: number;
  roi_pct: number;
  win_rate_pct: number;
}

interface Variant {
  label: string;
  selected: Stats;
  share_of_book_pct: number;
  /** what the rule adds over doing nothing (the slice is a subset of the book, never additive) */
  delta_vs_all_pm?: number;
  fee_entry_usd?: number;
  /** the slice after the entry-leg taker fee the paper ledger does not charge */
  pnl_net_entry_fee?: number;
  in_sample?: boolean;
}

interface Summary {
  asOf: string;
  kind: string;
  note: string;
  model: { fittedAt: string; nTrain: number; oosRankIcPurged: number; target: string; caveats: string[] };
  live: Stats;
  liveSinceSep5: Stats;
  /** fee comparison fields (2026-09-13): ledger books no fees at all */
  liveFeeEntryUsd?: number;
  livePnlNetEntryFee?: number;
  variants: Record<string, Variant>;
  series: { dates: string[]; liveCum: number[]; kalshiShadowCum: number[]; pmOnlyCum: number[] };
  shadowScoreSplit: {
    selected: Stats;
    rejected: Stats;
    inSample: boolean;
    oosSinceFit: Stats;
    oosRejected: Stats;
    oosStartedMs: number | null;
  };
}

function loadSummary(): Summary | null {
  try {
    return JSON.parse(
      readFileSync(path.join(process.cwd(), "data", "kalshi-shadow-summary.json"), "utf-8")
    ) as Summary;
  } catch {
    return null;
  }
}

/** The builder rewrites the summary file asynchronously; never let a missing
 *  field (older artifact) 500 the whole dashboard page. */
const ZERO: Stats = { n: 0, n_settled: 0, n_open: 0, pnl: 0, staked: 0, roi_pct: 0, win_rate_pct: 0 };
function st(v?: Partial<Stats> | null): Stats {
  return { ...ZERO, ...(v || {}) };
}

function money(v: number): string {
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
}

export function KalshiShadowCards() {
  const s = loadSummary();
  if (!s) {
    return (
      <Card title="Kalshi shadow — attribution + scoring">
        <Empty message="No shadow ledger yet — run scripts/kalshi-shadow.py (cron: copybot-kalshi-shadow)." />
      </Card>
    );
  }

  const shadow = st(s.shadowScoreSplit?.selected);
  const pmOnly = st(s.shadowScoreSplit?.rejected);
  const oos = st(s.shadowScoreSplit?.oosSinceFit);
  const live = st(s.live);
  const liveSince = st(s.liveSinceSep5);
  const dates = s.series?.dates ?? [];
  const liveCum = s.series?.liveCum ?? [];
  const shadowCum = s.series?.kalshiShadowCum ?? [];
  const pmCum = s.series?.pmOnlyCum ?? [];
  const series = dates.map((d, i) => ({ d, live: liveCum[i] ?? 0, shadow: shadowCum[i] ?? 0, rest: pmCum[i] ?? 0 }));
  const variantOrder = ["gate_as_written", "gate_pre_v37", "gate_repaired_raw", "shadow_model"];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Stat
          label="Live C-200 (all Polymarket)"
          value={money(live.pnl)}
          tone={live.pnl > 0 ? "pos" : "neg"}
          sub={`n=${live.n} · ROI ${live.roi_pct.toFixed(1)}% · win ${live.win_rate_pct.toFixed(0)}% · since Sep 5 ${money(liveSince.pnl)}`}
        />
        <Stat
          label="Model-selected slice (attribution)"
          value={money(shadow.pnl)}
          tone={shadow.pnl > 0 ? "pos" : "neg"}
          sub={`n=${shadow.n} · ROI ${shadow.roi_pct.toFixed(1)}% · win ${shadow.win_rate_pct.toFixed(0)}% · ${(100 * shadow.n / Math.max(1, live.n)).toFixed(0)}% of book · IN-SAMPLE · not venue P&L, NOT addable: slice + remainder = live`}
        />
        <Stat
          label="Polymarket-only remainder"
          value={money(pmOnly.pnl)}
          tone={pmOnly.pnl > 0 ? "pos" : "neg"}
          sub={`n=${pmOnly.n} · ROI ${pmOnly.roi_pct.toFixed(1)}% · win ${pmOnly.win_rate_pct.toFixed(0)}% · shadow + remainder = live`}
        />
      </div>

      <Card title="P&L path: live vs Kalshi-shadow attribution (cumulative, by finish day)">
        {series.length < 2 ? (
          <Empty message="Not enough settled days to chart." />
        ) : (
          <>
            <LineChart
              height={230}
              formatY={(v) => `$${v.toFixed(0)}`}
              series={[
                {
                  name: "live C-200 (Polymarket)",
                  strokeColor: "#34d399",
                  points: series.map((r) => ({ x: r.d, y: r.live })),
                },
                {
                  name: "Model-selected slice",
                  strokeColor: "#60a5fa",
                  points: series.map((r) => ({ x: r.d, y: r.shadow })),
                },
                {
                  name: "Polymarket-only remainder",
                  strokeColor: "#f87171",
                  dash: "4 4",
                  points: series.map((r) => ({ x: r.d, y: r.rest })),
                },
              ]}
            />
            <div className="text-xs text-dim mt-2">
              Green = the book as it stands (all Polymarket). Blue = the slice the shadow model selects;
              red dashed = the remainder. Blue + red = green by construction — this is an <strong>attribution</strong>,
              not venue P&L: live Kalshi routing is retired, so every row is priced at the Polymarket reference,
              and the blue number is a <strong>subset of the green book, never an addition to it</strong>.
              Fees are not modelled in any of the three lines.
            </div>
          </>
        )}
      </Card>

      <Card title="Candidate venue rules — what each would have routed">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-dim text-xs uppercase tracking-wide">
                <th className="text-left py-1">rule</th>
                <th className="text-right">n</th>
                <th className="text-right">share</th>
                <th className="text-right">PnL</th>
                <th className="text-right">Δ vs all-PM</th>
                <th className="text-right">net (entry fee)</th>
                <th className="text-right">ROI</th>
                <th className="text-right">win</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {variantOrder.map((k) => {
                const v = s.variants?.[k];
                if (!v) return null;
                const delta = v.delta_vs_all_pm;
                return (
                  <tr key={k} className={k === "shadow_model" ? "text-ink" : "text-dim"}>
                    <td className="text-left py-1 font-sans">{k.replace(/_/g, " ")}</td>
                    <td className="text-right">{v.selected.n}</td>
                    <td className="text-right">{v.share_of_book_pct.toFixed(1)}%</td>
                    <td className={`text-right ${v.selected.pnl > 0 ? "text-pos" : "text-neg"}`}>{money(v.selected.pnl)}</td>
                    <td className={`text-right ${(delta ?? 0) > 0 ? "text-pos" : "text-neg"}`}>
                      {delta == null ? "—" : money(delta)}
                    </td>
                    <td className="text-right">
                      {v.pnl_net_entry_fee == null ? "—" : money(v.pnl_net_entry_fee)}
                    </td>
                    <td className="text-right">{v.selected.roi_pct.toFixed(1)}%</td>
                    <td className="text-right">{v.selected.win_rate_pct.toFixed(0)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="text-xs text-dim mt-2 flex flex-wrap gap-2 items-center">
          <Badge kind="venue" />
          <span>
            All rows are counterfactual rules scored on realised, Polymarket-priced rows (attribution, in-sample).
            <span className="font-mono"> Δ vs all-PM</span> is what the rule adds over doing nothing — a slice is a
            subset of the book, so no variant&apos;s PnL is ever addable to it.
            <span className="font-mono"> net (entry fee)</span> applies the entry-leg taker fee the paper ledger does
            not charge (live book: {money(s.live?.pnl ?? 0)} gross → {money(s.livePnlNetEntryFee ?? 0)} net).
          </span>
        </div>
        <div className="text-xs text-dim mt-2 flex flex-wrap gap-2 items-center">
          <Badge kind="venue" />
          <span>
            gate pre-v37 (n=133) is the rule that produced the original 92-row Kalshi book: it is now the worst
            selector on the page — re-enabling that semantic is what routes the bleeding class.
          </span>
        </div>
      </Card>

      <Card title="Shadow expectancy score — model card">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-xs text-dim uppercase tracking-wide">fitted</div>
            <div className="font-mono">{s.model?.fittedAt ?? "—"}</div>
          </div>
          <div>
            <div className="text-xs text-dim uppercase tracking-wide">train rows</div>
            <div className="font-mono">{s.model?.nTrain ?? 0} settled C-200 copies</div>
          </div>
          <div>
            <div className="text-xs text-dim uppercase tracking-wide">purged OOS rank IC</div>
            <div className="font-mono">
              {(s.model?.oosRankIcPurged ?? 0) >= 0 ? "+" : ""}
              {(s.model?.oosRankIcPurged ?? 0).toFixed(3)}
            </div>
          </div>
          <div>
            <div className="text-xs text-dim uppercase tracking-wide">OOS clock (post-fit trades)</div>
            <div className="font-mono">
              n={oos.n} · {money(oos.pnl)}
            </div>
          </div>
        </div>
        <ul className="text-xs text-dim mt-3 list-disc pl-5 space-y-0.5">
          {(s.model?.caveats ?? []).map((c, i) => (
            <li key={i}>{c}</li>
          ))}
          <li>
            The model-call split on this page is fitted on the same rows it scores (in-sample). The honest forward
            number is the OOS clock — it starts at zero and fills as new copies settle.
          </li>
        </ul>
      </Card>
    </div>
  );
}
