/**
 * Open MTM horizon card (2026-10-04, user request).
 *
 * Answers one question the rest of the dashboard leaves implicit: the open
 * mark-to-market on /capital is not cash — WHEN does each open position stop
 * marking and become booked PnL? Three server-rendered SVG panels, no client JS
 * (same constraint as chart.tsx / capital-chart.tsx):
 *
 *   A) horizon bars   — Σ open unrealized by time-to-close bucket, with the
 *                       stranded cost drawn underneath so a bar is never bigger
 *                       than the money it is holding
 *   B) close timeline — one dot per open market, x = hours until its estimated
 *                       close (log axis, because horizons span 2 h to 8 mo),
 *                       area = |mark|. Overdue markets sit on the left edge.
 *   C) unlock ladder + the next closes as a table
 *
 * The estimate is `MarketSnapshot.collectedAt + timeToResolution` — see
 * src/lib/open-mtm-horizon.ts for why the card must also publish snapshot
 * staleness and the overdue count. Never present the horizon without them.
 */

import type { HorizonSummary } from "@/lib/open-mtm-horizon";
import { formatHorizon } from "@/lib/open-mtm-horizon";

const usd = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;
const usd0 = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(0)}`;
/** Bar ticks: cents matter below $10 — a $0.67 bar must not read "$0". */
const usdTick = (v: number) => (Math.abs(v) < 10 ? usd(v) : usd0(v));
const pct = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

const TICKS = [
  { h: 0, label: "overdue" },
  { h: 6, label: "6 h" },
  { h: 24, label: "1 d" },
  { h: 72, label: "3 d" },
  { h: 168, label: "7 d" },
  { h: 720, label: "30 d" },
  { h: 2160, label: "90 d" },
  { h: 8760, label: "1 y" },
];

/** log10 x-position for hours, clamped at the left edge for overdue/unknown. */
function makeX(hours: number, span: number, padL: number, padR: number, w: number) {
  const lo = Math.log10(0.25);
  const hi = Math.log10(span);
  return (h: number) => {
    const v = Math.max(0.25, Math.min(h, span));
    return padL + ((Math.log10(v) - lo) / (hi - lo)) * (w - padL - padR);
  };
}

export function OpenMtmHorizonCard({
  summary,
  label,
  capNote,
}: {
  summary: HorizonSummary;
  /** e.g. "C-200" / "STANDARD" — shown in the header and captions. */
  label: string;
  /** Optional page-specific note appended to the caption. */
  capNote?: string;
}) {
  const { buckets, groups, steps, totals, warnings } = summary;

  if (groups.length === 0) {
    return <div className="text-dim text-sm py-6 text-center">No open positions — nothing to close.</div>;
  }

  const cap = Math.max(totals.cost, totals.grossUnrealized, 1);

  // ---- panel A: horizon bars -------------------------------------------------
  const w = 720;
  const padL = 58;
  const padR = 14;
  const hA = 150;
  const step = (w - padL - padR) / buckets.length;
  const barW = Math.min(56, step * 0.54);
  const maxA = Math.max(
    ...buckets.map((b) => Math.max(Math.abs(b.unrealized), b.cost)),
    0.01,
  );
  const zeroA = 22 + hA / 2;
  const yA = (v: number) => zeroA - (v / maxA) * (hA / 2 - 12);

  // ---- panel B: timeline ----------------------------------------------------
  const padTopB = 26;
  const hB = 130;
  const span = Math.max(8760, totals.longestHours);
  const xB = makeX(totals.longestHours, span, padL, padR, w);
  const midB = padTopB + hB / 2;
  const dotR = (mtm: number) => Math.max(2.5, Math.min(16, Math.sqrt(Math.abs(mtm)) / 1.1));
  const timedDots = groups.filter((g) => g.remainHours !== null);

  // ---- panel C: next closes -------------------------------------------------
  const nextCloses = [...groups]
    .filter((g) => g.remainHours !== null)
    .sort((a, b) => (a.remainHours as number) - (b.remainHours as number))
    .slice(0, 12);

  const untimed = groups.filter((g) => g.remainHours === null);
  const topBySize = [...groups].sort((a, b) => Math.abs(b.unrealized) - Math.abs(a.unrealized)).slice(0, 3);

  return (
    <div className="space-y-3">
      {/* headline numbers */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
        <div className="border border-edge rounded-lg px-3 py-2">
          <div className="text-dim uppercase tracking-wide text-[10px]">open mark</div>
          <div className={`text-lg font-bold ${totals.unrealized >= 0 ? "text-pos" : "text-neg"}`}>
            {usd(totals.unrealized)}
          </div>
          <div className="text-dim">
            {totals.legs} legs · {totals.groups} markets · cost {usd(totals.cost)}
          </div>
        </div>
        <div className="border border-edge rounded-lg px-3 py-2">
          <div className="text-dim uppercase tracking-wide text-[10px]">closes ≤ 24 h</div>
          <div className="text-lg font-bold text-ink">{usd(totals.within24h)}</div>
          <div className="text-dim">
            ≤ 7 d {usd(totals.within7d)} · ≤ 30 d {usd(totals.within30d)}
          </div>
        </div>
        <div className="border border-edge rounded-lg px-3 py-2">
          <div className="text-dim uppercase tracking-wide text-[10px]">longest dated</div>
          <div className="text-lg font-bold text-ink">
            {formatHorizon(totals.longestHours)}
          </div>
          <div className="text-dim truncate" title={totals.longestMarketId ?? ""}>
            {totals.longestMarketId ?? "—"}
          </div>
        </div>
        <div className={`border rounded-lg px-3 py-2 ${totals.overdueGroups > 0 ? "border-warn/50 bg-warn/10" : "border-edge"}`}>
          <div className="text-dim uppercase tracking-wide text-[10px]">overdue, still open</div>
          <div className={`text-lg font-bold ${totals.overdueGroups > 0 ? "text-warn" : "text-ink"}`}>
            {totals.overdueGroups}
          </div>
          <div className="text-dim">
            {totals.overdueLegs} legs · cost {usd(totals.overdueCost)}
          </div>
        </div>
      </div>

      {warnings.length > 0 && (
        <div className="border border-warn/40 bg-warn/10 text-warn text-[11px] rounded-md px-3 py-2 space-y-0.5">
          {warnings.map((wm) => (
            <div key={wm}>⚠ {wm}</div>
          ))}
        </div>
      )}

      {/* panel A */}
      <svg viewBox={`0 0 ${w} ${hA + 34}`} className="w-full">
        <line x1={padL} x2={w - padR} y1={zeroA} y2={zeroA} stroke="#1e2433" strokeDasharray="4 4" />
        <text x={4} y={zeroA + 4} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          $0
        </text>
        <text x={4} y={yA(maxA) + 4} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          {usd0(maxA)}
        </text>
        {buckets.map((b, i) => {
          const cx = padL + i * step + step / 2;
          const x = cx - barW / 2;
          const y = yA(b.unrealized);
          const top = Math.min(y, zeroA);
          const h = Math.max(b.unrealized === 0 ? 1 : 2, Math.abs(y - zeroA));
          const yCost = yA(b.cost);
          const stranded =
            b.unrealized < 0
              ? { y: yCost, h: Math.max(1, zeroA - yCost) } // cost band above zero when the mark is negative
              : { y: zeroA, h: Math.max(1, yCost - zeroA) };
          return (
            <g key={b.id}>
              <title>
                {`${b.label}: mark ${usd(b.unrealized)} (gross ${usd(b.grossUnrealized)}) · ${b.legs} legs in ${b.groups} markets · cost locked ${usd(b.cost)}`}
              </title>
              {b.groups > 0 && (
                <rect
                  x={x}
                  y={stranded.y}
                  width={barW}
                  height={stranded.h}
                  fill="#334155"
                  opacity={0.45}
                  rx={1}
                />
              )}
              {b.unrealized !== 0 ? (
                <rect x={x} y={top} width={barW} height={h} fill={b.color} opacity={0.9} rx={1} />
              ) : (
                b.groups > 0 && <rect x={x} y={zeroA - 0.5} width={barW} height={1} fill="#334155" />
              )}
              <text x={cx} y={zeroA + 13} fill="#8b93a7" fontSize="9.5" fontFamily="monospace" textAnchor="middle">
                {b.label}
              </text>
              <text x={cx} y={zeroA + 25} fill="#6b7280" fontSize="9" fontFamily="monospace" textAnchor="middle">
                {b.groups > 0 ? `${b.groups}m/${b.legs}l` : "—"}
              </text>
              {b.groups > 0 && (
                <text
                  x={cx}
                  y={b.unrealized >= 0 ? top - 4 : top + h + 10}
                  fill={b.unrealized >= 0 ? "#e6e9f0" : "#f87171"}
                  fontSize="9.5"
                  fontFamily="monospace"
                  textAnchor="middle"
                >
                  {usdTick(b.unrealized)}
                </text>
              )}
            </g>
          );
        })}
        <text x={padL} y={12} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          Σ open mark by time to close ({label}) · slab behind each bar = cost still tied up
        </text>
      </svg>

      {/* panel B */}
      <svg viewBox={`0 0 ${w} ${padTopB + hB + 26}`} className="w-full">
        <text x={padL} y={12} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          when each open market closes (dot area = |mark|; log time axis)
        </text>
        <line x1={padL} x2={w - padR} y1={midB} y2={midB} stroke="#1e2433" />
        {TICKS.filter((t) => t.h <= span).map((t) => (
          <g key={t.label}>
            <line x1={xB(t.h)} x2={xB(t.h)} y1={midB - 44} y2={midB + 44} stroke="#1e2433" strokeDasharray="3 4" />
            <text x={xB(t.h)} y={padTopB + hB + 14} fill="#8b93a7" fontSize="9.5" fontFamily="monospace" textAnchor="middle">
              {t.label}
            </text>
          </g>
        ))}
        <line x1={xB(0)} x2={xB(0)} y1={midB - 52} y2={midB + 52} stroke="#fbbf24" strokeWidth="1.5" />
        {timedDots.map((g) => {
          const h = g.remainHours as number;
          const cx = xB(h);
          const jitter = ((g.marketId.length * 37) % 41) - 20;
          const cy = midB + jitter;
          const r = dotR(g.unrealized);
          const fill = g.bucket === "overdue" ? "#fbbf24" : g.unrealized >= 0 ? "#34d399" : "#f87171";
          return (
            <g key={g.marketId}>
              <title>
                {`${g.question ?? g.marketId}\ncloses in ${formatHorizon(h)} · mark ${usd(g.unrealized)} · cost ${usd(g.cost)} · ${g.legs} leg(s) · snapshot ${g.staleDays === null ? "none" : `${g.staleDays.toFixed(1)} d old`}`}
              </title>
              <circle cx={cx} cy={cy} r={r} fill={fill} opacity={g.bucket === "overdue" ? 0.95 : 0.62} stroke={fill} strokeWidth={g.bucket === "overdue" ? 1.4 : 0} />
            </g>
          );
        })}
        <text x={padL} y={padTopB + hB + 24} fill="#6b7280" fontSize="9.5" fontFamily="monospace">
          yellow line = now · dots left of it already passed their close and are still open
        </text>
      </svg>

      {/* unlock ladder */}
      <div className="text-[11px] font-mono text-dim">
        <span className="text-ink">unlock ladder —</span>{" "}
        {steps.map((s) => (
          <span key={s.label} className="mr-3">
            by {s.label}:{" "}
            <span className={s.cumUnrealized >= 0 ? "text-pos" : "text-neg"}>{usd(s.cumUnrealized)}</span>{" "}
            <span className="text-dim">({s.legs} legs)</span>
          </span>
        ))}
        {untimed.length > 0 && (
          <span className="text-warn">
            · {untimed.length} market{untimed.length === 1 ? "" : "s"} ({usd(totals.untimedUnrealized)}) have no close
            date at all
          </span>
        )}
      </div>

      {/* panel C */}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] font-mono">
          <thead className="text-dim">
            <tr className="text-left">
              <th className="py-1 pr-3 font-normal">next closes</th>
              <th className="py-1 pr-3 font-normal text-right">closes in</th>
              <th className="py-1 pr-3 font-normal text-right">mark</th>
              <th className="py-1 pr-3 font-normal text-right">cost</th>
              <th className="py-1 pr-3 font-normal text-right">legs</th>
              <th className="py-1 font-normal">evidence</th>
            </tr>
          </thead>
          <tbody>
            {nextCloses.map((g) => (
              <tr key={g.marketId} className="border-t border-edge/60">
                <td className="py-1 pr-3 max-w-[300px] truncate" title={`${g.question ?? ""} (${g.marketId})`}>
                  {g.isDemo && <span className="text-dim">[demo] </span>}
                  {g.question ?? g.marketId}
                </td>
                <td className={`py-1 pr-3 text-right ${g.bucket === "overdue" ? "text-warn" : "text-ink"}`}>
                  {formatHorizon(g.remainHours)}
                </td>
                <td className={`py-1 pr-3 text-right ${g.unrealized >= 0 ? "text-pos" : "text-neg"}`}>
                  {usd(g.unrealized)}
                </td>
                <td className="py-1 pr-3 text-right text-dim">{usd(g.cost)}</td>
                <td className="py-1 pr-3 text-right text-dim">{g.legs}</td>
                <td className="py-1 text-dim">
                  {g.staleDays === null ? "no snapshot" : `snap ${g.staleDays.toFixed(1)} d old`}
                  {g.staleDays !== null && g.staleDays > 3 && <span className="text-warn"> ·stale</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-dim">
        Close estimate = latest <span className="font-mono">MarketSnapshot.collectedAt</span> +{" "}
        <span className="font-mono">timeToResolution</span> for that market. It estimates the{" "}
        <em>venue clock</em>, not a promise: the monitor only snapshots a market when it sees a copy-eligible fill, so a
        quiet market&apos;s evidence can be days old (shown per row), and any position can still close earlier when an
        exit rule fires. Largest single mark:{" "}
        <span className="font-mono text-ink">{topBySize[0]?.question?.slice(0, 56) ?? topBySize[0]?.marketId ?? "—"}</span>{" "}
        at <span className="font-mono">{usd(topBySize[0]?.unrealized ?? 0)}</span> ({pct(totals.topShare)} of the open
        mark). Nothing on this card is realized PnL — it says when the mark stops moving{capNote ? ` ${capNote}` : ""}.
      </p>
      <p className="text-[10px] text-dim font-mono">
        scale: bars share one axis (max {usd0(maxA)} / cost cap {usd0(cap)}); dot area ∝ |mark| — a $630 dot dwarfs a
        $0.13 dot by design, the small ones are still listed in the table.
      </p>
    </div>
  );
}
