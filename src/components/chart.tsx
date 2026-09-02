/**
 * Lightweight SVG line chart (server-renderable, no client JS needed).
 */

export function LineChart({
  series,
  points,
  height = 160,
  formatY = (v: number) => v.toFixed(0),
}: {
  series?: Array<{
    name: string;
    points: { x: string; y: number }[];
    strokeColor: string;
    /** Optional dash pattern, e.g. "4 4" for projections. */
    dash?: string;
  }>;
  points?: { x: string; y: number }[];
  height?: number;
  formatY?: (v: number) => string;
}) {
  const chartSeries = series || (points ? [{ name: "series", points, strokeColor: "#34d399" }] : []);
  const validSeries = chartSeries.filter((s) => s.points.length >= 2);

  if (validSeries.length === 0) {
    return <div className="text-dim text-sm py-8 text-center">Not enough data to chart yet.</div>;
  }
  const w = 720;
  const h = height;
  const pad = 36;
  const ys = validSeries.flatMap((s) => s.points.map((p) => p.y));
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys, 0);
  const range = maxY - minY || 1;
  const sx = (i: number, len: number) => {
    if (len <= 1) return pad + (w - pad * 2) / 2; // Center single points
    return pad + (i / (len - 1)) * (w - pad * 2);
  };
  const sy = (y: number) => h - pad - ((y - minY) / range) * (h - pad * 2);

  const zeroY = sy(0);
  const firstX = validSeries.length > 0 ? validSeries[0].points[0].x : "Now";
  // Get max length series to determine last X label
  const longestSeries = validSeries.length > 0 ? validSeries.reduce((prev, curr) => (curr.points.length > prev.points.length ? curr : prev), validSeries[0]) : { points: [{ x: "Now" }] };
  const lastX = longestSeries.points[longestSeries.points.length - 1].x;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full">
      {/* zero line */}
      {minY < 0 && maxY > 0 && (
        <line x1={pad} x2={w - pad} y1={zeroY} y2={zeroY} stroke="#1e2433" strokeDasharray="4 4" />
      )}
      
      {chartSeries.map((s, idx) => {
        // Render something even if points < 2 for empty series (like a fresh bot)
        if (s.points.length === 0) return null;
        
        const path = s.points.map((p, i) => `${i === 0 ? "M" : "L"}${sx(i, s.points.length).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ");
        const last = s.points[s.points.length - 1];
        // Use a default red for negative single-series legacy mode, otherwise use the series color
        const color = (!series && last.y < 0) ? "#f87171" : s.strokeColor;
        
        return (
          <g key={s.name}>
            {s.points.length >= 2 && (
              <path d={path} fill="none" stroke={color} strokeWidth="2" strokeDasharray={s.dash} />
            )}
            <circle cx={sx(s.points.length - 1, s.points.length)} cy={sy(last.y)} r="3.5" fill={color} />
            <text x={w - pad + 4} y={sy(last.y) + (idx * 12) + 4} fill={color} fontSize="11" fontFamily="monospace">
              {formatY(last.y)}
            </text>
          </g>
        );
      })}
      
      {/* min/max labels */}
      <text x={4} y={sy(maxY) + 4} fill="#8b93a7" fontSize="10" fontFamily="monospace">
        {formatY(maxY)}
      </text>
      <text x={4} y={sy(minY) + 4} fill="#8b93a7" fontSize="10" fontFamily="monospace">
        {formatY(minY)}
      </text>
      {/* x labels: first and last */}
      <text x={pad} y={h - 8} fill="#8b93a7" fontSize="10" fontFamily="monospace">
        {firstX}
      </text>
      <text x={w - pad} y={h - 8} fill="#8b93a7" fontSize="10" fontFamily="monospace" textAnchor="end">
        {lastX}
      </text>
    </svg>
  );
}

/** Vertical bars with optional goal line + highlighted index range (streak). */
export function BarChart({
  bars,
  goalLine,
  goalLabel,
  highlight,
  height = 180,
  formatY = (v: number) => v.toFixed(0),
}: {
  bars: { x: string; y: number }[];
  goalLine?: number;
  goalLabel?: string;
  highlight?: { label: string; from: number; to: number };
  height?: number;
  formatY?: (v: number) => string;
}) {
  if (bars.length === 0) {
    return <div className="text-dim text-sm py-8 text-center">Not enough data to chart yet.</div>;
  }
  const w = 720;
  const h = height;
  const pad = 36;
  const ys = bars.map((b) => b.y).concat(goalLine !== undefined ? [goalLine] : []);
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys, 0);
  const range = maxY - minY || 1;
  const step = (w - pad * 2) / bars.length;
  const barW = Math.min(26, step * 0.6);
  const sy = (y: number) => h - pad - ((y - minY) / range) * (h - pad * 2);
  const zeroY = sy(0);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full">
      {highlight && highlight.from <= highlight.to && (
        <rect
          x={pad + highlight.from * step}
          y={pad * 0.4}
          width={(highlight.to - highlight.from + 1) * step - 4}
          height={h - pad * 1.4}
          fill="#3b82f6"
          opacity={0.08}
        />
      )}
      {minY < 0 && maxY > 0 && (
        <line x1={pad} x2={w - pad} y1={zeroY} y2={zeroY} stroke="#1e2433" strokeDasharray="4 4" />
      )}
      {bars.map((b, i) => {
        const y = sy(b.y);
        const bh = Math.max(1, Math.abs(zeroY - y));
        const color = b.y >= 0 ? "#34d399" : "#f87171";
        return (
          <g key={b.x}>
            <rect x={pad + i * step + (step - barW) / 2} y={Math.min(y, zeroY)} width={barW} height={bh} fill={color} opacity={0.85} rx={2}>
              <title>{`${b.x}: ${formatY(b.y)}`}</title>
            </rect>
            {bars.length <= 31 && (
              <text x={pad + i * step + step / 2} y={h - 10} fill="#8b93a7" fontSize="9" fontFamily="monospace" textAnchor="middle">
                {b.x}
              </text>
            )}
          </g>
        );
      })}
      {goalLine !== undefined && (
        <g>
          <line x1={pad} x2={w - pad} y1={sy(goalLine)} y2={sy(goalLine)} stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="6 3" />
          <text x={w - pad} y={sy(goalLine) - 4} fill="#fbbf24" fontSize="10" fontFamily="monospace" textAnchor="end">
            {goalLabel ?? `goal ${formatY(goalLine)}`}
          </text>
        </g>
      )}
      <text x={4} y={sy(maxY) + 4} fill="#8b93a7" fontSize="10" fontFamily="monospace">
        {formatY(maxY)}
      </text>
      <text x={4} y={sy(minY) + 4} fill="#8b93a7" fontSize="10" fontFamily="monospace">
        {formatY(minY)}
      </text>
      {highlight && (
        <text x={pad + highlight.from * step} y={pad * 0.35} fill="#93c5fd" fontSize="10">
          {highlight.label}
        </text>
      )}
    </svg>
  );
}

/** Grid heatmap: cell value -> red/green scale; cells with n < minN render dim. */
export function Heatmap({
  xLabels,
  yLabels,
  cells,
  height = 200,
  formatV = (v: number) => v.toFixed(0),
}: {
  xLabels: string[];
  yLabels: string[];
  cells: { x: number; y: number; v: number; n: number }[];
  height?: number;
  formatV?: (v: number) => string;
}) {
  const w = 720;
  const h = height;
  const pad = 40;
  const cw = (w - pad) / Math.max(1, xLabels.length);
  const chh = (h - pad) / Math.max(1, yLabels.length);
  const vs = cells.map((c) => c.v);
  const lim = Math.max(...vs.map((v) => Math.abs(v)), 1);

  const color = (v: number): string => {
    if (v >= 0) {
      const t = v / lim;
      return `rgb(${Math.round(52 + (52 - 52) * 0)}, ${Math.round(211 - 211 * t * 0.5)}, ${Math.round(153 - 153 * t * 0.55)})`;
    }
    const t = -v / lim;
    return `rgb(${Math.round(248 + 0)}, ${Math.round(113 - 40 * t)}, ${Math.round(113 - 40 * t)})`;
  };

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full">
      {xLabels.map((l, i) => (
        <text key={l} x={pad + i * cw + cw / 2} y={h - 8} fill="#8b93a7" fontSize="9" fontFamily="monospace" textAnchor="middle">
          {l}
        </text>
      ))}
      {yLabels.map((l, i) => (
        <text key={l} x={pad - 4} y={pad + i * chh + chh / 2 + 3} fill="#8b93a7" fontSize="9" fontFamily="monospace" textAnchor="end">
          {l}
        </text>
      ))}
      {cells.map((c, i) => {
        const dim = c.n < 3;
        return (
          <rect
            key={i}
            x={pad + c.x * cw + 1}
            y={pad + c.y * chh + 1}
            width={cw - 2}
            height={chh - 2}
            fill={dim ? "#141a26" : color(c.v)}
            opacity={dim ? 0.5 : 0.85}
            rx={2}
          >
            <title>{`${yLabels[c.y]} ${xLabels[c.x]}: ${formatV(c.v)} (n=${c.n})`}</title>
          </rect>
        );
      })}
    </svg>
  );
}

/** Scatter plot for wallet/signal analysis. */
export function Scatter({
  points,
  xLabel,
  yLabel,
  height = 220,
  formatX = (v: number) => v.toFixed(1),
  formatY = (v: number) => v.toFixed(1),
}: {
  points: { x: number; y: number; label?: string; color?: string; r?: number }[];
  xLabel: string;
  yLabel: string;
  height?: number;
  formatX?: (v: number) => string;
  formatY?: (v: number) => string;
}) {
  if (points.length === 0) {
    return <div className="text-dim text-sm py-8 text-center">Not enough data to chart yet.</div>;
  }
  const w = 720;
  const h = height;
  const pad = 40;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs, 0);
  const maxX = Math.max(...xs, 1);
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys, 1);
  const sx = (x: number) => pad + ((x - minX) / (maxX - minX || 1)) * (w - pad * 2);
  const sy = (y: number) => h - pad - ((y - minY) / (maxY - minY || 1)) * (h - pad * 2);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full">
      <text x={4} y={h - 8} fill="#8b93a7" fontSize="10" fontFamily="monospace">
        {xLabel}
      </text>
      <text x={w - pad} y={h - 8} fill="#8b93a7" fontSize="10" fontFamily="monospace" textAnchor="end">
        {formatX(maxX)}
      </text>
      <text x={4} y={pad - 6} fill="#8b93a7" fontSize="10" fontFamily="monospace">
        {yLabel} {formatY(maxY)}
      </text>
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={sx(p.x)} cy={sy(p.y)} r={p.r ?? 4} fill={p.color ?? "#3b82f6"} opacity={0.85}>
            <title>{`${p.label ?? ""} (${formatX(p.x)}, ${formatY(p.y)})`}</title>
          </circle>
        </g>
      ))}
    </svg>
  );
}
