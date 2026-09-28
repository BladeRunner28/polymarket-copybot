/**
 * event-family-concentration — READ-ONLY: how much of the C-200 OPEN book's cost
 * sits in its top-3 EVENT FAMILIES.
 *
 * Tuning review #38 rec 2 (user-approved 2026-09-28), carried from #36 R1 for a
 * 3rd cycle. Why it exists: the open book is four single-leg $100 positions, one
 * per FAMILY, and **v55 (per-market) and v59 (per-wallet) both read 0** because
 * the exposure is correlated ACROSS markets, not stacked inside one of them. The
 * −$300 realisation #37 documented came from exactly that shape (three adjacent
 * elon tweet-count bands, one wallet). The line prices the shape daily instead of
 * being re-derived by hand each cycle.
 *
 * FAMILY RULE (pre-registered — do NOT silently re-derive it; a reviewer's
 * cross-check and this line must agree):
 *   1. if the slug carries an ISO date (`<key>-YYYY-MM-DD[-<market suffix>]`),
 *      the family is everything up to and including that date — league/weather
 *      events are date-scoped (unl-nor-prt-2026-09-27-nor + -prt = ONE family);
 *   2. otherwise the first 3 dash tokens — will-<entity>-…, elon-musk-of-…,
 *      i.e. the entity an event set hangs off.
 * The rec's own verify clause asked for `substr(marketId,1,30)` instead; that SQL
 * cannot produce the id it quoted (`will-xavier-becerra` — `substr(…,1,30)` gives
 * `will-xavier-becerra-win-the-ca`) AND it splits same-event legs, so the
 * corrected form is the 3-token/ISO rule above. The 30-char prefix re-run is
 * printed on its own cross-check line so the original command still reconciles.
 *
 * Writes nothing. Reads PaperTrade only (open, non-demo, BANKROLL_200). The three
 * figures that must be read TOGETHER ship on one line: the family share, the
 * denominator (open cost + legs) and the family count.
 *
 * Verify (7 d post-apply): `grep -c "by event family" logs/cron/copybot-eod.log`
 * >= 1, and the newest printed top-3 equals a re-run of this script (deterministic)
 * or of the printed SQL for the 30-char prefix, and the EOD still exits 0.
 */
import { prisma } from "../src/lib/db";

const SQL = `SELECT marketId, simulatedPositionSize AS cost
FROM PaperTrade
WHERE botId = 'BANKROLL_200' AND isDemo = 0 AND status = 'open'`;

/** ISO date first, else the first 3 dash tokens (see the rule in the header). */
export function eventFamily(marketId: string): string {
  const dated = /^(.*?-\d{4}-\d{2}-\d{2})(?:-|$)/.exec(marketId);
  if (dated) return dated[1];
  const toks = marketId.split("-");
  return toks.length >= 3 ? toks.slice(0, 3).join("-") : marketId;
}

const money = (v: number) => `${v >= 0 ? "+" : "-"}$${Math.abs(v).toFixed(2)}`;

type Row = { marketId: string; cost: number | null };

async function main() {
  const rows = await prisma.$queryRawUnsafe<Row[]>(SQL);
  if (rows.length === 0) {
    console.log("C-200 open concentration by event family: no open legs.");
    return;
  }
  const byFamily = new Map<string, { legs: number; cost: number }>();
  let total = 0;
  for (const r of rows) {
    const cost = Number(r.cost ?? 0);
    total += cost;
    const k = eventFamily(r.marketId);
    const cur = byFamily.get(k) ?? { legs: 0, cost: 0 };
    byFamily.set(k, { legs: cur.legs + 1, cost: cur.cost + cost });
  }
  const ranked = [...byFamily.entries()].sort((a, b) => b[1].cost - a[1].cost);
  const top3 = ranked.slice(0, 3);
  const top3Cost = top3.reduce((s, [, v]) => s + v.cost, 0);
  const multi = ranked.filter(([, v]) => v.legs > 1);
  const share = (v: number) => (total > 0 ? `${((100 * v) / total).toFixed(1)}%` : "n/a");

  console.log(
    `C-200 open concentration by event family: ${rows.length} open legs / $${total.toFixed(2)} cost / ` +
      `${ranked.length} families — top-3: ` +
      top3.map(([k, v]) => `${k} ${money(v.cost)} (${share(v.cost)})`).join(" | ") +
      ` → top-3 = ${money(top3Cost)} = ${share(top3Cost)} of open cost` +
      ` | families with >1 leg: ${multi.length}` +
      (multi.length
        ? ` (${multi.map(([k, v]) => `${k} ${v.legs} legs ${money(v.cost)}`).join(" | ")})`
        : "")
  );
  console.log(
    "  family rule (pre-registered): slug cut at the ISO date when the slug carries one, " +
      "else the first 3 dash tokens — read the top-3 as a SHARE, not a leg count"
  );
  console.log("  reproduce: npx tsx scripts/event-family-concentration.ts");
  console.log(
    `  sql cross-check (30-char prefix stem, the rec's original form): sqlite3 -readonly prisma/dev.db ` +
      `"SELECT substr(marketId,1,30) stem, COUNT(*) legs, ROUND(SUM(simulatedPositionSize),2) cost ` +
      `FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status='open' GROUP BY stem ` +
      `ORDER BY cost DESC LIMIT 3;"`
  );
}

main()
  .catch((e) => {
    console.error("event-family-concentration FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
