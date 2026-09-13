/**
 * Dead-market resolution fallback.
 *
 * gamma /markets purges sports/daily markets shortly after they resolve, but
 * the parent /events record survives with the full resolution state (closed,
 * umaResolutionStatus, outcomePrices). Polymarket names child markets as
 * <event-slug>-<outcome-suffix>, so we derive candidate event slugs by
 * trimming one dash-token at a time, then scan the event's markets[] for our
 * slug. Returns the WINNING TOKEN LABEL ("Yes", "Under", "Vitality", …) or null
 * when the outcome is genuinely unavailable (the caller then falls back to
 * closing at the last known mark).
 *
 * It used to collapse this to "YES"/"NO" from the first token's price, which is
 * exactly the guess that booked every non-Yes/No market as a loss — the caller
 * compares the label to the trade's own outcome (see src/lib/resolution.ts).
 */

const GAMMA_API = "https://gamma-api.polymarket.com";
const CLOB_API = "https://clob.polymarket.com";
const FALLBACK_DELAY_MS = Number(process.env.API_DELAY_MS ?? 250);

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Winning token label straight from the CLOB by conditionId.
 *
 * Third resolution route, and the only one that still works for markets Gamma
 * has purged AND whose parent event no longer lists them. Returns the winner's
 * own label ("Dynasty", "Under", "Yes") or null when the market is not
 * resolvable by this id (some stored ids are event ids, not condition ids).
 */
export async function fetchWinningLabelViaClob(conditionId: string | null | undefined): Promise<string | null> {
  if (!conditionId || !/^0x[0-9a-fA-F]{10,}$/.test(conditionId)) return null;
  try {
    const res = await fetch(`${CLOB_API}/markets/${conditionId}`, {
      headers: { accept: "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)" },
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) return null;
    const m = (await res.json()) as { closed?: boolean; tokens?: Array<{ outcome?: string; winner?: boolean }> };
    if (m.closed === false) return null; // not resolved yet
    const winner = (m.tokens ?? []).find((t) => t.winner === true);
    return winner?.outcome ?? null;
  } catch {
    return null;
  }
}

export async function fetchEventResolution(marketId: string): Promise<string | null> {
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
      let labels: string[] | undefined;
      let prices: number[] | undefined;
      try {
        const rawLabels = JSON.parse(String(m.outcomes ?? "[]")) as unknown[];
        const rawPrices = JSON.parse(String(m.outcomePrices ?? "[]")) as unknown[];
        if (Array.isArray(rawLabels) && rawLabels.length > 0) {
          labels = rawLabels.map((x) => String(x));
          prices = Array.isArray(rawPrices) ? rawPrices.map((x) => Number(x)) : undefined;
        }
      } catch {
        /* labels unavailable on this payload */
      }
      if (labels && prices && prices.length === labels.length) {
        let best = 0;
        for (let k = 1; k < prices.length; k++) if (prices[k] > prices[best]) best = k;
        if (prices[best] > 0.5) return labels[best];
        await sleep(FALLBACK_DELAY_MS);
        continue;
      }
      // No labels: legacy binary fallback, still only meaningful for YES/NO.
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
      return yesPrice > 0.5 ? "Yes" : "No";
    } catch {
      await sleep(FALLBACK_DELAY_MS);
      continue;
    }
  }
  return null;
}
