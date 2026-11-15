/**
 * review:outcomes — judge past decisions. For each decision without a final
 * review, check whether the market resolved and record whether the decision
 * was good (copied winners / skipped losers) plus lessons learned.
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { computePnl } from "../src/lib/paper";
import { didOutcomeWin } from "../src/lib/resolution";
import { log, logError } from "../src/lib/redact";
import { type HorizonRead } from "../src/lib/decision-provenance";
import { horizonPricesFor } from "../src/lib/clob-horizon";

const HYPOTHETICAL_SIZE = 10;
const CLOB_API = "https://clob.polymarket.com";

/**
 * data2-per-decision-provenance (2026-11-14, Lane B): the horizon prices.
 *
 * OutcomeReview.priceAfter1h/6h/24h shipped in the schema and then had NO writer
 * and NO reader anywhere in the repo (verified 2026-11-14: 11,774 rows, 0 populated).
 * A binary label was all that existed, so nothing downstream could learn timing.
 *
 * BASIS: the venue's own fill tape for the token the decision HELD, via CLOB
 * /prices-history (keyless), window [decidedAt, decidedAt+24h], fidelity 1 minute.
 * The value written is the LAST print at or before the horizon within 90 minutes
 * (src/lib/decision-provenance.ts owns that rule, so writer and probe cannot
 * disagree); a print exactly at 0 or 1 is the settlement mark, not a horizon price,
 * and is recorded as NULL rather than as a certainty. NULL therefore always means
 * "the tape cannot say", never "zero".
 *
 * NOT usable as the basis: our own MarketSnapshot table. Measured on 400 decisions
 * (14d to 2026-11-14T02:00Z): a snapshot within +/-20min of +1h exists for 21.0%,
 * +6h for 5.5%, +24h for 0.0% — the snapshot writer bursts and never revisits.
 */
/**
 * Resolve archived markets via the CLOB API. Gamma 404s dead/renamed slugs
 * (the root cause of the empty OutcomeReview table), but CLOB keeps every
 * market by conditionId with a per-token `winner` flag — keyless, read-only.
 */
async function fetchResolvedViaClob(conditionId: string | null) {
  if (!conditionId) return null;
  const res = await fetch(
    `${CLOB_API}/markets/${encodeURIComponent(conditionId)}`,
    {
      headers: { accept: "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)" },
      signal: AbortSignal.timeout(15000),
    }
  );
  if (!res.ok) throw new Error(`clob ${res.status}`);
  const m = (await res.json()) as {
    closed?: boolean;
    tokens?: Array<{ outcome: string; winner: boolean }>;
  };
  if (!m.closed) return null;
  const winner = (m.tokens ?? []).find((t) => t.winner === true);
  return winner ? { resolved: true as const, winningOutcome: winner.outcome } : null;
}

async function main() {
  const adapter = getAdapter();
  // 2026-09-15 tuning review #26 rec 3 (user-approved): SELECTION FIX.
  //
  // The old selection (orderBy decision asc, take 200) returned the SAME 200
  // oldest pending copy decisions every night — all created 2026-07-15
  // (long-dated markets such as will-…-ballon-dor…), of which only 34/200 had a
  // resolved leg. The loop then found nothing new to judge, so labels froze
  // (688 for four days, 3 consecutive EOD runs at "0 judged") while 8,475 copy
  // decisions WITH a settled leg sat unreviewed behind that head-of-line block.
  //
  // A decision with a settled leg is provably reviewable, so page those first by
  // recency; fall back to the broad pending set (also by recency) so
  // watchlist/skip rows still accrue hypothetical labels.
  const REVIEW_TAKE = Number(process.env.REVIEW_TAKE ?? 300);
  // tuning review #66 Rec 1 (user-approved 2026-10-26): page RESOLVED legs first.
  //
  // The old selection ordered by createdAt desc over legs with status in
  // ["resolved","closed"] and took 300. v66's 701-leg stale exit (2026-10-24) flipped
  // ~700 STANDARD legs to `closed` -- an EARLY EXIT, not a natural settlement -- so those
  // decisions entered the window on a leg whose market had never resolved. 297 of the
  // newest 300 were that cohort (233 of them at the 02:06 tick), and a decision whose
  // market has not resolved cannot be judged. Labels fell 115/night -> 3 while **901
  // decisions that DO hold a resolved leg sat stranded behind them**.
  //
  // Two pages instead: resolved first (the judgeable population), early-closed second and
  // CAPPED, so an exit wave can never own the head of the queue again. Early-closed rows
  // still accrue labels -- they are simply no longer allowed to crowd out rows that can
  // actually be judged. The `[REVIEW-POOL]` line prints both, so the next starvation is
  // visible in one grep instead of inferred from a falling label count seven days later.
  const baseWhere = {
    outcomeReviews: { none: { finalOutcome: { not: null } } },
    ...(adapter.isDemo ? {} : { isDemo: false }),
  };
  const resolvedLegWhere = { ...baseWhere, paperTrades: { some: { status: "resolved" } } };
  const closedOnlyWhere = {
    ...baseWhere,
    paperTrades: { some: { status: "closed" }, none: { status: "resolved" } },
  };
  const CLOSED_TAKE = Number(process.env.REVIEW_CLOSED_TAKE ?? 50);

  const resolvedPool = await prisma.decisionJournal.findMany({
    where: resolvedLegWhere,
    include: { observedTrade: true, paperTrades: true },
    orderBy: { createdAt: "desc" },
    take: REVIEW_TAKE,
  });
  const settledCandidates = await prisma.decisionJournal.count({ where: resolvedLegWhere });
  // Only spend the second page if the first did not fill -- a healthy resolved pool means
  // the early-closed rows never enter the window at all.
  const closedPool =
    resolvedPool.length < REVIEW_TAKE
      ? await prisma.decisionJournal.findMany({
          where: closedOnlyWhere,
          include: { observedTrade: true, paperTrades: true },
          orderBy: { createdAt: "desc" },
          take: Math.min(CLOSED_TAKE, REVIEW_TAKE - resolvedPool.length),
        })
      : [];
  const closedCandidates = await prisma.decisionJournal.count({ where: closedOnlyWhere });
  let pending = [...resolvedPool, ...closedPool];
  log(
    `[REVIEW-POOL] resolved-leg pool: ${resolvedPool.length}/${REVIEW_TAKE} taken ` +
      `(${settledCandidates} candidates awaiting review); early-closed pool: ` +
      `${closedPool.length}/${CLOSED_TAKE} taken (${closedCandidates} candidates)`,
  );

  // 2026-09-17 tuning review #28 rec 1 (user-approved): price the GATE's cost.
  // `watchlist` decisions never open a leg (the risk gates fire before booking),
  // so the settled-leg selection above can never see them — the drawdown gate
  // alone blocked 459 of them in #28 and its cost was therefore unmeasurable
  // (0 watchlist labels ever). They are judged on the MARKET outcome instead
  // (the loop already does this for non-copy decisions).
  //
  // Starvation guard: oldest-first, but floored at 30 days. Oldest-first is
  // self-clearing (an older market is likelier to have settled, and the frontier
  // advances as they do); the 30-day floor is what stops the July-era long-dated
  // rows from rebuilding the head-of-line block that #26 rec 3 fixed.
  const WATCH_TAKE = Number(process.env.WATCH_TAKE ?? 100);
  const watchFloor = new Date(Date.now() - 30 * 86_400_000);
  const watchCeil = new Date(Date.now() - 2 * 3_600_000);
  const watchWhere = {
    outcomeReviews: { none: { finalOutcome: { not: null } } },
    ...(adapter.isDemo ? {} : { isDemo: false }),
    decision: "watchlist",
    createdAt: { gte: watchFloor, lte: watchCeil },
  };
  const watchCandidates = await prisma.decisionJournal.count({ where: watchWhere });
  const watchPool = await prisma.decisionJournal.findMany({
    where: watchWhere,
    include: { observedTrade: true, paperTrades: true },
    orderBy: { createdAt: "asc" },
    take: WATCH_TAKE,
  });
  if (pending.length === 0) {
    const fallback = await prisma.decisionJournal.findMany({
      where: {
        outcomeReviews: { none: { finalOutcome: { not: null } } },
        ...(adapter.isDemo ? {} : { isDemo: false }),
      },
      include: { observedTrade: true, paperTrades: true },
      orderBy: { createdAt: "desc" },
      take: REVIEW_TAKE,
    });
    if (fallback.length === 0) {
      log("No decisions awaiting outcome review.");
      return;
    }
    log(`No settled-leg candidates — falling back to the most recent ${fallback.length} pending decisions.`);
    for (const f of fallback) pending.push(f);
  }
  for (const w of watchPool) pending.push(w);

  // tuning #65 Rec 1 (user-approved 2026-10-24): a blank marketId can NEVER be reviewed.
  // Polymarket's AND-parlay legs carry no slug, so /markets/slug/ 404s and this loop used
  // to push one bare `: clob 404` per row into `failures` -- 38 of them per night. The
  // multi-line Failures block that produced then evicted this run's OWN summary out of
  // `copybot-eod.sh`'s `tail -5`, so the EOD log lost `Outcome review complete` while the
  // review had actually run (115 labels at 22:01). Drop them here, count them loudly, and
  // never let them in the loop.
  //
  // This is the same class the 10-23 intake fix (Rec 1 of tuning #64) stopped at the
  // SOURCE; these 38 are the historical rows already in the table, which that fix cannot
  // retro-edit. Both are needed: intake stops new ones, this stops the existing ones from
  // poisoning every night's log.
  const blankPending = pending.filter((d) => !d.marketId || d.marketId.trim() === "");
  if (blankPending.length > 0) {
    log(
      `[BLANK-REVIEW] skipped ${blankPending.length} decision(s) with no marketId -- unreviewable ` +
        `(AND-parlay rows); counted, not silent.`
    );
    pending = pending.filter((d) => d.marketId && d.marketId.trim() !== "");
  }

  log(
    `Reviewing ${pending.length} decisions (${settledCandidates} pending rows hold a RESOLVED leg; ` +
      `${closedCandidates} hold only an early-closed leg; ` +
      `${watchCandidates} watchlist rows in the 2h–30d window, taking the ${watchPool.length} oldest).`
  );

  let reviewed = 0;
  const failures: string[] = [];
  // Horizon-price coverage, printed as ONE line: a count with its basis, so a thin
  // tape is visible rather than inferred from a lot of NULLs later.
  const horizonsFilled = { "1h": 0, "6h": 0, "24h": 0 };
  let horizonsAttempted = 0;
  let horizonsUnavailable = 0;
  let horizonsCapped = 0;
  let horizonsFetched = 0;
  const HORIZON_FETCH_MAX = Number(process.env.HORIZON_FETCH_MAX ?? 400);

  for (const d of pending) {
    try {
      let m: { resolved?: boolean; winningOutcome?: string; winningLabel?: string; yesPrice?: number } | null = null;
      try {
        m = await adapter.fetchMarket(d.marketId);
      } catch {
        // Gamma 404s archived slugs — CLOB still serves them by conditionId.
        m = await fetchResolvedViaClob(d.observedTrade.conditionId);
      }
      // The venue's own token label ("Yes", "Under", "Vitality") — comparing it
      // case-insensitively is what makes these reviews correct: the old
      // `winningOutcome === outcome` compared an API-cased label ("No") to the
      // uppercased stored label ("NO"), so `won` was ALWAYS false and every
      // watchlist/skip review was stamped "avoided loser" regardless of reality.
      const winnerLabel = m?.winningLabel ?? m?.winningOutcome;
      if (!m || !m.resolved || !winnerLabel) continue; // not resolved yet

      const won = didOutcomeWin(d.observedTrade.outcome, { winningLabel: winnerLabel, yesPrice: m.yesPrice });
      if (won === null) {
        logError(
          `[REVIEW] unmapped outcome label — decision ${d.id} outcome='${d.observedTrade.outcome}' vs winner='${winnerLabel}': skipping rather than judging`
        );
        continue;
      }
      const pt = d.paperTrades[0];
      const simulatedPnl =
        pt?.realizedPnl ??
        computePnl(d.observedTrade.detectedPrice, won ? 1 : 0, HYPOTHETICAL_SIZE);

      let good: boolean;
      const lessons: string[] = [];
      if (d.decision === "paper_copy") {
        good = simulatedPnl > 0;
        lessons.push(
          good
            ? `Copy won ${simulatedPnl.toFixed(2)} — wallet signal + filters aligned`
            : `Copy lost ${simulatedPnl.toFixed(2)} — check whether entry drift or wallet quality was the miss`
        );
      } else {
        // For watchlist/skip: good if the market went against the wallet.
        good = !won;
        lessons.push(
          won
            ? `Missed winner (+${simulatedPnl.toFixed(2)} hypothetical) — decision was ${d.decision}, review which gate blocked it`
            : `Avoided loser (${simulatedPnl.toFixed(2)} hypothetical) — ${d.decision} was correct`
        );
      }

      // Horizon prices (data2-per-decision-provenance). Best-effort and NON-FATAL:
      // a venue hiccup must not lose the label this row exists for. Capped per run so
      // a widened review pool can never turn this into hundreds of venue reads: the
      // skipped rows stay NULL (visible in the [HORIZONS] line), they are not guessed.
      let horizons: Record<"1h" | "6h" | "24h", HorizonRead> | null = null;
      if (horizonsFetched < HORIZON_FETCH_MAX) {
        try {
          horizons = await horizonPricesFor(d.observedTrade.conditionId, d.observedTrade.outcome, d.createdAt.getTime());
          if (horizons) horizonsFetched++;
        } catch {
          horizons = null;
        }
      } else {
        horizonsCapped++;
      }
      if (horizons) {
        if (horizons["1h"].reason === "ok") horizonsFilled["1h"]++;
        if (horizons["6h"].reason === "ok") horizonsFilled["6h"]++;
        if (horizons["24h"].reason === "ok") horizonsFilled["24h"]++;
        horizonsAttempted++;
      } else {
        horizonsUnavailable++;
      }

      await prisma.outcomeReview.create({
        data: {
          decisionJournalId: d.id,
          paperTradeId: pt?.id,
          finalOutcome: winnerLabel,
          simulatedPnl,
          wasDecisionGood: good,
          lessonsJson: JSON.stringify(lessons),
          priceAfter1h: horizons?.["1h"].price ?? null,
          priceAfter6h: horizons?.["6h"].price ?? null,
          priceAfter24h: horizons?.["24h"].price ?? null,
        },
      });
      reviewed++;
    } catch (e) {
      failures.push(`${d.marketId}: ${e instanceof Error ? e.message : e}`);
    }
  }

  log(`Outcome review complete: ${reviewed} decisions judged.`);
  log(
    `[HORIZONS] token resolved + tape read for ${horizonsAttempted}/${reviewed} judged decisions; ` +
      `price present 1h ${horizonsFilled["1h"]}, 6h ${horizonsFilled["6h"]}, 24h ${horizonsFilled["24h"]}; ` +
      `${horizonsUnavailable} had no conditionId/token label and ${horizonsCapped} hit the per-run fetch cap ` +
      `(${HORIZON_FETCH_MAX}) — all left NULL, never guessed`
  );
  // ONE line, always. A multi-line block printed AFTER the summary is what `tail -5` cuts
  // first, so the run looked like it never reported. Keep the count, the first five, and an
  // explicit elision marker on the same line.
  if (failures.length) {
    const shown = failures.slice(0, 5).join(" | ");
    const more = failures.length > 5 ? ` | +${failures.length - 5} more` : "";
    logError(`Failures (${failures.length}): ${shown}${more}`);
  }
}

main()
  .catch((e) => {
    logError("review:outcomes FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
