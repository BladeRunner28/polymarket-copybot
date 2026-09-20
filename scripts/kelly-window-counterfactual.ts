/**
 * kelly-window-counterfactual — READ-ONLY probe for the Kelly-window staging
 * decision (2026-09-19). Writes nothing, changes no rules.
 *
 * Q1: what would the v57 change-B rail (cap Kelly admits in [0.20,0.60) at the
 *     legacy-equivalent size) have done to the window's 0.20-0.40 band?
 *     PnL is LINEAR in position size for a fixed entry price and exit path
 *     (shares = S/p, pnl = shares*price - S), so the counterfactual re-scales
 *     each row's booked realizedPnl by railedSize/bookedSize. Paper trading has
 *     no size-dependent slippage, so this is a first-order-exact replay.
 *
 * Q2: is kellyFraction a usable lever for the mid-band loss? Sizes are
 *     min(fraction*f**bankroll, maxBankrollPct*bankroll, maxSizeUsd) — printed
 *     per band at the live bankroll through the REAL sizer (kellySizeForCopy),
 *     so the table is the actual sizing function, not a reimplementation.
 *
 * Usage: DATABASE_URL="file:./dev.db" npx tsx scripts/kelly-window-counterfactual.ts
 */

import { prisma } from "../src/lib/db";
import { readFileSync } from "fs";
import { join } from "path";
import { applyKellyBandRails, mapBankroll200Size } from "../src/lib/paper";
import { clampPaperSize } from "../src/lib/safety";
import { kellySizeForCopy, fairProbability } from "../src/lib/kelly";

const REGIME_V49 = 49;
const C200 = "BANKROLL_200";

function bandOf(p: number): string {
  if (p < 0.2) return "<0.20";
  if (p < 0.4) return "0.20-0.40";
  if (p < 0.6) return "0.40-0.60";
  if (p < 0.8) return "0.60-0.80";
  return ">=0.80";
}

async function main() {
  const rs = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const rules = JSON.parse(rs?.rulesJson ?? "{}") as any;
  const cal = JSON.parse(readFileSync(join(__dirname, "..", "data", "premium-calibration.json"), "utf8"));
  const bandLambda = (p: number): number => {
    for (const b of cal.bands) if (p >= b.lo && p < b.hi) return b.lambda;
    return 0;
  };

  const br = await prisma.botBankroll.findUnique({ where: { botId: C200 } });
  const openAgg = await prisma.paperTrade.aggregate({
    where: { botId: C200, status: "open" },
    _sum: { simulatedPositionSize: true },
  });
  const availBankroll = (br?.cashBalance ?? 0) - (openAgg._sum.simulatedPositionSize ?? 0);

  const djs = await prisma.decisionJournal.findMany({
    where: { ruleSetVersion: { gte: REGIME_V49 }, paperTrades: { some: { botId: C200 } } },
    include: { paperTrades: { where: { botId: C200 } } },
  });
  type Row = {
    ep: number; booked: number; status: string; pnl: number; conf: number;
    legacyEquiv: number; railed: number; opened: number;
  };
  const rows: Row[] = [];
  for (const dj of djs) {
    if ((dj.reasonsJson || "").includes("Short-TTR lane")) continue;
    for (const t of dj.paperTrades) {
      const legacyEquiv = clampPaperSize(
        mapBankroll200Size(dj.simulatedPositionSize ?? 0, t.entryPrice, {
          longshot: rules.c200LongshotBandFactor,
          deadZone: rules.c200DeadZoneBandFactor,
        })
      );
      rows.push({
        ep: t.entryPrice,
        booked: t.simulatedPositionSize,
        status: t.status,
        pnl: t.realizedPnl ?? 0,
        conf: dj.confidence,
        legacyEquiv,
        railed: applyKellyBandRails(t.simulatedPositionSize, legacyEquiv, t.entryPrice),
        opened: t.openedAt instanceof Date ? t.openedAt.getTime() : new Date(t.openedAt as any).getTime(),
      });
    }
  }

  console.log(`rules v${rs?.version} | kellyFraction=${rules.kellyFraction} maxBankrollPct=${rules.kellyMaxBankrollPct} maxSizeUsd=$${rules.kellyMaxSizeUsd} minBet=$${rules.kellyMinBetUsd} minEdge=${rules.kellyMinEdgePct}`);
  console.log(`availableBankroll = cash $${(br?.cashBalance ?? 0).toFixed(2)} - open $${(openAgg._sum.simulatedPositionSize ?? 0).toFixed(2)} = $${availBankroll.toFixed(2)}`);
  console.log(`band factors: longshot x${rules.c200LongshotBandFactor} deadZone x${rules.c200DeadZoneBandFactor}`);
  console.log(`lambda bands: ${cal.bands.map((b: any) => `[${b.lo},${b.hi}) ${b.lambda}`).join(" | ")}`);
  console.log("");

  // ---- Q1: v57-B rail replay, per band ----
  const bands = ["<0.20", "0.20-0.40", "0.40-0.60", "0.60-0.80", ">=0.80"];
  console.log("Q1 — v57 change-B rail replayed over the window (main-lane Kelly, journal v>=49)");
  console.log("band | rows | staked | staked_railed | realized | realized_railed | rows_changed | open_rows");
  for (const b of bands) {
    const g = rows.filter((r) => bandOf(r.ep) === b);
    if (!g.length) { console.log(`${b} | 0`); continue; }
    const staked = g.reduce((a, r) => a + r.booked, 0);
    const stakedR = g.reduce((a, r) => a + r.railed, 0);
    const settled = g.filter((r) => r.status === "closed" || r.status === "resolved");
    const realized = settled.reduce((a, r) => a + r.pnl, 0);
    const realizedR = settled.reduce((a, r) => a + (r.booked > 0 ? r.pnl * (r.railed / r.booked) : 0), 0);
    const changed = g.filter((r) => Math.abs(r.railed - r.booked) > 0.005).length;
    console.log(
      `${b} | ${g.length} | $${staked.toFixed(0)} | $${stakedR.toFixed(0)} | $${realized.toFixed(0)} | $${realizedR.toFixed(0)} | ${changed} | ${g.filter((r) => r.status === "open").length}`
    );
  }
  const mid = rows.filter((r) => bandOf(r.ep) === "0.20-0.40");
  console.log("");
  console.log("Q1 detail — 0.20-0.40 rows, booked -> railed (legacyEquiv) and rescaled realized:");
  console.log("entry | booked | legacy_equiv | railed | status | realized | realized_railed | conf | opened");
  for (const r of mid.sort((a, b) => a.booked - b.booked)) {
    console.log(
      `${r.ep.toFixed(3)} | $${r.booked.toFixed(2)} | $${r.legacyEquiv.toFixed(2)} | $${r.railed.toFixed(2)} | ${r.status} | $${r.pnl.toFixed(2)} | $${(r.booked > 0 ? r.pnl * (r.railed / r.booked) : 0).toFixed(2)} | ${r.conf.toFixed(2)} | ${new Date(r.opened).toISOString().slice(0, 16)}`
    );
  }
  const lastOpen = Math.max(...rows.map((r) => r.opened));
  console.log(`newest main-lane Kelly row opened: ${new Date(lastOpen).toISOString()} (rail live since 2026-09-19T11:38Z)`);

  // ---- Q2: fraction sensitivity through the real sizer ----
  console.log("");
  console.log("Q2 — Kelly size vs kellyFraction at the live bankroll (real kellySizeForCopy)");
  const prices = [0.03, 0.05, 0.10, 0.15, 0.19, 0.22, 0.25, 0.30, 0.35, 0.39];
  const fracs = [0.5, 0.35, 0.25];
  console.log(`price | lambda | f* | q | ${fracs.map((f) => `size@${f}`).join(" | ")}`);
  for (const p of prices) {
    const lam = bandLambda(p);
    const base = kellySizeForCopy({
      price: p, outcome: "YES", lambda: lam, side: "BUY",
      availableBankroll: availBankroll, fraction: fracs[0],
      maxBankrollPct: rules.kellyMaxBankrollPct, maxSizeUsd: rules.kellyMaxSizeUsd,
      minBetUsd: rules.kellyMinBetUsd, minEdgePct: rules.kellyMinEdgePct ?? 0.02,
    });
    const sizes = fracs.map((f) => {
      const r = kellySizeForCopy({
        price: p, outcome: "YES", lambda: lam, side: "BUY",
        availableBankroll: availBankroll, fraction: f,
        maxBankrollPct: rules.kellyMaxBankrollPct, maxSizeUsd: rules.kellyMaxSizeUsd,
        minBetUsd: rules.kellyMinBetUsd, minEdgePct: rules.kellyMinEdgePct ?? 0.02,
      });
      return r.skip ? `skip(${r.reason?.slice(0, 18)})` : `$${r.sizeUsd.toFixed(0)}`;
    });
    const q = fairProbability(p, lam);
    console.log(`${p} | ${lam.toFixed(3)} | ${base.fStarFull.toFixed(3)} | ${q.toFixed(3)} | ${sizes.join(" | ")}`);
  }
  console.log("");
  console.log("(legacy-equivalent size for these bands is clampPaperSize(mapBankroll200Size(decisionSize)) — printed per row in Q1 detail)");
}

main()
  .catch((e) => { console.error("counterfactual FAILED:", e); process.exit(1); })
  .finally(() => prisma.$disconnect());
