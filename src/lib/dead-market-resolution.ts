/**
 * Dead-market resolution fallback.
 *
 * gamma /markets purges sports/daily markets shortly after they resolve, but
 * the parent /events record survives with the full resolution state (closed,
 * umaResolutionStatus, outcomePrices). Polymarket names child markets as
 * <event-slug>-<outcome-suffix>, so we derive candidate event slugs by
 * trimming one dash-token at a time, then scan the event's markets[] for our
 * slug. Returns "YES"/"NO", or null when the outcome is genuinely unavailable
 * (the caller then falls back to closing at the last known mark).
 */

const GAMMA_API = "https://gamma-api.polymarket.com";
const FALLBACK_DELAY_MS = Number(process.env.API_DELAY_MS ?? 250);

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

export async function fetchEventResolution(marketId: string): Promise<"YES" | "NO" | null> {
  const tokens = marketId.split("-");
  const minTokens = Math.max(2, tokens.length - 4);
  for (let i = tokens.length - 1; i >= minTokens; i--) {
    const eventSlug = tokens.slice(0, i).join("-");
    if (eventSlug === marketId || eventSlug.length < 8) continue;
    let res: Response;
    try {
      res = await fetch(`${GAMMA_API}/events?slug=${encodeURIComponent(eventSlug)}`, {
        headers: { accept: "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)" },
        signal: AbortSignal.timeout(15000),
      });
    } catch {
      await sleep(FALLBACK_DELAY_MS);
      continue;
    }
    if (!res.ok) {
      await sleep(FALLBACK_DELAY_MS);
      continue;
    }
    try {
      const events = (await res.json()) as Array<{ markets?: Array<Record<string, unknown>> }>;
      const m = events?.[0]?.markets?.find((x) => String(x.slug) === marketId);
      const resolved = m && (m.closed === true || m.umaResolutionStatus === "resolved");
      if (!resolved) {
        await sleep(FALLBACK_DELAY_MS);
        continue;
      }
      let yesPrice: number | undefined;
      try {
        yesPrice = Number(JSON.parse(String(m.outcomePrices ?? "[]"))[0]);
      } catch {
        /* leave undefined */
      }
      if (yesPrice === undefined || Number.isNaN(yesPrice)) {
        await sleep(FALLBACK_DELAY_MS);
        continue;
      }
      return yesPrice > 0.5 ? "YES" : "NO";
    } catch {
      await sleep(FALLBACK_DELAY_MS);
      continue;
    }
  }
  return null;
}
