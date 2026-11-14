/**
 * apply:v73 — C-200 cheap-band clip cap, $25 on 0.0-0.2.
 *
 * STATUS: PROPOSED, NEVER RUN. Written by the Lane A proposal
 * (drafts/profit-band-clip-rebalance-20261112.md, card profit-band-clip-rebalance);
 * the apply belongs to the operator after he reads the write-up.
 *
 *   c200BandClipCaps   ""  → "0.0-0.2:25"   (NEW FIELD: cap C-200 clips at $25 in 0.0-0.2)
 *
 * THIS SCRIPT IS ONLY HALF THE CHANGE. The field is inert until the four code edits in
 * §5.2 of the write-up land (Rules interface, DEFAULT_RULES "" , the parser + the min-only
 * helper in band-size.ts, the call site in openPaperTrade after clampPaperSize, and the
 * pass-through in score-trades.ts). Until then `keyof Rules` will not even accept the field
 * name, which is deliberate: it makes "field stored but nothing reads it" impossible.
 *
 * WHAT IT DOES AND DOES NOT BUY (measured, drafts/profit-band-clip-rebalance-20261112.md §4):
 *   cost      all-time −$2,421.93 (CI −6,320.80…+877.42), regime +$476.08 (CI −661.04…+1,362.64)
 *             — i.e. NOT distinguishable from zero, and the all-time cost flips to +$550.45
 *             once the top five wallets are removed.
 *   purchase  closed-leg max drawdown −$890.49 → −$547.82 all-time and −$776.58 → −$225.35 in
 *             the regime (against a $1,900 lane principal: 41% → 12%).
 *   So: a DRAWDOWN RAIL, not an edge trade. The 11-11 draft's "+$790, CI excludes zero" does not
 *   reproduce on today's book; it was the same statistic on the 11-11 population.
 *
 * REVERT: `npx tsx scripts/apply-v73-c200-cheap-band-clip.ts --revert` (writes ""), or delete the
 * field. The default is "", so a ruleset lacking it is exactly pre-v73 behaviour, and no
 * PaperTrade row is retro-edited either way.
 *
 * SAFETY: refuses to write without --yes. A bare run prints the plan and exits 0.
 *
 * Run:
 *   npx tsx scripts/apply-v73-c200-cheap-band-clip.ts            # dry run, writes nothing
 *   npx tsx scripts/apply-v73-c200-cheap-band-clip.ts --yes      # apply v73
 *   npx tsx scripts/apply-v73-c200-cheap-band-clip.ts --revert   # set the field back to ""
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { prisma } from "../src/lib/db";
import { applyRuleChanges, DEFAULT_RULES, type RuleChangeProposal, type Rules } from "../src/lib/rules";
import { log } from "../src/lib/redact";
import {
  assertRuleFieldHasReader,
  assertRuleFieldImplemented,
  countRuleFieldReaders,
} from "../src/lib/rule-field-guard";

const VALUE = "0.0-0.2:25";

/**
 * INTERLOCK (moved from compile time to run time 2026-11-13): this field does not
 * exist in `Rules` yet, and applying it before the consumers land would store a
 * value nothing reads. That used to be enforced by the type checker, which also
 * turned `tsc --noEmit` red for the entire repo — see src/lib/rule-field-guard.ts.
 * The same refusal now happens in main() before any write.
 */
const FIELD = "c200BandClipCaps";

const PROPOSALS: RuleChangeProposal[] = [
  {
    field: FIELD as keyof Rules,
    newValue: VALUE,
    reason:
      "v73 (Lane A proposal 2026-11-12): cap C-200 clips at $25 in 0.0-0.2 — a drawdown rail, not an edge trade. Regime closed-leg max drawdown −$776.58 → −$225.35 (−71%), all-time −$890.49 → −$547.82, against a $1,900 lane principal (41% → 12%). PnL cost is not distinguishable from zero: all-time −$2,421.93 (CI −6,320.80…+877.42), regime +$476.08 (CI −661.04…+1,362.64), and the all-time cost flips to +$550.45 ex-top-5 wallets.",
    evidence:
      "drafts/profit-band-clip-rebalance-20261112.md; reproduce with scripts/profit-band-clip-preflight.py and scripts/profit-band-clip-stability.py (DB opened mode=ro). The cap binds on BANKROLL_200 alone: all 69 all-time cheap-band legs above $25 are C-200 (69 legs / $6,056 / +$3,176 / +52.4%, largest clip $100 = kellyMaxSizeUsd v72); STANDARD has zero above $25 because BOT_LIMITS.STANDARD.max = $20.00. Regime: 20 touched legs, $1,900, −$563.21, −29.6%, 18 of 20 losing. The card's +$790 regime figure reproduces only on the 11-11 population (+$815.25, CI +293.26…+1,376.91); two 11-11 legs, one a +$552.23 win on a $100 clip, moved the CI across zero — a 20-leg sample whose leave-one-out spread is $489.17.",
  },
];

const REVERT: RuleChangeProposal[] = [
  {
    field: FIELD as keyof Rules,
    newValue: "",
    reason:
      "v73 revert (Lane A write-up §5.5): c200BandClipCaps back to \"\" — no cap, byte-identical to pre-v73. No PaperTrade row is retro-edited.",
    evidence:
      "drafts/profit-band-clip-rebalance-20261112.md §6 pre-registers the two refutations that trigger this (cost > $1,000 with a CI excluding zero on 150 forward cheap-band legs; or the drawdown cut failing to appear at ≥20%).",
  },
];

/** Every .ts/.tsx file under a source root, as {path,text} for the reader count. */
function readSourceTree(root: string): Array<{ path: string; text: string }> {
  const out: Array<{ path: string; text: string }> = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      const st = statSync(p);
      if (st.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(name)) out.push({ path: p, text: readFileSync(p, "utf8") });
    }
  };
  walk(root);
  return out;
}

async function main() {
  const argv = process.argv.slice(2);
  const apply = argv.includes("--yes");
  const revert = argv.includes("--revert");
  const proposals = revert ? REVERT : PROPOSALS;

  // INTERLOCK — refuses in dry run too, because a plan for a no-op write is worse
  // than no plan. Throws UnimplementedRuleFieldError, caught by the catch() below.
  assertRuleFieldImplemented(FIELD);
  assertRuleFieldHasReader(FIELD, countRuleFieldReaders(FIELD, readSourceTree("src")));

  const before = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (before) {
    const j = JSON.parse(before.rulesJson) as Record<string, unknown>;
    log(
      `apply:v73 before — v${before.version} c200BandClipCaps=${JSON.stringify(j.c200BandClipCaps ?? "(unset→''")} ` +
        `(unchanged: kellyMaxSizeUsd ${j.kellyMaxSizeUsd}, c200LongshotBandFactor ${j.c200LongshotBandFactor}, ` +
        `c200SkipBandRange ${JSON.stringify(j.c200SkipBandRange)})`
    );
  }

  if (!apply) {
    log(`DRY RUN — nothing written. Would set: ${proposals.map((p) => `${p.field}=${JSON.stringify(p.newValue)}`).join(", ")}`);
    log("Re-run with --yes to apply, or --revert to write the field back to \"\".");
    return;
  }

  const result = await applyRuleChanges(proposals, revert ? "hermes-v73-revert" : "hermes-v73-c200-cheap-band-clip-approved-20261112");
  if (!result) {
    log("No changes applied.");
    return;
  }
  const after = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const j = after ? (JSON.parse(after.rulesJson) as Record<string, unknown>) : {};
  log(`RuleSet v${result.newVersion} activated. c200BandClipCaps=${JSON.stringify(j.c200BandClipCaps ?? "")}`);
  log(
    "NOW PROVE IT BINDS (write-up §5.4): boundary probe at price 0.1999/0.2000/0.2001 and clip " +
      "24.99/25.00/25.01, the DEFAULT-empty test, and one live cycle of PaperTrade rows showing " +
      "simulatedPositionSize <= 25 in the band with the neighbouring bands untouched."
  );
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
