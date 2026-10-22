import { readFileSync, existsSync } from "fs";
import { join } from "path";
import { Card, Stat, Empty } from "@/components/ui";
import { BarChart } from "@/components/chart";
import { loadCapitalState, ML_BOT } from "@/lib/capital-data";

export const dynamic = "force-dynamic";

/**
 * /ml — the ML lane's measurement record.
 *
 * WHY THIS PAGE EXISTS: the user asked for the ML bot to be visually represented against pure copy
 * trading, with reports on training progress and trading effectiveness. What the measurements
 * actually established is a NEGATIVE, so this page shows the negative rather than a performance
 * curve that would imply progress the data does not support:
 *
 *   - market-only prediction loses in every band except 0.8-1.0, and that band dies at 1.5x the
 *     quoted premium with a geometric mean of -20.4%
 *   - identical <0.20 band: +47.75% WITH wallet selection vs -50.64% WITHOUT -- the alpha is in
 *     which wallets get copied, not in price prediction
 *   - the model-as-veto is not established (non-monotone sweep, quartile CIs span zero)
 *
 * All numbers are read from data/ml/dashboard.json, written by scripts/ml-dashboard-artifacts.py.
 * Deliberately no modelling happens here: the page cannot drift from the script that measured it.
 */

type Band = {
  band: string; rows: number; markets: number; premiumPct: number | null;
  roiMidPct: number | null; roiNetPct: number | null; ciLoPct: number | null; ciHiPct: number | null;
};
type SubBand = { band: string; rows: number; markets: number; roiNetPct: number; ciLoPct: number | null; ciHiPct: number | null; clearsZero: boolean };
type Art = {
  generatedAt: string;
  sources?: Record<string, { path: string; role?: string; exists: boolean; mtimeZ: string | null; ageHours: number | null }>;
  lane: { state: string; headline: string; detail: string; alphaSource: string };
  contrast: { withWalletPct: number; withoutWalletPct: number; note: string };
  marketOnly: { candidates: number; gated: number; bands: Band[] };
  nearCertainty: {
    subbands: SubBand[]; sensitivity: { premiumMult: number; roiNetPct: number }[];
    geometry: { loserSharePct: number; meanWinPct: number; meanLossPct: number; breakevenWrPct: number; realisedWrPct: number; marginPp: number; geoMeanPct: number; arithMeanPct: number };
    capitalDay: { perDayPct: number; per20LegUsd: number; c200Usd: number; standardUsd: number };
    rows: number;
  };
  veto: {
    available: boolean; baseline?: { legs: number; notionalUsd: number; pnlUsd: number; roiPct: number };
    sweep?: { threshold: number; legs: number; pnlUsd: number; roiPct: number }[];
    flips?: number; monotone?: boolean;
    quartiles?: { quartile: number; evLo: number; evHi: number; legs: number; roiPct: number | null; ciLoPct: number | null; ciHiPct: number | null }[];
    byBand?: { band: string; legs: number; roiPct: number }[];
    justified?: boolean;
  };
  v63Corroboration: { band: string; heldOutRoiPct: number | null; heldOutLegs: number | null; note: string };
};

function load(): Art | null {
  const p = join(process.cwd(), "data", "ml", "dashboard.json");
  if (!existsSync(p)) return null;
  try {
    return JSON.parse(readFileSync(p, "utf8")) as Art;
  } catch {
    return null;
  }
}

const sgn = (v: number | null, nd = 2) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(nd)}%`);

type ObsBucket = {
  bucket: number; n: number; markets: number; win_rate: number;
  roi_net_pct: number; ci_lo: number | null; ci_hi: number | null;
};
type ObserveReport = {
  built_at: string; status: string; observations: number; distinct_markets: number;
  settled_observations: number; settled_markets: number; by_day: Record<string, number>;
  baseline_roi_net_pct: number | null; buckets: number; tables: Record<string, ObsBucket[]>;
  nominal_tests: number; expected_hits_by_chance: number; hits: ObsBucket[];
};

/**
 * The observe-only record, written by scripts/ml-observe-read.py. Read, never recomputed here --
 * same rule as dashboard.json: the page must not be able to drift from the script that measured it.
 */
function loadObserve(): ObserveReport | null {
  const p = join(process.cwd(), "data", "ml", "observe-report.json");
  if (!existsSync(p)) return null;
  try {
    return JSON.parse(readFileSync(p, "utf8")) as ObserveReport;
  } catch {
    return null;
  }
}
type KalshiLane = {
  builtAt: string; status: string; closedOn: string; reason: string;
  arb: {
    byDirection: Record<string, { n: number; medianNet: number; netPositivePct: number }>;
    medianNetAll: number | null; feeBand: number;
  };
  information: {
    windows: number; labelled: number; aucPm: number | null; aucKalshi: number | null;
    disagreementMedian: number | null; disagreementOverOneFeePct: number | null;
  };
  coverage: { copiesSeen: number; withKalshiQuote: number; crossListPct: number; unverifiedMatches: number } | null;
  reopenCondition: string;
};

/**
 * Second-venue status, written by scripts/kalshi-lane-status.py. Same rule as above: the page
 * reads the artefact, it never restates a number the script did not measure.
 */
function loadKalshi(): KalshiLane | null {
  const p = join(process.cwd(), "data", "ml", "kalshi-lane.json");
  if (!existsSync(p)) return null;
  try {
    return JSON.parse(readFileSync(p, "utf8")) as KalshiLane;
  } catch {
    return null;
  }
}
const tone = (v: number | null): "pos" | "neg" | "neutral" | undefined =>
  v === null || v === undefined ? undefined : v > 0 ? "pos" : v < 0 ? "neg" : "neutral";

export default async function MlPage() {
  const a = load();
  // Same loader, same definitions as /capital -- parameterised by bot, so the ML lane's
  // capital/deposit series is produced by the identical code path C-200 uses rather than a
  // parallel implementation that could drift.
  const cap = await loadCapitalState({ days: 30, botId: ML_BOT });
  const obs = loadObserve();
  const kal = loadKalshi();
  if (!a) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">ML lane</h1>
        <Card title="No measurement artifact">
          <Empty message="data/ml/dashboard.json is missing. Run: .venv-ml/bin/python scripts/ml-dashboard-artifacts.py" />
        </Card>
      </div>
    );
  }

  const nc = a.nearCertainty;
  const v = a.veto;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">ML lane — measurement record</h1>
        <p className="text-dim text-sm mt-1">
          Generated {a.generatedAt.slice(0, 19).replace("T", " ")}Z by{" "}
          <code className="text-xs">scripts/ml-dashboard-artifacts.py</code>
        </p>
        {/* Data age, not just build age: a fresh rebuild over a stale parquet would otherwise
            read as current. Each entry is the mtime of the artefact the numbers come from. */}
        {a.sources && (
          <p className="text-dim text-xs mt-1">
            input data:{" "}
            {Object.entries(a.sources).map(([k, s], i) => (
              <span key={k}>
                {i > 0 && " · "}
                {k}{" "}
                {s.ageHours === null
                  ? "MISSING"
                  : s.role === "study"
                    ? `study ${s.mtimeZ?.slice(0, 10) ?? ""}`   /* frozen held-out artefact: date is provenance, not staleness */
                    : s.ageHours < 24 ? `${Math.round(s.ageHours)}h` : `${(s.ageHours / 24).toFixed(1)}d`}
              </span>
            ))}
          </p>
        )}
      </div>

      {kal && (
        <Card title={`Second venue — Kalshi (${kal.status}, ${kal.closedOn})`}>
          <div className="grid grid-cols-3 gap-3">
            <Stat
              label="Arb: complete pair"
              value={`$${(1 - (kal.arb.medianNetAll ?? 0)).toFixed(4)}`}
              sub={`cost per $1.00 payout · ${kal.arb.byDirection.A?.netPositivePct ?? 0}% / ${kal.arb.byDirection.B?.netPositivePct ?? 0}% net-positive`}
              tone="neg"
            />
            <Stat
              label="Information: AUC P(up)"
              value={`${kal.information.aucPm?.toFixed(4) ?? "—"} / ${kal.information.aucKalshi?.toFixed(4) ?? "—"}`}
              sub={`Polymarket / Kalshi · ${kal.information.labelled} labelled windows`}
            />
            <Stat
              label="Venue disagreement"
              value={`${(kal.information.disagreementOverOneFeePct ?? 0).toFixed(1)}%`}
              sub={`differ by >1 fee · median ${kal.information.disagreementMedian?.toFixed(4) ?? "—"}`}
            />
          </div>
          <p className="text-dim text-sm mt-3 leading-relaxed">
            Status: {kal.reason}. A complete cross-venue pair costs more than the payout it buys, and
            Kalshi&apos;s own quote adds nothing to Polymarket&apos;s price at predicting the same
            outcome. Reopening requires {kal.reopenCondition}.
          </p>
          <p className="text-dim text-xs mt-2">
            Measured {kal.builtAt.slice(0, 19).replace("T", " ")}Z by{" "}
            <code className="text-xs">scripts/kalshi-lane-status.py</code>
            {kal.coverage &&
              ` · copy cross-list coverage ${kal.coverage.crossListPct}% (${kal.coverage.withKalshiQuote}/${kal.coverage.copiesSeen}), ${kal.coverage.unverifiedMatches} unverified matches`}
          </p>
        </Card>
      )}

      <Card title={`PnL and capital — ML lane (${ML_BOT}), machinery identical to C-200`}>
        <div className="grid grid-cols-4 gap-3">
          <Stat label="Realised PnL" value={`$${cap.realized.toFixed(2)}`}
            sub={`${cap.series.points.length ? "booked" : "no trades yet"}`}
            tone={cap.realized > 0 ? "pos" : cap.realized < 0 ? "neg" : "neutral"} />
          <Stat label="Open MTM" value={`$${cap.openUnreal.toFixed(2)}`}
            sub={`${cap.openCount} open · $${cap.openNotional.toFixed(2)} notional`}
            tone={cap.openUnreal > 0 ? "pos" : cap.openUnreal < 0 ? "neg" : "neutral"} />
          <Stat label="Total capital (live)" value={`$${cap.liveTotalCapital.toFixed(2)}`}
            sub="principal + realized + open MTM" />
          <Stat label="Booked capital" value={`$${cap.bookedCapital.toFixed(2)}`}
            sub={`principal $${cap.principal.toFixed(2)}`} />
        </div>
        {cap.openCount === 0 && cap.realized === 0 && (
          <p className="text-dim text-sm mt-3 leading-relaxed">
            Standing at ${cap.principal.toFixed(0)} with no positions: the book starts here and every
            figure above is derived from <code className="text-xs">loadCapitalState({"{ botId }"})</code>, the
            same loader <code className="text-xs">/capital</code> uses for C-200. Nothing is duplicated,
            so the two lanes cannot disagree about what a deposit is.
          </p>
        )}
      </Card>

      <Card title={`Daily deposits — last ${cap.series.points.length} days (same definition as C-200)`}>
        {cap.series.points.length === 0 ? (
          <Empty message="No capital series yet." />
        ) : (
          <>
            <BarChart
              bars={cap.series.points.map((p) => ({ x: p.day.slice(5), y: p.deposit }))}
              goalLine={0}
              height={170}
              formatY={(y: number) => `$${y.toFixed(0)}`}
            />
            <div className="grid grid-cols-3 gap-3 mt-3">
              <Stat label="Deposits (sum)" value={`$${cap.series.points.reduce((s, p) => s + p.deposit, 0).toFixed(2)}`}
                sub={`${cap.series.points.filter((p) => p.deposit > 0).length} up / ${cap.series.points.filter((p) => p.deposit < 0).length} down`} />
              <Stat label="Booked PnL in window" value={`$${(cap.series.points[cap.series.points.length - 1]?.closing ?? 0).toFixed(2)}`}
                sub="closing booked capital" />
              <Stat label="Ledger entries" value={String(cap.ledger.length)}
                sub={cap.ledger.map((e) => `$${e.amountUsd} ${e.kind}`).join(" · ") || "none"} />
            </div>
            <p className="text-dim text-xs mt-2">
              Daily deposit = that day&apos;s booked PnL (finished trades at closedAt ?? resolvedAt) plus
              any ledger injection — the definition <code>/capital</code> uses, not a second one.
            </p>
          </>
        )}
      </Card>

      <Card title={`Observe-only record — the lane rates candidates and opens nothing (${obs?.status ?? "NOT YET"})`}>
        {!obs ? (
          <Empty message="No observe report yet. It is written by scripts/ml-observe-read.py." />
        ) : (
          <>
            <div className="grid grid-cols-4 gap-3">
              <Stat label="Observations" value={obs.observations.toLocaleString()}
                sub={`${obs.distinct_markets} distinct markets`} />
              <Stat label="Settled" value={obs.settled_observations.toLocaleString()}
                sub={`${obs.settled_markets} markets with an outcome`}
                tone={obs.settled_observations > 0 ? "pos" : "neutral"} />
              <Stat label="Days accumulating" value={String(Object.keys(obs.by_day ?? {}).length)}
                sub="one observation per market+side per day" />
              <Stat label="Baseline net ROI" value={obs.baseline_roi_net_pct === null ? "—" : sgn(obs.baseline_roi_net_pct, 3)}
                sub={obs.settled_observations > 0 ? "settled, net of fee at ask" : "nothing resolved yet"} />
            </div>
            {obs.status === "NOT_YET" ? (
              <p className="text-dim text-sm mt-3 leading-relaxed">
                The lane is recording and this is the honest state: {obs.observations} candidates rated,
                none resolved yet. Candidates are restricted to the model&apos;s trained time-to-resolution
                support so the served scores mean what they meant in training. At ~58–196 observations/day
                the first quintile read is roughly <strong>3 weeks</strong> away and a decile read ~6 weeks.
              </p>
            ) : (
              <>
                <p className="text-dim text-xs mt-2">
                  {obs.nominal_tests} nominal 95% intervals computed → {obs.expected_hits_by_chance} expected
                  to clear zero by chance alone. {obs.hits.length} did. This lane never trades on its own:
                  a cleared bucket raises a promotion question for you, it does not act.
                </p>
                {Object.entries(obs.tables ?? {}).map(([arm, rows]) => (
                  rows.length === 0 ? null : (
                    <div key={arm} className="mt-3">
                      <div className="text-xs text-dim mb-1">{arm}</div>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-dim text-xs">
                            <th className="text-left">Bucket</th><th className="text-right">n</th>
                            <th className="text-right">Win</th><th className="text-right">Net ROI</th>
                            <th className="text-right">95% CI</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((r) => (
                            <tr key={`${arm}-${r.bucket}`}>
                              <td>B{r.bucket}</td>
                              <td className="text-right">{r.n}</td>
                              <td className="text-right">{r.win_rate.toFixed(1)}%</td>
                              <td className="text-right">{sgn(r.roi_net_pct, 3)}</td>
                              <td className="text-right text-dim">
                                {r.ci_lo === null ? "—" : `[${sgn(r.ci_lo)}, ${sgn(r.ci_hi)}]`}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )
                ))}
              </>
            )}
          </>
        )}
      </Card>

      <Card title={`Verdict — lane ${a.lane.state}`}>
        <p className="text-sm font-medium">{a.lane.headline}</p>
        <p className="text-dim text-sm mt-2 leading-relaxed">{a.lane.detail}</p>
        <p className="text-sm mt-3">
          <span className="text-dim">Alpha source:</span> <strong>{a.lane.alphaSource}</strong>
        </p>
      </Card>

      <Card title="The decisive contrast — same band, same accounting">
        <div className="grid grid-cols-2 gap-4">
          <Stat label="<0.20 WITH wallet selection" value={sgn(a.contrast.withWalletPct, 1)} sub="copy book, measured legs" tone="pos" />
          <Stat label="<0.20 WITHOUT wallet selection" value={sgn(a.contrast.withoutWalletPct, 1)} sub="market-only candidates, net of ask+fee" tone="neg" />
        </div>
        <p className="text-dim text-sm mt-3">{a.contrast.note}</p>
        <BarChart
          bars={[
            { x: "with wallet", y: a.contrast.withWalletPct },
            { x: "without wallet", y: a.contrast.withoutWalletPct },
          ]}
          goalLine={0}
          height={170}
          formatY={(y: number) => `${y.toFixed(0)}%`}
        />
      </Card>

      <Card title={`Market-only band economics — ${a.marketOnly.gated.toLocaleString()} gated of ${a.marketOnly.candidates.toLocaleString()} candidates`}>
        <div className="overflow-x-auto">
          <table className="text-sm w-full">
            <thead className="text-dim text-xs">
              <tr className="text-left">
                <th className="py-1">band</th><th>rows</th><th>mkts</th><th>prem</th>
                <th>@mid</th><th>net</th><th>95% CI</th>
              </tr>
            </thead>
            <tbody>
              {a.marketOnly.bands.map((b) => (
                <tr key={b.band} className="border-t border-white/5">
                  <td className="py-1 font-mono">{b.band}</td>
                  <td>{b.rows.toLocaleString()}</td>
                  <td>{b.markets.toLocaleString()}</td>
                  <td>{b.premiumPct?.toFixed(1)}%</td>
                  <td>{sgn(b.roiMidPct)}</td>
                  <td className={b.roiNetPct !== null && b.roiNetPct > 0 ? "text-pos" : "text-neg"}>{sgn(b.roiNetPct)}</td>
                  <td className="text-dim text-xs">[{sgn(b.ciLoPct)}, {sgn(b.ciHiPct)}]</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-dim text-xs mt-2">
          Net = after the taker premium and taker fee. Cheap entries are the most expensive place to
          cross the spread, not the cheapest.
        </p>
      </Card>

      <Card title={`The one positive band, examined — 0.8–1.0 (${nc.rows.toLocaleString()} rows)`}>
        <div className="overflow-x-auto">
          <table className="text-sm w-full">
            <thead className="text-dim text-xs">
              <tr className="text-left"><th className="py-1">sub-band</th><th>rows</th><th>mkts</th><th>net</th><th>95% CI</th><th>clears 0</th></tr>
            </thead>
            <tbody>
              {nc.subbands.map((s) => (
                <tr key={s.band} className="border-t border-white/5">
                  <td className="py-1 font-mono">{s.band}</td>
                  <td>{s.rows.toLocaleString()}</td>
                  <td>{s.markets.toLocaleString()}</td>
                  <td className={s.roiNetPct > 0 ? "text-pos" : "text-neg"}>{sgn(s.roiNetPct)}</td>
                  <td className="text-dim text-xs">[{sgn(s.ciLoPct)}, {sgn(s.ciHiPct)}]</td>
                  <td>{s.clearsZero ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="grid grid-cols-3 gap-4 mt-4">
          {nc.sensitivity.map((s) => (
            <Stat key={s.premiumMult} label={`premium ×${s.premiumMult}`} value={sgn(s.roiNetPct)}
              sub={s.premiumMult === 1 ? "as quoted" : s.roiNetPct > 0 ? "survives" : "edge gone"}
              tone={tone(s.roiNetPct)} />
          ))}
        </div>
        <p className="text-dim text-sm mt-2">
          A fill 50 % worse than the quoted ask erases the edge entirely. There is no margin for error.
        </p>

        <div className="grid grid-cols-4 gap-3 mt-4">
          <Stat label="trades losing ≥95%" value={`${nc.geometry.loserSharePct}%`} sub={`mean loss ${nc.geometry.meanLossPct}%`} tone="neg" />
          <Stat label="win rate vs breakeven" value={`${nc.geometry.realisedWrPct}%`} sub={`breakeven ${nc.geometry.breakevenWrPct}%`} />
          <Stat label="margin" value={`${nc.geometry.marginPp >= 0 ? "+" : ""}${nc.geometry.marginPp}pp`} sub="thin" tone={tone(nc.geometry.marginPp)} />
          <Stat label="geometric mean / trade" value={`${nc.geometry.geoMeanPct}%`} sub={`arithmetic ${sgn(nc.geometry.arithMeanPct)}`} tone="neg" />
        </div>
        <p className="text-dim text-sm mt-2 leading-relaxed">
          The arithmetic mean is positive; the geometric mean is <strong>{nc.geometry.geoMeanPct}%</strong>.
          At full size this compounds to ruin, and sized small enough to survive it, the absolute return
          is nil.
        </p>
      </Card>

      <Card title="Edge per capital-day — the metric that decided STANDARD vs C-200">
        <div className="grid grid-cols-3 gap-4">
          <Stat label="0.8–1.0 lane, $20 leg" value={`$${nc.capitalDay.per20LegUsd.toFixed(4)}`} sub={`${nc.capitalDay.perDayPct}% of capital/day`} tone="neg" />
          <Stat label="STANDARD" value={`$${nc.capitalDay.standardUsd.toFixed(4)}`} sub="measured 2026-10-20" />
          <Stat label="C-200" value={`$${nc.capitalDay.c200Usd.toFixed(4)}`} sub="measured 2026-10-20" tone="pos" />
        </div>
        <p className="text-dim text-sm mt-2">
          The near-certainty lane is 2× worse than STANDARD — the lane v64 is freezing for lack of edge —
          and 69× worse than C-200.
        </p>
      </Card>

      <Card title="Model-as-veto — is the ranking tradeable?">
        {!v.available || !v.baseline ? (
          <Empty message="No held-out legs joined the model predictions yet." />
        ) : (
          <>
            <div className="grid grid-cols-4 gap-3">
              <Stat label="held-out legs" value={v.baseline.legs.toLocaleString()} sub={`$${v.baseline.notionalUsd.toLocaleString()} notional`} />
              <Stat label="baseline PnL" value={`$${v.baseline.pnlUsd.toFixed(2)}`} sub={`ROI ${sgn(v.baseline.roiPct)}`} tone={tone(v.baseline.roiPct)} />
              <Stat label="sweep direction changes" value={String(v.flips)} sub={v.monotone ? "monotone" : "non-monotone"} tone={v.monotone ? "neutral" : "neg"} />
              <Stat label="veto justified" value={v.justified ? "YES" : "NO"} sub="on this holdout" tone={v.justified ? "pos" : "neg"} />
            </div>

            {v.sweep && v.sweep.length > 0 && (
              <div className="mt-3">
                <BarChart
                  bars={v.sweep.map((s) => ({ x: `EV>${s.threshold}`, y: s.pnlUsd }))}
                  goalLine={v.baseline.pnlUsd}
                  goalLabel="take-all baseline"
                  height={170}
                  formatY={(y: number) => `$${y.toFixed(0)}`}
                />
              </div>
            )}

            {v.quartiles && (
              <table className="text-sm w-full mt-3">
                <thead className="text-dim text-xs">
                  <tr className="text-left"><th className="py-1">EV quartile</th><th>range</th><th>legs</th><th>realised ROI</th><th>95% CI</th></tr>
                </thead>
                <tbody>
                  {v.quartiles.map((q) => (
                    <tr key={q.quartile} className="border-t border-white/5">
                      <td className="py-1">Q{q.quartile}</td>
                      <td className="font-mono text-xs">{q.evLo} … {q.evHi}</td>
                      <td>{q.legs}</td>
                      <td className={q.roiPct !== null && q.roiPct > 0 ? "text-pos" : "text-neg"}>{sgn(q.roiPct)}</td>
                      <td className="text-dim text-xs">[{sgn(q.ciLoPct)}, {sgn(q.ciHiPct)}]</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="text-dim text-sm mt-2 leading-relaxed">
              A real ordering must be monotone — raising the threshold keeps a strictly better subset.
              This sweep reverses direction and every quartile CI spans zero, so the apparent best
              threshold is a point on a noisy curve rather than a signal. No veto is proposed.
            </p>
          </>
        )}
      </Card>

      <Card title="Independent corroboration of v63">
        <div className="grid grid-cols-2 gap-4">
          <Stat label={`held-out ${a.v63Corroboration.band} legs`} value={sgn(a.v63Corroboration.heldOutRoiPct)}
            sub={`${a.v63Corroboration.heldOutLegs ?? "—"} legs, same outcome as the live rule`} tone={tone(a.v63Corroboration.heldOutRoiPct)} />
          <Stat label="v63 live rule" value="skip 0.4–0.6" sub="standardSkipBandRange" />
        </div>
        <p className="text-dim text-sm mt-2">{a.v63Corroboration.note}</p>
      </Card>
    </div>
  );
}
