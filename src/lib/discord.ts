/**
 * Discord delivery — optional, via webhook env var. Secrets are never logged.
 * If no webhook is configured, reports are stored in the DB only.
 *
 * 2026-11-15 (card `research-source-silent-death`, found while wiring the
 * research-source alarm): this sent `content.slice(0, 1990)` and reported
 * success for the truncated message, so every EOD report longer than one
 * message was silently HALF-delivered. Measured on the stored reports: the
 * 2026-11-14 summary is 3,971 chars, 2026-11-11 4,041, 2026-11-10 3,644 —
 * chars 1,990→end never reached Discord on any of them, which is where the
 * rule changes, the instrument heartbeat, the selection caveat and the new
 * research-source alarm all live. The report looked delivered
 * (`sentToDiscord=1`) and was not. Long content is now chunked on line
 * boundaries and each chunk is sent in order; success means EVERY chunk
 * arrived, and a partial delivery is a failure that says so.
 */

import { log, logError } from "./redact";

/** Discord's hard content limit is 2,000; keep a margin for the "(n/m)" tag. */
export const DISCORD_CONTENT_LIMIT = 1990;

/**
 * Split content into ordered chunks that fit Discord, preferring line
 * boundaries. A single line longer than the limit is hard-split rather than
 * dropped: a lost line is the defect this function exists to prevent.
 */
export function chunkForDiscord(content: string, limit = DISCORD_CONTENT_LIMIT): string[] {
  if (content.length === 0) return [];
  const tag = (i: number, n: number) => (n > 1 ? `(${i}/${n}) ` : "");
  // Reserve room for the tag, whose width depends on n; n <= content.length always,
  // so using the full length as the worst case is safe and simple.
  const budget = Math.max(1, limit - `${tag(content.length, content.length)}`.length);

  const lines = content.split("\n");
  const raw: string[] = [];
  let buf = "";
  for (const line of lines) {
    const candidate = buf ? `${buf}\n${line}` : line;
    if (candidate.length <= budget) {
      buf = candidate;
      continue;
    }
    if (buf) raw.push(buf);
    if (line.length <= budget) {
      buf = line;
    } else {
      // One line longer than a whole message: split it, never drop it.
      let rest = line;
      while (rest.length > budget) {
        raw.push(rest.slice(0, budget));
        rest = rest.slice(budget);
      }
      buf = rest;
    }
  }
  if (buf) raw.push(buf);

  if (raw.length <= 1) return raw;
  return raw.map((c, i) => `${tag(i + 1, raw.length)}${c}`);
}

async function postOnce(content: string): Promise<boolean> {
  const url = process.env.DISCORD_WEBHOOK_URL;
  if (!url) return false;
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ content }),
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

export async function sendDiscord(content: string): Promise<boolean> {
  if (!process.env.DISCORD_WEBHOOK_URL) {
    log("Discord webhook not configured — report stored locally only.");
    return false;
  }
  const chunks = chunkForDiscord(content);
  if (chunks.length === 0) {
    log("Discord: nothing to send (empty content).");
    return false;
  }
  if (chunks.length > 1) {
    log(`Discord: content is ${content.length} chars — sending in ${chunks.length} ordered messages.`);
  }
  for (let i = 0; i < chunks.length; i++) {
    const ok = await postOnce(chunks[i]);
    if (!ok) {
      logError(
        `Discord: chunk ${i + 1}/${chunks.length} FAILED — delivery is PARTIAL ` +
          `(${i} of ${chunks.length} messages landed); this is not a sent report.`
      );
      return false;
    }
  }
  return true;
}
