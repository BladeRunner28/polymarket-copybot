/**
 * Minimal read-only venue HTTP for offline/advisory scripts.
 *
 * WHY a separate helper: the live adapter's `getJson` is tuned for the
 * monitoring loop (4 attempts, exponential backoff, negative caching) and is
 * private. Offline capture/measurement scripts want the opposite trade-off —
 * strict, loud, one attempt, generous timeout — so a flaky read fails visibly
 * instead of silently retrying into a partial file.
 *
 * READ ONLY, by construction: GET only, no auth headers, no key material, and
 * no request body. Nothing here can place an order or sign anything.
 */

const DEFAULT_UA = "copybot-research/0.1 (paper-trading-only)";
const DEFAULT_TIMEOUT_MS = 20_000;

/**
 * GET JSON. Throws with the real HTTP status and a body excerpt on failure —
 * callers must not substitute placeholder data for a failed read.
 */
export async function venueGetJson(url: string, opts: { userAgent?: string; timeoutMs?: number } = {}): Promise<unknown> {
  const res = await fetch(url, {
    method: "GET",
    headers: { accept: "application/json", "user-agent": opts.userAgent ?? DEFAULT_UA },
    signal: AbortSignal.timeout(opts.timeoutMs ?? DEFAULT_TIMEOUT_MS),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`GET ${url} -> ${res.status} ${res.statusText}${body ? `: ${body.slice(0, 200)}` : ""}`);
  }
  try {
    return await res.json();
  } catch (e) {
    throw new Error(`GET ${url} -> invalid JSON: ${e instanceof Error ? e.message : String(e)}`);
  }
}

/** Venue hosts used by the capture scripts. */
export const VENUE = {
  gamma: "https://gamma-api.polymarket.com",
  dataApi: "https://data-api.polymarket.com",
  clob: "https://clob.polymarket.com",
} as const;

/** Numeric coercion that never turns a missing field into 0 by accident. */
export function asNumber(v: unknown): number | undefined {
  if (v === null || v === undefined || v === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

/** Parse a JSON-string-or-array field the venue returns in two shapes. */
export function parseJsonArray(v: unknown): unknown[] | undefined {
  if (Array.isArray(v)) return v;
  if (typeof v !== "string") return undefined;
  try {
    const parsed = JSON.parse(v);
    return Array.isArray(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}
