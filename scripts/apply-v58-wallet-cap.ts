/**
 * apply:v58 — per-wallet notional ceiling (2026-09-19 tuning review #30 rec 1,
 * user-approved in-thread).
 *
 *   maxWalletNotionalPctOfCap  0 → 0.25   (ceiling = 25% of the effective cap)
 *
 * WHY: one wallet (`0xb0c8…fe7f`) carried 50 open rows / $997.38 = **84.6%** of
 * the C-200 book (top-3 94.1%) on a book that nearly tripled post-thaw to
 * $1,179.45 — 57.5% of the entire $1,734.50 effective cap in a single wallet.
 * The v55 per-market rail is the only concentration rail that existed and it is
 * now MEASURED and non-binding (10 blocks, all 2026-09-18 08:36–08:52 at the
 * pre-growth $125.12 ceiling; 0 since the cap rose; max 2 legs/market), which is
 * exactly the precondition #29 set for adding the wallet half: the two rails no
 * longer confound each other.
 *
 * SCOPE: C-200 only (BANKROLL_200), the same book v55 scopes to — STANDARD runs
 * a different book/scale and has no such evidence. No existing threshold moves.
 *
 * FREEZE CLASSIFICATION (references/measurement-window-governance.md): a NEW
 * threshold is a rule change and the Kelly window (Sep 8–Oct 8) is pre-registered
 * as no-rule-change, so this needs — and has — an explicit user override
 * (approved 2026-09-19 in the #30 thread). Like v57-A, it is a mid-window change:
 * attribute the Oct 8 read by `ruleSetVersion`, never as one total.
 *
 * Run (apply):   DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v58-wallet-cap.ts
 * Run (probe):   … scripts/apply-v58-wallet-cap.ts --dry-run     # prints, writes nothing
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { effectiveExposureCap } from "../src/lib/exposure-cap";
import { log } from "../src/lib/redact";

const DRY = process.argv.includes("--dry-run");
const PCT = 0.25;

async function main() {
  const rs = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (!rs) throw new Error("no active RuleSet");
  const rules = JSON.parse(rs.rulesJson) as Record<string, number>;
  const before = rules.maxWalletNotionalPctOfCap ?? 0;

  // Effective cap exactly as the scorer computes it (equity-linked, v46/v50).
  const br = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const openRows = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", status: "open", isDemo: false },
    select: { walletAddress: true, simulatedPositionSize: true, realizedPnl: true, unrealizedPnl: true },
  });
  const principal = br?.principal ?? 0;
  const realized = br?.realizedPnl ?? 0;
  const unreal = openRows.reduce((s, r) => s + (r.unrealizedPnl ?? 0), 0);
  // The declared basis decides the net worth the cap is linked to (v56). Mirror
  // score-trades.ts:177-192 EXACTLY, or the ceiling printed here is not the one
  // the gate enforces (MTM net worth is ~$600 above the realized one on this book).
  const mtmNW = principal + realized + unreal;
  const realizedNW = principal + realized;
  const basis = String((rules as unknown as Record<string, unknown>).ddBasis ?? "mtm");
  const netWorth = basis === "realized" ? realizedNW : basis === "min" ? Math.min(mtmNW, realizedNW) : mtmNW;
  const cap = effectiveExposureCap(rules.maxGrossExposureUsd, netWorth, principal);

  const perWallet = new Map<string, { n: number; usd: number }>();
  for (const r of openRows) {
    const e = perWallet.get(r.walletAddress) ?? { n: 0, usd: 0 };
    e.n += 1;
    e.usd += r.simulatedPositionSize ?? 0;
    perWallet.set(r.walletAddress, e);
  }
  const ranked = [...perWallet.entries()].sort((a, b) => b[1].usd - a[1].usd);
  const book = openRows.reduce((s, r) => s + (r.simulatedPositionSize ?? 0), 0);
  const newCap = PCT * cap;

  log(`apply:v58 before — RuleSet v${rs.version} maxWalletNotionalPctOfCap=${before} (unset→0, disabled)`);
  log(
    `  book: ${openRows.length} open / $${book.toFixed(2)} across ${perWallet.size} wallets | ` +
      `cap $${cap.toFixed(2)} (base $${rules.maxGrossExposureUsd} + 50% × (NW $${netWorth.toFixed(2)} − principal $${principal.toFixed(2)}))`
  );
  log(`  the ceiling this activates: ${PCT} × $${cap.toFixed(2)} = $${newCap.toFixed(2)} per wallet`);
  for (const [w, e] of ranked.slice(0, 3)) {
    log(
      `  ${w.slice(0, 10)}… ${e.n} rows / $${e.usd.toFixed(2)} = ${((100 * e.usd) / book).toFixed(1)}% of book ` +
        `→ ${e.usd > newCap ? `OVER the new ceiling by $${(e.usd - newCap).toFixed(2)} (new legs blocked until it unwinds)` : `under (allows $${(newCap - e.usd).toFixed(2)} more)`}`
    );
  }

  if (DRY) {
    log("--dry-run: nothing written.");
    return;
  }

  const result = await applyRuleChanges(
    [
      {
        field: "maxWalletNotionalPctOfCap" as const,
        newValue: PCT,
        reason:
          "v58 (user-approved 2026-09-19, tuning review #30 rec 1): per-wallet notional ceiling at 25% of the effective cap, mirroring the v55 per-market rail — one wallet reached 84.6% of the C-200 book (top-3 94.1%) with no per-wallet rail in force",
        evidence:
          "C-200 open book 75 rows / $1,179.45: top wallet 0xb0c8…fe7f = 50 rows / $997.38 = 84.6% of open cost (57.4% → 45.0% → 61.2% → 84.6% on four consecutive windows), top-3 94.1%; v55 per-market rail measured non-binding in the same window (10 blocks, all pre-cap-growth at the $125.12 ceiling, 0 since; max 2 legs/market), so the wallet axis is un-confounded. Ceiling expressed as a fraction of the effective cap so it scales: 0.25 × $1,734.50 = $433.63.",
      },
    ],
    "hermes-v58-perwallet-cap-approved"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated — maxWalletNotionalPctOfCap ${before} → ${PCT} ` +
      `(ceiling $${newCap.toFixed(2)} per wallet on the current cap). RuleChange audit row written.`
  );
}

main()
  .catch((e) => {
    log(`apply:v58 FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
