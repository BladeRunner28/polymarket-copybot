/**
 * kelly-window-report — daily/weekly/final reporting for the Phase-B Kelly
 * sizing effort (drafts/phase-b-kelly-design.md). Regime = C-200 decisions
 * journaled under ruleSetVersion >= 49 (kellyEnabled=1; v50 raised the size
 * cap 60→100). Short-TTR lane copies are EXEMPT from Kelly (fixed size,
 * channel design) and reported separately.
 *
 * Usage: DATABASE_URL="file:./dev.db" npx tsx scripts/kelly-window-report.ts [auto|daily|weekly|final]
 *   auto   = daily + window; weekly rollup on Mondays/7-day marks; FINAL
 *            verdict once past the official window end (2026-10-08)
 * Emits markdown to stdout (narrow tables — Discord-safe).
 */

import { prisma } from "../src/lib/db";
import { readFileSync, writeFileSync, existsSync } from "fs";
import { join } from "path";

const REGIME_V49_MS = 1788677096846; // RuleSet v49 createdAt (kellyEnabled=1)
const WINDOW_END = Date.UTC(2026, 9, 8, 23, 59); // official read window close
const LANE = { not: { contains: "Short-TTR lane" } }; // reasonsJson filter
const DAY = 86_400_000;

const mode = (process.argv[2] || "auto") as string;
const now = new Date();
const isFinal = mode === "final" || (mode === "auto" && now.getTime() > WINDOW_END);
const isWeekly = mode === "weekly" || (mode === "auto" && now.getDay() === 1); // Mondays

function band(price: number): string {
  if (price < 0.2) return "<0.20";
  if (price < 0.4) return "0.20-0.40";
  if (price < 0.6) return "0.40-0.60";
  if (price < 0.8) return "0.60-0.80";
  return ">=0.80";
}
const BANDS = ["<0.20", "0.20-0.40", "0.40-0.60", "0.60-0.80", ">=0.80"];

async function state() {
  const br = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const open = await prisma.paperTrade.aggregate({ where: { botId: "BANKROLL_200", status: "open" }, _sum: { simulatedPositionSize: true, unrealizedPnl: true } });
  const rs = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const rules = JSON.parse(rs?.rulesJson || "{}");
  const netWorth = (br?.principal ?? 0) + (br?.realizedPnl ?? 0) + (open._sum.unrealizedPnl ?? 0);
  const baseCap = rules.maxGrossExposureUsd ?? 0;
  const effCap = baseCap + 0.5 * Math.max(0, netWorth - (br?.principal ?? 0));
  let peak = 0;
  try { peak = JSON.parse(readFileSync(join(__dirname, "..", "data", "c200-drawdown.json"), "utf8")).peak ?? 0; } catch { /* */ }
  const dd = peak > 0 ? Math.max(0, (peak - netWorth) / peak) : 0;
  return { br, openNotional: open._sum.simulatedPositionSize ?? 0, openUnreal: open._sum.unrealizedPnl ?? 0, netWorth, effCap, dd, rules, rulesVersion: rs?.version };
}

/** C-200 trades under Kelly rules (journal v>=49), split main-lane vs lane. */
async function windowTrades() {
  const djs = await prisma.decisionJournal.findMany({
    where: { ruleSetVersion: { gte: 49 }, paperTrades: { some: { botId: "BANKROLL_200" } } },
    include: { paperTrades: { where: { botId: "BANKROLL_200" } } },
  });
  const main: Record<string, { n: number; sizes: number[]; realized: number; open: number; resolved: number }> = {};
  const lane: typeof main = {};
  for (const b of BANDS) { main[b] = { n: 0, sizes: [], realized: 0, open: 0, resolved: 0 }; lane[b] = { n: 0, sizes: [], realized: 0, open: 0, resolved: 0 }; }
  for (const dj of djs) {
    const isLane = (dj.reasonsJson || "").includes("Short-TTR lane");
    for (const t of dj.paperTrades) {
      const g = (isLane ? lane : main)[band(t.entryPrice)];
      g.n++; g.sizes.push(t.simulatedPositionSize);
      if (t.status === "resolved" || t.status === "closed") { g.realized += t.realizedPnl ?? 0; g.resolved++; }
      else g.open += t.simulatedPositionSize;
    }
  }
  return { main, lane };
}

/** Pre-Kelly baseline: resolved/closed C-200 under journal v<49, by entry band. */
async function baseline() {
  const djs = await prisma.decisionJournal.findMany({
    where: { ruleSetVersion: { lt: 49 }, paperTrades: { some: { botId: "BANKROLL_200", status: { in: ["closed", "resolved"] } } } },
    include: { paperTrades: { where: { botId: "BANKROLL_200", status: { in: ["closed", "resolved"] } } } },
  });
  const out: Record<string, { n: number; realized: number }> = {};
  for (const b of BANDS) out[b] = { n: 0, realized: 0 };
  for (const dj of djs) for (const t of dj.paperTrades) { const g = out[band(t.entryPrice)]; g.n++; g.realized += t.realizedPnl ?? 0; }
  return out;
}

/** [KELLY] decision lines from the scorer log (cumulative; note if rotated). */
function kellyLog() {
  const p = join(__dirname, "..", "logs", "cron", "copybot-monitor-score.log");
  if (!existsSync(p)) return null;
  const lines = readFileSync(p, "utf8").split("\n").filter((l) => l.includes("[KELLY]"));
  const sized: Record<string, number> = {}; const skipped: Record<string, number> = {};
  const reasons: Record<string, number> = {};
  for (const l of lines) {
    const bm = l.match(/band=\[?([0-9.,]+)/);
    const b = bm ? bm[1] : "?";
    if (l.includes("SKIP")) {
      skipped[b] = (skipped[b] || 0) + 1;
      const rm = l.match(/SKIP (.+)$/);
      if (rm) { const r = rm[1].split("(")[0].trim(); reasons[r] = (reasons[r] || 0) + 1; }
    } else sized[b] = (sized[b] || 0) + 1;
  }
  return { total: lines.length, sized, skipped, reasons, sizedUsd: lines.filter((l) => !l.includes("SKIP")).length > 0 };
}

function fmtRow(band: string, g: any): string {
  const avg = g.n ? (g.sizes.reduce((a: number, b: number) => a + b, 0) / g.n) : 0;
  const mx = g.n ? Math.max(...g.sizes) : 0;
  return `| ${band} | ${g.n} | $${avg.toFixed(0)} | $${mx.toFixed(0)} | $${g.realized.toFixed(0)} (${g.resolved} res) | $${g.open.toFixed(0)} open |`;
}

async function main() {
  const [st, wt, bl, kl] = await Promise.all([state(), windowTrades(), baseline(), kellyLog()]);
  const regimeDays = Math.floor((now.getTime() - REGIME_V49_MS) / DAY) + 1;
  const daysLeft = Math.max(0, Math.ceil((WINDOW_END - now.getTime()) / DAY));
  const out: string[] = [];
  out.push(`**Kelly Window Report — ${now.toISOString().slice(0, 10)}** (regime day ${regimeDays}${isFinal ? " — FINAL READ" : `, official window ends in ~${daysLeft}d`})`);
  out.push(`Rules v${st.rulesVersion}: kellyEnabled=${st.rules.kellyEnabled} fraction=${st.rules.kellyFraction} maxBankrollPct=${(st.rules.kellyMaxBankrollPct * 100).toFixed(0)}% maxSizeUsd=$${st.rules.kellyMaxSizeUsd} minBet=$${st.rules.kellyMinBetUsd} minEdge=${((st.rules.kellyMinEdgePct ?? 0.02) * 100).toFixed(0)}%`);
  out.push("");
  out.push("**State:** cash $" + (st.br?.cashBalance ?? 0).toFixed(0) + " | open $" + st.openNotional.toFixed(0) + " | net worth $" + st.netWorth.toFixed(0) + " | realized $" + (st.br?.realizedPnl ?? 0).toFixed(0) + " | exposure " + st.openNotional.toFixed(0) + "/$" + st.effCap.toFixed(0) + " | drawdown " + (st.dd * 100).toFixed(1) + "%");
  if (st.openNotional > st.effCap * 0.9) out.push("⚠ exposure cap nearly binding — Kelly sizing headroom limited");
  const ddGate = st.rules.maxDrawdownPct ?? 0.2;
  if (ddGate > 0 && st.dd > ddGate) out.push("⚠ **drawdown " + (st.dd * 100).toFixed(1) + "% EXCEEDS the " + (ddGate * 100).toFixed(0) + "% gate** — new copies should be journaled watchlist; confirm the gate is tripping");
  out.push("");
  // --- daily ---
  const d1 = new Date(now.getTime() - DAY);
  const djs24 = await prisma.decisionJournal.findMany({
    where: { ruleSetVersion: { gte: 49 }, paperTrades: { some: { botId: "BANKROLL_200", openedAt: { gte: d1 } } } },
    include: { paperTrades: { where: { botId: "BANKROLL_200", openedAt: { gte: d1 } } } },
  });
  const opened: { simulatedPositionSize: number; isLane: boolean }[] = [];
  for (const dj of djs24) {
    const isLane = (dj.reasonsJson || "").includes("Short-TTR lane");
    for (const t of dj.paperTrades) opened.push({ simulatedPositionSize: t.simulatedPositionSize, isLane });
  }
  const realizedRows = await prisma.paperTrade.findMany({ where: { botId: "BANKROLL_200", status: { in: ["closed", "resolved"] }, OR: [{ resolvedAt: { gte: d1 } }, { closedAt: { gte: d1 } }] }, select: { realizedPnl: true } });
  const realized24 = realizedRows.reduce((a, t) => a + (t.realizedPnl ?? 0), 0);
  const main24 = opened.filter((t) => !t.isLane).length;
  const lane24 = opened.length - main24;
  out.push("**Last 24h:** " + opened.length + " Kelly-regime copies opened (" + main24 + " main-lane, " + lane24 + " lane) | realized $" + realized24.toFixed(2) + " | $" + opened.reduce((a, t) => a + t.simulatedPositionSize, 0).toFixed(0) + " booked");
  if (kl) {
    const sz = Object.values(kl.sized).reduce((a: number, b: number) => a + b, 0);
    const sk = Object.values(kl.skipped).reduce((a: number, b: number) => a + b, 0);
    const top = Object.entries(kl.reasons).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([r, c]) => `${r} (${c})`).join("; ");
    out.push("[KELLY] decisions in log: " + (sz + sk) + " (" + sz + " sized, " + sk + " skipped). Top skip reasons: " + (top || "none") + (sz + sk < 15 ? " — log may be partial/rotated" : ""));
  }
  out.push("");
  // --- window cumulative ---
  out.push("**Window (since v49, main-lane Kelly):**");
  out.push("| band | n | avg size | max | realized | open |");
  out.push("|---|---|---|---|---|---|");
  for (const b of BANDS) out.push(fmtRow(b, wt.main[b]));
  const totalN = BANDS.reduce((a, b) => a + wt.main[b].n, 0);
  const midHighN = wt.main["0.40-0.60"].n + wt.main["0.60-0.80"].n + wt.main[">=0.80"].n;
  out.push("");
  out.push("**Lane (short-TTR, Kelly-exempt):** " + BANDS.reduce((a, b) => a + wt.lane[b].n, 0) + " copies, realized $" + BANDS.reduce((a, b) => a + wt.lane[b].realized, 0).toFixed(0));
  out.push("**Target check:** mid/high-band main-lane copies " + midHighN + "/" + totalN + (midHighN <= Math.max(2, totalN * 0.1) ? " → ≈0 ✓ (zero-edge skips holding)" : " → ABOVE expected ≈0 ✗ — inspect"));
  out.push("");
  // --- weekly ---
  if (isWeekly || mode === "weekly") {
    const w1 = new Date(now.getTime() - 7 * DAY);
    const wdjs = await prisma.decisionJournal.findMany({
      where: { ruleSetVersion: { gte: 49 }, paperTrades: { some: { botId: "BANKROLL_200", openedAt: { gte: w1 } } } },
      select: { paperTrades: { where: { botId: "BANKROLL_200", openedAt: { gte: w1 } }, select: { simulatedPositionSize: true } } },
    });
    const wOpened = wdjs.reduce((a, dj) => a + dj.paperTrades.length, 0);
    const wRealized = await prisma.paperTrade.aggregate({ where: { botId: "BANKROLL_200", status: { in: ["closed", "resolved"] }, OR: [{ resolvedAt: { gte: w1 } }, { closedAt: { gte: w1 } }] }, _sum: { realizedPnl: true } });
    out.push("**WEEKLY (7d):** " + wOpened + " copies opened | realized $" + (wRealized._sum.realizedPnl ?? 0).toFixed(2));
  }
  // --- baseline + final ---
  if (isFinal || mode === "final") {
    const blTot = Object.values(bl).reduce((a: any, b: any) => a + b.realized, 0);
    const cur = BANDS.reduce((a, b) => a + wt.main[b].realized, 0);
    out.push("");
    out.push("**FINAL — pre-Kelly baseline (all resolved, journal v<49):**");
    out.push("| band | n | realized |");
    out.push("|---|---|---|");
    for (const b of BANDS) out.push(`| ${b} | ${bl[b].n} | $${bl[b].realized.toFixed(0)} |`);
    out.push("Baseline total realized $" + blTot.toFixed(0) + " | Kelly-window main-lane realized $" + cur.toFixed(0));
    out.push("Long-shot (<0.20) realized: baseline $" + bl["<0.20"].realized.toFixed(0) + " → window $" + wt.main["<0.20"].realized.toFixed(0) + (bl["<0.20"].realized !== 0 ? " (" + ((wt.main["<0.20"].realized / bl["<0.20"].realized)).toFixed(1) + "x)" : " (baseline 0 — ratio n/a)"));
    out.push("**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown " + (st.dd * 100).toFixed(1) + "% vs 20% gate " + (st.dd <= 0.2 ? "✓" : "✗"));
    out.push("CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.");
    const doc = out.join("\n");
    const fp = join(__dirname, "..", "drafts", `kelly-final-read-${now.toISOString().slice(0, 10)}.md`);
    writeFileSync(fp, doc + "\n");
    out.push("📄 Final read saved: drafts/kelly-final-read-" + now.toISOString().slice(0, 10) + ".md");
  }
  console.log(out.join("\n"));
}

main().catch((e) => { console.error("kelly-window-report FAILED:", e); process.exit(1); }).finally(() => prisma.$disconnect());
