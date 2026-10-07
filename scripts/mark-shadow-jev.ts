/**
 * shadow:jev-mark — the Jev shadow lane's marker + collector (Option B of
 * `drafts/jev-rag-copybot.md`, user-approved 2026-10-06; write-only instrumentation).
 *
 * What it does, in order:
 *   1. prints the call configuration (the lane is DEFAULT OFF and has no default endpoint),
 *   2. COLLECTS the leg population from the DB (every scored leg in the window, not just the
 *      copies), builds the typed state we would send to Jev, and logs one `candidate` row per
 *      leg to data/jev-shadow.jsonl — with the model arm null until a call is configured,
 *   3. when a call IS configured, asks Jev (openrouter Decisions API, model from JEV_MODEL)
 *      and stores its probability/confidence/action + latency on the same row,
 *   4. marks pending candidates to settlement (adapter, then the event-resolution fallback,
 *      label-aware via didOutcomeWin — never the old YES/NO guess),
 *   5. re-summarises: Brier/AUC/log-loss for the PRICE arm and the JEV arm on the same rows,
 *      plus the counterfactual gate (kept vs vetoed vs copy-all, net of fee), and writes
 *      data/jev-shadow-summary.json.
 *
 * Modes:
 *   npx tsx scripts/mark-shadow-jev.ts --dry-run    # print ONE state, write nothing (safe default when off)
 *   npx tsx scripts/mark-shadow-jev.ts --collect    # states only, no model calls (starts the corpus)
 *   JEV_SHADOW=1 JEV_ENDPOINT=... OPENROUTER_API_KEY=... npx tsx scripts/mark-shadow-jev.ts
 *
 * The price arm is the DETECTION MID (`ObservedTrade.detectedPrice`), which is the market's own
 * implied probability at the moment the lane fired — the honest baseline. It is deliberately NOT
 * the C-200 booked entry (`mid − 2¢`, sidecar maker fill): comparing a model against a fill
 * improvement would credit the model with the fill model. Both are stored on every row.
 */

import { getAdapter } from "../src/lib/adapters";
import { fetchEventResolution } from "../src/lib/dead-market-resolution";
import { prisma } from "../src/lib/db";
import { didOutcomeWin } from "../src/lib/resolution";
import { log, logError } from "../src/lib/redact";
import * as fs from "fs";
import {
  appendJevRows,
  buildCandidateRow,
  buildJevQuestions,
  buildJevState,
  jevCallConfig,
  readJevRows,
  summarizeJev,
  JEV_SHADOW_FILE,
  JEV_SHADOW_SUMMARY_FILE,
  parseJevDecision,
  type JevDecision,
  type JevLeg,
  type JevShadowRow,
} from "../src/lib/shadow-jev";

const COLLECT_LIMIT = Number(process.env.JEV_COLLECT_LIMIT ?? 200);
const WINDOW_HOURS = Number(process.env.JEV_WINDOW_HOURS ?? 24);
const RESOLVE_LIMIT = Number(process.env.MARK_LIMIT ?? 300);
const CALL_TIMEOUT_MS = Number(process.env.JEV_TIMEOUT_MS ?? 8000);
/** Cap on replaying stored states through the model per run, so a backlog drains steadily. */
const BACKFILL_LIMIT = Number(process.env.JEV_BACKFILL_LIMIT ?? 100);

const DRY = process.argv.includes("--dry-run");
const COLLECT = process.argv.includes("--collect");

/** The market snapshot the scorer could have seen at detection (spread/liquidity/TTR come
 *  from here — a state without market microstructure under-sells the model by construction). */
async function snapshotFor(marketId: string, at: Date) {
  const before = await prisma.marketSnapshot.findFirst({
    where: { marketId, isDemo: false, collectedAt: { lte: at } },
    orderBy: { collectedAt: "desc" },
  });
  if (before) return before;
  return prisma.marketSnapshot.findFirst({ where: { marketId, isDemo: false }, orderBy: { collectedAt: "desc" } });
}

/** Legs the scorer actually evaluated in the window. Excludes observation-only rows. */
async function collectLegs(max: number): Promise<JevLeg[]> {
  const since = new Date(Date.now() - WINDOW_HOURS * 3600 * 1000);
  const rows = await prisma.decisionJournal.findMany({
    where: { createdAt: { gte: since }, isDemo: false, observedTrade: { observationOnly: false } },
    orderBy: { createdAt: "desc" },
    take: max,
    include: { observedTrade: true, paperTrades: true },
  });
  const legs: JevLeg[] = [];
  for (const d of rows) {
    const o = d.observedTrade;
    if (!o) continue;
    // the detection mid IS the market-implied probability we score against
    const price = o.detectedPrice > 0 ? o.detectedPrice : o.walletEntryPrice;
    if (!(price > 0 && price < 1)) continue;
    const booked = d.paperTrades.length ? d.paperTrades[0].entryPrice : null;
    const snap = await snapshotFor(d.marketId, d.createdAt);
    legs.push({
      decisionJournalId: d.id,
      marketId: d.marketId,
      outcome: o.outcome,
      side: o.side,
      walletAddress: d.walletAddress,
      entryPrice: price,
      bookedEntryPrice: booked,
      detectedPrice: o.detectedPrice,
      walletEntryPrice: o.walletEntryPrice,
      spread: snap?.spread ?? null,
      liquidity: snap?.liquidity ?? null,
      ttrHours: snap?.timeToResolution ?? null,
      copyScore: d.adjustedCopyScore ?? d.copyScore,
      confidence: d.rawConfidence ?? d.confidence,
      liveDecision: d.decision,
      lane: d.paperTrades.length ? d.paperTrades[0].botId : null,
      marketQuestion: o.marketQuestion,
      marketCategory: o.marketCategoryFine ?? o.marketCategoryClass ?? o.marketCategory ?? null,
      ruleSetVersion: d.ruleSetVersion ?? null,
    });
  }
  return legs;
}

/** One Jev call. The shape is asserted from evidence, never assumed: a payload we cannot
 *  parse stores the RAW response on the row instead of an invented probability. */
async function callJev(
  leg: JevLeg,
  cfg: { endpoint: string | null; model: string }
): Promise<{ decision: JevDecision | null; latencyMs: number; error: string | null; raw: unknown }> {
  const url = cfg.endpoint as string;
  const key = process.env.OPENROUTER_API_KEY ?? process.env.JEV_API_KEY ?? "";
  const body = { model: cfg.model, state: buildJevState(leg), questions: buildJevQuestions(leg) };
  const t0 = Date.now();
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), CALL_TIMEOUT_MS);
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      body: JSON.stringify(body),
      signal: ctl.signal,
    });
    clearTimeout(timer);
    const latencyMs = Date.now() - t0;
    const text = await res.text();
    let raw: unknown = null;
    try {
      raw = JSON.parse(text);
    } catch {
      raw = { unparsed: text.slice(0, 2000) };
    }
    if (!res.ok) return { decision: null, latencyMs, error: `HTTP ${res.status}`, raw };
    const decision = parseJevDecision(raw);
    if (decision.probability === null && decision.action === null) {
      return { decision: null, latencyMs, error: "unparsed payload shape", raw };
    }
    return { decision, latencyMs, error: null, raw };
  } catch (e) {
    return {
      decision: null,
      latencyMs: Date.now() - t0,
      error: e instanceof Error ? `${e.name}: ${e.message}` : String(e),
      raw: null,
    };
  }
}

async function main() {
  const cfg = jevCallConfig();
  log(
    `shadow-jev: canCall=${cfg.canCall} (${cfg.reason}); model=${cfg.model}; ` +
      `endpoint=${cfg.endpoint ?? "UNSET"}; file=${JEV_SHADOW_FILE}`
  );

  const existing = readJevRows();
  const seen = new Set(existing.map((r) => `${r.decisionJournalId}|${r.marketId}|${r.outcome}`));

  if (DRY) {
    const sample = (await collectLegs(1))[0];
    if (!sample) {
      log("shadow-jev --dry-run: no scored legs in the window; nothing to show (wrote nothing).");
      return;
    }
    log(`shadow-jev --dry-run state (wrote nothing): ${JSON.stringify(buildJevState(sample))}`);
    log(`shadow-jev --dry-run questions: ${JSON.stringify(buildJevQuestions(sample))}`);
    return;
  }

  if (cfg.canCall || COLLECT) {
    const legs = await collectLegs(COLLECT_LIMIT);
    const fresh = legs.filter((l) => !seen.has(`${l.decisionJournalId}|${l.marketId}|${l.outcome}`));
    log(
      `shadow-jev: ${legs.length} scored legs in the last ${WINDOW_HOURS}h, ${fresh.length} not yet logged` +
        (cfg.canCall ? " — calling the model for each." : " — states only (no call configured).")
    );
    let called = 0;
    let failed = 0;
    const rows: JevShadowRow[] = [];
    for (const leg of fresh) {
      if (cfg.canCall) {
        const r = await callJev(leg, cfg);
        if (r.decision) called++;
        else failed++;
        rows.push(
          buildCandidateRow(leg, r.decision, {
            model: cfg.model,
            latencyMs: r.latencyMs,
            error: r.error,
            raw: r.raw,
          })
        );
      } else {
        rows.push(buildCandidateRow(leg, null, { model: cfg.model, latencyMs: null }));
      }
    }
    appendJevRows(rows);
    if (cfg.canCall) {
      log(`shadow-jev: ${called} responses parsed, ${failed} failed (raw payload kept on the row).`);
    } else {
      log(`shadow-jev: appended ${rows.length} state-only rows (model arm null until JEV_SHADOW=1).`);
    }

    // BACKFILL the model arm onto rows collected while the lane was off. Without this a
    // state-only row is skipped as "seen" forever and the corpus seeded today can never
    // carry a probability — the states are stored precisely so they can be replayed.
    if (cfg.canCall) {
      const need = readJevRows()
        .filter((r) => r.type === "candidate" && (r.jevProbability === null || r.jevProbability === undefined))
        .slice(0, BACKFILL_LIMIT);
      if (need.length) {
        const back: JevShadowRow[] = [];
        let bOk = 0;
        for (const r of need) {
          const reconstructed: JevLeg = {
            decisionJournalId: (r.decisionJournalId as string) ?? null,
            marketId: String(r.marketId),
            outcome: String(r.outcome),
            side: String(r.side),
            walletAddress: String(r.wallet),
            entryPrice: Number(r.entryPrice),
            bookedEntryPrice: (r.bookedEntryPrice as number) ?? null,
            detectedPrice: (r.detectedPrice as number) ?? null,
            walletEntryPrice: (r.walletEntryPrice as number) ?? null,
            spread: (r.spread as number) ?? null,
            liquidity: (r.liquidity as number) ?? null,
            ttrHours: (r.ttrHours as number) ?? null,
            copyScore: Number(r.copyScore),
            confidence: Number(r.confidence),
            liveDecision: String(r.liveDecision),
            lane: (r.lane as string) ?? null,
            marketQuestion: (r.marketQuestion as string) ?? null,
            marketCategory: (r.marketCategory as string) ?? null,
            ruleSetVersion: (r.ruleSetVersion as number) ?? null,
          };
          const res = await callJev(reconstructed, cfg);
          if (res.decision) bOk++;
          back.push(
            buildCandidateRow(reconstructed, res.decision, {
              model: cfg.model,
              latencyMs: res.latencyMs,
              error: res.error,
              raw: res.raw,
            })
          );
        }
        appendJevRows(back);
        log(`shadow-jev: backfilled ${bOk}/${need.length} state-only rows with a model arm.`);
      }
    }
  } else {
    log("shadow-jev: lane is off (JEV_SHADOW != 1) — pass --collect to seed states, --dry-run to preview.");
  }

  // ---- mark pending candidates to settlement --------------------------------
  const rows = readJevRows();
  const candidates = rows.filter((r) => r.type === "candidate");
  const resolves = new Set(rows.filter((r) => r.type === "resolve").map((r) => `${r.marketId}|${r.outcome}`));
  const pending = new Map<string, { marketId: string; outcome: string }>();
  for (const c of candidates) {
    const key = `${c.marketId}|${c.outcome}`;
    if (!resolves.has(key)) pending.set(key, { marketId: String(c.marketId), outcome: String(c.outcome) });
  }
  const adapter = getAdapter();
  let markedNow = 0;
  for (const { marketId, outcome } of [...pending.values()].slice(0, RESOLVE_LIMIT)) {
    let value: number | undefined;
    try {
      const m = await adapter.fetchMarket(marketId);
      const winnerLabel = m.winningLabel ?? m.winningOutcome;
      if (m.resolved && winnerLabel) {
        const won = didOutcomeWin(outcome, { winningLabel: winnerLabel, yesPrice: m.yesPrice });
        if (won !== null) value = won ? 1 : 0;
      }
    } catch {
      /* fall through to the event-resolution path */
    }
    if (value === undefined) {
      try {
        const ev = await fetchEventResolution(marketId);
        if (ev) {
          const won = didOutcomeWin(outcome, { winningLabel: ev });
          if (won !== null) value = won ? 1 : 0;
        }
      } catch {
        /* leave unresolved */
      }
    }
    if (value === undefined) continue;
    fs.appendFileSync(
      JEV_SHADOW_FILE,
      JSON.stringify({ ts: new Date().toISOString(), type: "resolve", marketId, outcome, value }) + "\n"
    );
    markedNow++;
  }

  const summary = summarizeJev(readJevRows());
  fs.writeFileSync(JEV_SHADOW_SUMMARY_FILE, JSON.stringify(summary, null, 2));
  const fmt = (v: number | null, d = 4): string => (v === null ? "—" : v.toFixed(d));
  log(
    `shadow-jev: +${markedNow} marked (backlog ${pending.size}), ${summary.candidates} candidates, ` +
      `${summary.resolved} resolved (${summary.resolvedWithModel} with a model arm). ` +
      `PRICE arm n=${summary.priceOnly.n} AUC ${fmt(summary.priceOnly.auc, 3)} Brier ${fmt(summary.priceOnly.brier)} | ` +
      `JEV arm n=${summary.jev.n} AUC ${fmt(summary.jev.auc, 3)} Brier ${fmt(summary.jev.brier)} | ` +
      `copyScore AUC ${fmt(summary.copyScore.auc, 3)}. ` +
      `Gate @${summary.gate.threshold}: kept ${summary.gate.keptN} legs net/leg ${fmt(summary.gate.keptMeanPnlPerStakeNetOfFee, 4)} vs ` +
      `copy-all ${fmt(summary.gate.copyAllMeanPnlPerStakeNetOfFee, 4)} (vetoed ${summary.gate.vetoedN} legs, ` +
      `net/leg ${fmt(summary.gate.vetoedMeanPnlPerStakeNetOfFee, 4)} — a veto count is not a cost). ` +
      `Bar readable: ${summary.barReadable} (n>=50 with a model arm); beatsPriceOnly=${summary.beatsPriceOnly}. ` +
      `Summary: ${JEV_SHADOW_SUMMARY_FILE}`
  );
}

main()
  .catch((e) => {
    logError("shadow:jev-mark FAILED:", e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect().catch(() => undefined);
    process.exit(0);
  });
