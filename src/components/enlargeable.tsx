"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

/**
 * Click-to-enlarge wrapper for server-rendered SVG charts.
 * The chart (children) renders inline; clicking opens a fullscreen overlay
 * with the same chart at full width (SVG viewBox scales proportionally).
 * Close via ESC or clicking anywhere outside the chart.
 */
export function Enlargeable({ children, label }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, close]);

  return (
    <>
      <div
        className="cursor-zoom-in group"
        onClick={() => setOpen(true)}
        role="button"
        title={label ? `Enlarge: ${label}` : "Click to enlarge"}
      >
        {children}
        <div className="text-[10px] text-dim text-center mt-1 opacity-0 group-hover:opacity-60 transition-opacity">
          ⤢ click to enlarge
        </div>
      </div>
      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/90 backdrop-blur-sm flex flex-col p-4 md:p-10 overflow-auto cursor-zoom-out"
          onClick={close}
        >
          <div className="flex items-center justify-between mb-3 text-sm max-w-6xl w-full mx-auto text-dim">
            <span className="text-ink font-semibold">{label ?? "Enlarged chart"}</span>
            <span className="text-xs">ESC / click to close</span>
          </div>
          <div
            className="m-auto w-full max-w-6xl cursor-default"
            onClick={(e) => e.stopPropagation()}
          >
            {children}
          </div>
        </div>
      )}
    </>
  );
}
