"use client";

/**
 * Live/interactive dashboard primitives:
 *  - SystemStatus: header chips w/ sidecar + cron-pipeline health (polls /api/system/status)
 *  - AutoRefresh: silently calls router.refresh() on an interval (server pages stay server-rendered)
 *  - CmdPalette: ⌘K / Ctrl-K palette — jump to pages or search wallets
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

// ─────────────────────────────────────────────────────────────────────────────
// SystemStatus
// ─────────────────────────────────────────────────────────────────────────────

interface SystemStatusState {
  ts: number;
  sidecarUp: boolean;
  sidecarSecs?: number;
  cronTotal: number;
  cronHealthy: number;
  cronAttention: number;
}

function fmtUptime(secs?: number): string {
  if (!secs && secs !== 0) return "";
  const m = Math.floor(secs / 60);
  const h = Math.floor(m / 60);
  if (h >= 48) return `${Math.floor(h / 24)}d up`;
  if (h >= 1) return `${h}h ${m % 60}m up`;
  if (m >= 1) return `${m}m up`;
  return `${secs}s up`;
}

export function SystemStatus() {
  const [state, setState] = useState<SystemStatusState | null>(null);
  const [dead, setDead] = useState(false);

  const poll = useCallback(async () => {
    try {
      const r = await fetch("/api/system/status", { cache: "no-store" });
      if (!r.ok) throw new Error(`http ${r.status}`);
      setState(await r.json());
      setDead(false);
    } catch {
      setDead(true);
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 15000);
    return () => clearInterval(id);
  }, [poll]);

  const sidecarTone = dead ? "neg" : state == null ? "dim" : state.sidecarUp ? "pos" : "neg";
  const cronTone =
    dead || state == null ? "dim" : state.cronAttention > 0 ? "warn" : "pos";

  return (
    <div className="flex items-center gap-2 text-xs">
      {/* Sidecar */}
      <span
        className={`hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-mono ${
          sidecarTone === "pos"
            ? "border-pos/30 bg-pos/10 text-pos"
            : sidecarTone === "neg"
              ? "border-neg/30 bg-neg/10 text-neg"
              : "border-edge bg-edge/20 text-dim"
        }`}
        title={
          state?.sidecarUp
            ? `Polyhydra whale-signal sidecar listening on :3014 — ${fmtUptime(state.sidecarSecs)}`
            : "Sidecar (polyhydra-whale-signal, :3014) not reachable — check launchd/cron watchdog"
        }
      >
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            sidecarTone === "pos"
              ? "bg-pos live-dot-pos"
              : sidecarTone === "neg"
                ? "bg-neg live-dot-neg"
                : "bg-dim"
          }`}
        />
        sidecar
        {state ? (sidecarTone === "pos" ? ` · ${fmtUptime(state.sidecarSecs)}` : " · down") : " · …"}
      </span>

      {/* Cron pipeline */}
      <span
        className={`hidden md:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-mono ${
          cronTone === "pos"
            ? "border-pos/30 bg-pos/10 text-pos"
            : cronTone === "warn"
              ? "border-warn/30 bg-warn/10 text-warn"
              : "border-edge bg-edge/20 text-dim"
        }`}
        title={
          state
            ? `${state.cronHealthy}/${state.cronTotal} jobs healthy on last run${
                state.cronAttention ? ` · ${state.cronAttention} need attention` : ""
              } — see Cron Health page`
            : "Cron pipeline state unknown — see Cron Health page"
        }
      >
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            cronTone === "pos"
              ? "bg-pos live-dot-pos"
              : cronTone === "warn"
                ? "bg-warn live-dot-warn"
                : "bg-dim"
          }`}
        />
        cron
        {state ? ` ${state.cronHealthy}/${state.cronTotal}` : " …"}
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// AutoRefresh — keep a server-rendered page fresh without converting it to a client page
// ─────────────────────────────────────────────────────────────────────────────

export function AutoRefresh({ seconds = 60 }: { seconds?: number }) {
  const router = useRouter();
  useEffect(() => {
    const id = setInterval(() => router.refresh(), seconds * 1000);
    return () => clearInterval(id);
  }, [router, seconds]);
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// CmdPalette
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// PaletteButton — safe to render from a server component (dispatch-only)
// ─────────────────────────────────────────────────────────────────────────────

export function PaletteButton({
  className,
  title,
  children,
}: {
  className?: string;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={className}
      title={title}
      onClick={() => window.dispatchEvent(new Event("copybot:toggle-palette"))}
    >
      {children}
    </button>
  );
}

export interface PalettePage {
  href: string;
  label: string;
  group: string;
}

export interface PaletteWallet {
  address: string;
  label?: string | null;
}

interface Item {
  kind: "page" | "wallet";
  href: string;
  label: string;
  hint?: string;
}

export function CmdPalette({ pages, wallets }: { pages: PalettePage[]; wallets: PaletteWallet[] }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    };
    const onToggle = () => setOpen((v) => !v);
    window.addEventListener("keydown", onKey);
    window.addEventListener("copybot:toggle-palette", onToggle);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("copybot:toggle-palette", onToggle);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const q = query.trim().toLowerCase();
    const pageItems: Item[] = pages
      .filter((p) => !q || p.label.toLowerCase().includes(q) || p.href.toLowerCase().includes(q))
      .map((p) => ({ kind: "page" as const, href: p.href, label: p.label, hint: p.group }));
    const walletItems: Item[] = wallets
      .filter((w) => {
        if (!q) return false;
        const addr = w.address.toLowerCase();
        const lbl = (w.label ?? "").toLowerCase();
        return addr.includes(q) || lbl.includes(q);
      })
      .slice(0, 8)
      .map((w) => ({
        kind: "wallet" as const,
        href: `/wallets/${w.address}`,
        label: w.label || `${w.address.slice(0, 6)}…${w.address.slice(-4)}`,
        hint: w.address,
      }));
    const all = [...pageItems, ...walletItems];
    return all.slice(0, 30);
  }, [pages, wallets, query]);

  useEffect(() => setCursor(0), [query]);

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-start justify-center pt-[16vh] px-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
    >
      <div className="w-full max-w-lg bg-panel border border-edge rounded-xl shadow-2xl shadow-black/50 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-edge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-dim shrink-0">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => Math.min(c + 1, items.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              } else if (e.key === "Enter" && items[cursor]) {
                go(items[cursor].href);
              }
            }}
            placeholder="Jump to page or search wallets…"
            className="flex-1 bg-transparent text-sm text-ink placeholder:text-dim/70 outline-none"
          />
          <kbd className="text-[10px] text-dim border border-edge rounded px-1.5 py-0.5">esc</kbd>
        </div>
        <div className="max-h-[50vh] overflow-y-auto py-1">
          {items.length === 0 ? (
            <div className="px-4 py-6 text-sm text-dim text-center">No matches for “{query}”</div>
          ) : (
            items.map((it, i) => (
              <button
                key={`${it.kind}-${it.href}`}
                onMouseEnter={() => setCursor(i)}
                onClick={() => go(it.href)}
                className={`w-full flex items-center justify-between gap-3 px-4 py-2 text-left text-sm ${
                  i === cursor ? "bg-accent/10 border-l-2 border-accent" : "border-l-2 border-transparent"
                }`}
              >
                <span className="flex items-center gap-2 min-w-0">
                  <span className="text-dim shrink-0">{it.kind === "page" ? "→" : "◈"}</span>
                  <span className="truncate text-ink">{it.label}</span>
                </span>
                <span className="text-[10px] text-dim font-mono truncate shrink-0 max-w-[40%]">{it.hint}</span>
              </button>
            ))
          )}
        </div>
        <div className="px-4 py-2 border-t border-edge text-[10px] text-dim flex items-center justify-between">
          <span>↑↓ navigate · enter open</span>
          <span>{items.length} results</span>
        </div>
      </div>
    </div>
  );
}
