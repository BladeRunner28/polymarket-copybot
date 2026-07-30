/**
 * Secret redaction. Any env value that looks like a secret is masked before
 * it can appear in logs or UI. There are no private keys in this app by
 * design, but webhook URLs and future optional API keys are still secrets.
 */

const SECRET_ENV_KEYS = ["DISCORD_WEBHOOK_URL", "DATABASE_URL"];

export function redactSecrets(text: string): string {
  let out = text;
  for (const key of SECRET_ENV_KEYS) {
    const val = process.env[key];
    if (val && val.length > 4) {
      out = out.split(val).join(`[REDACTED:${key}]`);
    }
  }
  // Generic patterns: webhook URLs, bearer tokens, long hex that could be a key
  out = out.replace(
    /https:\/\/discord\.com\/api\/webhooks\/[^\s"']+/g,
    "[REDACTED:webhook]"
  );
  out = out.replace(/Bearer\s+[A-Za-z0-9._-]{16,}/g, "Bearer [REDACTED]");
  out = out.replace(/\b(0x)?[0-9a-fA-F]{64}\b/g, "[REDACTED:possible-key]");
  return out;
}

export function log(...args: unknown[]) {
  const line = args
    .map((a) => (typeof a === "string" ? a : JSON.stringify(a)))
    .join(" ");
  console.log(redactSecrets(line));
}

export function logError(...args: unknown[]) {
  const line = args
    .map((a) =>
      a instanceof Error ? `${a.name}: ${a.message}` : typeof a === "string" ? a : JSON.stringify(a)
    )
    .join(" ");
  console.error(redactSecrets(line));
}
