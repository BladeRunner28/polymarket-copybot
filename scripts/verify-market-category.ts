/**
 * verify:market-category — proof harness for the observed-trade-category-field
 * card (approved 2026-09-23). Two claims, both empirical:
 *
 *   1. PARITY: the TypeScript classifier (src/lib/market-category.ts) labels the
 *      same rows exactly as the validated Python reference implementation
 *      (scripts/wallet-concentration-test.py::classify). Mismatches are printed
 *      and fail the run.
 *   2. WHAT THE FIELD MEANT: over the same stratified sample, how much of the
 *      stored `marketCategory` token is a question word rather than a market
 *      family, and what the market actually is.
 *
 * Usage:
 *   python3 scripts/verify-market-category.py        # reference labels
 *   npx tsx scripts/verify-market-category.ts        # diff + census
 */

import { classifyMarketCategory } from "../src/lib/market-category";
import * as fs from "fs";
import { join } from "path";

const ROOT = join(__dirname, "..");
const REF = join(ROOT, "data", "market-category-reference.json");
const OUT = join(ROOT, "data", "market-category-verification.json");

const QUESTION_WORDS = new Set([
  "will", "would", "what", "which", "who", "when", "where", "how", "why", "is", "are", "was",
  "were", "can", "could", "does", "do", "did", "at", "by", "on", "in", "of", "the", "to", "for",
  "highest", "lowest", "most", "least", "best", "worst", "next", "first", "last", "new", "any",
  "all", "this", "that", "if", "before", "after", "over", "under", "between", "during", "than",
  "more", "less", "top", "no", "not", "yes", "us", "up", "down", "who-will", "will-the",
]);

function isQuestionWord(token: string | null): boolean {
  if (!token) return false;
  const parts = token.toLowerCase().split(/[-_\s]+/).filter(Boolean);
  return parts.some((p) => QUESTION_WORDS.has(p));
}

type RefRow = {
  marketId: string;
  question: string;
  token: string | null;
  refCoarse: string;
  refFine: string;
};

function main() {
  if (!fs.existsSync(REF)) {
    throw new Error(`Missing ${REF} — run: python3 scripts/verify-market-category.py`);
  }
  const { rows, generatedAt, classifier } = JSON.parse(fs.readFileSync(REF, "utf-8")) as {
    rows: RefRow[];
    generatedAt: string;
    classifier: string;
  };

  const mismatches: Array<{ marketId: string; expected: string; got: string }> = [];
  const coarse = new Map<string, number>();
  const fine = new Map<string, number>();
  const tokenHit = new Map<string, number>();
  let questionWordRows = 0;
  let tokenAlwaysOther = 0;
  let tokenSpansManyClasses = 0;
  const tokenClasses = new Map<string, Set<string>>();

  for (const r of rows) {
    const got = classifyMarketCategory(r.marketId, r.question);
    if (got.coarse !== r.refCoarse || got.fine !== r.refFine) {
      mismatches.push({ marketId: r.marketId, expected: `${r.refCoarse}/${r.refFine}`, got: `${got.coarse}/${got.fine}` });
    }
    coarse.set(got.coarse, (coarse.get(got.coarse) ?? 0) + 1);
    fine.set(got.fine, (fine.get(got.fine) ?? 0) + 1);
    const tok = r.token ?? "(null)";
    tokenHit.set(tok, (tokenHit.get(tok) ?? 0) + 1);
    if (isQuestionWord(r.token)) questionWordRows++;
    if (!tokenClasses.has(tok)) tokenClasses.set(tok, new Set());
    tokenClasses.get(tok)!.add(got.coarse);
  }

  for (const tok of tokenHit.keys()) {
    const classes = tokenClasses.get(tok)!;
    if (classes.size === 1 && classes.has("other")) tokenAlwaysOther++;
    if (classes.size > 2) tokenSpansManyClasses++;
  }

  const total = rows.length;
  const pc = (n: number) => `${((100 * n) / total).toFixed(1)}%`;
  const topEntries = (m: Map<string, number>, n = 12) =>
    [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, n);

  console.log(`\nSample: ${total} stratified rows | reference classifier: ${classifier} (${generatedAt})`);
  console.log(`\nPARITY: ${mismatches.length === 0 ? "PASS — 0 mismatches" : `FAIL — ${mismatches.length} mismatch(es)`}`);
  for (const m of mismatches.slice(0, 10)) console.log(`   ${m.marketId.slice(0, 50)} expected ${m.expected} got ${m.got}`);

  console.log(`\nWHAT THE STORED TOKEN IS`);
  console.log(`  rows whose token is a question/function word: ${questionWordRows} (${pc(questionWordRows)})`);
  console.log(`  tokens that classify to 'other' only: ${tokenAlwaysOther} of ${tokenHit.size} distinct tokens`);
  console.log(`  tokens spanning >2 real categories (i.e. not a category at all): ${tokenSpansManyClasses}`);
  console.log(`  top tokens in sample: ${topEntries(tokenHit, 8).map(([t, n]) => `${t}=${n}`).join(", ")}`);

  console.log(`\nWHAT THE MARKET ACTUALLY IS (coarse category over the same rows)`);
  for (const [c, n] of topEntries(coarse, 12)) console.log(`  ${c.padEnd(10)} ${String(n).padStart(6)}  ${pc(n)}`);
  console.log(`\nfine grain, top 12:`);
  for (const [c, n] of topEntries(fine, 12)) console.log(`  ${c.padEnd(18)} ${String(n).padStart(6)}  ${pc(n)}`);

  fs.writeFileSync(
    OUT,
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        reference: { classifier, generatedAt, rows: total },
        parity: { passed: mismatches.length === 0, mismatchCount: mismatches.length, mismatches: mismatches.slice(0, 50) },
        tokenSemantics: {
          questionWordRows,
          questionWordShare: questionWordRows / total,
          tokensClassifyingToOtherOnly: tokenAlwaysOther,
          tokensSpanningMoreThanTwoCategories: tokenSpansManyClasses,
          distinctTokens: tokenHit.size,
        },
        classes: { coarse: Object.fromEntries(topEntries(coarse, 50)), fine: Object.fromEntries(topEntries(fine, 50)) },
      },
      null,
      2
    )
  );
  console.log(`\nReport → ${OUT}`);
  if (mismatches.length > 0) process.exitCode = 1;
}

main();
