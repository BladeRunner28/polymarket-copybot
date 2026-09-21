/**
 * capital-deposits-report — the report half of the /capital deliverable
 * (2026-09-20, user request: "a chart ... also a report that shows the same
 * information"). SAME series as src/app/capital/page.tsx (both call
 * src/lib/capital.ts), so the page and the report cannot disagree; the page
 * links the newest drafts/capital-deposits-*.md this script writes.
 *
 * DEFINITIONS
 *   Total Capital (live) = principal + realized + open mark-to-market
 *                          (the Overview's own stat — moves with marks)
 *   Booked capital       = principal + realized only
 *   Daily deposit        = booked PnL that day + ledger injection that day
 *
 * Usage:
 *   npx tsx scripts/capital-deposits-report.ts                  # print markdown (writes nothing)
 *   npx tsx scripts/capital-deposits-report.ts --write          # also write drafts/capital-deposits-<day>.md
 *   npx tsx scripts/capital-deposits-report.ts --days=90 --write
 *
 * Read-only against the DB. The only file it writes is the markdown draft, and
 * only with --write.
 */

import { prisma } from "../src/lib/db";
import { writeFileSync } from "fs";
import { join } from "path";
import { localDayKey, positiveStreak, topDays } from "../src/lib/capital";
import { loadCapitalState } from "../src/lib/capital-data";

const BOT = "BANKROLL_200";
const args = process.argv.slice(2);
const WRITE = args.includes("--write");
const DISCORD = args.includes("--discord");
const daysArg = args.find((a) => a.startsWith("--days="));
const DAYS = daysArg ? Number(daysArg.split("=")[1]) : 30;

const usd = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;
const signed = (v: number) => `${v >= 0 ? "+" : "-"}$${Math.abs(v).toFixed(2)}`;

async function main() {
  // ONE loader, shared with /capital and the Overview card (src/lib/capital-data.ts).
  const state = await loadCapitalState({ days: DAYS });
  const { series: s, ledger, principal, realized, openUnreal, openNotional } = state;

  const streak = positiveStreak(s.points);
  // Best = largest POSITIVE deposits, worst = largest negative ones (no overlap,
  // so the same day cannot appear in both lists).
  const top = s.points.filter((p) => p.deposit > 0).sort((a, b) => b.deposit - a.deposit).slice(0, 5);
  const bottom = s.points.filter((p) => p.deposit < 0).sort((a, b) => a.deposit - b.deposit).slice(0, 5);
  const upDays = s.points.filter((p) => p.deposit > 0).length;
  const downDays = s.points.filter((p) => p.deposit < 0).length;
  const flatDays = s.points.length - upDays - downDays;
  const best = s.points.reduce((a, b) => (b.closing > a.closing ? b : a), s.points[0]);
  const day = localDayKey(Date.now());

  const L: string[] = [];
  L.push(`# Capital report — daily deposits into Total Capital (${day})`);
  L.push("");
  L.push(
    `**Definitions.** *Total Capital (live)* = principal ${usd(principal)} + realized ${usd(realized)} + open mark-to-market ${usd(openUnreal)} = **${usd(principal + realized + openUnreal)}** — the Overview's own stat, so it moves with marks and can fall without a trade closing. *Daily deposit* = the capital added on a local calendar day = that day's **booked** PnL (finished trades, booked at \`closedAt ?? resolvedAt\`) + any **ledger injection**. This report and the chart on \`/capital\` are the same \`src/lib/capital.ts\` series.`
  );
  L.push("");
  L.push("## Window");
  L.push("");
  L.push(`- Window: **${s.points[0]?.day} → ${s.points[s.points.length - 1]?.day}** (${s.points.length} local days)`);
  L.push(`- Opening booked capital: **${usd(s.openingUsd)}** (\`opening\` ledger entry ${usd(s.seedUsd)}${s.seededOn ? ` dated ${s.seededOn}` : ""})`);
  L.push(`- Deposits in window: **${signed(s.bookedTotal + s.injectedTotal)}** = booked ${signed(s.bookedTotal)} + injected ${signed(s.injectedTotal)}`);
  L.push(`- Closing booked capital: **${usd(s.closingUsd)}** · peak close ${usd(best.closing)} on ${best.day}`);
  L.push(`- Up days ${upDays} · down days ${downDays} · flat ${flatDays} · longest up-run ${streak.best} (current ${streak.current})`);
  L.push(`- Open positions excluded from every row: notional ${usd(openNotional)}, unrealized ${signed(openUnreal)}`);
  L.push("");
  L.push("## Daily deposits (same numbers as the /capital chart)");
  L.push("");
  L.push("| day | deposit | booked | closing |");
  L.push("|---|---|---|---|");
  for (const p of [...s.points].reverse()) {
    const inj = p.injected !== 0 ? ` (incl. ledger ${signed(p.injected)})` : "";
    L.push(`| ${p.day} | ${p.deposit === 0 ? "—" : signed(p.deposit)}${inj} | ${p.booked === 0 ? "—" : signed(p.booked)} | ${usd(p.closing)} |`);
  }
  L.push(`| **total** | **${signed(s.bookedTotal + s.injectedTotal)}** | **${signed(s.bookedTotal)}** | **${usd(s.closingUsd)}** |`);
  L.push("");
  L.push("## Best / worst days");
  L.push("");
  L.push(`- Best: ${top.map((p) => `${p.day} ${signed(p.deposit)}`).join(" · ")}`);
  L.push(`- Worst: ${bottom.map((p) => `${p.day} ${signed(p.deposit)}`).join(" · ")}`);
  L.push("");
  L.push("## Capital ledger (injections)");
  L.push("");
  if (ledger.length === 0) {
    L.push("- no entries — \`data/capital-ledger.json\` is empty");
  } else {
    for (const e of ledger) L.push(`- \`${e.kind}\` ${e.date} **${usd(e.amountUsd)}**${e.note ? ` — ${e.note}` : ""}`);
  }
  L.push("");
  L.push(
    `- Ledger reconciliation: principal ${usd(principal)} − (seed ${usd(s.seedUsd)} + net flows ${usd(
      ledger.filter((e) => e.kind !== "opening").reduce((a, e) => a + e.amountUsd, 0)
    )}) = **${usd(s.ledgerGapUsd)}**${Math.abs(s.ledgerGapUsd) < 0.01 ? " ✓" : " ⚠ unexplained — record the injection/withdrawal"}`
  );
  L.push("");
  L.push("## Caveats");
  L.push("");
  L.push(
    "- **Pre-ledger funding is unrecoverable.** \`BotBankroll.principal\` has no history (\`prisma/dev.db\` is gitignored, nothing logs a principal change). The ledger seeds the standing principal once as an \`opening\` entry dated to the bot's first trade — that date is the bot's start, NOT a documented funding date. Real injections are recorded from 2026-09-20 forward; an unlogged principal move surfaces as the ledger gap above."
  );
  L.push(
    "- **Booked, not marked.** The rows use booked PnL only (paper trades pay out at 1/0 on resolution; early exits book at \`closedAt\`). The live Total Capital figure includes open mark-to-market, so it will differ from the closing column — by design, and both are labelled on \`/capital\`."
  );
  L.push("- **Local-day boundary.** Days are local (America/Chicago) calendar days, the same boundary the Overview's startOfDay and the EOD report use. A finished trade is immutable once booked, so past rows never change.");
  L.push("- Fees/slippage are not modelled in the paper ledger (see the paper-ledger fee-fidelity card), so a deposit is gross of execution costs.");
  L.push("");
  L.push("## Reproduce");
  L.push("");
  L.push("```bash");
  L.push(`npx tsx scripts/capital-deposits-report.ts --days=${DAYS}          # print, writes nothing`);
  L.push(`npx tsx scripts/capital-deposits-report.ts --days=${DAYS} --write  # + drafts/capital-deposits-${day}.md`);
  L.push("npx vitest run tests/capital.test.ts");
  L.push("```");
  L.push("");

  const doc = L.join("\n");

  // ---- Discord digest (no-agent cron: stdout IS the delivered message) ----
  // Narrow: no wide tables, short columns (the user's standing Discord rule).
  // Always informative, even on a flat day, so the job never goes silent.
  const yest = s.points[s.points.length - 1];
  const D: string[] = [];
  D.push(`💰 **Capital report — ${day}** (${s.points.length}d window)`);
  D.push(
    `**Total Capital (live): ${usd(state.liveTotalCapital)}** = principal ${usd(principal)} + realized ${usd(realized)} + open MTM ${signed(openUnreal)}`
  );
  D.push(
    `Today (${yest.day}, partial): deposit **${signed(yest.deposit)}** (booked ${signed(yest.booked)}, ledger ${signed(yest.injected)}) · ${yest.trades} trade(s) · closing capital ${usd(yest.closing)}`
  );
  D.push(
    `7d deposits: **${signed(s.points.slice(-7).reduce((a, p) => a + p.deposit, 0))}** · streak ${streak.current} (best ${streak.best}) · ${upDays} up / ${downDays} down / ${flatDays} flat`
  );
  D.push(
    `${s.points.length}d deposits: **${signed(s.bookedTotal + s.injectedTotal)}** = booked ${signed(s.bookedTotal)} + injected ${signed(s.injectedTotal)} → booked capital ${usd(s.openingUsd)} → **${usd(s.closingUsd)}**`
  );
  D.push("");
  D.push("Top days (window):");
  for (const p of top.slice(0, 5)) D.push(`• ${p.day}  **${signed(p.deposit)}**  (capital ${usd(p.closing)})`);
  D.push("Worst days (window):");
  for (const p of bottom.slice(0, 3)) D.push(`• ${p.day}  **${signed(p.deposit)}**  (capital ${usd(p.closing)})`);
  D.push("");
  D.push(
    Math.abs(s.ledgerGapUsd) < 0.01
      ? `Ledger: reconciled ✓ (principal ${usd(principal)} = seed ${usd(s.seedUsd)} + net flows ${usd(0)})`
      : `⚠ Ledger gap ${usd(s.ledgerGapUsd)} — principal is not explained by data/capital-ledger.json (record the injection/withdrawal)`
  );
  D.push(
    `📄 report: :3013/drafts/capital-deposits-${day} · chart: :3013/capital · regenerate: \`npx tsx scripts/capital-deposits-report.ts --write --discord\``
  );
  const digest = D.join("\n");

  if (WRITE) {
    const fp = join(__dirname, "..", "drafts", `capital-deposits-${day}.md`);
    writeFileSync(fp, doc);
  }

  if (DISCORD) {
    // Message only — the wrapper logs everything else to logs/cron/.
    console.log(digest);
    return;
  }
  console.log(doc);
  console.log(
    WRITE
      ? `\n📄 written: drafts/capital-deposits-${day}.md (served at :3013/drafts/capital-deposits-${day})`
      : "\n(report only — pass --write to save drafts/capital-deposits-<day>.md, --discord for the cron digest)"
  );
}

main()
  .catch((e) => {
    console.error("capital-deposits-report FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
