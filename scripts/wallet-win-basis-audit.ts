/**
 * wallet-win-basis-audit — READ-ONLY. What does the wallet activity sample's
 * `won` flag actually mean, and how much of it is a MARK or an EARLY EXIT
 * standing in for a settled outcome?
 *
 * WHY: `src/lib/adapters/polymarket.ts` sets
 *   `won: (curPrice > 0.5) || realizedPnl > 0`
 * on every CLOSED position. Two defects in one expression:
 *   (1) a MARK (last price above .5 on a market that may not be settled) is
 *       read as a resolved win;
 *   (2) a position sold early at a profit is credited as a win even when the
 *       token it held went on to settle to zero.
 * The roadmap card (label-integrity-wallet-win-filter) claims this flows into
 * `winRate30d`/`roi30d` -> `globalScore` -> the copy decision. THIS SCRIPT
 * TESTS THAT CLAIM: `scoreWallet` derives every win-rate arm from `pnl > 0`
 * and never reads `won` at all, so the labelling defect is real but the stated
 * blast radius is not. Both halves are measured here:
 *   (A) the label: share of `won=true` rows that are marks, that are early
 *       exits on a token that later LOST (CLOB ground truth), and how many the
 *       current expression gets wrong;
 *   (B) the score: does substituting a settlement basis for the win-rate arms
 *       move `globalScore` / `walletStatus` (i.e. is the FIX a Lane A value
 *       change or a Lane B label change)?
 *
 * BASIS, stated per line (every print carries population, clock, level):
 *   population = wallets this run sampled (status rank) x their CLOSED rows in
 *                the 30-day lookback the hourly scanner uses;
 *   clock      = the sample is fetched now and the lookback is 30d, so the same
 *                SQL tomorrow returns a different set (wallet cap re-ranks);
 *   level      = leg (one closed position). Wallet-level aggregates are marked
 *                as such.
 *
 * Writes only the JSON artifact below. No DB writes, no scoring change — it re-implements the
 * scorer's arithmetic with a pluggable win basis and prices each basis on the same rows. (The
 * settlement basis it prices is what src/lib/scoring/wallet.ts SHIPS since 2026-11-11; the
 * exit-sign basis is kept as the counterfactual, and the replication check fails loudly if the
 * re-implementation ever drifts from the shipped scorer.)
 *
 *   npx tsx scripts/wallet-win-basis-audit.ts                 # 25 wallets, track tier first
 *   npx tsx scripts/wallet-win-basis-audit.ts --limit=60
 *   npx tsx scripts/wallet-win-basis-audit.ts --clob-limit=150 # ground-truth cap
 *   npx tsx scripts/wallet-win-basis-audit.ts --out=data/probe.json  # never clobber the artifact
 *
 * Output: data/wallet-win-basis-audit.json
 */
import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { getActiveRules, Rules } from "../src/lib/rules";
import { copyabilityScore, oneHitWonderPenalty, scoreWallet, walletStatus, WalletScore } from "../src/lib/scoring/wallet";
import { fetchWinningLabelViaClob } from "../src/lib/dead-market-resolution";
import { didOutcomeWin } from "../src/lib/resolution";
import { WalletActivityTrade } from "../src/lib/types";
import * as fs from "fs";
import { join, resolve } from "path";

const ROOT = join(__dirname, "..");
/** `--out=<path>` so a probe run cannot overwrite the published artifact. */
const argStr = (name: string, dflt: string) => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.split("=").slice(1).join("=") : dflt;
};
const OUT = resolve(ROOT, argStr("out", join("data", "wallet-win-basis-audit.json")));
const arg = (name: string, dflt: number) => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? Number(hit.split("=")[1]) : dflt;
};
const LIMIT = arg("limit", 25);
const CLOB_LIMIT = arg("clob-limit", 120);
const LOOKBACK_DAYS = 30;
/** A settled binary token prices at 0 or 1. 1c is the practical terminal band
 *  (venues leave 0.001/0.999 residue); anything inside is a live MARK. */
const TERMINAL_HI = 0.99;
const TERMINAL_LO = 0.01;

const pct = (n: number, d: number) => (d > 0 ? `${((n / d) * 100).toFixed(1)}%` : "n/a");
const r3 = (v: number) => Math.round(v * 1000) / 1000;

/** curPrice for a closed-position row, straight off the raw payload. */
function curPriceOf(t: WalletActivityTrade): number | undefined {
  const raw = t.raw as Record<string, unknown> | undefined;
  if (!raw) return undefined;
  const v = raw.curPrice ?? raw.cur_price ?? raw.currentPrice;
  const n = typeof v === "string" ? Number(v) : typeof v === "number" ? v : NaN;
  return Number.isFinite(n) ? n : undefined;
}

type LegBasis =
  | "settled_mark_win"
  | "settled_mark_loss"
  | "early_exit_on_winning_token"
  | "early_exit_on_losing_token"
  | "unknown_mark";

type LegRow = {
  conditionId: string | null;
  outcome: string;
  curPrice: number | undefined;
  pnl: number;
  wonAsBooked: boolean;
  /** The expression replaced on 2026-10-29 — kept so the two readings are
   *  priced on the SAME rows instead of across two drifting populations. */
  wonLegacy: boolean;
  /** terminal-mark settlement read; null = market not settled in this pull */
  markSettled: boolean | null;
  /** CLOB ground truth; null = unresolvable */
  clobWon: boolean | null;
  basis: LegBasis;
};

/** Replicates scoreWallet's arithmetic with a pluggable win-rate basis, so a hypothetical
 *  basis can be priced on the SAME rows as the shipped one.
 *
 *  Two arms exist now (2026-11-11): the SETTLEMENT basis ships in src/lib/scoring/wallet.ts,
 *  and the exit-sign basis (`pnl > 0`) is kept here as the counterfactual that prices the
 *  change. `classify` returning null on a leg excludes it from the win-rate DENOMINATOR
 *  (never defaulted), which is the same rule as settledWinRate(). */
function scoreWithBasis(
  trades: WalletActivityTrade[],
  rules: Rules,
  classify: (t: WalletActivityTrade) => boolean | null
): WalletScore {
  const clamp = (v: number, lo = 0, hi = 100) => Math.min(hi, Math.max(lo, v));
  const resolved = trades.filter((t) => t.resolved && t.pnl !== undefined);
  const invested = trades.reduce((a, t) => a + t.size, 0);
  const realized = resolved.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const roi30d = invested > 0 ? realized / invested : 0;

  const cls = resolved.map((t) => ({ t, w: classify(t) })).filter((x) => x.w !== null) as { t: WalletActivityTrade; w: boolean }[];
  const winRate = cls.length ? cls.filter((x) => x.w).length / cls.length : 0;

  // consistencyScore with the substituted win rate; all other terms identical.
  let cons: number;
  if (resolved.length < 3) cons = 10;
  else {
    const pnls = resolved.map((t) => t.pnl ?? 0);
    const mean = pnls.reduce((a, b) => a + b, 0) / pnls.length;
    const std = Math.sqrt(pnls.reduce((a, b) => a + (b - mean) ** 2, 0) / pnls.length);
    const cov = mean > 0 ? std / mean : 5;
    const covScore = clamp(100 - cov * 20);
    const wrScore = clamp(winRate * 130 - 20);
    const volumeBonus = clamp(resolved.length * 3, 0, 20);
    cons = clamp(covScore * 0.4 + wrScore * 0.5 + volumeBonus * 0.5);
  }
  // UNROUNDED internals: scoreWallet returns copyability/penalty rounded to 1dp, and multiplying
  // a rounded field into a 0-100 global score moves it up to ~0.03 — enough to cross the 0.1
  // rounding step and report a phantom "replication mismatch" on high-score wallets.
  const copy = copyabilityScore(trades, rules);
  const penalty = oneHitWonderPenalty(trades);
  const roiScore = clamp(40 + roi30d * 90);
  let global = roiScore * rules.weightRoi + cons * rules.weightConsistency + copy * rules.weightCopyability;
  global = global * (1 - (penalty / 100) * 0.6);
  if (resolved.length < rules.minResolvedTrades) global = Math.min(global, 40);

  const cats: Record<string, { trades: number; wins: number; winRate: number; pnl: number }> = {};
  for (const t of trades) {
    const c = t.marketCategory ?? "uncategorized";
    cats[c] ??= { trades: 0, wins: 0, winRate: 0, pnl: 0 };
    cats[c].trades++;
    if (t.resolved && classify(t) === true) cats[c].wins++;
    cats[c].pnl += t.pnl ?? 0;
  }
  for (const v of Object.values(cats)) v.winRate = v.trades ? v.wins / v.trades : 0;
  return {
    ...scoreWallet(trades, rules),
    roi30d,
    consistencyScore: Math.round(cons * 10) / 10,
    copyabilityScore: Math.round(copy * 10) / 10,
    oneHitWonderPenalty: Math.round(penalty * 10) / 10,
    globalScore: Math.round(clamp(global) * 10) / 10,
    winRate30d: winRate,
    categoryStrengths: cats,
    // v72: this audit builds `cats` from the TOKEN explicitly, so it must label itself as such
    // rather than inherit the live rule's basis from the spread.
    categoryBasis: "token",
  };
}

async function main() {
  const { rules } = await getActiveRules();
  const adapter = getAdapter();
  // POPULATION: the tiers the status boundary is DECIDED on, fetched in rank order.
  //
  // This used to be `orderBy: [{status:"asc"},{globalScore:"desc"}], take: LIMIT`, then a
  // client-side re-rank. `status` is a STRING, so `asc` is alphabetical — ignore < track <
  // watch — and the take(25) never reached a track row: the report claimed "status rank:
  // track first" while measuring the IGNORE tier only. The 2026-10-29 read that priced this
  // card's delta inherited that defect. Re-ranking after the take cannot fix a fetch that
  // already excluded the tier, so each tier is queried explicitly.
  const wallets: {
    address: string;
    status: string;
    globalScore: number | null;
    winRate30d: number | null;
  }[] = [];
  for (const status of ["track", "watch", "ignore"]) {
    const room = LIMIT - wallets.length;
    if (room <= 0) break;
    const tier = await prisma.walletProfile.findMany({
      where: { status, ...(adapter.isDemo ? {} : { isDemo: false }) },
      orderBy: [{ globalScore: "desc" }],
      take: room,
    });
    wallets.push(...tier);
  }
  const tierCounts = wallets.reduce<Record<string, number>>(
    (a, w) => ((a[w.status] = (a[w.status] ?? 0) + 1), a),
    {}
  );

  const legs: LegRow[] = [];
  const walletRows: Record<string, unknown>[] = [];
  const replicationDetail: Record<string, unknown>[] = [];
  const walletTrades: {
    w: { address: string; status: string; globalScore: number | null; winRate30d: number | null };
    trades: WalletActivityTrade[];
    resolved: WalletActivityTrade[];
    mine: LegRow[];
    shipped: WalletScore;
    exitArm: WalletScore;
    flagArm: WalletScore;
  }[] = [];
  let replicationMismatches = 0;
  let walletsScored = 0;

  for (const w of wallets) {
    let trades: WalletActivityTrade[];
    try {
      trades = await adapter.fetchWalletActivity(w.address, LOOKBACK_DAYS);
    } catch (e) {
      console.log(`  ! ${w.address.slice(0, 10)} fetch failed: ${(e as Error).message.slice(0, 80)}`);
      continue;
    }
    const resolved = trades.filter((t) => t.resolved && t.pnl !== undefined);
    if (resolved.length === 0) continue;
    walletsScored++;

    // (A) label audit per leg
    const mine: LegRow[] = [];
    for (const t of resolved) {
      const cur = curPriceOf(t);
      const pnl = t.pnl ?? 0;
      const terminalWin = cur !== undefined && cur >= TERMINAL_HI;
      const terminalLoss = cur !== undefined && cur <= TERMINAL_LO;
      const markSettled: boolean | null = terminalWin ? true : terminalLoss ? false : null;
      // A terminal mark IS the settlement read; a mid mark is a MARK, and the
      // leg's truth is filled in below from the archived CLOB when available.
      const basis: LegBasis = markSettled === true ? "settled_mark_win" : markSettled === false ? "settled_mark_loss" : "unknown_mark";
      mine.push({
        conditionId: t.conditionId ?? null,
        outcome: t.outcome,
        curPrice: cur,
        pnl,
        wonAsBooked: t.won === true,
        wonLegacy: (cur ?? 0) > 0.5 || pnl > 0,
        markSettled,
        clobWon: null,
        basis,
      });
    }
    legs.push(...mine);

    // (B) THREE bases priced on the SAME rows:
    //   shipped  = scoreWallet() as it now reads (settlement flag `won`)
    //   exitBasis = the expression this change replaced (`pnl > 0`)
    //   truth    = mark + CLOB ground truth (filled in below, after the CLOB pass)
    const shipped = scoreWallet(trades, rules);
    const flagArm = scoreWithBasis(trades, rules, (t) =>
      t.won === true ? true : t.won === false ? false : null
    );
    const exitArm = scoreWithBasis(trades, rules, (t) => (t.pnl ?? 0) > 0);
    // REPLICATION: the re-implementation must reproduce the shipped scorer on the basis the
    // scorer now reads. A non-zero count means they have drifted, and no delta below is
    // trustworthy — this is the check that catches a change to the arithmetic on either side.
    const drift = Math.max(
      Math.abs(flagArm.globalScore - shipped.globalScore),
      Math.abs(flagArm.consistencyScore - shipped.consistencyScore),
      Math.abs(flagArm.winRate30d - shipped.winRate30d) * 100
    );
    if (drift > 0.05) {
      replicationMismatches++;
      replicationDetail.push({
        address: w.address,
        drift: r3(drift),
        shipped: { g: shipped.globalScore, c: shipped.consistencyScore, wr: r3(shipped.winRate30d) },
        reimplemented: { g: flagArm.globalScore, c: flagArm.consistencyScore, wr: r3(flagArm.winRate30d) },
      });
    }
    // The truth arm is priced AFTER the CLOB pass below, so a leg the mark cannot settle still
    // counts once its truth is fetched.
    walletTrades.push({ w, trades, resolved, mine, shipped, exitArm, flagArm });
  }

  // CLOB ground truth for legs the mark could NOT settle (the mark is the defect)
  const unresolved = legs.filter((l) => l.markSettled === null && l.conditionId);
  const ids = [...new Set(unresolved.map((l) => l.conditionId!))].slice(0, CLOB_LIMIT);
  const truth = new Map<string, string | null>();
  for (const cid of ids) {
    truth.set(cid, await fetchWinningLabelViaClob(cid));
    await new Promise((r) => setTimeout(r, 60));
  }
  for (const l of unresolved) {
    const label = l.conditionId ? truth.get(l.conditionId) : null;
    if (!label) continue;
    l.clobWon = didOutcomeWin(l.outcome, { winningLabel: label });
    if (l.clobWon === null) continue;
    l.basis = l.clobWon ? "early_exit_on_winning_token" : "early_exit_on_losing_token";
  }

  // (B) the change priced on stored-data-equivalent rows: exit basis -> settlement flag,
  // plus the truth arm (mark + CLOB) as the label audit's own ground truth
  for (const { w, trades, resolved, mine, shipped, exitArm } of walletTrades) {
    const settleKnown = new Map<WalletActivityTrade, boolean>();
    for (let i = 0; i < resolved.length; i++) {
      const truthI = mine[i]?.markSettled ?? mine[i]?.clobWon ?? null;
      if (truthI !== null) settleKnown.set(resolved[i], truthI);
    }
    const truthArm = scoreWithBasis(trades, rules, (t) => (settleKnown.has(t) ? settleKnown.get(t)! : null));
    const before = walletStatus(exitArm, rules); // what the OLD basis decided
    const after = walletStatus(shipped, rules); // what the SHIPPED basis decides
    const truthStatus = walletStatus(truthArm, rules);
    walletRows.push({
      address: w.address,
      statusNow: w.status,
      storedGlobal: w.globalScore,
      storedWinRate30d: w.winRate30d,
      closedLegs: resolved.length,
      settleKnownLegs: settleKnown.size,
      knownFlagLegs: resolved.filter((t) => t.won !== undefined).length,
      winRate_exitBasis: r3(exitArm.winRate30d),
      winRate_shipped: r3(shipped.winRate30d),
      winRate_truth: r3(truthArm.winRate30d),
      global_exitBasis: exitArm.globalScore,
      global_shipped: shipped.globalScore,
      global_truth: truthArm.globalScore,
      status_exitBasis: before.status,
      status_shipped: after.status,
      status_truth: truthStatus.status,
      /** THE CHANGE: did any wallet change tier when the win-rate basis moved? */
      statusChanged: before.status !== after.status,
      /** Diagnostic: shipped basis vs the CLOB-augmented truth read (may differ where a mid
       *  mark was resolvable offline; the live scorer never sees that truth). */
      statusChangedVsTruth: after.status !== truthStatus.status,
      storedMatchesShipped:
        Math.abs((w.globalScore ?? -1) - shipped.globalScore) < 0.15 &&
        Math.abs((w.winRate30d ?? -1) - shipped.winRate30d) < 1e-6,
      storedMatchesExitBasis:
        Math.abs((w.globalScore ?? -1) - exitArm.globalScore) < 0.15 &&
        Math.abs((w.winRate30d ?? -1) - exitArm.winRate30d) < 1e-6,
    });
  }

  const bookedWins = legs.filter((l) => l.wonAsBooked);
  const legacyWins = legs.filter((l) => l.wonLegacy);
  const settled = legs.filter((l) => l.markSettled !== null || l.clobWon !== null);
  const truthOf = (l: LegRow) => l.markSettled ?? l.clobWon;
  const blame =
    bookedWins.filter((l) => {
      const t = truthOf(l);
      return t === false; // booked a win on a leg that actually LOST
    }).length;
  const missed =
    legs.filter((l) => !l.wonAsBooked && truthOf(l) === true).length;

  const report = {
    generatedAt: new Date().toISOString(),
    basis: {
      population: `${walletsScored} wallets (tiers: ${Object.entries(tierCounts)
        .map(([k, v]) => `${k} ${v}`)
        .join(", ")}) x their closed positions`,
      clock: `fetched now, ${LOOKBACK_DAYS}d lookback of the hourly scanner's own call`,
      level: "leg (one closed position); wallet aggregates flagged in walletRows",
      terminalBand: `curPrice >= ${TERMINAL_HI} or <= ${TERMINAL_LO}`,
      clobCap: CLOB_LIMIT,
    },
    legs: {
      closed: legs.length,
      bookedWins: bookedWins.length,
      bookedWinRate: r3(legs.length ? bookedWins.length / legs.length : 0),
      settlementKnown: settled.length,
      settlementWinRate: r3(settled.length ? settled.filter((l) => truthOf(l) === true).length / settled.length : 0),
      bookedWinOnSettledLoss: blame,
      bookedLossOnSettledWin: missed,
      bookedErrRateOnSettled: r3(settled.length ? (blame + missed) / settled.length : 0),
      // the same two errors under the REPLACED expression (curPrice>0.5 || pnl>0)
      legacy: {
        bookedWins: legacyWins.length,
        bookedWinRate: r3(legs.length ? legacyWins.length / legs.length : 0),
        bookedWinOnSettledLoss: legacyWins.filter((l) => truthOf(l) === false).length,
        bookedLossOnSettledWin: legs.filter((l) => !l.wonLegacy && truthOf(l) === true).length,
      },
      markOnlyWins: legs.filter((l) => l.markSettled === null && l.clobWon === null && l.wonAsBooked).length,
      byBasis: legs.reduce<Record<string, number>>((a, l) => ((a[l.basis] = (a[l.basis] ?? 0) + 1), a), {}),
    },
    score: {
      replicationMismatches,
      replicationDetail,
      wallets: walletRows.length,
      /** THE CHANGE: exit-sign basis -> settlement flag, tier flips */
      statusChanged: walletRows.filter((w) => w.statusChanged).length,
      /** Diagnostic: shipped flag vs the CLOB-augmented truth read */
      statusChangedVsTruth: walletRows.filter((w) => w.statusChangedVsTruth).length,
      storedMatchesShipped: walletRows.filter((w) => w.storedMatchesShipped).length,
      storedMatchesExitBasis: walletRows.filter((w) => w.storedMatchesExitBasis).length,
    },
    walletRows,
  };
  fs.writeFileSync(OUT, JSON.stringify(report, null, 1));

  console.log(`\nWALLET WIN-BASIS AUDIT — ${report.generatedAt}`);
  console.log(`population: ${report.basis.population}; clock: ${report.basis.clock}; level: ${report.basis.level}`);
  console.log(
    `LEGS ${legs.length} closed | booked wins (settlement flag) ${bookedWins.length} (${pct(bookedWins.length, legs.length)}) | ` +
      `settlement-known ${settled.length} -> true win rate ${pct(settled.filter((l) => truthOf(l) === true).length, settled.length)}`
  );
  console.log(
    `booked a WIN on a leg that settled LOST: ${blame} | booked a LOSS on a leg that settled WON: ${missed} ` +
      `(${pct(blame + missed, settled.length)} of ${settled.length} settlement-known legs)`
  );
  console.log(
    `LEGACY EXPRESSION (curPrice>0.5 || pnl>0) on the same rows: booked wins ${legacyWins.length} ` +
      `(${pct(legacyWins.length, legs.length)}), ${legacyWins.filter((l) => truthOf(l) === false).length} of them on legs that settled LOST, ` +
      `${legs.filter((l) => !l.wonLegacy && truthOf(l) === true).length} settled wins called losses`
  );
  console.log(`by basis: ${JSON.stringify(report.legs.byBasis)}`);
  console.log(
    `SCORE: replication vs scoreWallet (settlement basis) mismatches=${replicationMismatches} | wallets=${walletRows.length}`
  );
  console.log(
    `STATUS under the shipped basis vs the EXIT basis it replaced: ${report.score.statusChanged} flip(s) | ` +
      `vs the CLOB-augmented truth read: ${report.score.statusChangedVsTruth} flip(s)`
  );
  console.log(
    `stored WalletProfile rows matching a fresh score: shipped basis ${report.score.storedMatchesShipped}/${walletRows.length}, ` +
      `exit basis ${report.score.storedMatchesExitBasis}/${walletRows.length} (the hourly scan rewrites each wallet as it rotates)`
  );
  for (const d of replicationDetail) {
    console.log(`  MISMATCH ${String(d.address).slice(0, 10)} drift=${d.drift} ${JSON.stringify(d.shipped)} vs ${JSON.stringify(d.reimplemented)}`);
  }
  for (const w of walletRows.filter((x) => x.statusChanged)) {
    console.log(
      `  FLIP ${String(w.address).slice(0, 10)} ${w.status_exitBasis}->${w.status_shipped} ` +
        `g ${w.global_exitBasis}->${w.global_shipped} wr ${w.winRate_exitBasis}->${w.winRate_shipped} (n=${w.closedLegs}, known=${w.knownFlagLegs})`
    );
  }
  console.log(`artifact: ${OUT}`);
}

main()
  .catch((e) => {
    console.error("AUDIT FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
