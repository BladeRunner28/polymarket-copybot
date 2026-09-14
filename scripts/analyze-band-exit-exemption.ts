/**
 * band-exit-exemption — COUNTERFACTUAL measurement for the 2026-09-13 daily
 * report Change 2 (user-approved): should <0.20 C-200 entries be exempt from the
 * tier-1 / 168h-hard-age exits?
 *
 * The report's claim (all-time, raw rows): the <0.20 band returns +3.2% on
 * rule-closed tickets vs +119.5% on naturally-resolved ones, and every other
 * band shows the same closed-vs-resolved split. The caveat, stated in the report
 * and repeated in the output: that gap is partly SURVIVORSHIP — the rule cuts the
 * positions that are not working. This script does not assume the gap is real; it
 * prices each cut ticket at what it would actually have been worth if held.
 *
 * Two counterfactuals, because they answer different questions:
 *   1. HOLD-TO-HORIZON (primary): the token price at +24h / +72h / +168h after
 *      the cut, from data/exit-recovery.jsonl. This is the answerable question —
 *      most long-dated <0.20 markets (LPL season, MLS cup, UCL winner) do not
 *      settle for months, so "hold to settlement" is not a number we can have,
 *      and holding them that long is the capital-lock risk itself.
 *   2. HOLD-TO-SETTLEMENT (secondary): the token's 0/1 value, from the market's
 *      own resolution (adapter / event fallback) or exit-recovery's `final` mark.
 *
 * Decision-level sample: one row per market+outcome (duplicate accumulation rows
 * are pseudo-replication and inflate every statistic).
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/analyze-band-exit-exemption.ts
 *      ... --since 2026-09-13 --band-max 0.20
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { fetchEventResolution } from "../src/lib/dead-market-resolution";
import { log } from "../src/lib/redact";
import * as fs from "fs";
import { join } from "path";

const EXIT_RECOVERY_LOG = join(__dirname, "..", "data", "exit-recovery.jsonl");
const OUT = join(__dirname, "..", "data", "band-exit-exemption.json");

const HARD_AGE_HOURS = 168;
const HORIZONS = ["1h", "6h", "24h", "72h", "168h"];
const BUCKET_RANK = [...HORIZONS, "final"];

/** tradeId -> bucket -> tokenPrice (keeps the newest mark per bucket). */
function readMarks(): Map<string, Map<string, number>> {
  const out = new Map<string, Map<string, number>>();
  let raw = "";
  try {
    raw = fs.readFileSync(EXIT_RECOVERY_LOG, "utf8");
  } catch {
    return out;
  }
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    let r: any;
    try {
      r = JSON.parse(line);
    } catch {
      continue;
    }
    if (r.type !== "mark" || typeof r.tokenPrice !== "number") continue;
    if (!out.has(r.tradeId)) out.set(r.tradeId, new Map());
    out.get(r.tradeId)!.set(r.bucket, r.tokenPrice);
  }
  return out;
}

function arg(name: string, def?: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

async function main() {
  const botId = arg("bot", "BANKROLL_200")!;
  const bandMax = Number(arg("band-max", "0.20"));
  const since = arg("since", undefined);
  const sinceMs = since ? new Date(`${since}T00:00:00-04:00`).getTime() : null;

  const trades = await prisma.paperTrade.findMany({
    where: {
      botId,
      isDemo: false,
      venue: { not: "Kalshi" },
      entryPrice: { lt: bandMax },
      status: { in: ["closed", "resolved"] },
      realizedPnl: { not: null },
      ...(sinceMs ? { openedAt: { gte: new Date(sinceMs) } } : {}),
    },
    orderBy: { openedAt: "asc" },
  });

  const seen = new Set<string>();
  const decisions = trades.filter((t) => {
    const k = `${t.marketId}|${t.outcome}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });

  const marks = readMarks();
  const adapter = getAdapter();
  const resolutionCache = new Map<string, number | undefined>();

  const rows: any[] = [];
  const agg: Record<string, { n: number; realized: number; cf: Record<string, number>; cfN: Record<string, number> }> = {};
  const bump = (kind: string) =>
    (agg[kind] ??= { n: 0, realized: 0, cf: Object.fromEntries(BUCKET_RANK.map((b) => [b, 0])), cfN: Object.fromEntries(BUCKET_RANK.map((b) => [b, 0])) });

  for (const t of decisions) {
    const stake = t.simulatedPositionSize;
    const exitAt = t.resolvedAt ?? t.closedAt;
    const ageHours = exitAt ? (exitAt.getTime() - t.openedAt.getTime()) / 3_600_000 : null;
    const kind =
      t.status === "resolved" ? "resolved" : ageHours !== null && ageHours >= HARD_AGE_HOURS ? "hard_max_age" : "tier1_cut";

    const mark = marks.get(t.id);
    const cfPnl = (value: number) => Math.round(((value - t.entryPrice) / t.entryPrice) * stake * 100) / 100;

    // Settlement value: own resolution for `resolved` rows, else the market's.
    let settlement: number | undefined;
    let settlementSource = "none";
    if (t.status === "resolved") {
      settlement = (t.realizedPnl ?? 0) > 0 ? 1 : 0;
      settlementSource = "own-resolution";
    } else {
      if (!resolutionCache.has(t.marketId)) {
        let v: number | undefined;
        try {
          const m = await adapter.fetchMarket(t.marketId);
          if (m.resolved && m.winningOutcome) v = m.winningOutcome === t.outcome ? 1 : 0;
        } catch {
          /* fall through */
        }
        if (v === undefined) {
          try {
            const ev = await fetchEventResolution(t.marketId);
            if (ev) v = ev === t.outcome ? 1 : 0;
          } catch {
            /* leave undefined */
          }
        }
        resolutionCache.set(t.marketId, v);
      }
      settlement = resolutionCache.get(t.marketId);
      if (settlement !== undefined) settlementSource = "market-settlement";
      else if (mark?.has("final")) {
        settlement = mark.get("final");
        settlementSource = "exit-recovery:final";
      }
    }

    const a = bump(kind);
    a.n++;
    const realized = t.realizedPnl ?? 0;
    a.realized += realized;

    const cfByBucket: Record<string, number | null> = {};
    for (const b of HORIZONS) {
      const v = mark?.get(b);
      cfByBucket[b] = v === undefined ? null : cfPnl(v);
      if (v !== undefined) {
        a.cf[b] += cfByBucket[b]!;
        a.cfN[b]++;
      }
    }
    const cfSettlement = settlement === undefined ? null : cfPnl(settlement);
    if (cfSettlement !== null) {
      a.cf["final"] += cfSettlement;
      a.cfN["final"]++;
    }

    rows.push({
      tradeId: t.id,
      marketId: t.marketId,
      entryPrice: t.entryPrice,
      stakeUsd: stake,
      kind,
      ageHours: ageHours === null ? null : Math.round(ageHours * 10) / 10,
      realizedPnl: realized,
      counterfactualByHorizon: cfByBucket,
      settlementValue: settlement ?? null,
      settlementSource,
      counterfactualSettlement: cfSettlement,
    });
  }

  const round = (o: Record<string, number>) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, Math.round(v * 100) / 100]));
  const byKindOut = Object.fromEntries(
    Object.entries(agg).map(([k, v]) => [
      k,
      { n: v.n, realizedPnl: Math.round(v.realized * 100) / 100, counterfactualPnl: round(v.cf), pricedCount: v.cfN },
    ])
  );

  const cuts = agg["tier1_cut"];
  const summary = {
    generatedAt: new Date().toISOString(),
    botId,
    bandMax,
    since: since ?? "all-time",
    rawRows: trades.length,
    decisions: decisions.length,
    dedupeCollapsed: trades.length - decisions.length,
    exitRecoveryTrades: marks.size,
    byExitKind: byKindOut,
    headline: cuts
      ? {
          tier1Cuts: cuts.n,
          realizedPnl: Math.round(cuts.realized * 100) / 100,
          hold24hPnl: Math.round(cuts.cf["24h"] * 100) / 100,
          hold24hPriced: cuts.cfN["24h"],
          hold72hPnl: Math.round(cuts.cf["72h"] * 100) / 100,
          hold72hPriced: cuts.cfN["72h"],
          hold168hPnl: Math.round(cuts.cf["168h"] * 100) / 100,
          hold168hPriced: cuts.cfN["168h"],
          settlementPnl: Math.round(cuts.cf["final"] * 100) / 100,
          settlementPriced: cuts.cfN["final"],
        }
      : null,
    caveat:
      "Survivorship: the rule cuts positions that are not working, so closed-vs-resolved gaps overstate the case for holding. Hold-to-horizon marks answer 'did the cut tickets recover inside the horizon we would actually have held' — that is the decision metric. Guarantee rule: read only buckets with >= 20 priced tickets and >= 7 days of accumulation; anything less is noise.",
    rows,
  };
  fs.writeFileSync(OUT, JSON.stringify(summary, null, 2));

  const f = (v: number) => (v >= 0 ? `+$${v.toFixed(2)}` : `-$${Math.abs(v).toFixed(2)}`);
  log(`band-exit-exemption (${botId}, entry < ${bandMax}, ${since ?? "all-time"}) — decision-level n=${decisions.length} (raw ${trades.length})`);
  for (const [k, v] of Object.entries(byKindOut) as any) {
    const cf = v.counterfactualPnl;
    log(
      `  [${k}] n=${v.n} realized ${f(v.realizedPnl)} | ` +
        HORIZONS.map((b) => `${b} ${v.pricedCount[b] ? `${f(cf[b])} (n=${v.pricedCount[b]})` : "—"}`).join("  ") +
        ` | settle ${v.pricedCount.final ? `${f(cf.final)} (n=${v.pricedCount.final})` : "—"}`
    );
  }
  log(`  wrote ${OUT}`);
  process.exit(0);
}

main().catch((e) => {
  log(`band-exit-exemption FAILED: ${e instanceof Error ? e.message : e}`);
  process.exit(1);
});
