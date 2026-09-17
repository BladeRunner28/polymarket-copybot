/**
 * apply:v56 — drawdown/exposure BASIS change (NOT RUN — awaits an explicit pick).
 *
 * Why this exists: the MTM drawdown gate froze BOTH lanes on 2026-09-17 (cycle
 * #28) — 459 blocked decisions, 17.4 h with no opens — for the SECOND time
 * (Sep 7/8 was the first). The trigger is a peak set on unrealized marks three
 * days earlier ($3,409.47 on 09-12) that has since been given back, while the
 * REALIZED ledger sits at its best level on record (DD 1.1%).
 *
 * State at the time of writing (recompute before acting — these move):
 *   realized NW $2,414.32 (principal $1,900 + realized $514.32)   realized DD 1.1%
 *   MTM NW      $2,548.01 (unrealized $133.69)                    MTM DD    25.3%  → FROZEN
 *   cap: $1,324.00 on the mtm basis vs $1,257.16 on realized (open gross $471.45)
 *
 * The three options, and what each costs:
 *   --basis realized   gate clears immediately (1.1%), cap -$66.84 vs mtm, and the
 *                      ratchet can no longer be armed by marks that are later given
 *                      back. This is the only option that removes the deadlock
 *                      mechanism rather than resetting it.
 *   --basis min        same effect as realized here (min peak $2,441.69 / min NW
 *                      $2,414.32 = 1.1%); most conservative of the three.
 *   --reseed-peak      keeps the mtm basis and sets peak = current MTM NW. Clears
 *                      now, but the freeze returns on the next mark spike (the
 *                      Sep 8 precedent, and this is the second occurrence).
 *
 * Usage (requires an explicit flag; no default action):
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v56-drawdown-basis.ts --basis realized
 *   DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v56-drawdown-basis.ts --basis realized --reseed-peak
 */

import { prisma } from "../src/lib/db";
import { effectiveExposureCap } from "../src/lib/exposure-cap";
import { log, logError } from "../src/lib/redact";
import * as fs from "fs";
import { join } from "path";

const FILE = join(__dirname, "..", "data", "c200-drawdown.json");

type Basis = "mtm" | "realized" | "min";

async function snapshot() {
  const b = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const un = await prisma.paperTrade.aggregate({
    where: { botId: "BANKROLL_200", status: "open" },
    _sum: { unrealizedPnl: true, simulatedPositionSize: true },
  });
  const st = JSON.parse(fs.readFileSync(FILE, "utf8")) as {
    peak: number;
    realizedPeak: number;
    basis?: Basis;
    peakRule?: string;
    note?: string;
  };
  const principal = b?.principal ?? 0;
  const realizedNW = principal + (b?.realizedPnl ?? 0);
  const mtmNW = realizedNW + (un._sum.unrealizedPnl ?? 0);
  const dd = (peak: number, nw: number) => (peak > 0 ? Math.max(0, (peak - nw) / peak) : 0);
  return {
    st,
    principal,
    realizedNW,
    mtmNW,
    gross: un._sum.simulatedPositionSize ?? 0,
    cash: b?.cashBalance ?? 0,
    mtmDD: dd(st.peak, mtmNW),
    realDD: dd(st.realizedPeak, realizedNW),
    capMtm: effectiveExposureCap(1000, mtmNW, principal),
    capReal: effectiveExposureCap(1000, realizedNW, principal),
  };
}

async function main() {
  const args = process.argv.slice(2);
  const basisIdx = args.indexOf("--basis");
  const basis = basisIdx >= 0 ? (args[basisIdx + 1] as Basis) : undefined;
  const reseed = args.includes("--reseed-peak");
  const noteIdx = args.indexOf("--note");
  const note = noteIdx >= 0 ? args[noteIdx + 1] : undefined;

  if (basis && !["mtm", "realized", "min"].includes(basis)) {
    throw new Error(`--basis must be mtm|realized|min (got '${basis}')`);
  }
  if (!basis && !reseed) {
    throw new Error(
      "nothing to do — pass --basis <mtm|realized|min> and/or --reseed-peak (this script has no default action on purpose)"
    );
  }

  const s = await snapshot();
  log(
    `apply:v56 BEFORE — basis=${s.st.basis ?? "(unset→mtm)"} peak(mtm)=$${s.st.peak.toFixed(2)} peak(realized)=$${s.st.realizedPeak.toFixed(2)}`
  );
  log(
    `  NW mtm $${s.mtmNW.toFixed(2)} (DD ${(s.mtmDD * 100).toFixed(1)}%) | NW realized $${s.realizedNW.toFixed(2)} (DD ${(s.realDD * 100).toFixed(1)}%) | ` +
      `cap mtm $${s.capMtm.toFixed(2)} vs realized $${s.capReal.toFixed(2)} | gross $${s.gross.toFixed(2)} cash $${s.cash.toFixed(2)}`
  );

  const next: Record<string, unknown> = { ...s.st };
  if (basis) next.basis = basis;
  if (reseed) {
    next.peak = s.mtmNW;
    next.realizedPeak = Math.max(s.realizedNW, s.st.realizedPeak);
    next.note =
      note ??
      `peak reseeded 2026-09-17 to MTM NW $${s.mtmNW.toFixed(2)} (MTM DD was ${(s.mtmDD * 100).toFixed(1)}% on a 09-12 mark peak; realized DD ${(s.realDD * 100).toFixed(1)}%)`;
  }
  if (note && !reseed) next.note = note;
  next.basisDeclaredAt = new Date().toISOString();
  next.peakRule =
    next.peakRule ??
    "peak ratchets on the declared basis only; a reset is a deliberate act — record note + basisDeclaredAt with it";

  fs.writeFileSync(FILE, JSON.stringify(next, null, 2) + "\n");
  log(`apply:v56 AFTER — ${JSON.stringify({ basis: next.basis, peak: next.peak, realizedPeak: next.realizedPeak, note: next.note ?? null })}`);
  log("Takes effect on the next score:trades run (the gate reads this file each cycle).");
}

main()
  .catch((e) => {
    logError("apply:v56 FAILED:", e instanceof Error ? e.message : e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
