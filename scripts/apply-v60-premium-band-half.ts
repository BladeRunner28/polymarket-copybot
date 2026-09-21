/**
 * apply:v60 — band-scoped size factor on the 0.60–0.80 C-200 band
 * (2026-09-20 C-200 daily report change 1, user-approved in-thread).
 *
 *   c200BandSizeFactor       1 → 0.5
 *   c200BandSizeFactorRange  "" → "0.6-0.8"
 *
 * APPROVED INTENT: halve new size in the 0.60–0.80 band (excess −0.0995, z=−3.96 on
 * N=382; +$2.66 over 30d on $1,015 of flow) while it takes a third of the day's opens.
 *
 * THE NAMED MECHANISM WAS A NO-OP, SO THE DELTA IS THE REAL ONE. The rec proposed
 * flipping `premiumOverlayEnabled 0 → 1` (k=0.5) "scoped to 0.60–0.80". That overlay
 * resizes only `!kellySized && lane !== "short_ttr"` copies, and every 0.60–0.80 copy
 * in the book is a short-TTR lane copy — measured 7d: 87 opens, 84 of them at exactly
 * $4.99 (= fixed lane size × the 0.5 band map), zero Kelly admits (Kelly refuses λ̂>0
 * bands). Flipping the flag would have changed nothing in the target band, and would
 * have BOOSTED the <0.20 band by 1.39× (λ̂=−0.789) — the tail-variance increase the
 * same report argues against. Also: with k=0.5 the overlay factor for 0.60–0.80 is
 * `1 − 0.5×0.2142 = 0.893`, i.e. −10.7%, not the headline's −50%; the literal flag
 * would have been a 1/5-sized cut in the wrong place.
 *
 * Magnitude shipped = the headline's (−50%, factor 0.5), reached by the one knob that
 * can express it.

 * Run (apply):  cd ~/polymarket-copybot && DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v60-premium-band-half.ts
 * Run (probe):  … --dry-run     # prints the live consequence, writes NOTHING
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log } from "../src/lib/redact";

const DRY = process.argv.includes("--dry-run");
const RANGE = "0.6-0.8";
const FACTOR = 0.5;
const [LO, HI] = [0.6, 0.8];

async function main() {
  const rs = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (!rs) throw new Error("no active RuleSet");
  const rules = JSON.parse(rs.rulesJson) as Record<string, number | string>;
  const beforeFactor = Number(rules.c200BandSizeFactor ?? 1);
  const beforeRange = String(rules.c200BandSizeFactorRange ?? "");

  const since7d = new Date(Date.now() - 7 * 86400000);
  const rows = await prisma.paperTrade.findMany({
    where: {
      botId: "BANKROLL_200",
      isDemo: false,
      openedAt: { gte: since7d },
      entryPrice: { gte: LO, lt: HI },
    },
    select: { simulatedPositionSize: true, entryPrice: true, realizedPnl: true },
  });
  const n = rows.length;
  const notional = rows.reduce((s, r) => s + r.simulatedPositionSize, 0);
  const realized = rows.reduce((s, r) => s + (r.realizedPnl ?? 0), 0);
  const avg = n ? notional / n : 0;
  const sizes = new Map<number, number>();
  for (const r of rows) {
    const k = Math.round(r.simulatedPositionSize * 100) / 100;
    sizes.set(k, (sizes.get(k) ?? 0) + 1);
  }

  log(`apply:v60 before — RuleSet v${rs.version} c200BandSizeFactor=${beforeFactor} range="${beforeRange}"`);
  log(
    `  target band [${LO}, ${HI}) last 7d: ${n} opens / $${notional.toFixed(2)} notional ` +
      `(avg $${avg.toFixed(2)}, realized ${realized >= 0 ? "+" : "-"}$${Math.abs(realized).toFixed(2)})`
  );
  log(`  size histogram: ${[...sizes.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([s, c]) => `$${s}×${c}`).join(" ")}`);
  log(
    `  consequence at factor ${FACTOR}: avg $${avg.toFixed(2)} → $${(avg * FACTOR).toFixed(2)}, ` +
      `7d notional $${notional.toFixed(2)} → $${(notional * FACTOR).toFixed(2)} (Δ −$${(notional * (1 - FACTOR)).toFixed(2)})`
  );
  log(
    `  blast radius: only C-200 copies with entry in [${LO}, ${HI}); other bands, the STANDARD book, ` +
      `gates (v45/v47/v55/v58) and Kelly sizing are untouched. Kelly admits the band only at λ̂<0.`
  );

  if (DRY) {
    log("--dry-run: nothing written.");
    return;
  }

  const result = await applyRuleChanges(
    [
      {
        field: "c200BandSizeFactor" as const,
        newValue: FACTOR,
        reason:
          "v60 (user-approved 2026-09-20, C-200 daily report change 1): halve new size in the 0.60-0.80 band — significant negative excess (-0.0995, z=-3.96, N=382) with ~zero cash (+$2.66/30d on $1,015 of flow) while taking a third of the day's new positions",
        evidence:
          `Band is the worst significant band and pays nothing. Measured 7d flow: ${n} opens / $${notional.toFixed(2)} notional, avg $${avg.toFixed(2)} (84 of 87 at exactly $4.99 = fixed lane size x 0.5 band map), realized ${realized.toFixed(2)}. The rec named the v38 premium-overlay flag; it resizes only !kellySized && lane!=='short_ttr' copies, so it is a provable no-op here (every copy in the band is a lane copy, zero Kelly admits because Kelly refuses λ̂>0 bands) and its k=0.5 factor would have been -10.7%, not -50%. Implemented as a band-scoped factor on the final size instead. Revert: c200BandSizeFactor 1 (or the range "").`,
      },
      {
        field: "c200BandSizeFactorRange" as const,
        newValue: RANGE,
        reason: "v60 (same approval): scope the size factor to the 0.60-0.80 band only",
        evidence:
          "Range form \"lo-hi\", lo inclusive / hi exclusive, parsed by parseBandRange (unit-tested). Every other band is provably unaffected (tests/band-size.test.ts).",
      },
    ],
    "hermes-v60-premium-band-half-approved"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated — c200BandSizeFactor ${beforeFactor} → ${FACTOR} on [${LO}, ${HI}). ` +
      `Revert: set the factor back to 1 (or the range to "").`
  );
}

main()
  .catch((e) => {
    log(`apply:v60 FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
