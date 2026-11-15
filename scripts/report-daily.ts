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
  // 2026-11-15 self-audit: the old single line said
  //   "ℹ️ Stored locally (no Discord webhook configured or send failed)."
  // and exited 0 in BOTH cases. `copybot-eod` delivers locally (deliver=local) and its
  // failure channel is the exit code, so a configured-but-failing webhook — Discord 5xx,
  // revoked webhook, 429 storm past the retries — lost the day's report with the job
  // still green and nothing on any alert path. That is the same shape as 2026-11-13,
  // when a killed run silently produced no EOD at all. A missing config is not an
  // incident; a failed delivery is.
  const webhookConfigured = Boolean(process.env.DISCORD_WEBHOOK_URL);
  const { summary, sent } = await generateDailyReport({ dryRun });
  log(summary);
  if (dryRun) {
    log("🧪 Dry run — nothing sent, no DailyReport row written.");
  } else if (sent) {
    log("✅ Sent to Discord.");
  } else if (webhookConfigured) {
    logError(
      "❌ Discord delivery FAILED — DISCORD_WEBHOOK_URL is set but the send returned false. " +
        "The report is stored in DailyReport only; failing this job so the failure is routed."
    );
    process.exitCode = 1;
  } else {
    log("ℹ️ Stored locally — DISCORD_WEBHOOK_URL is not set, so no delivery was attempted.");
  }
}

main()
  .catch((e) => {
    logError("report:daily FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
