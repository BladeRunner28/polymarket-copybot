/**
 * Capital deposits chart (2026-09-20, user request).
 *
 * Two server-rendered SVG panels, no client JS (same constraint as chart.tsx):
 *   A) daily deposits into Total Capital — signed bars (green = up day, red =
 *      down day); the ledger-funded part of a bar is outlined in blue so an
 *      injection is never confused with trading PnL
 *   B) booked capital level — the cumulative result of those deposits
 *
 * SCALE: a couple of outlier days ($993 and $743 in the Sep window) would
 * otherwise flatten every ordinary day to 1–2px, which reads as an empty chart —
 * that was the first version's bug. The bar panel now uses `depositScale()`
 * (90th-percentile axis, real maximum unless an outlier exceeds 2.5× it) and
 * draws over-range days clipped with a caret marker; the true value is in the
 * hover title, the caption and the table. Never silently truncate.
 */

import { depositScale, type DailyCapitalPoint } from "@/lib/capital";

const MIN_BAR_PX = 2;

export function CapitalDepositsChart({
  points,
  principal,
  height = 200,
}: {
  points: DailyCapitalPoint[];
  /** Standing principal — drawn as a dashed reference line when in range. */
  principal?: number;
  height?: number;
}) {
  const valid = points.filter((p) => p && p.day);
  if (valid.length < 2) {
    return <div className="text-dim text-sm py-8 text-center">Not enough data to chart yet.</div>;
  }

  const w = 720;
  const padL = 62;
  const padR = 22;
  const gap = 34;
  const hB = 116;
  const totalH = height + gap + hB + 16;

  const scale = depositScale(valid);
  const axisMax = scale.axisMax;
  const clippedDays = new Set(scale.clipped.map((c) => c.day));

  // ---- panel A: daily deposits (flow), symmetric robust axis ----
  const minA = -axisMax;
  const maxA = axisMax;
  const rangeA = maxA - minA || 1;
  const yA = (v: number) => 12 + (1 - (v - minA) / rangeA) * (height - 26);
  const zeroA = yA(0);

  const step = (w - padL - padR) / valid.length;
  const barW = Math.max(2, Math.min(22, step * 0.62));

  // ---- panel B: capital level ----
  const levels = valid.map((p) => p.closing);
  const rawMin = Math.min(...levels);
  const rawMax = Math.max(...levels);
  const padB = (rawMax - rawMin) * 0.12 || Math.max(1, Math.abs(rawMax) * 0.01);
  const minB = rawMin - padB;
  const maxB = rawMax + padB;
  const rangeB = maxB - minB || 1;
  const topB = height + gap;
  const yB = (v: number) => topB + (1 - (v - minB) / rangeB) * (hB - 22);
  const xB = (i: number) => padL + i * step + step / 2;
  const linePath = valid.map((p, i) => `${i === 0 ? "M" : "L"}${xB(i).toFixed(1)},${yB(p.closing).toFixed(1)}`).join(" ");
  const lastPoint = valid[valid.length - 1];
  const principalInRange = principal !== undefined && principal >= minB && principal <= maxB;

  const fmt = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(Math.abs(v) < 10 ? 2 : 0)}`;

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-dim font-mono px-1">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "#34d399" }} /> up day
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "#f87171" }} /> down day
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm border border-dashed" style={{ borderColor: "#3b82f6" }} /> ledger injection
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-4 h-0.5" style={{ background: "#60a5fa" }} /> capital level
        </span>
        {scale.isClipped && (
          <span className="inline-flex items-center gap-1.5 text-warn">
            ▴ clipped at {fmt(axisMax)} ({scale.clipped.length} day{scale.clipped.length === 1 ? "" : "s"} beyond — values in the table)
          </span>
        )}
      </div>

      <svg viewBox={`0 0 ${w} ${totalH}`} className="w-full">
        {/* panel A axis labels */}
        <text x={4} y={yA(maxA) + 8} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          {fmt(maxA)}
        </text>
        <text x={4} y={yA(minA)} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          {fmt(minA)}
        </text>
        <line x1={padL} x2={w - padR} y1={zeroA} y2={zeroA} stroke="#1e2433" strokeDasharray="4 4" />

        {valid.map((p, i) => {
          const x = padL + i * step + (step - barW) / 2;
          const isClipped = clippedDays.has(p.day);
          const shown = isClipped ? (p.deposit > 0 ? axisMax : -axisMax) : p.deposit;
          const y = yA(shown);
          const top = Math.min(y, zeroA);
          const h = Math.max(p.deposit === 0 ? 1 : MIN_BAR_PX, Math.abs(y - zeroA));
          const fill = p.deposit >= 0 ? "#34d399" : "#f87171";
          const injected = p.injected !== 0;
          const yDep = yA(shown);
          const yBooked = yA(Math.max(-axisMax, Math.min(axisMax, p.booked)));
          return (
            <g key={p.day}>
              <title>
                {`${p.day}: deposit ${fmt(p.deposit)} (booked ${fmt(p.booked)}${injected ? `, ledger ${fmt(p.injected)}` : ""})` +
                  ` · capital ${fmt(p.closing)} · ${p.trades} trade(s)${isClipped ? " · bar clipped" : ""}`}
              </title>
              {p.deposit === 0 && <rect x={x} y={zeroA - 0.5} width={barW} height={1} fill="#334155" opacity={0.6} />}
              {p.deposit !== 0 && (
                <>
                  <rect x={x} y={top} width={barW} height={h} fill={fill} opacity={0.85} rx={1} />
                  {injected && (
                    <rect
                      x={x}
                      y={Math.min(yDep, yBooked)}
                      width={barW}
                      height={Math.max(1, Math.abs(yDep - yBooked))}
                      fill="none"
                      stroke="#3b82f6"
                      strokeDasharray="2 2"
                    />
                  )}
                  {isClipped && (
                    <polygon
                      points={
                        p.deposit > 0
                          ? `${x + barW / 2},${top - 6} ${x},${top - 1} ${x + barW},${top - 1}`
                          : `${x + barW / 2},${top + h + 6} ${x},${top + h + 1} ${x + barW},${top + h + 1}`
                      }
                      fill={fill}
                    />
                  )}
                </>
              )}
            </g>
          );
        })}

        <text x={padL} y={height + 14} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          daily deposit into Total Capital (booked PnL + ledger flows)
        </text>

        {/* panel B */}
        <text x={4} y={yB(maxB) + 4} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          {fmt(maxB)}
        </text>
        <text x={4} y={yB(minB) + 4} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          {fmt(minB)}
        </text>
        <path d={linePath} fill="none" stroke="#60a5fa" strokeWidth="2" />
        {principalInRange && (
          <>
            <line x1={padL} x2={w - padR} y1={yB(principal as number)} y2={yB(principal as number)} stroke="#64748b" strokeDasharray="5 4" />
            <text x={w - padR} y={yB(principal as number) - 4} fill="#64748b" fontSize="10" fontFamily="monospace" textAnchor="end">
              principal {fmt(principal as number)}
            </text>
          </>
        )}
        <circle cx={xB(valid.length - 1)} cy={yB(lastPoint.closing)} r="3.5" fill="#60a5fa" />
        <text x={w - padR} y={yB(lastPoint.closing) - 6} fill="#60a5fa" fontSize="11" fontFamily="monospace" textAnchor="end">
          {fmt(lastPoint.closing)}
        </text>

        <text x={padL} y={totalH - 2} fill="#8b93a7" fontSize="10" fontFamily="monospace">
          {valid[0].day}
        </text>
        <text x={w - padR} y={totalH - 2} fill="#8b93a7" fontSize="10" fontFamily="monospace" textAnchor="end">
          {lastPoint.day}
        </text>
      </svg>

      <p className="text-[11px] text-dim px-1">
        Bar = the day&apos;s deposit (green up / red down), dashed outline = the part funded by a ledger injection rather
        than trading, line = booked capital at each close.
        {scale.isClipped && (
          <>
            {" "}
            Axis is scaled to the 90th percentile ({fmt(axisMax)}) so ordinary days stay visible —{" "}
            <span className="text-warn">
              {scale.clipped.map((c) => `${c.day} ${fmt(c.deposit)}`).join(", ")}
            </span>{" "}
            exceed it and are drawn clipped (▴). True values are in the table below.
          </>
        )}
      </p>
    </div>
  );
}
