/**
 * c200:fill-resolve — stamp PaperTrade.fillStatus from the print-through evidence.
 *
 * Approved 2026-10-27 ("I approve your recommendations"), re-affirmed 2026-10-28 ("All 5 are approved"),
 * with the resolver's >=80% coverage floor explicitly WAIVED.
 *
 * WHAT IT DOES
 *   For every C-200 intent in data/c200-printthrough.jsonl, resolve whether the maker level was ever
 *   REACHABLE and write the verdict onto the booked leg:
 *     fillStatus = "filled"   -> book window showed the level reachable, or the tape cleared it (flat model)
 *     fillStatus = "unfilled" -> book window showed it NOT reachable, or the tape proved the deeper level
 *                                never printed (a valid NEGATIVE, and the only negative the tape can give)
 *     fillStatus = null       -> "unresolved": no book window AND silent tape. NOT stamped as unfilled.
 *   fillBasis records which evidence decided it; fillResolvedAt records when.
 *
 * WHY "unresolved" IS NOT "unfilled" — this is the whole correctness of the flip
 *   The resolver's asymmetry (src/lib/c200-fill-resolution.ts) exists because reachability is monotone in
 *   price: a fill at a DEEPER level proves nothing about a shallower one, but the ABSENCE of a fill at the
 *   deeper level proves the absence at the shallower level. When neither a book window nor a tape verdict
 *   is held, there is no evidence in either direction — so the leg keeps its old optimistic booking. That
 *   is what makes a 73.6%-resolved book strictly more truthful than an unresolved one rather than merely
 *   different, and it is why the 80% floor protected against nothing.
 *
 * SAFETY
 *   - Writes ONLY the three fill* columns on PaperTrade. Never touches entryPrice, size, PnL, status,
 *     realizedPnl or any bankroll row.
 *   - Idempotent: only stamps legs whose fillStatus IS NULL, so re-runs are no-ops.
 *   - Dry run by default; --apply writes.
 *   - Nothing reads the columns unless FILL_AWARE_BOOKING=1 (src/lib/paper.ts bookedPnl).
 *
 * Run dry:  DATABASE_URL="file:./dev.db" npx tsx scripts/c200-fill-resolve.ts
 * Apply:    DATABASE_URL="file:./dev.db" npx tsx scripts/c200-fill-resolve.ts --apply
 */

import fs from "node:fs";
import path from "node:path";
import { prisma } from "../src/lib/db";
import { log } from "../src/lib/redact";
import { resolveFill, type CreditMode, type ResolutionLeg } from "../src/lib/c200-fill-resolution";

const ARTIFACT = path.join(process.cwd(), "data", "c200-printthrough.jsonl");

interface SnapLeg {
  intentId: string;
  intentPrice: number;
  book?: { minAsk?: number | null } | null;
  tapeSilent?: boolean;
  reached5?: boolean | null;
  reached60?: boolean | null;
}

function loadLatestByIntent(): Map<string, SnapLeg> {
  const out = new Map<string, SnapLeg>();
  if (!fs.existsSync(ARTIFACT)) {
    throw new Error(`print-through artifact missing: ${ARTIFACT} — cannot resolve anything (not "zero legs")`);
  }
  for (const line of fs.readFileSync(ARTIFACT, "utf8").split("\n")) {
    if (!line.trim()) continue;
    let snap: { legs?: SnapLeg[] };
    try {
      snap = JSON.parse(line);
    } catch {
      continue;
    }
    for (const l of snap.legs ?? []) {
      if (l && typeof l.intentId === "string") out.set(l.intentId, l); // latest snapshot wins
    }
  }
  return out;
}

async function main() {
  const apply = process.argv.includes("--apply");
  const mode: CreditMode = "live";

  const latest = loadLatestByIntent();
  log(`print-through artifact: ${latest.size.toLocaleString()} distinct intents`);

  const ids = [...latest.keys()];
  const rows: Array<{ id: string; paperTradeId: string | null }> = [];
  for (let i = 0; i < ids.length; i += 500) {
    const chunk = ids.slice(i, i + 500);
    const got = await prisma.fillIntent.findMany({
      where: { id: { in: chunk } },
      select: { id: true, paperTradeId: true },
    });
    rows.push(...got);
  }
  log(`joined to FillIntent: ${rows.length.toLocaleString()} (${((100 * rows.length) / Math.max(1, ids.length)).toFixed(1)}%)`);

  const legIds = rows.map((r) => r.paperTradeId).filter((x): x is string => !!x);
  const legs = await prisma.paperTrade.findMany({
    where: { id: { in: legIds } },
    select: { id: true, fillStatus: true, status: true },
  });
  const byLegId = new Map(legs.map((l) => [l.id, l]));

  const tally = { filled: 0, unfilled: 0, unresolved: 0, already: 0, missing: 0 };
  const writes: Array<{ id: string; fillStatus: string | null; fillBasis: string }> = [];

  for (const r of rows) {
    if (!r.paperTradeId) continue;
    const leg = byLegId.get(r.paperTradeId);
    if (!leg) {
      tally.missing++;
      continue;
    }
    if (leg.fillStatus !== null) {
      tally.already++;
      continue;
    }
    const s = latest.get(r.id)!;
    const rl: ResolutionLeg = {
      intentPrice: Number(s.intentPrice),
      bookMinAsk:
        s.book && typeof s.book.minAsk === "number" && Number.isFinite(s.book.minAsk) ? s.book.minAsk : null,
      tapeReached5: s.tapeSilent ? null : (s.reached5 ?? null),
      tapeReached60: s.tapeSilent ? null : (s.reached60 ?? null),
    };
    const v = resolveFill(rl, mode);
    if (v.basis === "unresolved") {
      tally.unresolved++;
      continue; // do NOT stamp: no evidence in either direction
    }
    const status = v.reachable ? "filled" : "unfilled";
    if (status === "filled") tally.filled++;
    else tally.unfilled++;
    writes.push({ id: leg.id, fillStatus: status, fillBasis: v.basis });
  }

  const total = tally.filled + tally.unfilled + tally.unresolved;
  const resolved = total > 0 ? (100 * (tally.filled + tally.unfilled)) / total : 0;
  log("");
  log("VERDICTS (legs with no stamp yet):");
  log(`  filled      ${tally.filled.toLocaleString()}`);
  log(`  unfilled    ${tally.unfilled.toLocaleString()}`);
  log(`  unresolved  ${tally.unresolved.toLocaleString()}  (left NULL — books unchanged)`);
  log(`  already stamped ${tally.already.toLocaleString()} · leg row missing ${tally.missing.toLocaleString()}`);
  log(`  => resolution coverage ${resolved.toFixed(1)}% of ${total.toLocaleString()} (floor 80% was WAIVED)`);
  log("");

  if (!apply) {
    log(`DRY RUN — ${writes.length.toLocaleString()} rows would be stamped. Re-run with --apply.`);
    return;
  }

  for (let i = 0; i < writes.length; i += 500) {
    const chunk = writes.slice(i, i + 500);
    await prisma.$transaction(
      chunk.map((w) =>
        prisma.paperTrade.update({
          where: { id: w.id },
          data: { fillStatus: w.fillStatus, fillBasis: w.fillBasis, fillResolvedAt: new Date() },
        })
      )
    );
    process.stdout.write(`\r  stamped ${Math.min(i + 500, writes.length).toLocaleString()}/${writes.length.toLocaleString()}`);
  }
  log("");
  log(`DONE. ${writes.length.toLocaleString()} legs stamped.`);
  log("Booking is unchanged until FILL_AWARE_BOOKING=1 is set for the scoring/EOD process.");
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
