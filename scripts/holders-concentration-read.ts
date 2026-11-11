/**
 * holders-concentration-read — the reproducible read over `data/market-hygiene.jsonl`
 * for card `polyterm-p5-holders-concentration`. READ-ONLY, advisory, no gate input.
 *
 * WHAT IT ANSWERS (the card's VERIFY gates (a) and (b), and nothing more):
 *   (a) is the `/holders` read USABLE on the markets this script scores — how many rows carry an
 *       assessed concentration, how many are truncated (upper bounds) and how many are nulls;
 *   (b) does concentration carry information INDEPENDENT of the hygiene score — Spearman between
 *       the concentration statistic and the risk / wash scores, reported rather than assumed, with
 *       the caveat that a shared market property (price, liquidity) can drive both.
 *
 * WHAT IT DOES NOT DO: gate (c), the PRE-REGISTERED read (rank correlation vs realized copy
 * outcomes, per ruleSetVersion era, >=150 settled rows/arm). That read needs a holder snapshot at
 * or before each leg's decision instant, and this JSONL is a spot market snapshot with no leg join
 * — it can only ever support a FORWARD read once a snapshot series exists. The verdict line says so
 * instead of inventing a number.
 *
 * BASIS: population = rows in one run (default: the latest day present); level = the market, and
 * per-outcome within it; clock = scoredAt (the snapshot instant, never "now").
 *
 * Usage: npx tsx scripts/holders-concentration-read.ts [--day YYYY-MM-DD]
 */
import { readFileSync } from "fs";
import { join } from "path";
import { spearman } from "../src/lib/hygiene-rank";

const SRC = join(__dirname, "..", "data", "market-hygiene.jsonl");

type Profile = {
  holderCount: number;
  top1Share: number;
  top5Share: number;
  top10Share: number;
  hhi: number;
  effectiveHolders: number;
  supplyShares: number;
  listedShares: number;
  supplyComplete: boolean;
  topHolder?: { wallet?: string; share: number };
  assessed: boolean;
};

type Row = {
  scoredAt: string;
  slug: string;
  wash: { score: number; band: string; assessed: boolean };
  risk: { score: number; grade: string };
  concentration: Profile;
  concentrationByOutcome?: (Profile & { outcomeIndex?: number })[];
  holdersBasis?: { endpoint?: string; pages?: number; outcomes?: number; supplyComplete?: boolean; error?: string };
  qualityFlags?: string[];
  conditionId?: string;
};

const pct = (n: number | undefined) => (n === undefined || !Number.isFinite(n) ? "n/a" : `${(100 * n).toFixed(1)}%`);
const f3 = (n: number | null) => (n === null || !Number.isFinite(n) ? "n/a" : n.toFixed(3));

function quantile(v: readonly number[], p: number): number {
  if (v.length === 0) return NaN;
  const s = [...v].sort((a, b) => a - b);
  const k = (s.length - 1) * p;
  const lo = Math.floor(k);
  const hi = Math.min(lo + 1, s.length - 1);
  return s[lo] + (s[hi] - s[lo]) * (k - lo);
}

function main() {
  const args = process.argv.slice(2);
  const dayArgIdx = args.indexOf("--day");
  const rows: Row[] = readFileSync(SRC, "utf8")
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .map((l) => JSON.parse(l) as Row);

  const days = [...new Set(rows.map((r) => r.scoredAt.slice(0, 10)))].sort();
  const day = dayArgIdx >= 0 ? args[dayArgIdx + 1] : days[days.length - 1];
  const dayRows = rows.filter((r) => r.scoredAt.slice(0, 10) === day);
  // The scorer APPENDS, so two runs on one day leave the same market in the file twice. Collapse to
  // the LAST row per slug (the newest snapshot) and say how many were dropped — otherwise every
  // count, median and correlation below is silently double-weighted.
  const bySlug = new Map<string, Row>();
  for (const r of dayRows) bySlug.set(r.slug, r);
  const run = [...bySlug.values()];
  const dupes = dayRows.length - run.length;

  console.log(`source      ${SRC}`);
  console.log(`rows total  ${rows.length} across ${days.length} day(s): ${days.join(", ")}`);
  console.log(`this read   ${run.length} rows scoredAt ${day} (level = market; clock = scoredAt)`);
  if (dupes > 0) console.log(`deduped     ${dupes} earlier row(s) of the same slug on this day (scorer appends; last wins)`);
  console.log(`endpoints   ${[...new Set(run.map((r) => r.holdersBasis?.endpoint ?? "none"))].join(", ")}`);
  console.log("");

  // ---- (a) usability -------------------------------------------------------------------------
  const assessed = run.filter((r) => r.concentration?.assessed);
  const truncated = run.filter((r) => (r.qualityFlags ?? []).includes("holder_supply_truncated"));
  const incomplete = assessed.filter((r) => r.concentration.supplyComplete === false);
  const unavailable = run.filter((r) => !r.concentration?.assessed);
  console.log("(a) USABILITY");
  console.log(`  assessed      ${assessed.length}/${run.length}   truncated walk ${truncated.length}   flagged incomplete-denominator ${incomplete.length}   unavailable ${unavailable.length}`);
  if (unavailable.length) {
    const reasons = new Map<string, number>();
    for (const r of unavailable) {
      const k = r.holdersBasis?.error ?? "unknown";
      reasons.set(k, (reasons.get(k) ?? 0) + 1);
    }
    for (const [k, n] of reasons) console.log(`    unavailable x${n}: ${k.slice(0, 120)}`);
  }
  const holders = assessed.map((r) => r.concentration.holderCount);
  const supply = assessed.map((r) => r.concentration.supplyShares);
  const listedGap = assessed
    .filter((r) => r.concentration.supplyShares > 0)
    .map((r) => 1 - r.concentration.listedShares / r.concentration.supplyShares);
  console.log(
    `  holders/market min ${Math.min(...holders)} p25 ${quantile(holders, 0.25)} median ${quantile(holders, 0.5)} max ${Math.max(...holders)}` +
      ` ; supply min ${Math.round(Math.min(...supply)).toLocaleString("en-US")} max ${Math.round(Math.max(...supply)).toLocaleString("en-US")}`
  );
  console.log(`  unlisted share of supply (should be ~0 on a complete walk): max ${pct(Math.max(...listedGap, 0))}`);
  console.log("");

  // ---- per-outcome asymmetry -----------------------------------------------------------------
  console.log("(b1) PER-OUTCOME ASYMMETRY (worst outcome vs the other side of the same market)");
  let asym = 0;
  const asymRows: string[] = [];
  for (const r of assessed) {
    const outs = r.concentrationByOutcome ?? [];
    if (outs.length < 2) continue;
    const sorted = [...outs].sort((x, y) => y.top5Share - x.top5Share);
    const gap = sorted[0].top5Share - sorted[sorted.length - 1].top5Share;
    asym += 1;
    if (asymRows.length < 5)
      asymRows.push(
        `    ${r.slug.slice(0, 46).padEnd(46)} top5 ${pct(sorted[0].top5Share)} (outcome ${sorted[0].outcomeIndex}, n=${sorted[0].holderCount}) vs ${pct(sorted[sorted.length - 1].top5Share)} (outcome ${sorted[sorted.length - 1].outcomeIndex}, n=${sorted[sorted.length - 1].holderCount})`
      );
  }
  for (const l of asymRows) console.log(l);
  const gaps = assessed
    .map((r) => {
      const outs = r.concentrationByOutcome ?? [];
      if (outs.length < 2) return null;
      const s = [...outs].sort((x, y) => y.top5Share - x.top5Share);
      return s[0].top5Share - s[s.length - 1].top5Share;
    })
    .filter((g): g is number => g !== null);
  console.log(`  markets with both outcomes: ${asym} ; median top5 gap between sides ${pct(quantile(gaps, 0.5))} (min ${pct(Math.min(...gaps))} max ${pct(Math.max(...gaps))})`);
  console.log("");

  // ---- (b) correlation with the hygiene scores ------------------------------------------------
  const top5 = assessed.map((r) => r.concentration.top5Share);
  const minSide = assessed.map((r) => Math.min(...(r.concentrationByOutcome ?? [r.concentration]).map((o) => o.top5Share)));
  const riskScore = assessed.map((r) => r.risk.score);
  const washRows = assessed.filter((r) => r.wash.assessed);
  const vol = assessed.map((r) => Number((r as unknown as { volume24hr?: number }).volume24hr ?? 0));
  console.log("(b2) INDEPENDENCE FROM THE HYGIENE SCORE (Spearman, this run only — descriptive, NOT the pre-registered verdict)");
  console.log(`  top5(worst side) vs risk score   ${f3(spearman(top5, riskScore))}   (n=${top5.length})`);
  // wash score only exists where an indicator fired: an unassessed 0 is a MISSING input, not a clean market.
  console.log(
    `  top5(worst side) vs wash score   ${f3(spearman(washRows.map((r) => r.concentration.top5Share), washRows.map((r) => r.wash.score)))}   (n=${washRows.length} wash-assessed rows of ${assessed.length})`
  );
  console.log(`  top5(worst side) vs volume24hr   ${f3(spearman(top5, vol))}   (n=${top5.length})`);
  console.log(`  top5(spread side) vs risk score  ${f3(spearman(minSide, riskScore))}   (n=${minSide.length})`);
  console.log("");

  // ---- structural holder ---------------------------------------------------------------------
  const wallets = new Map<string, { n: number; shares: number[] }>();
  for (const r of assessed) {
    const w = r.concentration.topHolder?.wallet;
    if (!w) continue;
    const rec = wallets.get(w) ?? { n: 0, shares: [] };
    rec.n += 1;
    rec.shares.push(r.concentration.topHolder?.share ?? 0);
    wallets.set(w, rec);
  }
  const ranked = [...wallets.entries()].sort((a, b) => b[1].n - a[1].n);
  console.log("(b3) WHO THE TOP HOLDER IS (a metric that reads one address is not measuring a crowd)");
  console.log(`  distinct #1 holders: ${wallets.size} across ${assessed.length} rows`);
  for (const [w, rec] of ranked.slice(0, 5)) {
    console.log(`    ${w}  #1 in ${rec.n} row(s)  median share ${pct(quantile(rec.shares, 0.5))}`);
  }
  const single = assessed.filter((r) => (r.concentration.topHolder?.share ?? 0) >= 0.5);
  console.log(`  rows whose #1 holder alone holds >=50% of that outcome's supply: ${single.length}/${assessed.length}`);
  console.log(
    "  CAVEAT: a repeated address across unrelated markets is structural inventory (a mint/sell-the-other-side " +
      "position), not conviction. Any read must name it and report concentration with it stripped."
  );
  console.log("");

  // ---- verdict -------------------------------------------------------------------------------
  console.log("PRE-REGISTERED READ (card gate (c)): NOT TAKEN and NOT TAKEN HERE.");
  console.log("  It requires Spearman(concentration, per-$1 realized return) with the sign checked inside each");
  console.log("  ruleSetVersion era on >=150 settled legs per arm, joining a holder snapshot at/before each leg's");
  console.log("  decision instant. This JSONL is one spot snapshot per market with no leg join, so the only");
  console.log("  honest verdict today is: instrument usable, series too short to read. Do not quote these rows as");
  console.log("  evidence for or against the metric.");
}

main();
