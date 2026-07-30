import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "CopyBot — Polymarket Research (Paper Only)",
  description:
    "Hermes-operated Polymarket copy-trading research dashboard. Paper trading only — no real trades.",
};

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/wallets", label: "Wallet Rankings" },
  { href: "/signals", label: "Trade Signals" },
  { href: "/paper-trades", label: "Paper Trades" },
  { href: "/journal", label: "Decision Journal" },
  { href: "/performance", label: "Performance" },
  { href: "/rules", label: "Rules" },
  { href: "/reports", label: "Reports" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen">
          <header className="border-b border-edge bg-panel/80 backdrop-blur sticky top-0 z-10">
            <div className="mx-auto max-w-7xl px-4 py-3 flex items-center gap-6 flex-wrap">
              <div className="flex items-center gap-2">
                <span className="text-accent font-bold">◈ CopyBot</span>
                <span className="text-[10px] uppercase tracking-wider bg-warn/15 text-warn px-2 py-0.5 rounded-full border border-warn/30">
                  paper only
                </span>
              </div>
              <nav className="flex gap-1 text-sm flex-wrap">
                {NAV.map((n) => (
                  <Link
                    key={n.href}
                    href={n.href}
                    className="px-3 py-1.5 rounded-md text-dim hover:text-ink hover:bg-edge/60 transition-colors"
                  >
                    {n.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
          <footer className="mx-auto max-w-7xl px-4 py-6 text-xs text-dim border-t border-edge mt-8">
            Research tool. Paper trading only — this system never places real trades, never holds
            keys, and never spends money. Not financial advice.
          </footer>
        </div>
      </body>
    </html>
  );
}
