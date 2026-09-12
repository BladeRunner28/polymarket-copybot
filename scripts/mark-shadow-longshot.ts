/**
 * shadow:longshot-mark — resolve pending long-shot shadow-ladder candidates and
 * publish the shadow-book summary (2026-09-11 C-200 daily report Change 1,
 * approved; freeze-allowed instrumentation).
 *
 * Reads data/longshot-shadow.jsonl (written by score-trades), resolves every
 * would-admit candidate whose market has settled (adapter market state, then
 * the parent-event fallback for dead/renamed slugs), appends one `resolve`
 * record per settled row, and writes data/longshot-shadow-summary.json.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/mark-shadow-longshot.ts
 */

import { getAdapter } from "../src/lib/adapters";
import { fetchEventResolution } from "../src/lib/dead-market-resolution";
import { readShadowRows, summarizeShadow, SHADOW_FILE, SHADOW_SUMMARY_FILE } from "../src/lib/shadow-longshot";
import { log, logError } from "../src/lib/redact";
import * as fs from "fs";

async function main() {
  const adapter = getAdapter();
  const rows = readShadowRows();
  const candidates = rows.filter((r) => r.type === "candidate" && r.wouldAdmit === true);
  const already = new Set(
    rows.filter((r) => r.type === "resolve").map((r) => `${r.marketId}|${r.outcome}`)
  );

  const pending = new Map<string, { marketId: string; outcome: string }>();
  for (const c of candidates) {
    const key = `${c.marketId}|${c.outcome}`;
    if (!already.has(key)) pending.set(key, { marketId: String(c.marketId), outcome: String(c.outcome) });
  }

  log(`shadow-longshot: ${candidates.length} admits, ${already.size} resolved, ${pending.size} pending.`);
  let resolvedNow = 0;

  for (const { marketId, outcome } of pending.values()) {
    let value: number | undefined;
    try {
      const m = await adapter.fetchMarket(marketId);
      if (m.resolved && m.winningOutcome) value = m.winningOutcome === outcome ? 1 : 0;
    } catch {
      // fall through to the event-resolution path
    }
    if (value === undefined) {
      try {
        const ev = await fetchEventResolution(marketId);
        if (ev) value = ev === outcome ? 1 : 0;
      } catch {
        /* leave unresolved */
      }
    }
    if (value === undefined) continue;
    fs.appendFileSync(
      SHADOW_FILE,
      JSON.stringify({ ts: new Date().toISOString(), type: "resolve", marketId, outcome, value }) + "\n"
    );
    resolvedNow++;
  }

  const summary = summarizeShadow(readShadowRows());
  fs.writeFileSync(SHADOW_SUMMARY_FILE, JSON.stringify(summary, null, 2));
  log(
    `shadow-longshot: +${resolvedNow} resolved this run. Book: ${summary.wouldAdmit} admits, ` +
      `${summary.resolved} resolved (${summary.wins} wins, ` +
      `${summary.winRate === null ? "—" : (summary.winRate * 100).toFixed(1) + "%"}), ` +
      `PnL $${summary.totalPnl.toFixed(2)} @ $${summary.stakeUsd}/trade (` +
      `${summary.avgPnlPerTrade === null ? "—" : "$" + summary.avgPnlPerTrade.toFixed(2)}/trade). ` +
      `Summary: ${SHADOW_SUMMARY_FILE}`
  );
}

main()
  .catch((e) => {
    logError("shadow:longshot-mark FAILED:", e);
    process.exit(1);
  })
  .finally(() => process.exit(0));
