/**
 * apply:v59 — kellyFraction decision (STAGED, NOT APPLIED).
 *
 * This script exists so the kellyFraction pick is a 60-second execution at the
 * Oct 8 Kelly-window close instead of a new build. It has NO DEFAULT ACTION:
 * run without --fraction=<x> and it prints the live state, the consequence
 * arithmetic and a usage line, then exits non-zero without writing.
 *
 * RECOMMENDATION (2026-09-19, drafts/kelly-window-stage-20260919.md): HOLD at
 * 0.5. The window's loss is BAND-specific (0.20–0.40), and the v57 change-B
 * rail already caps that band at the legacy-equivalent ($17.99) — tighter than
 * what fraction 0.25 would produce there ($18–29) — while a global fraction cut
 * would shrink the only positive band (<0.20: +$988 on $2,488 staked). A blunt
 * exposure knob is the wrong scope for a band-specific defect; use this script
 * only if the <0.20 band itself turns negative before the close.
 *
 * FREEZE CLASSIFICATION (references/measurement-window-governance.md): a
 * sizing change NEEDS an explicit user override — the Kelly window (Sep 8–Oct 8)
 * is still pre-registered as NO rule/sizing/live-lane changes. The window
 * pre-commit card pre-authorized ONLY the scheduled λ̂ refits (Sep 15 / Oct 1).
 *
 * Usage:
 *   npx tsx scripts/apply-v59-kelly-fraction.ts                 # print state + consequences, write NOTHING
 *   npx tsx scripts/apply-v59-kelly-fraction.ts --fraction=0.25 --confirm
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log } from "../src/lib/redact";
import { kellySizeForCopy } from "../src/lib/kelly";
import { readFileSync } from "fs";
import { join } from "path";

const arg = process.argv.find((a) => a.startsWith("--fraction="));
const confirm = process.argv.includes("--confirm");

async function main() {
  const rs = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (!rs) throw new Error("no active RuleSet");
  const rules = JSON.parse(rs.rulesJson) as Record<string, number>;
  const current = rules.kellyFraction;

  const br = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const openAgg = await prisma.paperTrade.aggregate({
    where: { botId: "BANKROLL_200", status: "open" },
    _sum: { simulatedPositionSize: true },
  });
  const avail = (br?.cashBalance ?? 0) - (openAgg._sum.simulatedPositionSize ?? 0);
  const cal = JSON.parse(readFileSync(join(__dirname, "..", "data", "premium-calibration.json"), "utf8"));
  const lam = (p: number): number => {
    for (const b of cal.bands) if (p >= b.lo && p < b.hi) return b.lambda;
    return 0;
  };

  log(`apply:v58 before — RuleSet v${rs.version} kellyFraction=${current} (bankroll available $${avail.toFixed(2)})`);

  const prices = [0.05, 0.1, 0.15, 0.25, 0.3, 0.35];
  const sizeAt = (fraction: number, p: number): string => {
    const r = kellySizeForCopy({
      price: p,
      outcome: "YES",
      lambda: lam(p),
      side: "BUY",
      availableBankroll: avail,
      fraction,
      maxBankrollPct: rules.kellyMaxBankrollPct,
      maxSizeUsd: rules.kellyMaxSizeUsd,
      minBetUsd: rules.kellyMinBetUsd,
      minEdgePct: rules.kellyMinEdgePct ?? 0.02,
    });
    return r.skip ? `skip` : `$${r.sizeUsd.toFixed(0)}`;
  };

  if (!arg) {
    log(`prices:            ${prices.map((p) => p.toFixed(2).padStart(6)).join(" ")}`);
    log(`size @ fraction ${current}:  ${prices.map((p) => sizeAt(current, p).padStart(6)).join(" ")}`);
    log(`band: prices 0.05-0.15 are <0.20 (the +$988 window band); 0.25-0.35 are the 0.20-0.40 band the v57-B rail already caps at $17.99.`);
    log(`band rails: [0.20,0.60) capped at legacy-equivalent, <0.20 floored at legacy-equivalent — a fraction cut moves both.`);
    log(`NO DEFAULT ACTION. Pass --fraction=<x> --confirm to write a new RuleSet (needs an explicit window override).`);
    process.exit(2);
  }

  const target = Number(arg.split("=")[1]);
  if (!Number.isFinite(target) || target <= 0 || target > 1) {
    log(`invalid --fraction=${arg.split("=")[1]} — expected (0,1], e.g. --fraction=0.25`);
    process.exit(2);
  }
  log(`size @ fraction ${target}:  ${prices.map((p) => sizeAt(target, p).padStart(6)).join(" ")}`);
  if (!confirm) {
    log(`dry run (no --confirm): nothing written. Re-run with --confirm to apply kellyFraction ${current} -> ${target}.`);
    process.exit(0);
  }
  const res = await applyRuleChanges(
    [
      {
        field: "kellyFraction" as const,
        newValue: target,
        reason: `v58 (user-approved at the Oct 8 Kelly-window close): kellyFraction ${current} -> ${target}`,
        evidence: `Staged 2026-09-19 (drafts/kelly-window-stage-20260919.md). Window main-lane: <0.20 +$988 on $2,488 staked vs 0.20-0.40 -$427 on $1,125; v57-B rail caps the mid band at $17.99 legacy-equivalent. Fraction is a GLOBAL multiplier - it scales both bands, so it is only correct if the <0.20 band has itself turned negative.`,
      },
    ],
    "hermes-v58-kellyfraction-approved"
  );
  log(res ? `RuleSet v${res.newVersion} activated (kellyFraction=${target}).` : "No changes applied.");
}

main()
  .catch((e) => {
    console.error("apply:v58 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
