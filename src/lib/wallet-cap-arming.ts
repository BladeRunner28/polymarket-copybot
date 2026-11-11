/**
 * ARM CHECK for the per-wallet-ceiling shadow (card t_bfb9e54c, 2026-11-11).
 *
 * WHY THIS EXISTS. `data/wallet-cap-shadow.jsonl` held ZERO rows for the 53 days
 * between the writer landing (88662da, 2026-09-20 09:42:10Z) and this card, and
 * the reconcile gate scored that emptiness 10/10 against the golden — an
 * instrument whose silence is indistinguishable from a clean result. The two
 * facts that make the silence readable are both EXACT and both independent of
 * the feed:
 *
 *   1. Did the gate fire?    `blocksInWindow` — leg-block rows carrying the v58
 *                            reason in DecisionJournal.risksJson. This is the
 *                            scorer's own record, so it is ground truth for the
 *                            question "should the writer have produced a row".
 *   2. Could it fire today?  `wallets[].headroomUsd` — the live ceiling
 *                            (pct x effective cap + frozen baseline) against the
 *                            open C-200 notional per wallet, i.e. the same
 *                            operands `walletCapDecision` is handed.
 *
 * `contradiction` is the falsifiable part: an EMPTY feed while the rail fired in
 * the window, or while a wallet is already at/over its ceiling, means the writer
 * is broken — not that the rail cost nothing. Everything else is a legitimate
 * zero, and the note says so in words instead of leaving it to a reader.
 *
 * NOTHING here changes behaviour or a rule: it reads the live RuleSet, the
 * bankroll row and the open book, and reports.
 */

import { prisma } from "./db";
import { getActiveRules } from "./rules";
import { effectiveExposureCap } from "./exposure-cap";
import { readWalletCapBaseline, baselineFor, type WalletCapBaselineFile } from "./wallet-cap-basis";

/** The leg-block string the scorer journals and the marker's writer sits behind. */
export const WALLET_CAP_BLOCK_MARKER = "v58 per-wallet cap";

export interface WalletCapHolding {
  walletAddress: string;
  notionalUsd: number;
}

export interface WalletCapArmingInput {
  /** `rules.maxWalletNotionalPctOfCap` — 0 disables the rail outright. */
  walletPctOfCap: number;
  /** Effective gross-exposure cap the scorer would compute on its next cycle. */
  capUsd: number;
  basis: "stock" | "delta";
  baselines: WalletCapBaselineFile | null;
  holdings: ReadonlyArray<WalletCapHolding>;
  /** Leg-block rows carrying the v58 reason inside the window. */
  blocksInWindow: number;
  windowDays: number;
  /** Candidates the lane's own feed holds on disk (the thing that was empty). */
  feedRows: number;
  /**
   * Largest size the scorer could book on its next copy (worst case the rail
   * must absorb), used only to put the headroom in units a reader can size.
   */
  maxClipUsd?: number;
}

export interface WalletCapArmingWallet {
  walletAddress: string;
  notionalUsd: number;
  baselineUsd: number;
  ceilingUsd: number;
  /** ceiling − notional. <= 0 means the next copy from this wallet is blocked. */
  headroomUsd: number;
  /** notional / ceiling, so a book can be ranked without knowing the dollars. */
  ratio: number;
}

export type WalletCapArmingState = "DISABLED" | "FIRING" | "AT_CEILING" | "DORMANT";

export interface WalletCapArming {
  enabled: boolean;
  walletCapUsd: number;
  basis: "stock" | "delta";
  windowDays: number;
  blocksInWindow: number;
  feedRows: number;
  wallets: WalletCapArmingWallet[];
  /** The wallet closest to its ceiling (highest ratio), null on an empty book. */
  tightest: WalletCapArmingWallet | null;
  /** Wallets whose next copy the rail would block right now. */
  breached: string[];
  state: WalletCapArmingState;
  /** Empty feed while the rail fired, or while a wallet is over its ceiling. */
  contradiction: boolean;
  /** One sentence a report can print without further interpretation. */
  note: string;
}

const money = (n: number) => `$${n.toFixed(2)}`;

/**
 * Pure: the whole verdict is arithmetic over declared inputs, so the test file
 * can exercise every branch without a database.
 */
export function assessWalletCapArming(i: WalletCapArmingInput): WalletCapArming {
  const enabled = i.walletPctOfCap > 0 && i.capUsd > 0;
  const walletCapUsd = enabled ? i.walletPctOfCap * i.capUsd : 0;

  const wallets: WalletCapArmingWallet[] = i.holdings
    .map((h) => {
      const baselineUsd = i.basis === "delta" ? baselineFor(i.baselines, h.walletAddress) : 0;
      const ceilingUsd = walletCapUsd + baselineUsd;
      const headroomUsd = ceilingUsd - h.notionalUsd;
      return {
        walletAddress: h.walletAddress,
        notionalUsd: h.notionalUsd,
        baselineUsd,
        ceilingUsd,
        headroomUsd,
        ratio: ceilingUsd > 0 ? h.notionalUsd / ceilingUsd : 0,
      };
    })
    .sort((a, b) => b.ratio - a.ratio);

  const breached = enabled ? wallets.filter((w) => w.headroomUsd <= 0).map((w) => w.walletAddress) : [];
  const tightest = wallets.length > 0 ? wallets[0] : null;

  const state: WalletCapArmingState = !enabled
    ? "DISABLED"
    : i.blocksInWindow > 0
      ? "FIRING"
      : breached.length > 0
        ? "AT_CEILING"
        : "DORMANT";

  const contradiction = i.feedRows === 0 && (i.blocksInWindow > 0 || breached.length > 0);

  // The note is the deliverable: a reader who only sees the summary file must be
  // able to tell "the rail cost nothing" from "the writer never ran".
  const ceilingLine = enabled
    ? `${i.walletPctOfCap} x ${money(i.capUsd)} = ${money(walletCapUsd)}${i.basis === "delta" ? " + frozen baseline" : ""} (basis ${i.basis})`
    : i.walletPctOfCap > 0
      ? `pct ${i.walletPctOfCap} but effective cap ${money(i.capUsd)} — branch cannot run`
      : "maxWalletNotionalPctOfCap = 0 — branch cannot run";

  let note: string;
  if (contradiction) {
    note =
      `WRITER BROKEN: feed holds ${i.feedRows} row(s) while the rail ` +
      (i.blocksInWindow > 0
        ? `fired ${i.blocksInWindow}x in the last ${i.windowDays}d`
        : `is already breached by ${breached.length} wallet(s)`) +
      ` — a block is not being recorded. Ceiling: ${ceilingLine}.`;
  } else if (!enabled) {
    note = `DISABLED, so there is nothing to record: ${ceilingLine}.`;
  } else if (i.blocksInWindow > 0) {
    note = `FIRING: ${i.blocksInWindow} block(s) in the last ${i.windowDays}d; ceiling ${ceilingLine}.`;
  } else if (tightest) {
    const clips =
      i.maxClipUsd && i.maxClipUsd > 0 ? (tightest.headroomUsd / i.maxClipUsd).toFixed(1) : null;
    note =
      `DORMANT (a real zero, not a missing writer): 0 blocks in ${i.windowDays}d, ceiling ${ceilingLine}. ` +
      `Nearest wallet ${tightest.walletAddress.slice(0, 10)}… holds ${money(tightest.notionalUsd)} = ` +
      `${(tightest.ratio * 100).toFixed(1)}% of its ${money(tightest.ceilingUsd)} ceiling ` +
      `(${money(tightest.headroomUsd)} of headroom${clips === null ? "" : ` = ${clips}x the largest clip booked in the window (${money(i.maxClipUsd!)})`}).`;
  } else {
    note = `DORMANT: 0 blocks in ${i.windowDays}d and no open C-200 wallet to measure; ceiling ${ceilingLine}.`;
  }

  return {
    enabled,
    walletCapUsd,
    basis: i.basis,
    windowDays: i.windowDays,
    blocksInWindow: i.blocksInWindow,
    feedRows: i.feedRows,
    wallets,
    tightest,
    breached,
    state,
    contradiction,
    note,
  };
}

export type WalletCapArmingRead =
  | { ok: true; arming: WalletCapArming; capBasis: string }
  | { ok: false; error: string };

/**
 * Read the live operands the scorer would use, then hand them to the pure
 * assessor. The cap is derived exactly as `score-trades.ts` derives it (same
 * declared drawdown basis, same equity-linked formula) so the ceiling printed
 * here is the ceiling the next cycle evaluates — not a copy of a log line.
 */
export async function readWalletCapArming(opts: {
  feedRows: number;
  windowDays?: number;
  nowMs?: number;
}): Promise<WalletCapArmingRead> {
  const windowDays = opts.windowDays ?? 7;
  const nowMs = opts.nowMs ?? Date.now();
  try {
    const { rules } = await getActiveRules();
    const bankroll = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
    const principal = bankroll?.principal ?? 0;
    const realizedNW = principal + (bankroll?.realizedPnl ?? 0);
    const unrealAgg = await prisma.paperTrade.aggregate({
      where: { botId: "BANKROLL_200", status: "open" },
      _sum: { unrealizedPnl: true },
    });
    const mtmNW = realizedNW + (unrealAgg._sum.unrealizedPnl ?? 0);
    const ddBasis = (rules.ddBasis as string | undefined) ?? "mtm";
    const capNW = ddBasis === "realized" ? realizedNW : ddBasis === "min" ? Math.min(mtmNW, realizedNW) : mtmNW;
    const capUsd = effectiveExposureCap(rules.maxGrossExposureUsd ?? 0, capNW, principal);
    const capBasis = `ddBasis=${ddBasis} → cap NW ${money(capNW)} (principal ${money(principal)}, realizedPnl ${money(bankroll?.realizedPnl ?? 0)}, mtm NW ${money(mtmNW)})`;

    const grouped = await prisma.paperTrade.groupBy({
      by: ["walletAddress"],
      where: { botId: "BANKROLL_200", status: "open" },
      _sum: { simulatedPositionSize: true },
    });
    const holdings: WalletCapHolding[] = grouped.map((g) => ({
      walletAddress: g.walletAddress,
      notionalUsd: g._sum.simulatedPositionSize ?? 0,
    }));

    const blocksInWindow = await prisma.decisionJournal.count({
      where: {
        createdAt: { gt: new Date(nowMs - windowDays * 86400_000) },
        risksJson: { contains: WALLET_CAP_BLOCK_MARKER },
      },
    });

    // Largest size the rail must absorb on the next copy: the distance to the
    // ceiling is only meaningful against the clip the lane actually books.
    const clips = await prisma.paperTrade.aggregate({
      where: {
        botId: "BANKROLL_200",
        openedAt: { gt: new Date(nowMs - windowDays * 86400_000) },
      },
      _max: { simulatedPositionSize: true },
    });

    const arming = assessWalletCapArming({
      walletPctOfCap: rules.maxWalletNotionalPctOfCap ?? 0,
      capUsd,
      basis: rules.walletCapBasis === "delta" ? "delta" : "stock",
      baselines: readWalletCapBaseline(),
      holdings,
      blocksInWindow,
      windowDays,
      feedRows: opts.feedRows,
      maxClipUsd: clips._max.simulatedPositionSize ?? 0.25,
    });
    return { ok: true, arming, capBasis };
  } catch (e) {
    // Prisma's initialization errors can arrive with an EMPTY message, which
    // would print as "UNAVAILABLE — " and tell the reader nothing.
    const err = e as { message?: string; name?: string; constructor?: { name?: string } };
    const why =
      (e instanceof Error && e.message) ||
      err?.message ||
      err?.name ||
      err?.constructor?.name ||
      String(e) ||
      "unknown error (is DATABASE_URL set?)";
    return { ok: false, error: why };
  }
}
