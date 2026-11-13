/**
 * v74 — the CONCURRENT LONG-SHOT concentration rail (kelly rec 4).
 *
 * Approved via the approvals inbox 2026-11-13 (apr-kelly-single-loss-concentration-test,
 * kanban t_e0a4c4ad), on the measurement committed 2026-11-13 in
 * `scripts/kelly-single-loss-read.py` + `drafts/kelly-single-loss-concentration-20261113.md`.
 * The card pre-registered on 2026-10-21 authorises the TEST; the rule change is this file, and
 * the value it writes is the one the measured sweep selects.
 *
 * WHAT THIS CHANGES (one field)
 *   maxConcurrentLongshotPctOfNetWorth   0 (absent) -> 20
 *
 * Read by `scripts/score-trades.ts` at admission (immediately before the booking point, after the
 * v55 per-market and v58 per-wallet rails), through the pure helper
 * `longshotConcurrencyDecision()` in `src/lib/exposure-cap.ts`. A new leg whose entry price is
 * below `longshotMaxPrice` is refused when
 *   (open long-shot notional on THIS lane) + (this leg) > 20% x (this lane's REALISED net worth)
 * where realised NW = principal + realised PnL, the basis `ddBasis` already declares. Per lane, so
 * C-200 and STANDARD are bounded independently and neither can freeze the other.
 *
 * WHY 20 AND NOT 10/15 (measured, blocked legs / their realised PnL, whole non-demo book)
 *   C-200     10% 74 legs +$1,594.98 | 15% 58 +$1,451.81 | 20% 33 −$849.76 | 25% 30 −$643.32
 *   STANDARD  10% 338 +$1,667.42    | 15% 132 +$744.94  | 20% 23 +$182.20 | 25% blocks nothing
 * The 10% and 15% levels would have blocked net WINNERS on both lanes; 20% is the tightest level
 * that is value-positive where the peak occurred (C-200 saves $849.76) and it leaves STANDARD's
 * cost at $182.20. It also makes the two rails coherent: a total wipeout of the long-shot book can
 * then reach the 20% drawdown gate but cannot overshoot it.
 *
 * WHY NOT A TIGHTER PER-POSITION CAP (the other half of the card's either/or)
 *   The 60 C-200 legs at the $100 Kelly clip book +$3,141.77 lifetime, but the top 10 carry
 *   +$5,749.83 and the other 50 are −$2,608.06. The clip's apparent profitability is a top-10
 *   artefact, so tightening it is not supported and is not proposed.
 *
 * HEADROOM AT ACTIVATION (measured 2026-11-13, before this run)
 *   C-200      open long-shot $350.00 = 4.62% of NW $7,570.95  -> cap $1,514.19, headroom $1,164
 *   STANDARD   open long-shot $2,442.32 = 11.87% of NW $20,580.25 -> cap $4,116.05, headroom $1,674
 * Nothing is blocked at the moment of activation; the rail binds only if a lane's long-shot book
 * grows into it.
 *
 * REVERT
 *   npx tsx scripts/apply-longshot-concurrency.ts --apply --revert     (writes 0)
 *   Or: set maxConcurrentLongshotPctOfNetWorth = 0 on the active RuleSet. DEFAULT_RULES already
 *   carries 0, so every ruleset lacking the field reads byte-identically to pre-v74. Enforcement
 *   is one pre-admission arithmetic check: no booking, ledger or PnL path is touched.
 *
 * VERSION NUMBER: the RuleSet version is assigned by the DB (`activeVersion + 1`) and printed by
 * this script — the file is deliberately NOT named apply-vNN, because a sibling change (the
 * cheap-band clip) holds a pending apply script whose row has not landed, so any NN in this
 * filename would be a guess. "v74" below is the CHANGE's name, not a row number.
 */
import { prisma } from "../src/lib/db";
import { getActiveRules, applyRuleChanges } from "../src/lib/rules";

const TARGET = 20;
const REVERT_TO = 0;

const REASON =
  "v74: the sum of concurrent long-shot (<0.20) legs was unbounded — the v45/v55/v58 rails bound a " +
  "slug, a marketId and a wallet, never the cluster. With the $100 Kelly clip = 1.32% of C-200's " +
  "realised net worth, a correlated full-loss book is reachable: measured C-200 open long-shot " +
  "notional exceeded 10% of NW on 22 of 90 entry-days (peak 60.85% on 2026-09-14, $1,121 on NW " +
  "$1,842) and STANDARD on 103 of 116 (max 21.33%). Rail at 20% of realised NW per lane — the " +
  "tightest measured level that is value-positive where the peak occurred (C-200 33 blocked legs, " +
  "−$849.76) AND that makes a total long-shot wipeout reachable by, but not able to overshoot, the " +
  "20% drawdown gate.";

const EVIDENCE =
  "drafts/kelly-single-loss-concentration-20261113.md + scripts/kelly-single-loss-read.py " +
  "(--self-test 10/10, mutated arm proven RED) on the whole non-demo book 2026-07-14..2026-11-13. " +
  "Level sweep (blocked legs / their realised PnL): C-200 10% 74/+$1,594.98, 15% 58/+$1,451.81, " +
  "20% 33/−$849.76, 25% 30/−$643.32; STANDARD 10% 338/+$1,667.42, 15% 132/+$744.94, 20% 23/+$182.20, " +
  "25% 0. Per-position cap REFUTED as an instrument: the 60 C-200 legs at the $100 clip book " +
  "+$3,141.77 but −$2,608.06 ex-top-10. Cross-check: the same instrument reproduces " +
  "standard-longshot-concentration.py's open book (11.87% / 4.62%) and its 10/15/20% rows exactly.";

function log(s: string) {
  console.log(s);
}

/** What arming would do TODAY: per lane, open long-shot notional as a share of realised NW. */
async function laneSnapshot(longshotMaxPrice: number, pct: number) {
  const banks = await prisma.botBankroll.findMany({
    where: { botId: { in: ["BANKROLL_200", "STANDARD"] } },
    select: { botId: true, principal: true, realizedPnl: true },
  });
  const open = await prisma.paperTrade.findMany({
    where: { botId: { in: ["BANKROLL_200", "STANDARD"] }, status: "open" },
    select: { botId: true, entryPrice: true, simulatedPositionSize: true },
  });
  for (const b of banks) {
    const nw = (b.principal ?? 0) + (b.realizedPnl ?? 0);
    const ls = open
      .filter((r) => r.botId === b.botId && r.entryPrice < longshotMaxPrice)
      .reduce((s, r) => s + (r.simulatedPositionSize ?? 0), 0);
    const capUsd = nw > 0 && pct > 0 ? (pct / 100) * nw : 0;
    const share = nw > 0 ? (ls / nw) * 100 : 0;
    log(
      `  ${b.botId.padEnd(13)} open long-shot $${ls.toFixed(2)} = ${share.toFixed(2)}% of realised NW $${nw.toFixed(2)}` +
        (capUsd > 0
          ? ` | cap $${capUsd.toFixed(2)} -> headroom $${(capUsd - ls).toFixed(2)}`
          : " | no cap")
    );
  }
}

async function main() {
  const apply = process.argv.includes("--apply");
  const wantRevert = process.argv.includes("--revert");
  const target = wantRevert ? REVERT_TO : TARGET;

  const active = await getActiveRules();
  const current = active.rules.maxConcurrentLongshotPctOfNetWorth;

  log(`active rules v${active.version}: maxConcurrentLongshotPctOfNetWorth = ${current}`);
  log("open book now (this run); arming at " + target + " would compare against:");
  await laneSnapshot(active.rules.longshotMaxPrice, target === 0 ? TARGET : target);
  log(`the write below creates RuleSet v${active.version + 1} (the DB assigns the number).`);

  if (current === target) {
    log(`already ${target} — nothing to do.`);
    return;
  }

  log("");
  log("PLANNED CHANGE (one field):");
  log(`  maxConcurrentLongshotPctOfNetWorth  ${current} -> ${target}`);
  log("  effect: a new long-shot (<longshotMaxPrice) leg is refused when the lane's open");
  log("          long-shot notional + this leg would exceed the target % of that lane's");
  log("          REALISED net worth (principal + realised PnL). Per lane; not a portfolio gate.");
  log("  untouched: the $100 Kelly clip, every band/entry/exit rule, the v55/v58 rails, the");
  log("             drawdown gate, and every booking/PnL path.");
  log(`  revert: set maxConcurrentLongshotPctOfNetWorth = ${wantRevert ? TARGET : REVERT_TO} (default 0 = disabled)`);
  log("");

  if (!apply) {
    log(`DRY RUN — nothing written. Re-run with --apply to write the row (v${active.version + 1}).`);
    return;
  }

  const result = await applyRuleChanges(
    [
      {
        field: "maxConcurrentLongshotPctOfNetWorth",
        newValue: target,
        reason: wantRevert ? `${REASON} | REVERT to disabled (0).` : REASON,
        evidence: EVIDENCE,
      },
    ],
    wantRevert ? "hermes-v74-revert-longshot-concurrency" : "hermes-v74-longshot-concurrency"
  );
  if (!result) {
    log("no changes applied.");
    return;
  }
  // Verify through the same loader the scorer uses, not the row we just wrote.
  const after = await getActiveRules();
  log(
    `RuleSet v${result.newVersion} activated; effective maxConcurrentLongshotPctOfNetWorth = ${after.rules.maxConcurrentLongshotPctOfNetWorth}`
  );
  if (after.rules.maxConcurrentLongshotPctOfNetWorth !== target) {
    throw new Error(
      `post-apply read-back is ${after.rules.maxConcurrentLongshotPctOfNetWorth}, expected ${target}`
    );
  }
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
