import type { Metadata } from "next";
import { TopNav } from "@/components/topnav";
import { SystemStatus, CmdPalette, PaletteButton } from "@/components/live";
import { prisma } from "@/lib/db";
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
  { href: "/analytics", label: "Analytics" },
  { href: "/rules", label: "Rules" },
  { href: "/roadmap", label: "Roadmap" },
  { href: "/reports", label: "Reports" },
  { href: "/drafts", label: "Docs" },
  { href: "/cron-health", label: "Cron Health" },
  { href: "/atlas.html", label: "Atlas", external: true },
];

const PALETTE_PAGES = NAV.map((n) => ({
  href: n.href,
  label: n.label,
  group: n.external ? "external" : "page",
}));

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  let wallets: { address: string; label: string | null }[] = [];
  try {
    wallets = await prisma.walletProfile.findMany({
      orderBy: [{ globalScore: "desc" }],
      take: 25,
      select: { address: true, label: true },
    });
  } catch {
    /* db not ready — palette still works for page navigation */
  }

  return (
    <html lang="en">
      <body>
        <CmdPalette pages={PALETTE_PAGES} wallets={wallets} />
        <div className="min-h-screen flex flex-col">
          <header className="border-b border-edge bg-panel/80 backdrop-blur sticky top-0 z-10">
            <div className="mx-auto max-w-7xl px-4 py-2.5 flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-3 min-w-0">
                <PaletteButton
                  className="flex items-center gap-2 text-accent font-bold hover:opacity-80 transition-opacity shrink-0"
                  title="⌘K to open quick nav"
                >
                  <span className="text-accent">◈</span> CopyBot
                </PaletteButton>
                <span className="text-[10px] uppercase tracking-wider bg-warn/15 text-warn px-2 py-0.5 rounded-full border border-warn/30 shrink-0">
                  paper only
                </span>
              </div>
              <TopNav items={NAV} />
              <div className="flex items-center gap-3 shrink-0">
                <SystemStatus />
                <PaletteButton
                  className="hidden lg:flex items-center gap-1.5 text-[11px] text-dim border border-edge rounded-md px-2 py-1 hover:text-ink hover:border-dim/40 transition-colors font-mono"
                  title="Jump to page or search wallets"
                >
                  <kbd>⌘K</kbd>
                </PaletteButton>
              </div>
            </div>
          </header>
          <main className="mx-auto max-w-7xl px-4 py-6 w-full flex-1">{children}</main>
          <footer className="mx-auto max-w-7xl px-4 py-6 text-xs text-dim border-t border-edge mt-8 w-full">
            Research tool. Paper trading only — this system never places real trades, never holds keys,
            and never spends money. Not financial advice.
          </footer>
        </div>
      </body>
    </html>
  );
}
