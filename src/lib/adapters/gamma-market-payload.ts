/**
 * Gamma market-payload normalization + slug-endpoint selection.
 *
 * WHY (verified live 2026-09-28, see drafts/polyterm-audit-2026-09-28.md §P4):
 * our adapter reads markets through the LEGACY offset endpoint
 * `GET /markets?slug=…`, which now returns
 *
 *     deprecation: true
 *     sunset: Fri, 01 May 2026 00:00:00 GMT
 *
 * — i.e. it is already past its announced sunset (it still answers 200 today).
 * The current contract is `GET /markets/slug/{slug}`, which returns a single
 * OBJECT instead of a one-element ARRAY, with the same fields (probed live:
 * identical field set apart from an added `$schema`).
 *
 * This module holds the shape handling and the endpoint preference so both are
 * unit-testable without network access. The adapter keeps the retry/negative-
 * cache behaviour.
 */

export type GammaSlugEndpoint = "slug" | "legacy";

/**
 * Endpoint order for slug lookups. Default is current-contract-first with the
 * legacy endpoint as fallback; `GAMMA_SLUG_API=legacy` pins the old order so a
 * live regression can be reverted without a code change.
 */
export function gammaSlugEndpointOrder(env: Record<string, string | undefined> = process.env): GammaSlugEndpoint[] {
  const pref = String(env.GAMMA_SLUG_API ?? "slug").toLowerCase();
  return pref === "legacy" ? ["legacy", "slug"] : ["slug", "legacy"];
}

/** URL for one slug lookup on a given endpoint variant. */
export function gammaSlugUrl(baseUrl: string, slug: string, endpoint: GammaSlugEndpoint): string {
  const base = baseUrl.replace(/\/+$/, "");
  return endpoint === "slug"
    ? `${base}/markets/slug/${encodeURIComponent(slug)}`
    : `${base}/markets?slug=${encodeURIComponent(slug)}`;
}

/**
 * Normalize either shape to a single market object, or null when the payload
 * carries no market. Accepts:
 *   - the current contract: a plain object
 *   - the legacy contract: a one-element array
 *   - an empty array / empty object / error envelope / non-object → null
 *
 * A payload is only accepted when it actually looks like a market (has a slug,
 * a conditionId or an id): Gamma error envelopes are JSON objects too, and
 * treating one as a market would poison the negative cache with a live market.
 */
export function normalizeGammaMarketPayload(payload: unknown): Record<string, unknown> | null {
  let candidate: unknown = payload;
  if (Array.isArray(payload)) {
    if (payload.length === 0) return null;
    candidate = payload[0];
  }
  if (candidate === null || typeof candidate !== "object" || Array.isArray(candidate)) return null;
  const obj = candidate as Record<string, unknown>;
  const looksLikeMarket = Boolean(obj.slug ?? obj.conditionId ?? obj.id);
  if (!looksLikeMarket) return null;
  return obj;
}
