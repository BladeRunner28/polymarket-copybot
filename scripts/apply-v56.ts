/**
 * apply:v56 — drawdown/exposure BASIS as a first-class RuleSet field
 * (2026-09-19 tuning review #29 rec 3, user-approved).
 *
 *   ddBasis: "" → "realized"
 *
 * Why: the basis was switched to `realized` on 2026-09-18 via
 * scripts/apply-v56-drawdown-basis.ts, which writes ONLY the state file
 * (data/c200-drawdown.json). That made "v56" a narrative version, not a versioned
 * rule: nothing in the RuleSet recorded which basis was in force, so a future
 * reader (or an audit of the Oct 8 window) could not tell from the DB why the
 * drawdown gate stopped firing.
 *
 * Precedence after this change: RuleSet.ddBasis → state file → "mtm" (legacy).
 * score-trades also writes the resolved basis back into the state file, so the
 * two can never disagree.
 *
 * The value is not a threshold change: it makes the 09-18 decision auditable,
 * versioned, and revertible in the same place as every other rule.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v56.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";
import * as fs from "fs";
import { join } from "path";

const PROPOSALS = [
  {
    field: "ddBasis" as const,
    newValue: "realized",
    reason:
      "v56 (#29 rec 3, user-approved 2026-09-19): record the drawdown/exposure basis in the RuleSet so the 2026-09-18 mtm→realized decision is a versioned fact, not only a state-file line",
    evidence:
      "The MTM gate froze BOTH lanes twice in 10 days (Sep 7/8; Sep 16-18 for 39.7h, 1,424 vetoes) while realized DD never breached 3%. With the basis in the RuleSet, the Oct 8 window audit can read it from the DB. Precedence: RuleSet → data/c200-drawdown.json → 'mtm'. Revert: set ddBasis 'mtm'.",
  },
];

async function main() {
  const before = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (before) {
    const j = JSON.parse(before.rulesJson) as Record<string, unknown>;
    log(`apply:v56 before — v${before.version} ddBasis=${JSON.stringify(j.ddBasis ?? "(unset)")}`);
  }
  const result = await applyRuleChanges(PROPOSALS, "hermes-v56-tr29-rec3-approved");
  if (!result) {
    log("No changes applied.");
    return;
  }
  // Keep the state file consistent with the ruleset (it is the fallback, not the source).
  const FILE = join(__dirname, "..", "data", "c200-drawdown.json");
  try {
    const st = JSON.parse(fs.readFileSync(FILE, "utf8")) as Record<string, unknown>;
    st.basis = "realized";
    st.basisDeclaredAt = st.basisDeclaredAt ?? new Date().toISOString();
    fs.writeFileSync(FILE, JSON.stringify(st, null, 2) + "\n");
  } catch (e) {
    logError(`apply:v56: state file sync failed (ruleset is still authoritative): ${e}`);
  }
  log(`RuleSet v${result.newVersion} activated (ddBasis=realized). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v56 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
