/**
 * Proves the v63 STANDARD band skip is LIVE at runtime, without waiting for organic flow.
 *
 * Organic proof is unreliable here: STANDARD only produced ~2.5 dead-zone legs/day at the 30d
 * cut, so a single 11-minute scoring cycle legitimately contains none, and "no log line" would
 * be indistinguishable from "field is undefined and the guard never fires". This evaluates the
 * SAME three runtime pieces the loop uses — getActiveRules() -> rules.standardSkipBandRange ->
 * isInBandRange() — against the live RuleSet in the DB.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/verify-v63-band-skip.ts
 */
import { prisma } from "../src/lib/db";
import { getActiveRules } from "../src/lib/rules";
import { isInBandRange } from "../src/lib/band-size";
import { log } from "../src/lib/redact";

async function main() {
  const { rules, version } = await getActiveRules();
  const range = rules.standardSkipBandRange;

  log(`active RuleSet version : v${version}`);
  log(`standardSkipBandRange  : ${JSON.stringify(range)}`);
  log(`c200SkipBandRange      : ${JSON.stringify(rules.c200SkipBandRange)} (must be unchanged)`);
  log(`typeof field           : ${typeof range}${range === undefined ? "  <-- BUG: loader dropped it" : ""}`);
  log("");

  const cases: Array<[number, boolean, string]> = [
    [0.399, false, "just below the band"],
    [0.4, true, "lo edge (inclusive)"],
    [0.401, true, "inside"],
    [0.5, true, "mid-band"],
    [0.599, true, "inside, near hi"],
    [0.6, false, "hi edge (exclusive)"],
    [0.601, false, "just above the band"],
    [0.15, false, "cheap band — must NOT be skipped"],
    [0.9, false, "near-certainty — must NOT be skipped"],
  ];

  let fails = 0;
  for (const [price, want, why] of cases) {
    const got = isInBandRange(price, range);
    const ok = got === want;
    if (!ok) fails++;
    log(`${ok ? "PASS" : "FAIL"}  price ${price.toFixed(3)} -> skip=${got}  (want ${want})  ${why}`);
  }

  log("");
  if (fails > 0) {
    log(`RESULT: ${fails} FAILED — the STANDARD band skip is NOT enforcing correctly.`);
    process.exitCode = 1;
  } else {
    log("RESULT: ALL PASS — v63 STANDARD band skip is live and correctly scoped to [0.40, 0.60).");
  }
}

main()
  .catch((e) => {
    log("verify-v63 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
