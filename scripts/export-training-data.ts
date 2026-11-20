import { prisma } from "../src/lib/db";
import { Prisma } from "@prisma/client";
import * as fs from "fs";
import {
  dedupeFirstPerPosition,
  eraOf,
  feeDecomposition,
  netTargets,
  outcomeLabel,
  round4,
} from "../src/lib/training-export";
import { localiseFrozenPositions, parseFrozenCsv } from "../src/lib/decision-dataset-drift";

/**
 * ML training-data exporter (Phase 7; re-pointed 2026-10-11, card
 * `ml1-target-net-pnl-and-price-baseline`, user-approved).
 *
 * WHAT CHANGED AND WHY
 * --------------------
 * The target used to be the binary `wasDecisionGood = 1[PnL > 0]` read off `OutcomeReview` — a
 * 688-row / ~1-day / 10-wallet cohort whose `was_good` is force-stamped on skips. The labeled book
 * that actually exists is `PaperTrade JOIN DecisionJournal JOIN ObservedTrade`. Measured on that
 * book (drafts/ml1-target-and-price-baseline-20261011.md): win rate is 57.8% while mean net-entry
 * PnL is +$0.08, and avg winner (+$6.02) is smaller than avg loser (-$5.84) — a win-count target
 * rewards the wrong thing. The export now carries a magnitude target:
 *
 *   pnl_net_entry / y_net_entry   (fee-aware; ex-ante knowable cost)
 *   pnl_gross / pnl_net_full      so the target is auditable and the exit-contamination visible
 *   fee_rate / fee_entry_usd / fee_exit_usd / exit_price
 *
 * Other spec rules applied: `confidence` is NOT emitted (it is 0 by construction on skips, so it
 * encodes decision type, not signal); the mislabeled columns are split — the stored component
 * SCORES keep their `*_score` names and the raw market values get `raw_*` names (the old `ttr_hours`
 * column actually held `entryTimingScore`, and old `spread`/`liquidity` held scores, not raw
 * values); `legacy_was_good` is kept for continuity but is neither the target nor a feature;
 * `y_outcome` (`didOutcomeWin` against the venue's own winning label) ships as the second,
 * where-determinable label.
 *
 * Leakage: every market feature is the latest `MarketSnapshot` collected AT OR BEFORE
 * `PaperTrade.openedAt` for that market (one indexed seek per row), never a post-decision value.
 * Fee model is imported from `src/lib/scoring/price-edge.ts` — the same map
 * `scripts/build-decision-dataset.py` mirrors — so the two artifacts reconcile digit for digit; the
 * script re-reads `data/decision-dataset.manifest.json` and prints that reconciliation on every run.
 *
 * Doctrine: time-ordered + era-aware splits, never random row folds
 * (card ml-doctrine-time-and-era-splits). `decision_at` + `era` + `ruleSetVersion` are the inputs a
 * proper split needs. See also: `pnl_net_entry` is the label for the PROMOTION GATE, whose bar is
 * the price-only baseline on a frozen time-ordered holdout (card `ml1-target-net-pnl-and-price-baseline`).
 */

interface ExportRow {
  paper_trade_id: string;
  bot_id: string;
  venue: string;
  wallet: string;
  market_id: string;
  outcome: string;
  decision: string;
  status: string;
  rule_set_version: number | null;
  era: string;
  decision_at: string;
  /** When the label became KNOWABLE = COALESCE(closedAt, resolvedAt). The split PURGE key.
   *  Already selected as `terminalAt` since the export was written, and dropped on the floor
   *  until 2026-10-19 (card ml1-fit-population-gaps). */
  terminal_at: string | null;
  horizon_to_resolution_hours: number | null;
  pnl_net_entry: number;
  y_net_entry: 0 | 1;
  pnl_gross: number;
  pnl_net_full: number;
  entry_price: number;
  exit_price: number | null;
  fee_rate: number;
  /** 'venue' when the rate came from the venue's own feeSchedule.rate, 'proxy' when keyword-inferred. */
  fee_rate_source: "venue" | "proxy";
  fee_entry_usd: number;
  fee_exit_usd: number;
  detected_price: number | null;
  wallet_entry_price: number | null;
  size_usd: number;
  observed_size_usd: number | null;
  raw_spread: number | null;
  raw_liquidity: number | null;
  raw_volume: number | null;
  wallet_quality_score: number;
  category_fit_score: number;
  entry_timing_score: number;
  spread_score: number;
  liquidity_score: number;
  thesis_score: number;
  copy_score: number;
  /** Sentiment feature, re-derived per decision from the signal corpus (see
   *  scripts/export-sentiment-features.ts). Null = no research category or no signal
   *  coverage; the model must treat null as a distinct state, never as 0. */
  sentiment_n: number | null;
  sentiment_delta_signed: number | null;
  sentiment_delta_50: number | null;
  y_outcome: 0 | 1 | null;
  legacy_was_good: number | null;
  review_id: string | null;
  decision_id: string;
  market_question: string;
}

const COLUMNS: (keyof ExportRow)[] = [
  "review_id", "decision_id", "paper_trade_id", "bot_id", "venue", "wallet", "market_id", "outcome",
  "decision", "status", "rule_set_version", "era", "decision_at", "terminal_at", "horizon_to_resolution_hours",
  "pnl_net_entry", "y_net_entry", "pnl_gross", "pnl_net_full", "entry_price", "exit_price",
  "fee_rate", "fee_rate_source", "fee_entry_usd", "fee_exit_usd",
  "detected_price", "wallet_entry_price", "size_usd", "observed_size_usd",
  "raw_spread", "raw_liquidity", "raw_volume",
  "wallet_quality_score", "category_fit_score", "entry_timing_score",
  "spread_score", "liquidity_score", "thesis_score", "copy_score",
  "sentiment_n", "sentiment_delta_signed", "sentiment_delta_50",
  "y_outcome", "legacy_was_good", "market_question",
];

const num = (v: unknown): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);
const fixed = (v: number | null | undefined, d = 4): string =>
  v === null || v === undefined ? "" : Number(v).toFixed(d);
/** 1.5000 -> "1.5", 20.0000 -> "20" (trailing zeros only, never a significant digit). */
const trim = (s: string): string =>
  s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
/** A question can contain commas; the CSV is unquoted, so mirror the Python's sanitisation. */
const cell = (v: unknown): string => String(v ?? "").replace(/,/g, ";");

/**
 * Target sums for a given set of raw rows — the SAME lib math the export uses (fee decomposition +
 * net targets), applied to another row set, so the reconciliation cannot drift from the exports.
 */
function targetSums(
  rawRows: any[],
  opts: { forceProxyFee?: boolean } = {},
): { rows: number; gross: number; netEntry: number; netFull: number } {
  const dedup = dedupeFirstPerPosition(rawRows);
  let gross = 0;
  let netEntry = 0;
  let netFull = 0;
  for (const r of dedup) {
    const fees = feeDecomposition({
      entryPrice: Number(r.entryPrice),
      sizeUsd: Number(r.simulatedPositionSize ?? 10),
      feeText: `${r.marketQuestion ?? ""} ${r.marketId ?? ""}`,
      // `forceProxyFee` prices the row on the keyword proxy EVEN where the venue's own
      // schedule is known. Only the frozen-baseline reconciliation uses it: that
      // manifest was built on the proxy, so it can only be adjudicated on the proxy.
      feeRateTruth: opts.forceProxyFee ? null : feeRateTruthMap().get(String(r.marketId)) ?? null,
      status: String(r.status),
      currentPrice: num(r.currentPrice),
    });
    const t = netTargets({ realizedPnl: Number(r.realizedPnl), fees });
    gross += round4(Number(r.realizedPnl));
    netEntry += round4(t.pnlNetEntry);
    netFull += round4(t.pnlNetFull);
  }
  return { rows: dedup.length, gross: round4(gross), netEntry: round4(netEntry), netFull: round4(netFull) };
}

/**
 * Sentiment features, produced by scripts/export-sentiment-features.ts and joined on the paper
 * trade id. Absent file = every sentiment column null (the export must still run — the chain
 * order is features → export, and a missing corpus is data, not a crash).
 */
/**
 * The venue's own published fee rate, keyed by market slug, where we have captured it.
 * `categoryFeeRate` infers the rate from TEXT because MarketSnapshot.category is null on every
 * row; the venue publishes `feeType` + `feeSchedule.rate` per market and
 * scripts/capture-fee-schedules.ts already records them to data/fee-schedules.jsonl.
 * Lane A, approved 2026-10-26. Coverage is the open gap: truth exists for 8 of the export's
 * 3,987 markets (3 of those 8 disagree with the proxy), so every row now declares its basis
 * via `fee_rate_source` instead of blending both into one unlabelled column.
 */
function loadFeeRateTruth(path: string): Map<string, number> {
  const out = new Map<string, number>();
  if (!fs.existsSync(path)) {
    console.log(`  fee-rate truth: ${path} not found — every row falls back to the proxy`);
    return out;
  }
  for (const line of fs.readFileSync(path, "utf8").split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const o = JSON.parse(t) as { slug?: unknown; resolvedRate?: unknown; feeSchedule?: { rate?: unknown } };
      const rate = o.resolvedRate ?? o.feeSchedule?.rate;
      if (o.slug && typeof rate === "number" && Number.isFinite(rate)) out.set(String(o.slug), rate);
    } catch {
      /* skip a malformed line rather than failing the export */
    }
  }
  return out;
}

let FEE_RATE_TRUTH: Map<string, number> | null = null;
/** Memoised so `targetSums()` and `main()` share one read of the venue truth file. */
function feeRateTruthMap(): Map<string, number> {
  if (FEE_RATE_TRUTH === null) FEE_RATE_TRUTH = loadFeeRateTruth("data/fee-schedules.jsonl");
  return FEE_RATE_TRUTH;
}

function loadSentimentFeatures(path: string): Map<string, { n: string; dSigned: string; d50: string }> {
  const m = new Map<string, { n: string; dSigned: string; d50: string }>();
  if (!fs.existsSync(path)) {
    console.log(`  sentiment features: ${path} not found — sentiment columns will be null`);
    return m;
  }
  const lines = fs.readFileSync(path, "utf8").trim().split("\n");
  const head = lines[0].split(",");
  const ix = (name: string) => head.indexOf(name);
  const iT = ix("trade_id"), iN = ix("sentiment_n"), iS = ix("sentiment_delta_signed"), i5 = ix("sentiment_delta_50"), iH = ix("has_sentiment");
  let kept = 0;
  for (const l of lines.slice(1)) {
    const c = l.split(",");
    if (c[iH] !== "1") continue;
    m.set(c[iT], { n: c[iN], dSigned: c[iS], d50: c[i5] });
    kept++;
  }
  console.log(`  sentiment features: ${kept} of ${lines.length - 1} trades carry a value`);
  return m;
}

async function main() {
  console.log("Exporting ML training data (magnitude target, decision-book source)...");
  const started = Date.now();
  const sentimentByTrade = loadSentimentFeatures("data/sentiment-features.csv");
  const feeTruth = feeRateTruthMap();
  console.log(
    `  fee-rate truth: ${feeTruth.size} markets carry the venue's own feeSchedule.rate ` +
      `(rows without it fall back to the keyword proxy and are labelled fee_rate_source=proxy)`,
  );

  const raw = await prisma.$queryRaw<any[]>(Prisma.sql`
    SELECT pt.id AS paperTradeId, pt.botId, pt.venue, pt.walletAddress, pt.marketId, pt.outcome,
           pt.entryPrice, pt.currentPrice, pt.simulatedPositionSize, pt.realizedPnl, pt.status,
           pt.openedAt, COALESCE(pt.closedAt, pt.resolvedAt) AS terminalAt, pt.decisionJournalId,
           d.id AS decisionId, d.decision, d.copyScore, d.walletQualityScore,
           d.categoryFitScore, d.entryTimingScore, d.spreadScore, d.liquidityScore, d.thesisScore,
           d.ruleSetVersion, d.simulatedPositionSize AS decisionSize,
           t.marketQuestion, t.detectedPrice, t.walletEntryPrice, t.size AS observedSizeUsd,
           o.id AS reviewId, o.finalOutcome, o.wasDecisionGood,
           s.spread AS rawSpread, s.liquidity AS rawLiquidity, s.timeToResolution AS rawTtr,
           s.volume AS rawVolume, s.collectedAt AS snapshotAt
    FROM PaperTrade pt
    JOIN DecisionJournal d ON d.id = pt.decisionJournalId
    JOIN ObservedTrade t ON t.id = d.observedTradeId
    LEFT JOIN OutcomeReview o ON o.id = (
      SELECT o2.id FROM OutcomeReview o2 WHERE o2.paperTradeId = pt.id
      ORDER BY o2.createdAt DESC LIMIT 1)
    LEFT JOIN MarketSnapshot s ON s.id = (
      SELECT ms.id FROM MarketSnapshot ms
      WHERE ms.marketId = pt.marketId AND ms.collectedAt <= pt.openedAt
      ORDER BY ms.collectedAt DESC LIMIT 1)
    WHERE pt.status IN ('closed','resolved') AND pt.isDemo = 0
      AND pt.realizedPnl IS NOT NULL AND pt.entryPrice > 0 AND pt.entryPrice < 1
    ORDER BY pt.openedAt ASC
  `);

  const rows = dedupeFirstPerPosition(
    raw.map((r) => ({
      botId: String(r.botId),
      walletAddress: String(r.walletAddress),
      marketId: String(r.marketId),
      outcome: String(r.outcome),
      raw: r,
    })),
  );

  const out: ExportRow[] = [];
  const byEra = new Map<string, { n: number; wins: number; net: number }>();
  let noSnapshot = 0;
  let outcomeN = 0;
  let outcomeAgree = 0;

  for (const { raw: r } of rows) {
    const entry = Number(r.entryPrice);
    const size = Number(r.simulatedPositionSize ?? 10);
    const pnl = Number(r.realizedPnl);
    const fees = feeDecomposition({
      entryPrice: entry,
      sizeUsd: size,
      feeText: `${r.marketQuestion ?? ""} ${r.marketId ?? ""}`,
      feeRateTruth: feeRateTruthMap().get(String(r.marketId)) ?? null,
      status: String(r.status),
      currentPrice: num(r.currentPrice),
    });
    const targets = netTargets({ realizedPnl: pnl, fees });
    const yOutcome = outcomeLabel(r.outcome, r.finalOutcome);
    const rsv = r.ruleSetVersion === null || r.ruleSetVersion === undefined ? null : Number(r.ruleSetVersion);
    const sent = sentimentByTrade.get(String(r.paperTradeId));
    const era = eraOf(rsv);
    if (r.rawTtr === null || r.rawTtr === undefined) noSnapshot += 1;
    if (yOutcome !== null) {
      outcomeN += 1;
      if (yOutcome === targets.yNetEntry) outcomeAgree += 1;
    }

    out.push({
      review_id: r.reviewId ?? null,
      decision_id: String(r.decisionId),
      paper_trade_id: String(r.paperTradeId),
      bot_id: String(r.botId),
      venue: String(r.venue),
      wallet: String(r.walletAddress),
      market_id: String(r.marketId),
      outcome: String(r.outcome),
      decision: String(r.decision),
      status: String(r.status),
      rule_set_version: rsv,
      era,
      decision_at: new Date(Number(r.openedAt)).toISOString(),
      terminal_at:
        r.terminalAt === null || r.terminalAt === undefined ? null : new Date(Number(r.terminalAt)).toISOString(),
      horizon_to_resolution_hours: num(r.rawTtr),
      pnl_net_entry: round4(targets.pnlNetEntry),
      y_net_entry: targets.yNetEntry,
      pnl_gross: round4(pnl),
      pnl_net_full: round4(targets.pnlNetFull),
      entry_price: round4(entry),
      exit_price: fees.exitPrice === null ? null : round4(fees.exitPrice),
      fee_rate: fees.feeRate,
      fee_rate_source: fees.feeRateSource,
      fee_entry_usd: round4(fees.feeEntryUsd),
      fee_exit_usd: round4(fees.feeExitUsd),
      detected_price: num(r.detectedPrice),
      wallet_entry_price: num(r.walletEntryPrice),
      size_usd: round4(size),
      observed_size_usd: num(r.observedSizeUsd),
      raw_spread: num(r.rawSpread),
      raw_liquidity: num(r.rawLiquidity),
      raw_volume: num(r.rawVolume),
      wallet_quality_score: round4(Number(r.walletQualityScore)),
      category_fit_score: round4(Number(r.categoryFitScore)),
      entry_timing_score: round4(Number(r.entryTimingScore)),
      spread_score: round4(Number(r.spreadScore)),
      liquidity_score: round4(Number(r.liquidityScore)),
      thesis_score: round4(Number(r.thesisScore)),
      copy_score: round4(Number(r.copyScore)),
      sentiment_n: sent ? num(sent.n) : null,
      sentiment_delta_signed: sent ? num(sent.dSigned) : null,
      sentiment_delta_50: sent ? num(sent.d50) : null,
      y_outcome: yOutcome,
      legacy_was_good: r.wasDecisionGood === null || r.wasDecisionGood === undefined ? null : Number(r.wasDecisionGood),
      market_question: String(r.marketQuestion ?? "").slice(0, 160),
    });

    const e = byEra.get(era) ?? { n: 0, wins: 0, net: 0 };
    e.n += 1;
    e.wins += targets.yNetEntry;
    e.net += targets.pnlNetEntry;
    byEra.set(era, e);
  }

  const lines = [COLUMNS.join(",")];
  for (const row of out) {
    lines.push(
      COLUMNS.map((c) => {
        const v = row[c];
        if (v === null || v === undefined) return "";
        if (c === "market_question") return cell(v);
        if (typeof v === "number") {
          if (c === "fee_rate") return String(v);
          if (c === "rule_set_version") return String(Math.trunc(v));
          if (c === "horizon_to_resolution_hours") return trim(fixed(v, 3));
          return trim(fixed(v, 4));
        }
        return cell(v);
      }).join(","),
    );
  }
  fs.writeFileSync("training_data.csv", lines.join("\n"));

  // ---- report ------------------------------------------------------------------------------
  const sum = (f: (r: ExportRow) => number) => round4(out.reduce((a, r) => a + f(r), 0));
  const gross = sum((r) => r.pnl_gross);
  const netEntry = sum((r) => r.pnl_net_entry);
  const netFull = sum((r) => r.pnl_net_full);
  const wins = out.reduce((a, r) => a + r.y_net_entry, 0);

  console.log(`Exported ${out.length} rows to training_data.csv (raw ${raw.length}, dropped ${raw.length - out.length} duplicate-accumulation rows)`);
  console.log(`  columns: ${COLUMNS.length} | target = pnl_net_entry (regression) + y_net_entry (classification)`);
  console.log(`  target distribution: y_net_entry=1 ${wins}/${out.length} (${((100 * wins) / (out.length || 1)).toFixed(1)}%) | mean pnl_net_entry $${(netEntry / (out.length || 1)).toFixed(3)}`);
  console.log(`  sums: pnl_gross $${gross} | pnl_net_entry $${netEntry} | pnl_net_full $${netFull}`);
  console.log(`  label arms: y_net_entry vs y_outcome — determinable on ${outcomeN}/${out.length} rows (${((100 * outcomeN) / (out.length || 1)).toFixed(1)}%), disagree on ${outcomeN - outcomeAgree} (${(((outcomeN - outcomeAgree) / (outcomeN || 1)) * 100).toFixed(1)}% of those)`);
  console.log(`  market features: ${out.length - noSnapshot} rows carry a prior snapshot, ${noSnapshot} have none (horizon/raw_* blank)`);
  for (const [era, e] of [...byEra.entries()].sort((a, b) => b[1].n - a[1].n)) {
    console.log(`  ${era}: n=${e.n} y_net_entry=1 ${((100 * e.wins) / e.n).toFixed(1)}% meanNetEntry=$${(e.net / e.n).toFixed(3)}`);
  }

  // ---- reconciliation against the frozen Python-built dataset -------------------------------
  // Same fee model, same dedupe, same source — but that artifact saw the book as of its
  // generated_at, so the comparison is made on THAT STATE (`terminal_at <= generated_at`, then the
  // same dedupe), never on a date span alone: positions opened inside its span but settled later
  // belong to today's book, and comparing them would read as drift in the math when it is growth.
  try {
    const m = JSON.parse(fs.readFileSync("data/decision-dataset.manifest.json", "utf8"));
    const asOf = Date.parse(m.generated_at);

    // SCOPE THE COMPARISON TO ROWS THE FROZEN MANIFEST CAN STILL ADJUDICATE (tuning #70 Rec 2, option (b)).
    // The manifest was built entirely on the keyword PROXY fee. The approved fee-truth change (38f8762)
    // then stamped `fee_rate_source=venue` on a growing minority of rows, so any truth-bearing row now
    // disagrees with the frozen baseline BY CONSTRUCTION — which made this check unfalsifiable: it had
    // printed `1 check(s) DRIFTED` on three consecutive EODs (10-26/27/28) at a magnitude of $0.0496 on
    // $168.56, i.e. noise between two correct numbers. A check that cannot pass is the same defect class
    // as a probe that cannot fail.
    // Fix: keep the frozen baseline, reconcile only the proxy rows (which is what it measured), and
    // report the truth-bearing rows SEPARATELY so their movement stays visible instead of silently
    // disabling the check. Regenerating the manifest (option (a)) was rejected — it moves the baseline.
    const dedupAsOf = dedupeFirstPerPosition(
      raw.filter((r) => {
        const t = num(r.terminalAt);
        return t !== null && t <= asOf;
      }),
    );
    // PRICE THE FROZEN WINDOW ON THE FROZEN BASELINE'S OWN BASIS.
    //
    // tuning #70 Rec 2 scoped this check to rows with NO venue fee truth, because a
    // truth-bearing row disagrees with a proxy-built manifest BY CONSTRUCTION. That
    // was right while truth covered 9 markets (35 rows). On 2026-11-20 the fee
    // capture was run across the whole export — 4,387 of 4,397 markets now carry the
    // venue's rate — and the same filter silently swallowed the check: 3,498 of the
    // 3,516 frozen positions became "truth-bearing", the reconciliation ran on 18
    // rows, and it printed DRIFTED because the excluded mass moved out from under it.
    // A check that excludes 99.5% of its population is the same defect as one that
    // cannot pass.
    //
    // So the comparison no longer filters by label: every in-window position is priced
    // on the PROXY (what the manifest measured), and the label-basis figure is printed
    // beside it, with the difference named as the fee-truth effect. Same population,
    // same fee model, falsifiable again.
    const asOfSums = targetSums(dedupAsOf, { forceProxyFee: true });
    const labelledSums = targetSums(dedupAsOf);
    const feeTruthEffect = {
      netEntry: round4(labelledSums.netEntry - asOfSums.netEntry),
      netFull: round4(labelledSums.netFull - asOfSums.netFull),
    };
    const checks: [string, number, number][] = [
      ["rows", Number(m.rows_emitted), asOfSums.rows],
      ["pnl_gross", m.pnl_gross, asOfSums.gross],
      ["pnl_net_entry", m.pnl_net_entry, asOfSums.netEntry],
      ["pnl_net_full", m.pnl_net_full, asOfSums.netFull],
    ];
    console.log(`Reconcile vs data/decision-dataset.manifest.json (generated ${String(m.generated_at).slice(0, 10)}, span ${m.first_day}..${m.last_day}, raw ${m.rows_raw} -> ${m.rows_emitted}):`);
    let drift = 0;
    for (const [k, want, got] of checks) {
      const ok = k === "rows" ? want === got : Math.abs(want - got) < 0.02;
      if (!ok) drift += 1;
      const show = (v: number) => (k === "rows" ? String(v) : `$${v}`);
      console.log(`  ${k}: dataset ${show(want)} vs export ${show(got)} ${ok ? "OK" : "DRIFT"}`);
    }
    // Both bases named, so neither can be mistaken for the other.
    console.log(
      `  fee basis: frozen-window positions priced on the PROXY (the manifest's own model): ${asOfSums.rows} rows, ` +
        `net_entry $${asOfSums.netEntry} | at today's labels (venue truth where captured): net_entry $${labelledSums.netEntry} ` +
        `(fee-truth effect ${feeTruthEffect.netEntry >= 0 ? "+" : ""}$${feeTruthEffect.netEntry}, net_full ` +
        `${feeTruthEffect.netFull >= 0 ? "+" : ""}$${feeTruthEffect.netFull})`,
    );
    // LOCALISATION (card export-reconciliation-localisable, 2026-11-19). The line below used to blame
    // "the fee/target math" for every drift. Measured on this population: the math is unchanged and the
    // DATABASE moved — the 2026-11-11 ledger price-side repair restated 47 of the 3,512 positions that
    // sit inside the frozen window, and their deltas sum to exactly the gross drift printed here. The
    // frozen CSV is per-position, so the attribution is cheap: state it, instead of leaving the next
    // reader to re-derive it (and instead of re-baselining, which would erase the evidence).
    try {
      const { positions: frozenPositions, unparsed: frozenUnparsed } = parseFrozenCsv(
        fs.readFileSync("data/decision-dataset.csv", "utf8"),
      );
      const byId = new Map(out.map((r) => [r.paper_trade_id, r]));
      // The diff is made on the FROZEN model's basis: `out` carries venue rates wherever the
      // capture knows them, so the fee legs and net targets are recomputed at the proxy here.
      // Handing the labelled numbers to the localiser would make every truth-bearing position
      // look like "fee math moved" (and, before 2026-11-20, made it drop them entirely).
      const proxyById = new Map(
        raw.map((r: any) => {
          const fees = feeDecomposition({
            entryPrice: Number(r.entryPrice),
            sizeUsd: Number(r.simulatedPositionSize ?? 10),
            feeText: `${r.marketQuestion ?? ""} ${r.marketId ?? ""}`,
            feeRateTruth: null,
            status: String(r.status),
            currentPrice: num(r.currentPrice),
          });
          const t = netTargets({ realizedPnl: Number(r.realizedPnl), fees });
          return [
            String(r.paperTradeId),
            {
              feeRate: fees.feeRate,
              feeEntryUsd: fees.feeEntryUsd,
              feeExitUsd: fees.feeExitUsd,
              pnlNetEntry: t.pnlNetEntry,
              pnlNetFull: t.pnlNetFull,
            },
          ];
        }),
      );
      const loc = localiseFrozenPositions(
        frozenPositions,
        (id) => {
          const r = byId.get(id);
          if (!r) return null;
          const p = proxyById.get(id);
          return {
            tradeId: id,
            marketId: r.market_id,
            status: r.status,
            entryPrice: r.entry_price,
            sizeUsd: r.size_usd,
            realizedPnl: r.pnl_gross,
            feeRate: p ? p.feeRate : r.fee_rate,
            feeRateSource: r.fee_rate_source,
            feeEntryUsd: p ? p.feeEntryUsd : r.fee_entry_usd,
            feeExitUsd: p ? p.feeExitUsd : r.fee_exit_usd,
            pnlNetEntry: p ? p.pnlNetEntry : r.pnl_net_entry,
            pnlNetFull: p ? p.pnlNetFull : r.pnl_net_full,
          };
        },
        frozenUnparsed,
      );
      console.log(
        `  drift localisation (frozen CSV, level=position): ${loc.summary.moved}/${loc.deltas.length} positions moved — ` +
          `Σ Δgross $${loc.summary.sum.dGross.toFixed(4)}, Σ Δnet_full $${loc.summary.sum.dNetFull.toFixed(4)}, ` +
          `largest single position ${loc.summary.topSharePct.toFixed(1)}% of Σ|Δnet_full|` +
          (loc.summary.moved > 0 ? " — reproduce: npm run export:drift-localise" : ""),
      );
    } catch {
      console.log("  drift localisation: data/decision-dataset.csv unreadable — skipped");
    }
    console.log(drift === 0
      ? `  reconciliation: IDENTICAL on the frozen window — today's file adds ${out.length - asOfSums.rows} positions settled since ${String(m.generated_at).slice(0, 10)}`
      : `  reconciliation: ${drift} check(s) DRIFTED on the proxy rows — the frozen baseline's SUMS no longer` +
        ` match today's book. That is a DATA movement, not a math disagreement: the localisation line names` +
        ` the positions. Re-baselining is refused because it would erase the evidence (card export-reconciliation-localisable).`);
  } catch {
    console.log("Reconcile: data/decision-dataset.manifest.json not readable — skipped");
  }
  console.log(`  reproduce: npx tsx scripts/export-training-data.ts   (${Date.now() - started} ms)`);
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect());
