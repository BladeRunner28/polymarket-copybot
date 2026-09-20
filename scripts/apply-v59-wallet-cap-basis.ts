/**
 * apply:v59 — per-wallet ceiling BASIS (2026-09-19 C-200 daily report rec 2,
 * user-approved in-thread).
 *
 *   walletCapBasis  "stock" → "delta"   (+ data/wallet-cap-baseline.json snapshot)
 *
 * WHY: v58 (tuning #30 rec 1) measured the ceiling against the wallet's WHOLE open
 * notional, so a wallet already above it is frozen OUTRIGHT rather than gated
 * gradually — the rail cannot bind progressively, only absolutely. Measured cost of
 * that basis in its first 15 h: 109 vetoed legs (1–4 per scoring cycle) while the
 * top wallet held $993.66 against a $431 ceiling (2.3x), and entries collapsed from
 * 43 (morning) to 7 after activation.
 *
 * THE APPROVED OPTION CHOICE — grandfather, not raise. The report offered
 * (a) grandfather the pre-activation stock, or (b) raise maxWalletNotionalPctOfCap
 * 0.25 → 0.40 ($433 → $694). Option (b) is VOID as a fix: at 0.40 the ceiling is
 * $693.80 and the wallet still holds $993.66 (1.43x), i.e. it stays frozen and only
 * unwinds ~$300 sooner. (a) is the only option that implements the rec's own intent,
 * so `delta` ships, with the per-wallet snapshot taken at activation.
 *
 * SEMANTICS: ceiling(wallet) = baseline(wallet) + maxWalletNotionalPctOfCap × cap.
 * A wallet keeps its pre-activation book and may add at most one ceiling of NEW
 * notional; a wallet first seen after activation has baseline 0 and gets the plain
 * ceiling. Concentration is still bounded — it is bounded relative to activation
 * instead of relative to zero, which is what "gate new accumulation only" means.
 *
 * FREEZE CLASSIFICATION (references/measurement-window-governance.md): a rule whose
 * effect is to LOOSEN a rail mid-Kelly-window is still a rule change — ships on the
 * user's explicit approval of the daily report's rec 2, and is recorded on the
 * Kelly pre-commit card for ruleSetVersion attribution.
 *
 * Run (apply):  cd ~/polymarket-copybot && DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v59-wallet-cap-basis.ts
 * Run (probe):  … --dry-run     # prints the per-wallet consequence, writes NOTHING
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { effectiveExposureCap } from "../src/lib/exposure-cap";
import { WALLET_CAP_BASELINE_FILE, type WalletCapBaselineFile } from "../src/lib/wallet-cap-basis";
import { log } from "../src/lib/redact";
import * as fs from "fs";

const DRY = process.argv.includes("--dry-run");

async function main() {
  const rs = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (!rs) throw new Error("no active RuleSet");
  const rules = JSON.parse(rs.rulesJson) as Record<string, number & string>;
  const before = String(rules.walletCapBasis ?? "stock");
  const pct = Number(rules.maxWalletNotionalPctOfCap ?? 0);
  if (!(pct > 0)) {
    log(`apply:v59 — maxWalletNotionalPctOfCap is ${pct}; the ceiling is disabled, nothing to re-base.`);
    return;
  }

  const br = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const openRows = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", status: "open", isDemo: false },
    select: { walletAddress: true, simulatedPositionSize: true, unrealizedPnl: true },
  });
  const principal = br?.principal ?? 0;
  const realized = br?.realizedPnl ?? 0;
  const basis = String((rules as unknown as Record<string, unknown>).ddBasis ?? "mtm");
  const realizedNW = principal + realized;
  const mtmNW = realizedNW + openRows.reduce((s, r) => s + (r.unrealizedPnl ?? 0), 0);
  const netWorth = basis === "realized" ? realizedNW : basis === "min" ? Math.min(mtmNW, realizedNW) : mtmNW;
  const cap = effectiveExposureCap(Number(rules.maxGrossExposureUsd), netWorth, principal);
  const ceiling = pct * cap;

  const perWallet = new Map<string, { n: number; usd: number }>();
  for (const r of openRows) {
    const e = perWallet.get(r.walletAddress) ?? { n: 0, usd: 0 };
    e.n += 1;
    e.usd += r.simulatedPositionSize ?? 0;
    perWallet.set(r.walletAddress, e);
  }
  const ranked = [...perWallet.entries()].sort((a, b) => b[1].usd - a[1].usd);
  const book = openRows.reduce((s, r) => s + (r.simulatedPositionSize ?? 0), 0);

  log(`apply:v59 before — RuleSet v${rs.version} walletCapBasis=${before} maxWalletNotionalPctOfCap=${pct}`);
  log(
    `  cap $${cap.toFixed(2)} (${basis} basis) -> plain ceiling $${ceiling.toFixed(2)} | ` +
      `book ${openRows.length} open / $${book.toFixed(2)} / ${perWallet.size} wallets`
  );
  for (const [w, e] of ranked.slice(0, 4)) {
    const grand = ceiling + e.usd;
    log(
      `  ${w.slice(0, 10)}… $${e.usd.toFixed(2)} (${((100 * e.usd) / book).toFixed(1)}% of book) — ` +
        `stock basis: ${e.usd > ceiling ? `FROZEN (${(e.usd / ceiling).toFixed(2)}x the ceiling)` : `ok, $${(ceiling - e.usd).toFixed(2)} room`} | ` +
        `delta basis: ceiling $${grand.toFixed(2)} -> $${(grand - e.usd).toFixed(2)} of new notional allowed`
    );
  }
  const frozen = ranked.filter(([, e]) => e.usd > ceiling);
  log(
    `  ${frozen.length} of ${ranked.length} wallets are above the plain ceiling ` +
      `($${frozen.reduce((s, [, e]) => s + e.usd, 0).toFixed(2)} of stock); under delta each may add one ceiling of NEW notional.`
  );

  if (DRY) {
    log("--dry-run: nothing written.");
    return;
  }

  const file: WalletCapBaselineFile = {
    declaredAt: new Date().toISOString(),
    appliedWithRuleSet: rs.version + 1,
    capUsd: Math.round(cap * 100) / 100,
    ceilingUsd: Math.round(ceiling * 100) / 100,
    basis: "delta",
    baseline: Object.fromEntries(ranked.map(([w, e]) => [w, Math.round(e.usd * 100) / 100])),
  };
  fs.writeFileSync(WALLET_CAP_BASELINE_FILE, JSON.stringify(file, null, 2));
  log(`  baseline snapshot written: ${WALLET_CAP_BASELINE_FILE} (${Object.keys(file.baseline).length} wallets, $${book.toFixed(2)} total)`);

  const result = await applyRuleChanges(
    [
      {
        field: "walletCapBasis" as const,
        newValue: "delta",
        reason:
          "v59 (user-approved 2026-09-20, C-200 daily report rec 2): grandfather the pre-activation per-wallet notional — a ceiling measured on the whole open book freezes a wallet already above it outright (the top wallet at 2.3x held the ceiling dead) instead of gating new accumulation",
        evidence:
          "v58 ceiling $431.25 vs wallet 0xb0c8c85813…fe7f $993.66 open = 2.3x, 109 vetoed legs in the first 15h (1-4 per cycle), entries 43 pre-activation vs 7 after. Basis is now ceiling = baseline(wallet) + 25% x cap, snapshot per wallet in data/wallet-cap-baseline.json; a wallet first seen after activation gets baseline 0 (plain ceiling). The alternative in the same rec (raise pct 0.25 -> 0.40 = $693.80) does NOT unbind the wallet ($993.66 > $693.80) and was rejected as void.",
      },
    ],
    "hermes-v59-perwallet-basis-approved"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated — walletCapBasis ${before} → delta. ` +
      `The top wallet's ceiling is now $${(ceiling + (perWallet.get(ranked[0][0])?.usd ?? 0)).toFixed(2)}; revert with walletCapBasis "stock".`
  );
}

main()
  .catch((e) => {
    log(`apply:v59 FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
