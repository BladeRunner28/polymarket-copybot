import { ReactNode } from "react";

export function Card({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`bg-panel border border-edge rounded-xl p-4 ${className}`}>
      {title && <h2 className="text-sm font-semibold text-dim uppercase tracking-wide mb-3">{title}</h2>}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "pos" | "neg" | "neutral" }) {
  const color = tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : "text-ink";
  return (
    <div className="bg-panel border border-edge rounded-xl p-4">
      <div className="text-xs text-dim uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${color}`}>{value}</div>
      {sub && <div className="text-xs text-dim mt-1">{sub}</div>}
    </div>
  );
}

export function Pnl({ value }: { value: number }) {
  const tone = value > 0 ? "text-pos" : value < 0 ? "text-neg" : "text-dim";
  return (
    <span className={`font-mono ${tone}`}>
      {value >= 0 ? "+" : ""}${value.toFixed(2)}
    </span>
  );
}

export function Badge({ kind }: { kind: string }) {
  const styles: Record<string, string> = {
    track: "bg-pos/15 text-pos border-pos/30",
    watch: "bg-warn/15 text-warn border-warn/30",
    ignore: "bg-edge text-dim border-edge",
    paper_copy: "bg-pos/15 text-pos border-pos/30",
    watchlist: "bg-warn/15 text-warn border-warn/30",
    skip: "bg-edge text-dim border-edge",
    open: "bg-accent/15 text-accent border-accent/30",
    closed: "bg-edge text-dim border-edge",
    resolved: "bg-pos/15 text-pos border-pos/30",
    demo: "bg-warn/15 text-warn border-warn/30",
  };
  return (
    <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${styles[kind] ?? styles.ignore}`}>
      {kind.replace("_", " ")}
    </span>
  );
}

export function Addr({ address, label }: { address: string; label?: string | null }) {
  const short = `${address.slice(0, 6)}…${address.slice(-4)}`;
  return (
    <span className="font-mono text-sm" title={address}>
      {label ? (
        <>
          <span className="text-ink">{label}</span> <span className="text-dim">({short})</span>
        </>
      ) : (
        short
      )}
    </span>
  );
}

export function Empty({ message }: { message: string }) {
  return <div className="text-dim text-sm py-8 text-center">{message}</div>;
}

/** Score bar 0..100 */
export function ScoreBar({ score }: { score: number }) {
  const color = score >= 65 ? "bg-pos" : score >= 45 ? "bg-warn" : "bg-neg";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-edge rounded-full overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${Math.min(100, Math.max(0, score))}%` }} />
      </div>
      <span className="text-xs font-mono text-dim">{score.toFixed(0)}</span>
    </div>
  );
}
