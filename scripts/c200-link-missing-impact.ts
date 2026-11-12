/**
 * c200:link-missing-impact — READ-ONLY. What the 201 orphaned C-200 intent links would MOVE,
 * priced before anybody runs --apply.
 *
 * WHY THIS EXISTS
 *   `scripts/c200-link-missing.ts` prints the population it would link (201 pairs, $3,728.02
 *   notional, +$1,115.18 booked PnL) but says nothing about what changes AFTER the write. The
 *   chain it triggers is three links long and each one can break:
 *
 *     1. LINK      FillIntent.paperTradeId + PaperTrade.intentPrice  (the repair)
 *     2. STAMP     the resolver (scripts/c200-fill-resolve.ts, cron copybot-c200-fill-chain)
 *                  can now reach the leg and stamps fillStatus — but ONLY for an intent that is
 *                  present in data/c200-printthrough.jsonl, and only when the evidence is
 *                  one-sided. An intent the artifact never saw stays NULL forever.
 *     3. BOOK      src/lib/paper.ts::bookedPnl() zeroes a proven-unfilled leg, and that is
 *                  switched ON by default (2026-10-28) — but it is read at the moment a mark or
 *                  a settlement is WRITTEN. A leg that already settled keeps the optimistic
 *                  realizedPnl it booked, so a stamp alone reprices NO settled leg.
 *
 *   So "restates $1,115.18" is true only if a realized restatement runs as well. This script
 *   splits the two and prices each: MARKS (what linking + the resolver move on their own, i.e.
 *   the open legs) and RESTATEMENT (what additionally moving settled realizedPnl would take).
 *   It then walks the consequence the card names — realized net worth -> the equity-linked
 *   exposure cap -> the drawdown gate — against the LIVE RuleSet and the declared basis.
 *
 * READ-ONLY. No DB write, no RuleSet, no draft. Reads prisma/dev.db and the print-through artifact.
 *
 * Parity guard: this script re-derives the repair population with the same predicate as
 * c200-link-missing.ts and FAILS if its counts differ (201 / $3,728.02 / $1,115.18 as measured
 * 2026-11-12), so the two tools can never silently describe different books.
 *
 * Usage: DATABASE_URL="file:./dev.db" npx tsx scripts/c200-link-missing-impact.ts
 */
import fs from "node:fs";
import path from "node:path";
import { prisma } from "../src/lib/db";
import { log } from "../src/lib/redact";
import { resolveFill, type ResolutionLeg } from "../src/lib/c200-fill-resolution";
import { effectiveExposureCap } from "../src/lib/exposure-cap";

const LANE = "BANKROLL_200";
const ARTIFACT = path.join(process.cwd(), "data", "c200-printthrough.jsonl");
const DD_FILE = path.join(process.cwd(), "data", "c200-drawdown.json");

// Parity expectations from scripts/c200-link-missing.ts, read 2026-11-12.
const EXPECT = { pairs: 201, notional: 3728.02, booked: 1115.18 };

interface SnapLeg {
  intentId: string;
  intentPrice: number;
  book?: { minAsk?: number | null } | null;
  tapeSilent?: boolean;
  reached5?: boolean | null;
  reached60?: boolean | null;
}

function loadLatestByIntent(): Map<string, SnapLeg> {
  if (!fs.existsSync(ARTIFACT)) {
    throw new Error(`print-through artifact missing: ${ARTIFACT} — cannot price the stamp step`);
  }
  const out = new Map<string, SnapLeg>();
  for (const line of fs.readFileSync(ARTIFACT, "utf8").split("\n")) {
    if (!line.trim()) continue;
    let snap: { legs?: SnapLeg[] };
    try {
      snap = JSON.parse(line);
    } catch {
      continue;
    }
    for (const l of snap.legs ?? []) if (l && typeof l.intentId === "string") out.set(l.intentId, l);
  }
  return out;
}

const usd = (n: number) => `$${n.toFixed(2)}`;

async function main() {
  const latest = loadLatestByIntent();
  log(`print-through artifact: ${latest.size.toLocaleString()} distinct intents`);

  const intents = await prisma.fillIntent.findMany({
    where: { botId: LANE },
    select: {
      id: true,
      decisionJournalId: true,
      marketId: true,
      outcome: true,
      side: true,
      intentPrice: true,
      paperTradeId: true,
    },
  });
  const linkedTradeIds = new Set<string>();
  for (const i of intents) if (i.paperTradeId) linkedTradeIds.add(i.paperTradeId);

  const legs = await prisma.paperTrade.findMany({
    where: { botId: LANE, isDemo: false },
    select: {
      id: true,
      decisionJournalId: true,
      marketId: true,
      outcome: true,
      side: true,
      entryPrice: true,
      realizedPnl: true,
      unrealizedPnl: true,
      simulatedPositionSize: true,
      status: true,
      fillStatus: true,
      openedAt: true,
    },
  });

  const k = (r: { decisionJournalId: string; marketId: string; outcome: string; side: string }) =>
    `${r.decisionJournalId}\u0001${r.marketId}\u0001${r.outcome}\u0001${r.side}`;

  const legsByKey = new Map<string, typeof legs>();
  for (const l of legs) {
    const key = k(l);
    const arr = legsByKey.get(key) ?? [];
    arr.push(l);
    legsByKey.set(key, arr);
  }

  const isInverted = (entry: number, intent: number) =>
    Math.abs(entry - (1 - intent)) <= 0.012 && Math.abs(entry - intent) >= 0.05;

  type Pair = {
    intentId: string;
    leg: (typeof legs)[number];
    intentPrice: number;
  };
  const pairs: Pair[] = [];
  const inverted: Pair[] = [];
  const ambiguous: string[] = [];
  const noLeg: string[] = [];
  const seenKeys = new Set<string>();

  for (const i of intents) {
    if (i.paperTradeId) continue;
    const key = k(i);
    if (seenKeys.has(key)) continue;
    seenKeys.add(key);
    const sameKey = intents.filter((x) => !x.paperTradeId && k(x) === key);
    const cands = (legsByKey.get(key) ?? []).filter((l) => !linkedTradeIds.has(l.id));
    if (cands.length === 0) {
      noLeg.push(key);
      continue;
    }
    if (sameKey.length !== 1 || cands.length !== 1) {
      ambiguous.push(key);
      continue;
    }
    const p: Pair = { intentId: i.id, leg: cands[0], intentPrice: i.intentPrice };
    if (isInverted(cands[0].entryPrice, i.intentPrice)) inverted.push(p);
    else pairs.push(p);
  }

  const sum = (arr: Pair[], f: (p: Pair) => number) => arr.reduce((a, p) => a + f(p), 0);
  const notional = sum(pairs, (p) => p.leg.simulatedPositionSize);
  const booked = sum(pairs, (p) => p.leg.realizedPnl ?? 0);

  log("");
  log("PARITY GUARD (must match c200-link-missing.ts)");
  log(`  pairs ${pairs.length} (expect ${EXPECT.pairs}) · notional ${usd(notional)} (expect ${usd(EXPECT.notional)}) · booked PnL ${usd(booked)} (expect ${usd(EXPECT.booked)})`);
  const drift =
    pairs.length !== EXPECT.pairs ||
    Math.abs(notional - EXPECT.notional) > 0.01 ||
    Math.abs(booked - EXPECT.booked) > 0.01;
  if (drift) {
    log("  *** PARITY DRIFT — the two tools disagree about the book. Re-measure both before proposing. ***");
  }

  // ---- step 2: can the resolver even SEE these intents? ----
  type Bucket = "unfilled" | "filled" | "unresolved";
  const verdicts = new Map<string, { bucket: Bucket | "invisible"; basis: string }>();
  for (const p of pairs) {
    const s = latest.get(p.intentId);
    if (!s) {
      verdicts.set(p.intentId, { bucket: "invisible", basis: "not-in-artifact" });
      continue;
    }
    const rl: ResolutionLeg = {
      intentPrice: Number(s.intentPrice),
      bookMinAsk:
        s.book && typeof s.book.minAsk === "number" && Number.isFinite(s.book.minAsk) ? s.book.minAsk : null,
      tapeReached5: s.tapeSilent ? null : (s.reached5 ?? null),
      tapeReached60: s.tapeSilent ? null : (s.reached60 ?? null),
    };
    const v = resolveFill(rl, "live");
    verdicts.set(p.intentId, {
      bucket: v.basis === "unresolved" ? "unresolved" : v.reachable ? "filled" : "unfilled",
      basis: v.basis,
    });
  }

  const byBucket = new Map<string, Pair[]>();
  for (const p of pairs) {
    const b = verdicts.get(p.intentId)!.bucket;
    const arr = byBucket.get(b) ?? [];
    arr.push(p);
    byBucket.set(b, arr);
  }

  log("");
  log("STEP 2 — the resolver's verdict on each pair (mode=live, the credit the sidecar books today)");
  log("  bucket        pairs   notional     realized     unrealized   open   already-stamped");
  const order: Array<Bucket | "invisible"> = ["unfilled", "filled", "unresolved", "invisible"];
  for (const b of order) {
    const arr = byBucket.get(b) ?? [];
    if (!arr.length && b === "invisible") {
      log(`  ${b.padEnd(12)}  ${String(arr.length).padStart(5)}   ${usd(0).padStart(10)}`);
      continue;
    }
    const open = arr.filter((p) => p.leg.status === "open").length;
    const already = arr.filter((p) => p.leg.fillStatus !== null).length;
    log(
      `  ${b.padEnd(12)}  ${String(arr.length).padStart(5)}   ${usd(sum(arr, (p) => p.leg.simulatedPositionSize)).padStart(10)}   ` +
        `${usd(sum(arr, (p) => p.leg.realizedPnl ?? 0)).padStart(10)}   ${usd(sum(arr, (p) => p.leg.unrealizedPnl ?? 0)).padStart(10)}   ` +
        `${String(open).padStart(4)}   ${String(already).padStart(6)}`
    );
  }

  const unf = byBucket.get("unfilled") ?? [];
  const unfSettled = unf.filter((p) => p.leg.status !== "open");
  const unfOpen = unf.filter((p) => p.leg.status === "open");

  const markDelta = -sum(unfOpen, (p) => p.leg.unrealizedPnl ?? 0);
  const restateDelta = -sum(unfSettled, (p) => p.leg.realizedPnl ?? 0);

  log("");
  log("STEP 3 — what actually moves, split by which write path reads fillStatus");
  log(`  MARKS  (open legs, zeroed at the next hourly mark — this IS what linking alone moves): ${unfOpen.length} legs, ${usd(markDelta)} of unrealized`);
  log(`  RESTATE (settled legs, $0 only if a REALIZED restatement also runs — linking alone moves NOTHING here): ${unfSettled.length} legs, ${usd(restateDelta)} of realized`);
  log(`  total restatable PnL: ${usd(markDelta + restateDelta)} · notional on the proven-unfilled pairs: ${usd(sum(unf, (p) => p.leg.simulatedPositionSize))}`);

  // The restatement leaves each settled leg's historical PnlSnapshot marks where they are, so the
  // apply step has to SAY what happens to that surface instead of discovering it later.
  const phantomIdsAll = unfSettled.map((p) => p.leg.id);
  let marks = 0;
  let markSum = 0;
  for (let i = 0; i < phantomIdsAll.length; i += 200) {
    const chunk = phantomIdsAll.slice(i, i + 200);
    const agg = await prisma.pnlSnapshot.aggregate({
      where: { paperTradeId: { in: chunk } },
      _count: { _all: true },
      _sum: { pnl: true },
    });
    marks += agg._count._all;
    markSum += agg._sum.pnl ?? 0;
  }
  log(`  historical PnlSnapshot marks attached to those settled legs: ${marks.toLocaleString()} rows summing ${usd(markSum)} (marks are NOT touched by a realized restatement — report-only surface)`);

  // ---- step 3c: the SAME defect class that is already resolved but NOT restated ----
  // A leg can carry fillStatus='unfilled' and still hold a non-zero realizedPnl: that is a leg the
  // resolver proved was never a position AFTER it had already settled, so bookedPnl() never saw the
  // stamp. The queue fix has to price these too or it leaves the class half-repaired.
  const stampedUnf = await prisma.paperTrade.findMany({
    where: { botId: LANE, isDemo: false, fillStatus: "unfilled", NOT: { status: "open" } },
    select: { id: true, realizedPnl: true, simulatedPositionSize: true },
  });
  const stillBooked = stampedUnf.filter((l) => Math.round((l.realizedPnl ?? 0) * 100) !== 0);
  log("");
  log("STEP 3c — already-stamped 'unfilled' legs that STILL book a realized PnL (settled before the stamp)");
  log(
    `  ${stampedUnf.length} stamped-unfilled settled legs · ${stillBooked.length} of them carry non-zero realizedPnl = ` +
      `${usd(stillBooked.reduce((a, l) => a + (l.realizedPnl ?? 0), 0))} on ${usd(stillBooked.reduce((a, l) => a + l.simulatedPositionSize, 0))} notional`
  );
  log(`  positive ${stillBooked.filter((l) => (l.realizedPnl ?? 0) > 0).length} legs ${usd(stillBooked.filter((l) => (l.realizedPnl ?? 0) > 0).reduce((a, l) => a + (l.realizedPnl ?? 0), 0))}`);
  log(`  negative ${stillBooked.filter((l) => (l.realizedPnl ?? 0) < 0).length} legs ${usd(stillBooked.filter((l) => (l.realizedPnl ?? 0) < 0).reduce((a, l) => a + (l.realizedPnl ?? 0), 0))}`);

  // Re-verification, because an old stamp is a claim: re-run the CURRENT resolver against the CURRENT
  // artifact on those legs. A leg that now reads reachable must NOT be zeroed, so the restate tool has
  // to gate on this, not on the stored fillStatus alone.
  const linkedIntents = await prisma.fillIntent.findMany({
    where: { botId: LANE, paperTradeId: { in: stillBooked.map((l) => l.id) } },
    select: { id: true, paperTradeId: true, intentPrice: true },
  });
  const byLeg = new Map(linkedIntents.map((i) => [i.paperTradeId!, i]));
  const re = { agree: 0, disagree: 0, unresolved: 0, noIntent: 0, noArtifact: 0 };
  let agreeSum = 0;
  let disagreeSum = 0;
  for (const l of stillBooked) {
    const i = byLeg.get(l.id);
    if (!i) {
      re.noIntent++;
      continue;
    }
    const s = latest.get(i.id);
    if (!s) {
      re.noArtifact++;
      continue;
    }
    const v = resolveFill(
      {
        intentPrice: Number(s.intentPrice),
        bookMinAsk: s.book && typeof s.book.minAsk === "number" ? s.book.minAsk : null,
        tapeReached5: s.tapeSilent ? null : (s.reached5 ?? null),
        tapeReached60: s.tapeSilent ? null : (s.reached60 ?? null),
      },
      "live"
    );
    if (v.basis === "unresolved") re.unresolved++;
    else if (v.reachable) {
      re.disagree++;
      disagreeSum += l.realizedPnl ?? 0;
    } else {
      re.agree++;
      agreeSum += l.realizedPnl ?? 0;
    }
  }
  log(
    `  re-verified against the CURRENT artifact: still unfilled ${re.agree} (${usd(agreeSum)}) · now REACHABLE ${re.disagree} (${usd(disagreeSum)}, must not be zeroed) · ` +
      `unresolved ${re.unresolved} · no linked intent ${re.noIntent} · intent absent from artifact ${re.noArtifact}`
  );

  // ---- step 3b: the refused complement frame, priced separately ----
  if (inverted.length) {
    const invInArt = inverted.filter((p) => latest.has(p.intentId)).length;
    log("");
    log("REFUSED complement-frame pairs (entry = 1 − intent) — NOT part of this repair");
    log(
      `  ${inverted.length} pairs, notional ${usd(sum(inverted, (p) => p.leg.simulatedPositionSize))}, ` +
        `booked PnL ${usd(sum(inverted, (p) => p.leg.realizedPnl ?? 0))}, ${invInArt} present in the artifact`
    );
    log("  Linking one would hand the resolver a level a dollar away from the booked one; re-framing them is a measurement change.");
    // Priced for the FOLLOW-ON card only: re-frame the intent (level tested = (1 − intent) − credit).
    // Never used by this repair.
    let invUnf: Pair[] = [];
    for (const p of inverted) {
      const s = latest.get(p.intentId);
      if (!s) continue;
      const v = resolveFill(
        {
          intentPrice: Number((1 - s.intentPrice).toFixed(3)),
          bookMinAsk: s.book && typeof s.book.minAsk === "number" ? s.book.minAsk : null,
          tapeReached5: null, // tape was computed at the booked frame; not valid here
          tapeReached60: null,
        },
        "live"
      );
      if (v.basis !== "unresolved" && !v.reachable) invUnf.push(p);
    }
    log(
      `  if those were re-framed (a separate Lane A measurement), ${invUnf.length} would read unreachable: ` +
        `${usd(sum(invUnf, (p) => p.leg.realizedPnl ?? 0))} of booked PnL on ${usd(sum(invUnf, (p) => p.leg.simulatedPositionSize))} notional`
    );
  }

  // ---- step 4: netWorth -> exposure cap -> drawdown gate ----
  const br = await prisma.botBankroll.findUnique({ where: { botId: LANE } });
  const rs = await prisma.ruleSet.findFirst({ where: { active: true } });
  const rules = rs ? JSON.parse(rs.rulesJson) : {};
  const dd = fs.existsSync(DD_FILE) ? JSON.parse(fs.readFileSync(DD_FILE, "utf8")) : {};
  const ddBasis: "mtm" | "realized" | "min" = (rules.ddBasis as any) ?? dd.basis ?? "mtm";

  const openUnreal = await prisma.paperTrade.aggregate({
    where: { botId: LANE, status: "open" },
    _sum: { unrealizedPnl: true },
  });
  const openNotional = await prisma.paperTrade.aggregate({
    where: { botId: LANE, status: "open" },
    _sum: { simulatedPositionSize: true },
  });

  const principal = br?.principal ?? 0;
  const realizedNW = principal + (br?.realizedPnl ?? 0);
  const mtmNW = realizedNW + (openUnreal._sum.unrealizedPnl ?? 0);
  const pick = (basis: string, mtm: number, real: number) =>
    basis === "mtm" ? mtm : basis === "realized" ? real : Math.min(mtm, real);
  const nwBefore = pick(ddBasis, mtmNW, realizedNW);
  const nwMarks = pick(ddBasis, mtmNW + markDelta, realizedNW);
  const nwFull = pick(ddBasis, mtmNW + markDelta, realizedNW + restateDelta);

  const baseCap = Number(rules.maxGrossExposureUsd ?? 0);
  const capBefore = effectiveExposureCap(baseCap, nwBefore, principal);
  const capMarks = effectiveExposureCap(baseCap, nwMarks, principal);
  const capFull = effectiveExposureCap(baseCap, nwFull, principal);

  const peak = ddBasis === "mtm" ? (dd.peak ?? principal) : (dd.realizedPeak ?? principal);
  const ddPct = (nw: number) => (peak > 0 ? Math.max(0, (peak - nw) / peak) : 0);
  const threshold = Number(rules.maxDrawdownPct ?? 0);
  const oNot = openNotional._sum.simulatedPositionSize ?? 0;

  log("");
  log(`STEP 4 — declared basis "${ddBasis}" (RuleSet v${rs?.version ?? "?"}), peak ${usd(peak)}, gate ${(threshold * 100).toFixed(0)}%`);
  log("  state              net worth      cap    open notional   headroom    DD%     gate");
  const row = (label: string, nw: number, cap: number) => {
    const d = ddPct(nw);
    log(
      `  ${label.padEnd(18)} ${usd(nw).padStart(10)} ${usd(cap).padStart(8)} ${usd(oNot).padStart(14)} ` +
        `${usd(cap - oNot).padStart(10)}  ${(d * 100).toFixed(1)}%   ${d > threshold ? "TRIPPED" : "open"}`
    );
  };
  row("today", nwBefore, capBefore);
  row("+marks only", nwMarks, capMarks);
  row("+full restate", nwFull, capFull);
  log(
    `  delta from the full repair: net worth ${usd(nwFull - nwBefore)} · cap ${usd(capFull - capBefore)} · ` +
      `DD ${((ddPct(nwFull) - ddPct(nwBefore)) * 100).toFixed(1)}pp`
  );
  if (ddPct(nwBefore) > threshold && ddPct(nwFull) > threshold) {
    log("  NOTE: the gate is ALREADY past its threshold, so this repair changes the DISTANCE to recovery, not today's admission.");
  }

  // ---- step 5: the PUBLISHED number — the ladder's trailing-7-settled gate sum (GOAL POLICY v2) ----
  // Convention read off query_bankroll.js: closedAt ?? resolvedAt, as recorded at this timestamp
  // (T+0), summed over the trailing GATE_WINDOW_DAYS. This is a published figure, so its before/after
  // belongs in the proposal even though the restatement is what moves it, not the link.
  const GATE_WINDOW_DAYS = 7;
  const PHASE_TARGETS = [250, 500, 1000, 2000, 5000];
  const since = Date.now() - GATE_WINDOW_DAYS * 864e5;
  const windowLegs = await prisma.paperTrade.findMany({
    where: {
      botId: LANE,
      isDemo: false,
      OR: [{ closedAt: { gte: new Date(since) } }, { resolvedAt: { gte: new Date(since) } }],
    },
    select: { id: true, realizedPnl: true, closedAt: true, resolvedAt: true },
  });
  const phantomIds = new Set(unfSettled.map((p) => p.leg.id));
  const inWindow = windowLegs.filter((l) => phantomIds.has(l.id));
  const sumToday = windowLegs.reduce((a, l) => a + (l.realizedPnl ?? 0), 0);
  const sumAfter = windowLegs.reduce((a, l) => a + (phantomIds.has(l.id) ? 0 : (l.realizedPnl ?? 0)), 0);
  const rung = PHASE_TARGETS.find((t) => sumToday < t * GATE_WINDOW_DAYS) ?? PHASE_TARGETS[PHASE_TARGETS.length - 1];
  const rungAfter = PHASE_TARGETS.find((t) => sumAfter < t * GATE_WINDOW_DAYS) ?? PHASE_TARGETS[PHASE_TARGETS.length - 1];
  log("");
  log(`STEP 5 — ladder gate sum (trailing ${GATE_WINDOW_DAYS} settled days, closedAt ?? resolvedAt, T+0 as recorded)`);
  log(`  today : ${usd(sumToday)} over ${windowLegs.length} legs · need ${usd(rung * GATE_WINDOW_DAYS)} for the $${rung}/day rung (${((100 * sumToday) / (rung * GATE_WINDOW_DAYS)).toFixed(1)}%)`);
  log(`  after : ${usd(sumAfter)} over ${windowLegs.length - inWindow.length} legs · ${((100 * sumAfter) / (rung * GATE_WINDOW_DAYS)).toFixed(1)}% of the same target`);
  log(`  phantom legs inside this window: ${inWindow.length}, ${usd(inWindow.reduce((a, l) => a + (l.realizedPnl ?? 0), 0))} of booked PnL`);
  if (rungAfter !== rung) log(`  *** the rung itself moves: $${rung}/day -> $${rungAfter}/day`);

  // ---- step 6: the watermark interaction. The peak is a MONOTONE ratchet built from the same
  // realizedPnl these legs contributed to, so a downward restatement without a matching rebase
  // measures the new net worth against a high-water mark the phantom legs helped set. ----
  const curveRows = await prisma.$queryRawUnsafe<Array<{ ts: number | null; pnl: number | null; id: string }>>(
    `SELECT COALESCE(closedAt, resolvedAt) AS ts, realizedPnl AS pnl, id FROM PaperTrade
      WHERE botId='${LANE}' AND isDemo=0 AND status IN ('closed','resolved')
        AND COALESCE(closedAt, resolvedAt) IS NOT NULL
      ORDER BY COALESCE(closedAt, resolvedAt) ASC`
  );
  const hwm = (zero: Set<string>) => {
    let cum = 0;
    let peak = principal;
    let at: number | null = null;
    for (const r of curveRows) {
      cum += zero.has(r.id) ? 0 : Number(r.pnl ?? 0);
      const nw = principal + cum;
      if (nw > peak) {
        peak = nw;
        at = r.ts === null ? null : Number(r.ts);
      }
    }
    return { peak, at };
  };
  const curveNow = hwm(new Set());
  const curveFixed = hwm(phantomIds);
  const sbIds = new Set(stillBooked.map((l) => l.id));
  const sbSum = stillBooked.reduce((a, l) => a + (l.realizedPnl ?? 0), 0);
  const curveClass = hwm(new Set([...phantomIds, ...sbIds]));
  const ddWith = (peak: number, nw: number) => (peak > 0 ? (100 * Math.max(0, peak - nw)) / peak : 0);
  log("");
  log("STEP 6 — the watermark interaction (realized curve, principal + cumulative realizedPnl, ordered by closedAt ?? resolvedAt)");
  log(`  ledger as it stands          : high-water ${usd(curveNow.peak)} at ${curveNow.at ? new Date(curveNow.at).toISOString() : "—"}`);
  log(`  ledger with the 129 phantom legs zeroed: high-water ${usd(curveFixed.peak)} at ${curveFixed.at ? new Date(curveFixed.at).toISOString() : "—"}`);
  log(`  ledger with the WHOLE class zeroed (129 + ${stillBooked.length} already-stamped): high-water ${usd(curveClass.peak)}`);
  log("");
  log("  DD% under each ordering (peak, net worth) — order matters, so it is priced:");
  const nwClass = nwFull - sbSum;
  const states: Array<[string, number, number]> = [
    ["today", peak, nwBefore],
    ["restate only (peak kept)", peak, nwFull],
    ["peak rebase only (t_12711fe0 target)", curveNow.peak, nwBefore],
    ["rebase to the standing ledger, THEN restate", curveNow.peak, nwFull],
    ["restate + rebase on the fixed ledger", curveFixed.peak, nwFull],
    ["restate the WHOLE class + rebase on it", curveClass.peak, nwClass],
  ];
  for (const [label, p, nw] of states) {
    const d = ddWith(p, nw);
    log(`    ${label.padEnd(38)} peak ${usd(p).padStart(10)}  NW ${usd(nw).padStart(9)}  DD ${d.toFixed(1).padStart(5)}%  ${d > threshold * 100 ? "TRIPPED" : "open"}`);
  }
  log(`  stored realizedPeak in data/c200-drawdown.json: ${usd(peak)}`);


  if (drift) process.exitCode = 2;
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
