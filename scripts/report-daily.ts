/**
 * report:daily — generate + store the end-of-day report and send to Discord
 * if a webhook is configured.
 */

import { prisma } from "../src/lib/db";
import { generateDailyReport } from "../src/lib/report";
import { log, logError } from "../src/lib/redact";

async function main() {
  // --dry-run (or REPORT_DRY_RUN=1) prints the report without sending it to
  // Discord or writing the DailyReport row — safe way to preview a change to the
  // calendar-day window.
  const dryRun = process.argv.includes("--dry-run") || process.env.REPORT_DRY_RUN === "1";
  const { summary, sent } = await generateDailyReport({ dryRun });
  log(summary);
  log(
    dryRun
      ? "🧪 Dry run — nothing sent, no DailyReport row written."
      : sent
        ? "✅ Sent to Discord."
        : "ℹ️ Stored locally (no Discord webhook configured or send failed)."
  );
}

main()
  .catch((e) => {
    logError("report:daily FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
