/**
 * profit-c200-frame-census -- the "sibling price" frame class on the C-200 book:
 * what it was, what it cost, whether it is still live, and what Kelly says about
 * each leg on BOTH frames.
 *
 * READ-ONLY. Lane A proposal t_9753ec80 (drafts/profit-c200-price-frame-sizing-20261116.md).
 * Opens no write handle: every read goes through `sqlite3 -readonly "file:...?mode=ro"`.
 * It calls the SAME sizer the scorer calls (`kellySizeForCopy` + `getBandLambda`).
 *
 * WHY IT EXISTS
 * -------------
 * On a NAMED-outcome market (team names, UNDER/OVER, player props) `MarketState.yesPrice`
 * is POSITIONAL (`outcomePrices[0]`), so the pre-2026-11-09 read
 * `outcome === "NO" ? noPrice : yesPrice` priced a leg holding the SECOND token at the
 * FIRST token's price -- its complement. That one number fed Kelly, the λ̂ band, the
 * long-shot rails, the dispatched intent AND (via the sidecar, which books `intent.price`
 * minus the maker credit) the booked entry.
 *
 * Two repairs then moved different halves of the row:
 *   fbf9073  2026-11-09 09:15 the four Node WRITERS price by label (`priceForOutcome`) -> sizing fixed
 *   d974287  2026-11-11 12:43 the ledger repair rewrote entryPrice on 233 booked rows -> the book fixed
 * so on the repaired legs the size still carries the LONG-SHOT decision while the entry
 * carries the FAVOURITE price. This script measures that gap from the repair ledger's own
 * preimage, and checks the forward path is clean.
 *
 * USAGE
 *   npx tsx scripts/profit-c200-frame-census.ts
 *   npx tsx scripts/profit-c200-frame-census.ts --cash 7400
 *   npx tsx scripts/profit-c200-frame-census.ts --ledger data/repair-manifests/ledger-price-side-applied-20261111T123934.jsonl
 */
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { kellySizeForCopy } from "../src/lib/kelly";
import { getBandLambda } from "../src/lib/premium";

const args = process.argv.slice(2);
const arg = (n: string, d?: string) => {
  const i = args.indexOf(`--${n}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : d;
};

// fbf9073 "price-side: price the token the leg holds, by the venue's own label"
const PRICE_SIDE_FIX_MS = 1794237316000; // 2026-11-09T09:15:16-06:00
const FIX_MS = Number(arg("fix", String(PRICE_SIDE_FIX_MS)));
const REGIME_MS = Date.UTC(2026, 9, 27); // regime anchor: journal.ruleSetVersion >= 68
const T0 = 1793059200000; // 2026-10-27T00:00:00Z, printed so a reader can re-derive the window

const DB = resolve(arg("db", "prisma/dev.db")!);
const CASH = Number(arg("cash", "0"));

function q<T>(sql: string): T[] {
  const out = execFileSync(
    "sqlite3",
    ["-readonly", `file:${DB}?mode=ro`, "-json", sql],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 }
  );
  const t = out.trim();
  return t ? (JSON.parse(t) as T[]) : [];
}
const pad = (s: string | number, n: number) => String(s).padEnd(n);
const lpad = (s: string | number, n: number) => String(s).padStart(n);
const usd = (x: number) => `${x < 0 ? "-" : ""}$${Math.abs(x).toFixed(2)}`;

// ---- basis -----------------------------------------------------------------
const rules = q<{ version: number; rulesJson: string }>(
  `SELECT version, rulesJson FROM RuleSet WHERE active=1`
)[0];
const R = rules ? JSON.parse(rules.rulesJson) : {};
const cal = JSON.parse(readFileSync(join(__dirname, "..", "data", "premium-calibration.json"), "utf8"));
const bands = cal.bands as { lo: number; hi: number; lambda: number }[];
// The calibration LIVE when these legs were sized (2026-11-01 refit, superseded 2026-11-15) — the
// skip verdict must hold on the table the scorer actually read, not only on today's.
const calHist = (() => {
  try {
    const sha = arg("calib", "93a8b23")!;
    return JSON.parse(
      execFileSync("git", ["show", `${sha}:data/premium-calibration.json`], { encoding: "utf8" })
    ) as { calibratedAt: string; bands: { lo: number; hi: number; lambda: number }[] };
  } catch {
    return null;
  }
})();
const bankroll = q<{ cashBalance: number; principal: number }>(
  `SELECT cashBalance, principal FROM BotBankroll WHERE botId='BANKROLL_200'`
)[0];
const AVAIL = CASH > 0 ? CASH : Number(bankroll?.cashBalance ?? 7400);

const ledgerDir = join(__dirname, "..", "data", "repair-manifests");
const ledgerPath = resolve(
  arg("ledger") ??
    join(
      ledgerDir,
      readdirSync(ledgerDir)
        .filter((f) => /^ledger-price-side-applied-.*\.jsonl$/.test(f))
        .sort()
        .pop() ?? ""
    )
);

console.log(`DB            ${DB}   (read-only: file:...?mode=ro)`);
console.log(`regime        journal.ruleSetVersion >= 68, openedAt >= ${new Date(T0).toISOString()}`);
console.log(`price-side fix fbf9073 at ${new Date(FIX_MS).toISOString()}`);
console.log(
  `active ruleset v${rules?.version}  kelly: fraction ${R.kellyFraction} maxBankrollPct ${R.kellyMaxBankrollPct} ` +
    `maxSizeUsd $${R.kellyMaxSizeUsd} minBetUsd $${R.kellyMinBetUsd} minEdgePct ${R.kellyMinEdgePct} enabled ${R.kellyEnabled}`
);
console.log(`premium calib  ${cal.calibratedAt}  bands ` + bands.map((b) => `[${b.lo},${b.hi}) λ̂=${b.lambda}`).join(" "));
console.log(`repair ledger  ${ledgerPath}`);
console.log(`bankroll       available $${AVAIL.toFixed(2)} (BotBankroll cash ${bankroll?.cashBalance ?? "n/a"})`);

// ---- kelly, both frames ------------------------------------------------------
const KELLY = {
  fraction: Number(R.kellyFraction ?? 0.5),
  maxBankrollPct: Number(R.kellyMaxBankrollPct ?? 0.1),
  maxSizeUsd: Number(R.kellyMaxSizeUsd ?? 100),
  minBetUsd: Number(R.kellyMinBetUsd ?? 1),
  minEdgePct: Number(R.kellyMinEdgePct ?? 0.02),
};
function kelly(price: number, table: { lo: number; hi: number; lambda: number }[] = bands) {
  const lam = getBandLambda(price, table);
  return {
    lam,
    ...kellySizeForCopy({ price, outcome: "YES", lambda: lam, side: "BUY", availableBankroll: AVAIL, ...KELLY }),
  };
}
const bandOf = (p: number) => {
  for (const b of bands) if (p >= b.lo && p < b.hi) return `[${b.lo},${b.hi})`;
  const l = bands[bands.length - 1];
  return `[${l.lo},${l.hi}]`;
};

// ---- the repair ledger -------------------------------------------------------
type LRow = {
  botId: string;
  paperTradeId: string;
  type: string;
  pre: { entryPrice: number; realizedPnl: number; simulatedPositionSize: number; fillStatus?: string | null };
  post: { entryPrice: number; realizedPnl: number };
};
const ledger: LRow[] = readFileSync(ledgerPath, "utf8")
  .split("\n")
  .filter(Boolean)
  .map((l) => JSON.parse(l))
  .filter((r) => r.type === "row");
const byId = new Map(ledger.map((r) => [r.paperTradeId, r]));

console.log(`\n== §1 THE REPAIR'S OWN PREIMAGE (data/repair-manifests, type=row) ==`);
const byBot = new Map<string, LRow[]>();
for (const r of ledger) byBot.set(r.botId, [...(byBot.get(r.botId) ?? []), r]);
for (const [bot, rows] of [...byBot.entries()].sort()) {
  const pre = rows.reduce((s, r) => s + Number(r.pre.realizedPnl ?? 0), 0);
  const post = rows.reduce((s, r) => s + Number(r.post.realizedPnl ?? 0), 0);
  console.log(
    `  ${pad(bot, 14)} rows=${lpad(rows.length, 4)}  booked before ${lpad(usd(pre), 10)}  after ${lpad(usd(post), 9)}  delta ${usd(post - pre)}`
  );
}

// ---- the legs on the ledger --------------------------------------------------
type Leg = {
  id: string;
  marketId: string;
  outcome: string;
  size: number;
  entry: number;
  status: string;
  pnl: number;
  fillStatus: string | null;
  openedAt: number;
  v: number;
  risks: string;
  wallet: number | null;
  det: number | null;
  fi: number | null;
};
const legs = q<Leg>(`
  SELECT p.id, p.marketId, p.outcome, p.simulatedPositionSize size, p.entryPrice entry, p.status,
         COALESCE(p.realizedPnl,0) pnl, p.fillStatus, p.openedAt, d.ruleSetVersion v, d.risksJson risks,
         o.walletEntryPrice wallet, o.detectedPrice det, fi.intentPrice fi
  FROM PaperTrade p
  JOIN DecisionJournal d ON d.id = p.decisionJournalId
  LEFT JOIN ObservedTrade o ON o.id = d.observedTradeId
  LEFT JOIN FillIntent fi ON fi.paperTradeId = p.id
  WHERE p.isDemo = 0 AND p.openedAt >= ${REGIME_MS}
`);
const legById = new Map(legs.map((l) => [l.id, l]));
const allIds = new Set(q<{ id: string }>(`SELECT id FROM PaperTrade`).map((r) => r.id));
const jdLambda = (risks: string) => {
  const m = /premium λ̂=(-?[\d.]+)/.exec(risks ?? "");
  return m ? Number(m[1]) : null;
};

// ---- §2 the $100 tier inside the frame class ---------------------------------
const c200LedgerAll = (byBot.get("BANKROLL_200") ?? []).filter((r) => allIds.has(r.paperTradeId));
const c200Ledger = c200LedgerAll.filter((r) => legById.has(r.paperTradeId));
console.log(
  `  C-200 rows inside the regime window: ${c200Ledger.length} of ${c200LedgerAll.length} (the rest predate 2026-10-27)`
);
const clips = c200Ledger
  .filter((r) => Number(r.pre.simulatedPositionSize) >= 99)
  .map((r) => ({ r, l: legById.get(r.paperTradeId)! }))
  .sort((a, b) => a.l.openedAt - b.l.openedAt);

console.log(`\n== §2 THE $100 CLIPS INSIDE THE FRAME CLASS (${clips.length}) ==`);
console.log(
  `  ${pad("slug", 30)} ${pad("outcome", 15)} ${lpad("sized@", 7)} ${lpad("paid@", 7)} ${lpad("wallet", 7)} ${lpad("jdλ̂", 7)}  ` +
    `${pad("kelly@sized", 8)} ${pad("kelly@paid", 24)} ${lpad("prePnl", 9)} ${lpad("postPnl", 8)}`
);
let fundedAtSized = 0;
let fundedAtPaid = 0;
let preSum = 0;
let postSum = 0;
for (const { r, l } of clips) {
  const sized = Number(r.pre.entryPrice);
  const paid = Number(r.post.entryPrice);
  const a = kelly(sized);
  const b = kelly(paid);
  if (!a.skip) fundedAtSized++;
  if (!b.skip) fundedAtPaid++;
  preSum += Number(r.pre.realizedPnl ?? 0);
  postSum += Number(r.post.realizedPnl ?? 0);
  console.log(
    `  ${pad(l.marketId.slice(0, 30), 30)} ${pad(l.outcome.slice(0, 15), 15)} ${lpad(sized.toFixed(3), 7)} ${lpad(paid.toFixed(3), 7)} ` +
      `${lpad(l.wallet?.toFixed(3) ?? "-", 7)} ${lpad(jdLambda(l.risks)?.toFixed(2) ?? "-", 7)}  ` +
      `${pad(a.skip ? "SKIP" : `$${a.sizeUsd.toFixed(0)}`, 8)} ` +
      `${pad(b.skip ? `SKIP ${b.reason}` : `$${b.sizeUsd.toFixed(0)} ${bandOf(paid)}`, 24)} ` +
      `${lpad(Number(r.pre.realizedPnl ?? 0).toFixed(2), 9)} ${lpad(Number(r.post.realizedPnl ?? 0).toFixed(2), 8)}`
  );
}
console.log(
  `  -> Kelly funds ${fundedAtSized}/${clips.length} at the price the scorer sized; ` +
    `${fundedAtPaid}/${clips.length} at the price the book paid`
);
if (calHist) {
  const histBands = calHist.bands;
  const h = clips.map(({ r }) => kelly(Number(r.post.entryPrice), histBands));
  console.log(
    `  -> on the calibration LIVE at decision time (${calHist.calibratedAt.slice(0, 10)}, 0.8-1.01 λ̂=` +
      `${histBands.find((b) => b.hi > 1)?.lambda?.toFixed(4)}): ${h.filter((k) => !k.skip).length}/${clips.length} funded, ` +
      `${h.filter((k) => k.skip).length} SKIP`
  );
}
console.log(
  `  -> booked PnL on these ${clips.length}: ${usd(preSum)} before the repair, ${usd(postSum)} after ` +
    `(${usd(postSum - preSum)} of it was the frame)`
);

// ---- §3 forward verification -------------------------------------------------
const fixSplit = q<{ era: string; legs: number; mirror: number; agrees: number; named: number }>(`
  SELECT CASE WHEN p.openedAt < ${FIX_MS} THEN 'pre-fix' ELSE 'post-fix' END era,
         COUNT(*) legs,
         SUM(abs(fi.intentPrice - (1 - o.walletEntryPrice)) <= 0.012 AND abs(fi.intentPrice - o.walletEntryPrice) >= 0.05) mirror,
         SUM(abs(fi.intentPrice - o.walletEntryPrice) <= 0.06) agrees,
         SUM(p.outcome NOT IN ('YES','NO')) named
  FROM PaperTrade p
  JOIN DecisionJournal d ON d.id = p.decisionJournalId
  JOIN ObservedTrade o ON o.id = d.observedTradeId
  JOIN FillIntent fi ON fi.paperTradeId = p.id
  WHERE p.isDemo = 0 AND p.openedAt >= ${REGIME_MS}
  GROUP BY era
`);
console.log(`\n== §3 FORWARD VERIFICATION (intent vs the wallet's own print) ==`);
for (const s of fixSplit) {
  console.log(
    `  ${pad(s.era, 9)} legs=${lpad(s.legs, 4)}  intent MIRRORS the wallet (|intent-(1-wallet)|<=0.012 and >=0.05 away): ${lpad(s.mirror ?? 0, 3)}` +
      `   intent agrees (<=0.06): ${lpad(s.agrees ?? 0, 4)}   named-label legs: ${lpad(s.named ?? 0, 3)}`
  );
}
const colMirror = q<{ n: number }>(`
  SELECT COUNT(*) n FROM PaperTrade p
  JOIN DecisionJournal d ON d.id = p.decisionJournalId
  JOIN ObservedTrade o ON o.id = d.observedTradeId
  WHERE p.isDemo=0 AND p.openedAt >= ${REGIME_MS}
    AND abs(p.entryPrice - o.walletEntryPrice) >= 0.10
    AND abs(p.entryPrice - (1 - o.walletEntryPrice)) <= 0.06
`)[0]?.n;
console.log(
  `  booked-entry column still on the complement frame (|entry-wallet|>=0.10 and |entry-(1-wallet)|<=0.06): ${colMirror}`
);

// ---- §4 what this means for the $100-tier cohort read ------------------------
const tierRows = q<{ id: string; size: number; pnl: number; status: string }>(`
  SELECT p.id, p.simulatedPositionSize size, COALESCE(p.realizedPnl,0) pnl, p.status
  FROM PaperTrade p JOIN DecisionJournal d ON d.id = p.decisionJournalId
  WHERE p.botId='BANKROLL_200' AND p.isDemo=0 AND d.ruleSetVersion>=68
    AND p.status IN ('closed','resolved') AND p.simulatedPositionSize >= 99
`);
const frameInTier = tierRows.filter((t) => byId.has(t.id));
const restInTier = tierRows.filter((t) => !byId.has(t.id));
const agg = (rows: { size: number; pnl: number }[]) => ({
  n: rows.length,
  notional: rows.reduce((s, r) => s + Number(r.size), 0),
  pnl: rows.reduce((s, r) => s + Number(r.pnl), 0),
});
const A = agg(frameInTier);
const B = agg(restInTier);
console.log(`\n== §4 THE $100 TIER, SPLIT BY FRAME CLASS (settled, regime) ==`);
console.log(
  `  frame-repaired ${lpad(A.n, 3)} legs  notional ${lpad(usd(A.notional), 9)}  pnl ${lpad(usd(A.pnl), 9)}`
);
console.log(
  `  never-repaired ${lpad(B.n, 3)} legs  notional ${lpad(usd(B.notional), 9)}  pnl ${lpad(usd(B.pnl), 9)}`
);

// ---- §5 self-checks ----------------------------------------------------------
const missing = ledger.filter((r) => !allIds.has(r.paperTradeId)).length;
const postFix = fixSplit.find((s) => s.era === "post-fix");
console.log(`\n== §5 SELF-CHECKS ==`);
const chk = (name: string, ok: boolean, detail: string) =>
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${pad(name, 44)} ${detail}`);
chk("repair ledger resolves to leg rows", missing === 0, `unresolved C-200 ids=${missing}`);
chk("booked-entry complement class is 0", (colMirror ?? -1) === 0, `count=${colMirror}`);
chk("no post-fix intent mirrors the wallet", (postFix?.mirror ?? -1) === 0, `mirror=${postFix?.mirror ?? "n/a"} of ${postFix?.legs ?? 0}`);
chk("the fix is exercised (named legs post-fix)", (postFix?.named ?? 0) > 0, `named=${postFix?.named ?? 0}`);
chk("pre-fix class is non-empty (the premise)", (fixSplit.find((s) => s.era === "pre-fix")?.mirror ?? 0) > 0, `mirror=${fixSplit.find((s) => s.era === "pre-fix")?.mirror}`);
