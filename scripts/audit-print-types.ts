/**
 * audit:print-types — measure what a print-type filter would drop, BEFORE any
 * ingest behaviour changes.
 *
 * WHY (audit §P6, draft drafts/polyterm-audit-2026-09-28.md):
 * `data-api.polymarket.com/activity` mixes real fills with position-management
 * rows (`split`, `merge`, `redeem`, `reward`, `conversion`, liquidity ops,
 * deposits/withdrawals). Our adapter maps whatever comes back and never looks at
 * `row.type` (`grep -rniE "redeem|split|merge" src/lib` finds no classifier), so
 * a redemption row is indistinguishable from a fill downstream.
 *
 * THE RULE THIS SCRIPT RESPECTS: enabling the filter CHANGES INGEST COUNTS, and
 * counts feed published numbers. So this script does not enable anything — it
 * re-reads the same public activity pages, classifies them with
 * `src/lib/print-types.ts`, and reports kept/skipped per type per wallet. The
 * decision to flip ingest comes after that measurement, with both numbers on the
 * table.
 *
 * ENV
 *   PRINT_AUDIT_WALLETS  wallets to sample (default 5)
 *   PRINT_AUDIT_DAYS     activity lookback in days (default 2)
 *   PRINT_AUDIT_PAGE     page size (default 500)
 *
 * MODES
 *   (default)   sample wallets from our own DB (most observed trades first)
 *   --leaderboard  sample from the public leaderboard instead
 *   --unfiltered   DROP the server-side `type=TRADE` filter, so the tape returns
 *                  every row type. This is the counterfactual that matters: our
 *                  activity read already asks the API for trades only, so a
 *                  client-side filter can only matter where the filter is absent
 *                  (the `/trades` tape path used by c200-printthrough).
 */

import { appendFileSync } from "fs";
import { join } from "path";
import { prisma } from "../src/lib/db";
import { filterTradeRows, isKnownRowType, NON_TRADE_TYPES } from "../src/lib/print-types";
import { laggedDataApiProvenance } from "../src/lib/provenance";
import { VENUE, venueGetJson } from "../src/lib/venue-read";
import { log, logError } from "../src/lib/redact";

const OUT = join(__dirname, "..", "data", "print-type-audit.jsonl");
const WALLETS = Number(process.env.PRINT_AUDIT_WALLETS ?? 5);
const DAYS = Number(process.env.PRINT_AUDIT_DAYS ?? 2);
const PAGE = Number(process.env.PRINT_AUDIT_PAGE ?? 500);
const USE_LEADERBOARD = process.argv.includes("--leaderboard");
const UNFILTERED = process.argv.includes("--unfiltered");

/** Sample wallets we already track, so the sample is one our lane actually sees. */
async function sampleWallets(limit: number): Promise<string[]> {
  if (USE_LEADERBOARD) {
    const data = await venueGetJson(`${VENUE.dataApi}/v1/leaderboard?timePeriod=month&orderBy=PNL&limit=${limit}`);
    if (!Array.isArray(data)) throw new Error(`unexpected leaderboard shape: ${typeof data}`);
    return (data as Record<string, unknown>[])
      .map((r) => String(r.proxyWallet ?? r.address ?? "").toLowerCase())
      .filter(Boolean);
  }
  const grouped = await prisma.observedTrade.groupBy({
    by: ["walletAddress"],
    _count: { walletAddress: true },
    orderBy: { _count: { walletAddress: "desc" } },
    take: limit,
  });
  return grouped.map((g) => g.walletAddress.toLowerCase());
}

async function activityPage(address: string, since: number, limit: number): Promise<Record<string, unknown>[]> {
  // Our adapter asks for `type=TRADE` server-side; --unfiltered removes it to
  // measure what a client-side classifier would actually have to drop.
  const typeParam = UNFILTERED ? "" : "&type=TRADE";
  const url = `${VENUE.dataApi}/activity?user=${address}${typeParam}&limit=${limit}&offset=0&start=${since}`;
  const data = await venueGetJson(url);
  if (!Array.isArray(data)) throw new Error(`unexpected activity shape: ${typeof data}`);
  return data as Record<string, unknown>[];
}

async function main(): Promise<number> {
  const wallets = await sampleWallets(WALLETS);
  const since = Math.floor(Date.now() / 1000) - DAYS * 86400;
  log(
    `[print-types] wallets=${wallets.length} source=${USE_LEADERBOARD ? "leaderboard" : "observedTrade"} ` +
      `days=${DAYS} server_type_filter=${UNFILTERED ? "OFF (counterfactual)" : "type=TRADE"} ` +
      `non_trade_types=${[...NON_TRADE_TYPES].join(",")}`
  );

  const report: Record<string, unknown>[] = [];
  let totalRows = 0;
  let totalKept = 0;
  const skippedByType: Record<string, number> = {};
  const unclassified: string[] = [];

  for (const address of wallets) {
    let rows: Record<string, unknown>[] = [];
    try {
      rows = await activityPage(address, since, PAGE);
    } catch (e) {
      logError(`[print-types] ${address} activity failed: ${e instanceof Error ? e.message : e}`);
      continue;
    }
    const filtered = filterTradeRows(rows);
    totalRows += rows.length;
    totalKept += filtered.kept.length;
    for (const [t, n] of Object.entries(filtered.skippedByType)) skippedByType[t] = (skippedByType[t] ?? 0) + n;
    // A row the classifier cannot place is the interesting case: neither a known
    // non-trade nor an accepted fill. Compare lowercased (the API returns
    // `REDEEM`/`CONVERSION`) and against the TYPE SETS, not against
    // `skippedByType` keys — the earlier version compared a raw-case string to
    // lowercased keys, so every skipped row was reported as unclassified and the
    // signal was worthless.
    for (const row of rows) {
      const raw = (row as Record<string, unknown>).type;
      if (!isKnownRowType(raw)) unclassified.push(`${address}:${String(raw ?? "").toLowerCase() || "(empty)"}`);
    }
    report.push({
      auditedAt: new Date().toISOString(),
      address,
      rows: rows.length,
      pageSize: PAGE,
      /** True when the sample hit the page cap, so `rows` is a lower bound. */
      capped: rows.length >= PAGE,
      serverTypeFilter: UNFILTERED ? "off" : "type=TRADE",
      kept: filtered.kept.length,
      skipped: filtered.skipped,
      skippedByType: filtered.skippedByType,
      qualityFlags: filtered.qualityFlags,
      provenance: laggedDataApiProvenance(["activity_endpoint", "print_type_audit"]),
      note: "measurement only — ingest behaviour unchanged",
    });
    log(
      `[print-types] ${address.slice(0, 10)}… rows=${rows.length} kept=${filtered.kept.length} ` +
        `skipped=${filtered.skipped} ${JSON.stringify(filtered.skippedByType)}`
    );
  }

  if (report.length > 0) appendFileSync(OUT, report.map((r) => JSON.stringify(r)).join("\n") + "\n");

  const skipRate = totalRows > 0 ? totalKept / totalRows : 1;
  log(
    `[print-types] TOTAL rows=${totalRows} kept=${totalKept} (${(skipRate * 100).toFixed(1)}% fill-share) ` +
      `skipped=${totalRows - totalKept} ${JSON.stringify(skippedByType)}`
  );
  if (unclassified.length > 0) {
    log(`[print-types] unclassified types seen: ${[...new Set(unclassified)].slice(0, 10).join(", ")}`);
  }
  log(`[print-types] wrote ${report.length} rows -> ${OUT} (no ingest change; decide after this measurement)`);
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    logError(`[print-types] fatal: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  });
