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
 * EXTENDED for card t_1f579e82 (complement-frame refused pairs) — additive, the parity guard is untouched:
 *   STEP 3b  re-frames the 18 pairs the link tool refuses: level = levelFor(1 − intent, "live"), tested
 *            against the leg's OWN token book, with the public tape RECOMPUTED at each frame's level
 *            (the artifact's reached5/reached60 were computed at `intent − 0.02` on the booked frame and
 *            are invalid here). Prints three frames (A = intent, B = 1 − intent, C = booked entry).
 *   STEP 3d  audits the SAME frame error inside the already-STAMPED population: `intent ≈ 1 − walletPrint`
 *            finds the class independent of the entry, and every such leg is re-read at the re-framed level,
 *            so a stamp decided on the wrong token is visible instead of inherited.
 *   STEP 7   prices the basket's consequence — legs + bankroll + cash + the watermark orderings — and
 *            composes it with the 376-leg class of t_bb9577ae (minus the frame-artifact legs inside it).
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
import { resolveFill, levelFor, type ResolutionLeg } from "../src/lib/c200-fill-resolution";
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

// ---- shared tape helpers (the complement-frame read needs the recomputed tape at ITS OWN level;
// the artifact's reached5/reached60 were computed at `intent − 0.02` on the BOOKED frame and are
// invalid at any other operand). Read-only, cached public tape on disk. ----
interface TapePrint {
  asset: string;
  price: number | string;
  size: number | string;
  timestamp: number;
  side?: string;
  outcome?: string;
}
const TAPE_CACHE = new Map<string, TapePrint[] | null>();
const TAPE_MTIME = new Map<string, string>();
const CONDITION_OF = new Map<string, string | null>();

async function loadTape(marketId: string): Promise<TapePrint[] | null> {
  if (TAPE_CACHE.has(marketId)) return TAPE_CACHE.get(marketId)!;
  if (!CONDITION_OF.has(marketId)) {
    const ot = await prisma.observedTrade.findFirst({
      where: { marketId, conditionId: { not: null } },
      select: { conditionId: true },
      orderBy: { timestamp: "desc" },
    });
    CONDITION_OF.set(marketId, ot?.conditionId ?? null);
  }
  const cid = CONDITION_OF.get(marketId);
  let rows: TapePrint[] | null = null;
  if (cid) {
    const file = path.join(process.cwd(), "data", "c200-tape", `${cid}.json`);
    if (fs.existsSync(file)) {
      try {
        rows = JSON.parse(fs.readFileSync(file, "utf8")) as TapePrint[];
        TAPE_MTIME.set(marketId, fs.statSync(file).mtime.toISOString().slice(0, 16));
      } catch {
        rows = null;
      }
    }
  }
  TAPE_CACHE.set(marketId, rows);
  return rows;
}

/** Prints on the leg's own token in (dispatch, dispatch + 60 min], and whether any sits at ≤ level. */
function tapeAtLevel(
  tape: TapePrint[] | null,
  token: string | null,
  t0Sec: number,
  level: number,
  eps = 1e-9
): { hit60: boolean | null; sellHit60: boolean | null; prints60: number } {
  if (!tape || !token) return { hit60: null, sellHit60: null, prints60: 0 };
  const w = tape.filter(
    (x) => x.asset === token && Number(x.timestamp) > t0Sec && Number(x.timestamp) <= t0Sec + 3600
  );
  if (!w.length) return { hit60: null, sellHit60: null, prints60: 0 };
  const hit = w.filter((x) => Number(x.price) <= level + eps);
  return {
    hit60: hit.length > 0,
    sellHit60: hit.some((x) => String(x.side ?? "").toUpperCase() === "SELL"),
    prints60: w.length,
  };
}

/** The complement-frame signature, tested against the WALLET's own print on the same labelled outcome:
 *  intent ≈ 1 − walletPrint and not ≈ walletPrint. Independent of the entry (the 2026-11-11 ledger
 *  repair moved the entry, not the intent), so it finds the class on stamped and unstamped legs alike. */
function isComplementFrame(intentPrice: number, walletPrint: number | null | undefined): boolean {
  if (typeof walletPrint !== "number" || !Number.isFinite(walletPrint)) return false;
  return Math.abs(intentPrice - (1 - walletPrint)) <= 0.012 && Math.abs(intentPrice - walletPrint) >= 0.05;
}

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
      dispatchedAt: true,
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

  // ---- step 3b: the refused complement frame, RE-FRAMED (card t_1f579e82) ----
  //
  // WHY THE FRAME MATTERS
  //   On a named-outcome market (team / player / UNDER labels) the pre-2026-11-09 price read
  //   (`outcome === "NO" ? noPrice : yesPrice`) priced every non-"NO" label at the FIRST token,
  //   i.e. at the COMPLEMENT of the token the leg holds. Both write paths inherited it:
  //   `ObservedTrade.detectedPrice` and `FillIntent.intentPrice` (= params.entryPrice =
  //   score-trades' `currentPrice`) landed on the other token's frame, and the sidecar booked
  //   its entry from that same number.
  //   The 2026-11-11 price-side ledger repair then moved each leg's `entryPrice` onto the token
  //   price at the trade minute (data/repair-manifests/ledger-price-side-applied-20261111T123934),
  //   so TODAY these pairs read `entry ≈ 1 − intent`: the entry is on the leg's own token and the
  //   intent is still on the complement.
  //
  //   Handing `resolveFill` the stored intent asks it to test a level ($0.26) against the leg's own
  //   token book ($0.73) — a dollar away, always "unreachable", and wrong for the opposite reason
  //   on any leg where the complement happens to sit inside the book. So the operand is re-framed:
  //
  //     frame A  level = levelFor(intent,        "live")   ← what a naive link hands the resolver
  //     frame B  level = levelFor(1 − intent,    "live")   ← the level the lane was actually handed
  //     frame C  level = entryPrice                        ← the booked level itself (post-repair,
  //                                                          no maker credit) — a strictness check
  //
  //   TWO EVIDENCE ARMS, AND WHY THE ARTIFACT'S TAPE COLUMN IS NOT ONE OF THEM
  //   `reached5/reached60` in data/c200-printthrough.jsonl were computed at `intent − 0.02`
  //   (the FLAT credit), i.e. on the wrong frame at a deeper level — invalid here. The tape is
  //   therefore recomputed from the cached public tape (`data/c200-tape/<conditionId>.json`) at
  //   each frame's own level, on the leg's own token (the artifact's `token`, which was resolved by
  //   OUTCOME LABEL on all 18 — no proximity guess). At a level computed exactly as tested, a print
  //   at or below it is a valid POSITIVE (unlike resolveFill's rule, which refuses tape positives for
  //   any credit shallower than the flat one its column was built at).
  //   The book arm needs no recompute: `book.minAsk` is level-independent, so it is the same number
  //   the resolver would read.
  if (inverted.length) {
    const EPS = 1e-9;
    const invInArt = inverted.filter((p) => latest.has(p.intentId)).length;
    log("");
    log("REFUSED complement-frame pairs (entry = 1 − intent) — NOT part of the 201-pair repair");
    log(
      `  ${inverted.length} pairs, notional ${usd(sum(inverted, (p) => p.leg.simulatedPositionSize))}, ` +
        `booked PnL ${usd(sum(inverted, (p) => p.leg.realizedPnl ?? 0))}, ${invInArt} present in the artifact`
    );
    log("  Linking one would hand the resolver a level a dollar away from the booked one; re-framing them is a measurement change.");

    // Parity line kept verbatim: the card quotes this first-pass estimate, so it must reproduce.
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

    // ---- the tape arm, recomputed at each frame (shared helper; cached public tape) ----
    for (const m of [...new Set(inverted.map((p) => p.leg.marketId))]) await loadTape(m);

    type Frame = { label: string; level: number };
    type InvRow = {
      pair: Pair;
      intent: number;
      entry: number;
      frames: Frame[];
      minAsk: number | null;
      book: Record<string, boolean | null>;
      tape: Record<string, { hit60: boolean | null; sellHit60: boolean | null; prints60: number; token: string | null; rows: number }>;
      artifactTape: { reached5: boolean | null; reached60: boolean | null; level: number | null };
    };
    const invRows: InvRow[] = [];
    for (const p of inverted) {
      const s = latest.get(p.intentId);
      const intent = Number(s?.intentPrice ?? p.intentPrice);
      const entry = p.leg.entryPrice;
      const frames: Frame[] = [
        { label: "A", level: levelFor(intent, "live") },
        { label: "B", level: levelFor(1 - intent, "live") },
        { label: "C", level: entry },
      ];
      const minAsk =
        s && s.book && typeof s.book.minAsk === "number" && Number.isFinite(s.book.minAsk) ? s.book.minAsk : null;
      const book: Record<string, boolean | null> = {};
      for (const f of frames) book[f.label] = minAsk === null ? null : minAsk <= f.level + EPS;

      const tape: InvRow["tape"] = {};
      const t = TAPE_CACHE.get(p.leg.marketId) ?? null;
      const token = (s as any)?.token ?? null;
      const t0 = Math.floor(new Date(p.leg.openedAt).getTime() / 1000);
      for (const f of frames) {
        const r = tapeAtLevel(t, token, t0, f.level);
        tape[f.label] = { ...r, token, rows: t ? t.length : 0 };
      }
      invRows.push({
        pair: p,
        intent,
        entry,
        frames,
        minAsk,
        book,
        tape,
        artifactTape: {
          reached5: (s as any)?.reached5 ?? null,
          reached60: (s as any)?.reached60 ?? null,
          level: (s as any)?.level ?? null,
        },
      });
    }

    const fmt = (x: number | null | undefined) => (x === null || x === undefined || !Number.isFinite(x) ? "  —  " : x.toFixed(3));
    const yn = (x: boolean | null | undefined) => (x === true ? "Y" : x === false ? "n" : "?");
    log("");
    log("  per-leg operands (level = levelFor(price, \"live\"); book = minAsk ≤ level; tape = a post-dispatch print ≤ level)");
    log("    #  dispatched           market                          outcome          intent  entry  lvlA   lvlB   lvlC   minAsk  bkA bkC  tapeA tapeB tapeC  p60  pnl   size");
    invRows
      .slice()
      .sort((a, b) => new Date(a.pair.leg.openedAt).getTime() - new Date(b.pair.leg.openedAt).getTime())
      .forEach((r, i) => {
        const [A, B, C] = r.frames;
        log(
          `   ${String(i + 1).padStart(2)}  ${new Date(r.pair.leg.openedAt).toISOString().slice(0, 10)}  ` +
            `${r.pair.leg.marketId.slice(0, 30).padEnd(30)} ${r.pair.leg.outcome.slice(0, 15).padEnd(15)} ` +
            `${fmt(r.intent)}  ${fmt(r.entry)}  ${fmt(A.level)} ${fmt(B.level)} ${fmt(C.level)}  ${fmt(r.minAsk)}   ` +
            `${yn(r.book.A)}   ${yn(r.book.C)}   ${yn(r.tape.A.hit60)}    ${yn(r.tape.B.hit60)}     ${yn(r.tape.C.hit60)}   ` +
            `${String(r.tape.B.prints60).padStart(3)}  ${usd(r.pair.leg.realizedPnl ?? 0).padStart(7)} ${r.pair.leg.simulatedPositionSize.toFixed(2).padStart(6)}` +
            `${r.pair.leg.status === "open" ? "  OPEN" : ""}`
        );
      });
    const tapeProv = [...TAPE_MTIME.entries()];
    log(
      `  tape provenance: cached public tape data/c200-tape/<conditionId>.json — ${tapeProv.length}/${inverted.length} covered` +
        (tapeProv.length ? ` (fetched ${tapeProv[0][1]} … ${tapeProv[tapeProv.length - 1][1]})` : "")
    );
    log(
      `  artifact tape column at these legs (INVALID here — computed at the flat level on the booked frame): ` +
        `level ${fmt(invRows[0]?.artifactTape.level ?? null)}, reached60 ${yn(invRows[0]?.artifactTape.reached60)}`
    );

    // Verdict per frame. PRECEDENCE IS POSITIVE-FIRST, and it differs from resolveFill's on
    // purpose: our L2 sampler reads the best ask every ~5s, so a book negative is "no ask at or
    // below the level in the instants we sampled", while a tape print at or below the level is a
    // trade that actually happened there (an ask at ≤ level, or a seller who crossed to ≤ level —
    // either way a resting bid at the level fills). So a tape positive OVERRIDES a book negative;
    // a tape negative never overrides a book positive.
    type Verdict = "reachable" | "unreachable" | "unresolved";
    const verdictOf = (r: InvRow, f: Frame, useTape: boolean): { v: Verdict; basis: string } => {
      if (r.book[f.label] === true) return { v: "reachable", basis: "book-window" };
      if (useTape && r.tape[f.label].hit60 === true)
        return { v: "reachable", basis: "tape-positive" };
      if (r.book[f.label] === false) return { v: "unreachable", basis: "book-window" };
      if (useTape && r.tape[f.label].hit60 === false) return { v: "unreachable", basis: "tape-at-level" };
      return { v: "unresolved", basis: "no-coverage" };
    };
    const bucketise = (label: string, useTape: boolean) => {
      const out = new Map<string, Pair[]>();
      const basis = new Map<string, number>();
      for (const r of invRows) {
        const { v, basis: b } = verdictOf(r, r.frames.find((f) => f.label === label)!, useTape);
        const key = v === "reachable" ? "filled" : v === "unreachable" ? "unfilled" : "unresolved";
        const arr = out.get(key) ?? [];
        arr.push(r.pair);
        out.set(key, arr);
        basis.set(b, (basis.get(b) ?? 0) + 1);
      }
      return { out, basis };
    };
    log("");
    log("  RE-FRAMED verdicts — book window only (the arm the card's first-pass estimate used)");
    log("    frame  meaning                                                    unfilled   notional      PnL   filled  unres");
    const summary: Record<string, { unf: Pair[]; filled: Pair[]; unres: Pair[] }> = {};
    for (const f of ["A", "B", "C"] as const) {
      for (const useTape of [false, true]) {
        const { out, basis } = bucketise(f, useTape);
        const unf = out.get("unfilled") ?? [];
        const filled = out.get("filled") ?? [];
        const unres = out.get("unresolved") ?? [];
        if (useTape) summary[`${f}+tape`] = { unf, filled, unres };
        else summary[f] = { unf, filled, unres };
        const frameLabel =
          f === "A" ? "A  level = intent (a naive link)" : f === "B" ? "B  level = 1 − intent (re-framed)" : "C  level = entryPrice (strict)   ";
        const basisStr = [...basis.entries()].map(([k, n]) => `${k} ${n}`).join(", ");
        log(
          `    ${frameLabel.padEnd(57)} ${String(unf.length).padStart(5)}   ${usd(sum(unf, (p) => p.leg.simulatedPositionSize)).padStart(9)} ` +
            `${usd(sum(unf, (p) => p.leg.realizedPnl ?? 0)).padStart(9)}   ${String(filled.length).padStart(5)}  ${String(unres.length).padStart(4)}` +
            (useTape ? `   [+ tape recomputed at level]` : `   [book-window]`)
        );
        if (useTape) log(`    ${" ".repeat(57)} basis: ${basisStr}`);
      }
    }
    const bBook = summary.B;
    log("");
    log(
      `  frame B book-window: ${bBook.unf.length}/18 unreachable = ${usd(sum(bBook.unf, (p) => p.leg.realizedPnl ?? 0))} of booked PnL on ` +
        `${usd(sum(bBook.unf, (p) => p.leg.simulatedPositionSize))} notional  ` +
        `(the card's first-pass estimate, reproduced: ${invUnf.length}/${inverted.length}, ${usd(sum(invUnf, (p) => p.leg.realizedPnl ?? 0))}, ${usd(sum(invUnf, (p) => p.leg.simulatedPositionSize))})`
    );
    const bTape = summary["B+tape"];
    log(
      `  frame B with the tape: ${bTape.unf.length}/18 unreachable = ${usd(sum(bTape.unf, (p) => p.leg.realizedPnl ?? 0))} on ` +
        `${usd(sum(bTape.unf, (p) => p.leg.simulatedPositionSize))} · filled ${bTape.filled.length} (${usd(sum(bTape.filled, (p) => p.leg.realizedPnl ?? 0))})`
    );
    const aNaive = summary.A;
    log(
      `  frame A (what linking would actually test): ${aNaive.unf.length}/18 unreachable, ${usd(sum(aNaive.unf, (p) => p.leg.realizedPnl ?? 0))} — ` +
        `a verdict decided ~$1 away from the booked level, so it must never be written`
    );

    // The tape's own contribution: legs the 5s book sampler called negative and the tape proved
    // positive. This is the column the card warned is invalid at the booked frame.
    const tapeSaved = invRows.filter((r) => r.book.B === false && r.tape.B.hit60 === true);
    if (tapeSaved.length) {
      log(
        `  tape turns ${tapeSaved.length} of the ${bBook.unf.length} book-only negatives POSITIVE at frame B ` +
          `(${usd(sum(tapeSaved.map((r) => r.pair), (p) => p.leg.realizedPnl ?? 0))} of PnL, ` +
          `${usd(sum(tapeSaved.map((r) => r.pair), (p) => p.leg.simulatedPositionSize))} notional; ` +
          `SELL-aggressor direction on ${tapeSaved.filter((r) => r.tape.B.sellHit60).length}): ` +
          tapeSaved.map((r) => `${r.pair.leg.outcome.slice(0, 12)}@${r.frames[1].level.toFixed(3)}`).join(", ")
      );
    }

    // The legs the strict frame C disagrees with frame B on — the marginal set a stricter test moves.
    const marginal = invRows.filter((r) => verdictOf(r, r.frames[1], false).v === "unreachable" && r.book.C === true);
    if (marginal.length) {
      log(
        `  marginal set (unreachable at frame B's credited level, reachable at the booked entry): ${marginal.length} legs, ` +
          `${usd(sum(marginal.map((m) => m.pair), (p) => p.leg.realizedPnl ?? 0))} of PnL`
      );
    }

    // ---- quality of the negatives, the same four checks the 201-pair repair earned ----
    // A negative the ledger acts on has to rest on a window that covers the decision moment and a
    // gap that is not tick-sized.
    const cov = invRows.map((r) => {
      const s: any = latest.get(r.pair.intentId);
      const b = s?.book ?? {};
      const lagMin = b.coverStartMs ? (Number(b.coverStartMs) - new Date(r.pair.leg.openedAt).getTime()) / 60000 : null;
      const lenMin = b.coverStartMs && b.coverEndMs ? (Number(b.coverEndMs) - Number(b.coverStartMs)) / 60000 : null;
      return { lagMin, lenMin, snaps: b.snapsInWindow ?? null };
    });
    const lags = cov.map((c) => c.lagMin).filter((x): x is number => x !== null).sort((a, b) => a - b);
    const lens = cov.map((c) => c.lenMin).filter((x): x is number => x !== null).sort((a, b) => a - b);
    const fragile = cov.filter((c) => (c.lagMin ?? 0) > 15 || (c.lenMin ?? 0) < 10).length;
    const med = (a: number[]) => (a.length ? a[Math.floor(a.length / 2)] : NaN);
    log(
      `  window quality: dispatch→coverage median ${med(lags).toFixed(1)} min (max ${Math.max(...lags).toFixed(1)}) · ` +
        `coverage length median ${med(lens).toFixed(0)} min (min ${Math.min(...lens).toFixed(0)}) · fragile ${fragile} of ${invRows.length} · legs without book coverage ${invRows.filter((r) => r.minAsk === null).length}`
    );
    const unfB = invRows.filter((r) => verdictOf(r, r.frames[1], true).v === "unreachable");
    const gaps = unfB
      .map((r) => (r.minAsk === null ? null : (r.minAsk - r.frames[1].level) / r.frames[1].level))
      .filter((x): x is number => x !== null)
      .sort((a, b) => a - b);
    if (gaps.length) {
      log(
        `  gap minAsk − levelB on the unreachable set: median ${(100 * med(gaps)).toFixed(1)}% (min ${(100 * gaps[0]).toFixed(1)}%, ` +
          `max ${(100 * gaps[gaps.length - 1]).toFixed(1)}%) — a tick-sized gap would make the verdict arguable`
      );
    }
    log(
      `  basis tally at frame B: ${(() => {
        const m = new Map<string, number>();
        for (const r of invRows) {
          const b = verdictOf(r, r.frames[1], true).basis;
          m.set(b, (m.get(b) ?? 0) + 1);
        }
        return [...m.entries()].map(([k, n]) => `${k} ${n}`).join(", ");
      })()}`
    );

    (globalThis as any).__invReframe = {
      rows: invRows,
      summary,
      notional: sum(inverted, (p) => p.leg.simulatedPositionSize),
      booked: sum(inverted, (p) => p.leg.realizedPnl ?? 0),
    };
  }

  // ---- step 3d: the SAME frame error inside the already-STAMPED population (card t_1f579e82) ----
  // The 18 refused pairs are the intents a link repair cannot touch. But a resolver STAMP is a claim
  // too, and one decided on a complement-frame intent is a claim about the wrong token. The test here
  // is frame-independent of the entry (the 2026-11-11 ledger repair moved the entry, not the intent):
  // the intent should sit at the wallet's print for the SAME labelled outcome, so `intent ≈ 1 −
  // walletPrint` is the complement signature. Every such leg is re-read at the re-framed level.
  const FIX_AT = Date.parse("2026-11-09T15:15:16Z"); // fbf9073 "price-side: price the token the leg holds"
  const legsById = new Map(legs.map((l) => [l.id, l]));
  type FrameRow = {
    intent: (typeof intents)[number];
    leg: (typeof legs)[number];
    linked: boolean;
    walletPrint: number | null;
    bookedLevel: number;
    reframedLevel: number;
    minAsk: number | null;
    booked: string;
    reframed: string;
    postFix: boolean;
  };
  const frameRows: FrameRow[] = [];
  {
    const markets = new Set<string>();
    const draft: Array<Omit<FrameRow, "reframed" | "booked">> = [];
    for (const i of intents) {
      let leg: (typeof legs)[number] | null = i.paperTradeId ? legsById.get(i.paperTradeId) ?? null : null;
      if (!leg) {
        const cands = (legsByKey.get(k(i)) ?? []).filter((l) => !linkedTradeIds.has(l.id));
        if (cands.length === 1) leg = cands[0];
      }
      if (!leg) continue;
      const s: any = latest.get(i.id);
      const wp = typeof s?.walletPrintPrice === "number" ? s.walletPrintPrice : null;
      if (!isComplementFrame(i.intentPrice, wp)) continue;
      markets.add(i.marketId);
      draft.push({
        intent: i,
        leg,
        linked: !!i.paperTradeId,
        walletPrint: wp,
        bookedLevel: levelFor(i.intentPrice, "live"),
        reframedLevel: levelFor(1 - i.intentPrice, "live"),
        minAsk: s?.book && typeof s.book.minAsk === "number" ? s.book.minAsk : null,
        postFix: new Date((i as any).dispatchedAt).getTime() >= FIX_AT,
      });
    }
    for (const m of markets) await loadTape(m);
    const verdictFor = (book: boolean | null, tape: { hit60: boolean | null }) =>
      book === true ? "reachable" : tape.hit60 === true ? "reachable(tape)" : book === false ? "unreachable" : tape.hit60 === false ? "unreachable(tape)" : "unresolved";
    for (const d of draft) {
      const s: any = latest.get(d.intent.id);
      const token = s?.token ?? null;
      const t0 = Math.floor(new Date(d.leg.openedAt).getTime() / 1000);
      const t = TAPE_CACHE.get(d.intent.marketId) ?? null;
      const book = d.minAsk === null ? null : d.minAsk <= d.reframedLevel + 1e-9;
      const bookBooked = d.minAsk === null ? null : d.minAsk <= d.bookedLevel + 1e-9;
      frameRows.push({
        ...d,
        booked: verdictFor(bookBooked, tapeAtLevel(t, token, t0, d.bookedLevel)),
        reframed: verdictFor(book, tapeAtLevel(t, token, t0, d.reframedLevel)),
      });
    }
  }
  const frameStamped = frameRows.filter((r) => r.leg.fillStatus !== null);
  const frameStampedUnf = frameStamped.filter((r) => r.leg.fillStatus === "unfilled");
  const flips = frameStampedUnf.filter((r) => r.reframed.startsWith("reachable"));
  const inRestate = frameStampedUnf.filter((r) => Math.round((r.leg.realizedPnl ?? 0) * 100) !== 0);
  const flipRestate = inRestate.filter((r) => r.reframed.startsWith("reachable"));
  const post = frameRows.filter((r) => r.postFix);
  type LegRow = (typeof legs)[number];
  const sumLegs = (arr: LegRow[], f: (l: LegRow) => number) => arr.reduce((a, l) => a + f(l), 0);
  log("");
  log("STEP 3d — the complement frame inside the STAMPED population (a stamp decided on the wrong token)");
  log(
    `  complement-frame intents in the instrument era (intent ≈ 1 − wallet print, not ≈ wallet print): ${frameRows.length} · ` +
      `linked/stamped ${frameStamped.length} (unfilled ${frameStampedUnf.length}, filled ${frameStamped.length - frameStampedUnf.length}) · unlinked ${frameRows.length - frameStamped.length}`
  );
  log(
    `  of the ${frameStampedUnf.length} stamped-unfilled: re-framed verdict REACHABLE on ${flips.length} — i.e. ${flips.length} stored "unfilled" stamps are ` +
      `frame artifacts, not evidence (${usd(sumLegs(flips.map((r) => r.leg), (l) => l.realizedPnl ?? 0))} of realizedPnl, ${usd(sumLegs(flips.map((r) => r.leg), (l) => l.simulatedPositionSize))} notional)`
  );
  log(
    `  overlap with the RESTATE population (stamped-unfilled AND still booking, the 247 class): ${inRestate.length} legs ` +
      `${usd(sumLegs(inRestate.map((r) => r.leg), (l) => l.realizedPnl ?? 0))} — of which ${flipRestate.length} read REACHABLE when re-framed, so a frame-blind re-verify would zero a real position`
  );
  for (const r of flips) {
    const inClass = Math.round((r.leg.realizedPnl ?? 0) * 100) !== 0;
    log(
      `    ${inClass ? "EXCLUDE" : "re-stamp"} ${r.leg.id} ${r.intent.marketId.slice(0, 30).padEnd(30)} ${String(r.intent.outcome).slice(0, 14).padEnd(14)} ` +
        `intent ${r.intent.intentPrice.toFixed(3)} booked-level ${r.bookedLevel.toFixed(3)} → re-framed ${r.reframedLevel.toFixed(3)} · ` +
        `minAsk ${r.minAsk === null ? "—" : r.minAsk.toFixed(3)} · ${r.reframed} · PnL ${usd(r.leg.realizedPnl ?? 0)}` +
        `${inClass ? "  ← inside the 247 class: a frame-blind re-verify would zero it" : ""}`
    );
  }
  log(
    `  write path (card item 4): intents dispatched at/after fbf9073 (${new Date(FIX_AT).toISOString()}): ` +
      `${intents.filter((i) => new Date((i as any).dispatchedAt).getTime() >= FIX_AT).length} · complement-frame among them: ${post.length} — ` +
      `${post.length === 0 ? "the forward path is CLOSED (measured, not assumed)" : "*** STILL OPEN ***"}`
  );
  (globalThis as any).__frameExclusions = {
    ids: new Set(inRestate.map((r) => r.leg.id)),
    sum: sumLegs(inRestate.map((r) => r.leg), (l) => l.realizedPnl ?? 0),
    legIds: inRestate.map((r) => r.leg.id),
  };

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


  // ---- step 7: the complement bucket's money consequence (card t_1f579e82) ----
  // Same class as step 3 of t_bb9577ae: zeroing a settled leg's realizedPnl moves
  // PaperTrade + BotBankroll.realizedPnl + cashBalance together, and the stored peak is a
  // monotone ratchet built from the same numbers — so both orderings are priced.
  const inv = (globalThis as any).__invReframe as
    | undefined
    | {
        rows: Array<{ pair: Pair; entry: number; intent: number }>;
        summary: Record<string, { unf: Pair[]; filled: Pair[]; unres: Pair[] }>;
        notional: number;
        booked: number;
      };
  if (inv) {
    const pick = (key: string) => inv.summary[key] ?? { unf: [], filled: [], unres: [] };
    for (const key of ["B", "B+tape"]) {
      const s = pick(key);
      const unfSettled = s.unf.filter((p) => p.leg.status !== "open");
      const delta = -sum(unfSettled, (p) => p.leg.realizedPnl ?? 0);
      const ids = new Set(unfSettled.map((p) => p.leg.id));
      const excl = ((globalThis as any).__frameExclusions ?? { ids: new Set<string>(), sum: 0 }) as {
        ids: Set<string>;
        sum: number;
      };
      const combined = new Set([...phantomIds, ...sbIds, ...ids]);
      const curveAll = hwm(combined);
      const realizedNow = br?.realizedPnl ?? 0;
      const cashNow = br?.cashBalance ?? 0;
      // The 376-leg class minus the complement-frame legs inside it (they are real positions stamped
      // unfilled on the wrong operand), plus this bucket — that is the release, composed honestly.
      const classDelta = restateDelta - sbSum + excl.sum;
      const nwBucket = nwBefore + delta; // this bucket ONLY (nothing else applied)
      const nwBoth = nwBefore + classDelta + delta; // the corrected 376-leg class AND this bucket
      log("");
      log(`STEP 7 — if the complement bucket is restated at frame ${key} (${key === "B" ? "book window only" : "book + recomputed tape"})`);
      log(
        `  population: ${unfSettled.length} settled legs · notional ${usd(sum(unfSettled, (p) => p.leg.simulatedPositionSize))} · ` +
          `realizedPnl ${usd(-delta)} -> $0.00 · open legs in bucket ${s.unf.length - unfSettled.length} (marks only, not restated)`
      );
      log("  state                        bankroll realized        cash      netWorth   peak used      DD%   gate");
      const row7 = (label: string, realized: number, cash: number, nw: number, peakUsed: number) => {
        const d = ddWith(peakUsed, nw);
        log(
          `  ${label.padEnd(28)} ${usd(realized).padStart(14)} ${usd(cash).padStart(11)} ${usd(nw).padStart(13)} ` +
            `${usd(peakUsed).padStart(12)}  ${d.toFixed(1).padStart(5)}%  ${d > threshold * 100 ? "TRIPPED" : "open"}`
        );
      };
      row7("today", realizedNow, cashNow, nwBefore, peak);
      row7("+ this bucket only", realizedNow + delta, cashNow + delta, nwBucket, peak);
      row7("+ 376-class (corrected)", realizedNow + classDelta, cashNow + classDelta, nwBefore + classDelta, peak);
      row7("+ both (rebased peak)", realizedNow + classDelta + delta, cashNow + classDelta + delta, nwBoth, curveAll.peak);
      log(
        `  as a release: ${usd(-delta)} restated on top of the corrected 376-leg class ${usd(-classDelta)} = ` +
          `${usd(-(delta + classDelta))} over ${combined.size - excl.ids.size} legs ` +
          `(the ${excl.ids.size} frame-artifact legs inside the 247 class, ${usd(excl.sum)}, are excluded from the zeroing and re-stamped instead)`
      );
      // The published figure: does this bucket sit inside the trailing-7-settled ladder window?
      const inWin = unfSettled.filter((p) => windowLegs.some((w) => w.id === p.leg.id));
      const winDelta = -sum(inWin, (p) => p.leg.realizedPnl ?? 0);
      log(
        `  ladder (trailing ${GATE_WINDOW_DAYS} settled days): ${usd(sumToday)} -> ${usd(sumToday + winDelta)} ` +
          `(${inWin.length} bucket legs inside the window carry ${usd(-winDelta)}; rung $${rung}/day either way — it sits at ${((100 * (sumToday + winDelta)) / (rung * GATE_WINDOW_DAYS)).toFixed(1)}% of the target)`
      );
    }
    // The identity the release has to keep, same as §4 of the parent proposal.
    log(
      `  identity check (today): principal ${usd(principal)} + realized ${usd(br?.realizedPnl ?? 0)} − open notional ${usd(oNot)} = cash ${usd(br?.cashBalance ?? 0)}`
    );
  }


  if (drift) process.exitCode = 2;
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
