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
            {s.points.length >= 2 && <path d={path} fill="none" stroke={color} strokeWidth="2" />}
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
