/**
 * Discord delivery — optional, via webhook env var. Secrets are never logged.
 * If no webhook is configured, reports are stored in the DB only.
 */

import { log, logError } from "./redact";

export async function sendDiscord(content: string): Promise<boolean> {
  const url = process.env.DISCORD_WEBHOOK_URL;
  if (!url) {
    log("Discord webhook not configured — report stored locally only.");
    return false;
  }
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ content: content.slice(0, 1990) }),
        signal: AbortSignal.timeout(15000),
      });
      if (res.status === 429) {
        // Discord's retry_after is sub-second in practice; honor it and retry.
        const body = (await res.json().catch(() => ({}))) as { retry_after?: number };
        await new Promise((r) => setTimeout(r, Math.ceil(((body.retry_after ?? 1) + 0.1) * 1000)));
        continue;
      }
      if (!res.ok) {
        logError(`Discord webhook failed: HTTP ${res.status} ${await res.text().catch(() => "")}`);
        return false;
      }
      return true;
    }
    logError("Discord webhook failed: still rate-limited after 3 attempts.");
    return false;
  } catch (e) {
    logError("Discord webhook error:", e instanceof Error ? e.message : String(e));
    return false;
  }
}
