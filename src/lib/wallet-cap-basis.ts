/**
 * Per-wallet ceiling BASIS (2026-09-19 C-200 daily report rec 2, user-approved).
 *
 * v58 measured the ceiling against the wallet's WHOLE open notional, so a wallet
 * already above it was frozen outright rather than being gated gradually: the top
 * wallet held $993.66 against a $431.25 ceiling, i.e. 2.3x it, and stayed dead
 * until ~$560 of its book closed on its own (109 vetoes in the first 15 h, 1-4 per
 * cycle). The approved fix is to grandfather the pre-activation stock: the ceiling
 * becomes `baseline(wallet) + pct x effectiveCap`, which (a) unblocks the wallet by
 * exactly one ceiling's worth of NEW notional and (b) keeps the rail's purpose —
 * no wallet may ever exceed its activation notional by more than the ceiling.
 *
 * `baseline` is a snapshot of the open C-200 notional per wallet, taken when the
 * basis changed (scripts/apply-v59-wallet-cap-basis.ts writes it). A wallet first
 * seen AFTER activation is absent from the file and gets baseline 0, i.e. the plain
 * ceiling — the intended treatment for new wallets, not a fallback.
 *
 * The file is rule-state (not a log): it is read by the scorer every cycle and must
 * not be regenerated implicitly, or the grandfather level would drift upward.
 */

import * as fs from "fs";
import { join } from "path";

export const WALLET_CAP_BASELINE_FILE = join(__dirname, "..", "..", "data", "wallet-cap-baseline.json");

export interface WalletCapBaselineFile {
  /** When the basis changed (the snapshot's reference moment). */
  declaredAt: string;
  /** RuleSet version that activated the basis. */
  appliedWithRuleSet: number;
  /** Effective exposure cap and the pct x cap ceiling in force at that moment. */
  capUsd: number;
  ceilingUsd: number;
  basis: string;
  /** wallet -> open C-200 notional at activation. */
  baseline: Record<string, number>;
}

export function readWalletCapBaseline(): WalletCapBaselineFile | null {
  try {
    const raw = JSON.parse(fs.readFileSync(WALLET_CAP_BASELINE_FILE, "utf-8")) as WalletCapBaselineFile;
    if (!raw || typeof raw !== "object" || !raw.baseline) return null;
    return raw;
  } catch {
    return null;
  }
}

/** Grandfathered notional for one wallet; 0 when the wallet is new since activation. */
export function baselineFor(file: WalletCapBaselineFile | null, wallet: string): number {
  if (!file) return 0;
  const v = file.baseline?.[wallet];
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0;
}
