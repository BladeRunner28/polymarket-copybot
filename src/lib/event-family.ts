/**
 * event-family + wallet concentration helpers — PURE (no logger, no DB), so the pre-registered
 * family rule and the wallet split can be unit-tested without running the EOD read.
 *
 * Two dimensions, one line each, because they answer different questions and the difference is
 * the whole point of tuning #48 rec 1: the event-family view prices correlated exposure ACROSS
 * markets (eight cities are eight markets but one weather regime), and the wallet view asks
 * whether that correlated block is ALSO one counterparty's book. On 2026-10-07 the C-200 book
 * showed `highest-temperature-in` at 64.6% of open cost — 12 legs, all one wallet — a shape the
 * family read alone cannot distinguish from eight independent city bets.
 *
 * FAMILY RULE (pre-registered — do NOT silently re-derive it; a reviewer's cross-check and the
 * EOD line must agree):
 *   1. if the slug carries an ISO date (`<key>-YYYY-MM-DD[-<market suffix>]`), the family is
 *      everything up to and including that date — league/weather events are date-scoped
 *      (unl-nor-prt-2026-09-27-nor + -prt = ONE family);
 *   2. otherwise the first 3 dash tokens — will-<entity>-…, elon-musk-of-…, i.e. the entity an
 *      event set hangs off.
 */

/** ISO date first, else the first 3 dash tokens (see the rule above). */
export function eventFamily(marketId: string): string {
  const dated = /^(.*?-\d{4}-\d{2}-\d{2})(?:-|$)/.exec(marketId);
  if (dated) return dated[1];
  const toks = marketId.split("-");
  return toks.length >= 3 ? toks.slice(0, 3).join("-") : marketId;
}

/** Sentinel for a leg with no stored wallet — never silently folded into a real address. */
export const NO_WALLET = "(no wallet)";

export interface CostedLeg {
  walletAddress?: string | null;
  cost: number | null;
}

export interface WalletShare {
  wallet: string;
  legs: number;
  cost: number;
}

/**
 * Wallet split of one population (a family, or the whole book). Ordering is cost DESC, then
 * wallet ASC so the SAME population always prints the same string — the EOD line is verified by
 * re-running it at a fixed instant, which only works if ties cannot flip between runs.
 */
export function walletSplit(legs: CostedLeg[]): WalletShare[] {
  const byWallet = new Map<string, WalletShare>();
  for (const l of legs) {
    const w = l.walletAddress && l.walletAddress.length ? l.walletAddress : NO_WALLET;
    const cur = byWallet.get(w) ?? { wallet: w, legs: 0, cost: 0 };
    cur.legs += 1;
    cur.cost += Number(l.cost ?? 0);
    byWallet.set(w, cur);
  }
  return [...byWallet.values()].sort((a, b) => b.cost - a.cost || a.wallet.localeCompare(b.wallet));
}

/** `0x7c63520c…` — deterministic short form; the full address stays in the DB, not the log line. */
export function shortWallet(wallet: string): string {
  if (wallet === NO_WALLET) return wallet;
  return wallet.length > 10 ? `${wallet.slice(0, 10)}…` : wallet;
}

/** Renders a split as `0xabc… 12 legs +$279.90 (64.6%)` entries joined by ` | `. */
export function describeSplit(
  shares: WalletShare[],
  total: number,
  limit = 3
): string {
  const share = (v: number) => (total > 0 ? `${((100 * v) / total).toFixed(1)}%` : "n/a");
  const money = (v: number) => `${v >= 0 ? "+" : "-"}$${Math.abs(v).toFixed(2)}`;
  return shares
    .slice(0, limit)
    .map((s) => `${shortWallet(s.wallet)} ${s.legs} legs ${money(s.cost)} (${share(s.cost)})`)
    .join(" | ");
}
