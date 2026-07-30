/**
 * report:daily — generate + store the end-of-day report and send to Discord
 * if a webhook is configured.
 */

import { prisma } from "../src/lib/db";
import { generateDailyReport } from "../src/lib/report";
import { log, logError } from "../src/lib/redact";

async function main() {
  const { summary, sent } = await generateDailyReport();
  log(summary);
  log(sent ? "✅ Sent to Discord." : "ℹ️ Stored locally (no Discord webhook configured or send failed).");
}

main()
  .catch((e) => {
    logError("report:daily FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
