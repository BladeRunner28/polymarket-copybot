const { PrismaClient } = require('@prisma/client');
const fs = require('fs');
const path = require('path');
const prisma = new PrismaClient();

// C-200 phase goals.
//
// GOAL POLICY v2 (2026-10-12, user-approved in-thread — option "A"): the ladder gains a
// real first rung ($250) and the ADVANCE BASIS changes from "STABILITY_DAYS consecutive
// days each individually >= target" to "the trailing GATE_WINDOW_DAYS SETTLED days SUM to
// at least target x GATE_WINDOW_DAYS".
//
// WHY THE BASIS CHANGED (measured, not asserted — read 2026-10-12 on the settled series,
// artifact data/longshot-flow-funnel.json + the 67-day settled daily series): under the old
// basis Phase 1 was unsatisfiable in practice, and it was not the level that was wrong, it
// was the TEST. Settled 67 days: mean $86.96/day but a MEDIAN day of $0.15, and the top 3
// days = 60% of all PnL — the book earns a run-rate while almost never posting 7
// individually-qualifying days. Longest CONSECUTIVE run at $250/day = 2 days (current 1);
// at $500/day = 2 days (current 0). Rolling 7-day windows clearing $1,750 (= $250/day) =
// 8 of 61 (13%), and the most recent window 2026-10-03..10-09 = $1,708.78, i.e. 2.4% short.
// Rolling windows clearing $3,500 (= $500/day) = 0 of 61 — never once. So $500/day was an
// unanchored target, and the consecutive-day test measured a day-to-day consistency this
// book structurally does not have.
//
// The old consecutive-day streak is STILL COMPUTED AND PRINTED (the daily reviews quote it
// and it is a useful instrument) but it is explicitly NOT the advance basis any more.
const PHASES = [
  { name: "Phase 1", target: 250 },
  { name: "Phase 2", target: 500 },
  { name: "Phase 3", target: 1000 },
  { name: "Phase 4", target: 2000 },
  { name: "Ultimate", target: 5000 },
];
const STABILITY_DAYS = 7;
// The advance-gate window. Equal to STABILITY_DAYS by construction: the gate is "the
// trailing 7 SETTLED days sum to at least 7x the target", i.e. the same 7-day ambition,
// asserted over the window instead of over each day in it.
const GATE_WINDOW_DAYS = STABILITY_DAYS;

// Goal-policy version, printed in every report so any read can say which ladder AND which
// basis produced it (the same discipline as RuleSet version for the rules themselves).
const GOAL_POLICY = "v2-rolling-7d-sum";

// Tuning review #30 rec 2 (2026-09-19, user-approved): the phase streak is a
// measurement instrument and it was not reproducible across reviews. Sep 17 read
// +$12.36 (31 legs) in #29 and +$714.75 (38) in #30 — the SAME DAY, two answers,
// because a day's bucket keeps growing for a few days after it ends (positions
// that closed on that date keep being booked as their exits/resolutions are
// discovered). A day that clears the $500 bar was therefore banked as a MISS on
// the day it happened, and no review could reproduce another review's streak.
//
// Convention now stated in the output itself:
//   T+0        = bucket by closedAt ?? resolvedAt as the rows stand RIGHT NOW.
//                Today's bucket is PROVISIONAL by construction.
//   settled    = the same buckets, restricted to days that have had SETTLE_DAYS
//                to finish booking (T-1 … T-SETTLE_DAYS excluded). This is the
//                basis a phase ADVANCE is judged on; the T+0 streak is reported
//                alongside it because it is what a same-day report prints.
// Measurement only — no gate, threshold or trading behavior lives here.
const SETTLE_DAYS = 3;

// As-recorded history: the one thing the DB cannot reconstruct. Each run stores
// TODAY's T+0 read for today's date; a later run (≥SETTLE_DAYS on) can then diff
// "what the day read at T+0" against "what it settled at".
const HISTORY_FILE = path.join(__dirname, 'data', 'phase-streak-history.json');

// Tuning #31 rec 1 (2026-09-20, user-approved): an IMMUTABLE as-recorded series.
// HISTORY_FILE is a per-day map that every run OVERWRITES, so the value a day read
// at 18:00 is gone by the next run — which is what makes 'the daily read moved'
// unfalsifiable across reviews. This log only ever appends: one row per run per
// recent day, carrying BOTH day conventions (the gate's local calendar day and the
// UTC day an ad-hoc review SQL returns), so a later review can diff as-recorded vs
// re-read AND tell instantly which basis it is quoting.
const AS_RECORDED_LOG = path.join(__dirname, 'data', 'phase-streak-log.jsonl');
// Days still capable of moving (today + the settle window); older days are frozen.
const AS_RECORDED_DAYS = SETTLE_DAYS + 1;

function dayKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function readHistory() {
  try {
    return JSON.parse(fs.readFileSync(HISTORY_FILE, 'utf-8'));
  } catch {
    return {};
  }
}

async function main() {
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);

  const bankroll = await prisma.botBankroll.findUnique({
    where: { botId: 'BANKROLL_200' }
  });

  if (!bankroll) {
    console.log("BANKROLL_200 not found");
    process.exit(0);
  }

  // All closed/resolved C-200 trades in the last 14 days. Use the actual close
  // timestamp (closedAt for early exits, resolvedAt for resolved; Unix-ms
  // ints) so daily PnL history and the stability streak are accurate. NOTE: the
  // Kalshi re-price rows re-join this series (kalshi-reprice-92, 2026-09-05) —
  // the TR-17 venue exclusion is lifted.
  const since14 = new Date(startOfDay.getTime() - 13 * 86400000);
  const finished = await prisma.paperTrade.findMany({
    where: {
      botId: 'BANKROLL_200',
      status: { in: ['closed', 'resolved'] },
      OR: [{ closedAt: { gte: since14 } }, { resolvedAt: { gte: since14 } }],
    },
    select: { realizedPnl: true, closedAt: true, resolvedAt: true },
  });

  // Per-day bucket, carrying both the money and the LEG COUNT: the leg count is
  // what makes a "the day moved" claim checkable (`38 legs` not just `+$714.75`),
  // and the closed/resolved split names which convention contributed what.
  const byDay = new Map();
  for (const t of finished) {
    const ts = t.closedAt ?? t.resolvedAt;
    if (!ts) continue;
    const k = dayKey(new Date(ts));
    const e = byDay.get(k) ?? { pnl: 0, legs: 0, closedLegs: 0, resolvedLegs: 0 };
    e.pnl += t.realizedPnl ?? 0;
    e.legs += 1;
    if (t.closedAt) e.closedLegs += 1;
    else e.resolvedLegs += 1;
    byDay.set(k, e);
  }

  // Last 14 days, most recent first (days with no closes = $0 / 0 legs).
  const EMPTY = { pnl: 0, legs: 0, closedLegs: 0, resolvedLegs: 0 };
  const series = [];
  for (let i = 0; i < 14; i++) {
    const d = new Date(startOfDay.getTime() - i * 86400000);
    series.push({ day: dayKey(d), ...(byDay.get(dayKey(d)) ?? EMPTY) });
  }
  const dailyPnl = series.map((s) => s.pnl);

  // Current goal (GOAL_POLICY v2): a phase is CLEARED when the settled rolling
  // GATE_WINDOW_DAYS-day SUM is >= target x GATE_WINDOW_DAYS; the goal advances
  // accordingly. Judged on the SETTLED window (the 7 days ending SETTLE_DAYS back) — the
  // T+0 window is reported when the two disagree.
  const sumOf = (arr) => arr.reduce((a, b) => a + b, 0);
  const gateFrom = (arr) => {
    let idx = 0;
    for (let i = 0; i < PHASES.length; i++) {
      const need = PHASES[i].target * GATE_WINDOW_DAYS;
      if (arr.length === GATE_WINDOW_DAYS && sumOf(arr) >= need) idx = i + 1;
      else break;
    }
    return Math.min(idx, PHASES.length - 1);
  };
  const settledStart = SETTLE_DAYS; // index of the youngest settled day
  const settledWindow = dailyPnl.slice(settledStart, settledStart + GATE_WINDOW_DAYS);
  const goalIdx = gateFrom(settledWindow);
  const goalIdxT0 = gateFrom(dailyPnl.slice(0, GATE_WINDOW_DAYS));
  const goal = PHASES[goalIdx];

  // The gate, printed: the settled rolling sum vs what the CURRENT goal needs.
  const gateNeed = goal.target * GATE_WINDOW_DAYS;
  const gateSumSettled = sumOf(settledWindow);
  const gateSumT0 = sumOf(dailyPnl.slice(0, GATE_WINDOW_DAYS));
  const gatePctSettled = gateNeed > 0 ? (gateSumSettled / gateNeed) * 100 : 0;
  const gatePctT0 = gateNeed > 0 ? (gateSumT0 / gateNeed) * 100 : 0;
  const gateWindowLabel = `${series[settledStart + GATE_WINDOW_DAYS - 1].day} .. ${series[settledStart].day}`;


  // Streaks. T+0 starts at today (index 0); settled starts at the youngest
  // settled day (index SETTLE_DAYS) and can only be as long as the settled data.
  const streakFrom = (start) => {
    let s = 0;
    for (let i = start; i < dailyPnl.length; i++) {
      if (dailyPnl[i] >= goal.target) s++;
      else break;
    }
    return s;
  };
  const streakT0 = streakFrom(0);
  const streakSettled = streakFrom(settledStart);

  const realizedToday = byDay.get(dayKey(startOfDay)) ?? EMPTY;
  const openTrades = await prisma.paperTrade.aggregate({
    where: {
      botId: 'BANKROLL_200',
      status: 'open',
    },
    _sum: { unrealizedPnl: true }
  });
  const openUnrealized = openTrades._sum.unrealizedPnl || 0;

  // As-recorded snapshot of TODAY (overwritten on every run, so the file holds
  // the last read of the current day; past days are frozen once the date rolls).
  const history = readHistory();
  const today = dayKey(startOfDay);
  history[today] = {
    asRecordedPnl: Number(realizedToday.pnl.toFixed(2)),
    legs: realizedToday.legs,
    streakT0,
    recordedAt: new Date().toISOString(),
    convention: 'closedAt ?? resolvedAt, as recorded at this timestamp',
  };
  let historyNote = '';
  try {
    fs.writeFileSync(HISTORY_FILE, JSON.stringify(history, null, 1));
    historyNote = ` · as-recorded history: data/phase-streak-history.json (${Object.keys(history).length} days)`;
  } catch (e) {
    historyNote = ` · as-recorded history write FAILED (${e.message})`;
  }

  // ---- immutable as-recorded log (rec 1) -------------------------------------
  // UTC counterpart of the same buckets, computed once here so the log row and the
  // printed cross-check cannot disagree.
  const utcKey = (d) => d.toISOString().slice(0, 10);
  const byDayUtc = new Map();
  for (const t of finished) {
    const ts = t.closedAt ?? t.resolvedAt;
    if (!ts) continue;
    const k = utcKey(new Date(ts));
    const e = byDayUtc.get(k) ?? { pnl: 0, legs: 0 };
    e.pnl += t.realizedPnl ?? 0;
    e.legs += 1;
    byDayUtc.set(k, e);
  }

  const readLog = () => {
    try {
      return fs
        .readFileSync(AS_RECORDED_LOG, 'utf-8')
        .split('\n')
        .filter((l) => l.trim().length > 0)
        .map((l) => JSON.parse(l));
    } catch {
      return [];
    }
  };
  const priorLog = readLog();
  const appended = [];
  for (let i = 0; i < AS_RECORDED_DAYS; i++) {
    const day = series[i].day;
    const u = byDayUtc.get(day) ?? { pnl: 0, legs: 0 };
    appended.push({
      ts: new Date().toISOString(),
      day,
      // declared convention first: the gate/ladder/Overview local calendar day
      localPnl: Number(series[i].pnl.toFixed(2)),
      localLegs: series[i].legs,
      // the UTC day an ad-hoc review SQL returns (kept so quoting it is explicit)
      utcPnl: Number(u.pnl.toFixed(2)),
      utcLegs: u.legs,
      convention: 'closedAt ?? resolvedAt · local = America/Chicago calendar day',
      ruleSetVersion: null,
    });
  }
  let logNote = '';
  try {
    fs.appendFileSync(AS_RECORDED_LOG, appended.map((r) => JSON.stringify(r)).join('\n') + '\n');
    logNote = ` · immutable log: data/phase-streak-log.jsonl (+${appended.length} rows, ${priorLog.length + appended.length} total)`;
  } catch (e) {
    logNote = ` · immutable log write FAILED (${e.message})`;
  }

  // As-recorded vs now. The baseline is the day's LAST logged read while that day was
  // still current (18:00 in practice) — the figure the day was last reported at — and
  // the live value is the re-read.
  //
  // 2026-11-20 self-audit: this used the FIRST row logged for a day and printed its
  // wall-clock time with no date. That row is written by the ~07:00 run ON the day
  // itself (measured in the live log: the first row for 11-17 is 11-17 06:51, for 11-18
  // it is 11-18 07:01, for 11-19 it is 11-19 07:00), so the "as-recorded" baseline was a
  // SEVEN-HOUR PARTIAL of the day, and `MOVED` fired on every day that settled anything
  // after 7am — i.e. every day, always. Live before → after on the same log:
  //   11-18  `as-recorded 07:01 -109.97 (2)`  → `last-read 11-18 18:00 -129.97 (4)`
  //   11-17  `as-recorded 06:51   +0.00 (0)`  → `last-read 11-17 18:00 -217.86 (15)`
  // A bare HH:MM also could not say WHICH of those two reads a reader was looking at.
  // Days with no logged row say so rather than being omitted; a day whose only reads
  // came from a later day is labelled `first-seen`, not `last-read`.
  const localDayOfTs = (iso) =>
    new Date(iso).toLocaleDateString('en-CA', { timeZone: 'America/Chicago' }); // YYYY-MM-DD
  const localStampOf = (iso) => {
    const hm = new Date(iso).toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/Chicago',
    });
    return `${localDayOfTs(iso).slice(5)} ${hm}`;
  };
  const signed = (n) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}`;
  const rowsByDay = new Map();
  for (const r of priorLog) {
    const l = rowsByDay.get(r.day) ?? [];
    l.push(r);
    rowsByDay.set(r.day, l);
  }
  const asRecorded = series
    .slice(0, 4)
    .map((s) => {
      const rows = (rowsByDay.get(s.day) ?? [])
        .slice()
        .sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
      if (rows.length === 0)
        return `${s.day.slice(5)} baseline (first row recorded now: ${signed(s.pnl)} (${s.legs}))`;
      const inDay = rows.filter((r) => localDayOfTs(r.ts) === s.day);
      const base = inDay.length ? inDay[inDay.length - 1] : rows[0];
      const how = inDay.length ? 'last-read' : 'first-seen';
      const dPnl = s.pnl - base.localPnl;
      const dLegs = s.legs - base.localLegs;
      const moved = Math.abs(dPnl) >= 0.01 || dLegs !== 0;
      return (
        `${s.day.slice(5)} ${how} ${localStampOf(base.ts)} ${signed(base.localPnl)} (${base.localLegs}) → ` +
        `now ${signed(s.pnl)} (${s.legs})` +
        (moved ? ` ⇐ MOVED (${signed(dPnl)} / ${dLegs >= 0 ? '+' : ''}${dLegs} legs)` : '')
      );
    })
    .join(' · ');
  const utcCrossCheck = series
    .slice(0, 3)
    .map((s) => {
      const u = byDayUtc.get(s.day) ?? { pnl: 0, legs: 0 };
      return `${s.day.slice(5)} ${u.pnl >= 0 ? '+' : ''}${u.pnl.toFixed(2)} (${u.legs})`;
    })
    .join(' · ');

  // Days where the T+0 snapshot (recorded then) differs from today's settled
  // read — the settlement drift the settled streak exists to absorb.
  const drift = [];
  for (const s of series.slice(SETTLE_DAYS)) {
    const h = history[s.day];
    if (!h || typeof h.asRecordedPnl !== 'number') continue;
    const d = s.pnl - h.asRecordedPnl;
    if (Math.abs(d) >= 0.01) drift.push(`${s.day} ${h.asRecordedPnl.toFixed(2)} → ${s.pnl.toFixed(2)} (${d >= 0 ? '+' : ''}${d.toFixed(2)})`);
  }

  // v52 (tuning review #19 rec 4, user-approved 2026-09-08):
  //  - "Today's PnL" is REALIZED-only, matching the phase-streak definition
  //    (the gate counts realized closes; open unrealized is mark-to-market of
  //    the whole book, most of it older positions — mixing it into "today"
  //    produced misleading ON TRACK reads like $752.51 with 0/7 days).
  //  - "Current Bankroll" = cashBalance alone: closes increment cash by
  //    (size + pnl) at close time, so today's realized is ALREADY in cash —
  //    adding realizedToday double-counted it (e.g. $581.81 display on a
  //    cash balance that already held the day's closes).
  // Reproduction line: the buckets above are LOCAL calendar days (the same
  // boundary the ladder, the Overview cards and the EOD report use), so the SQL
  // must convert using this machine's own zone rules for EACH row.
  //
  // 2026-11-20 self-audit: this inserted ONE fixed offset, computed from the current
  // moment (`-new Date().getTimezoneOffset()`, -21600 in CST), into every historical
  // row. A fixed offset is only right for the half of the year sharing the current DST
  // state: on CDT days it shifted the day boundary by an hour, so every row closing
  // 23:00-24:00 local landed a day early — and on the printed window that is enough to
  // make the "Reproduce" command disagree with the line above it. Measured, fixed offset
  // vs 'localtime' on this book: 2026-10-22 +$8.21 (6 legs) vs +$101.24 (6 legs);
  // 2026-09-18 +$973.04 (10) vs +$993.70 (12) — the second is the very figure the log
  // comment cites as the correct local read. 2026-09-17: $53.73 vs $12.36.
  // 'localtime' applies the zone's DST rules per row, which is what the JS bucketing does.
  const reproduce = `sqlite3 prisma/dev.db "SELECT date(COALESCE(closedAt,resolvedAt)/1000,'unixepoch','localtime') d, COUNT(*) legs, ROUND(SUM(realizedPnl),2) pnl FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved') GROUP BY d ORDER BY d DESC LIMIT 14;"`;

  console.log(`**C-200 Daily Progress Report**
- **Goal:** $${goal.target}/day (${goal.name}${goalIdx > 0 ? " — CLEARED" : ""})${goalIdx !== goalIdxT0 ? ` — ⚠️ T+0 window would read ${PHASES[goalIdxT0].name}` : ""}
- **Goal policy:** ${GOAL_POLICY} — advance basis = trailing ${GATE_WINDOW_DAYS} SETTLED days SUM >= $${gateNeed.toLocaleString()} (target × ${GATE_WINDOW_DAYS}). Changed 2026-10-12 from "7 consecutive days each >= target": that test was structurally unsatisfiable here (median settled day $0.15; best consecutive run ever 2 days at either $250 or $500; rolling 7d windows clearing $3,500 = 0 of 61).
- **Phase gate (settled rolling ${GATE_WINDOW_DAYS}d SUM — THE ADVANCE BASIS):** $${gateSumSettled.toFixed(2)} vs $${gateNeed.toLocaleString()} needed for $${goal.target}/day (${gatePctSettled.toFixed(1)}%) — ${gateSumSettled >= gateNeed ? "[✅ MET]" : `[❌ SHORT by $${(gateNeed - gateSumSettled).toFixed(2)}]`} — window ${gateWindowLabel}
- **Today's realized PnL:** $${realizedToday.pnl.toFixed(2)} (${realizedToday.legs} legs, PROVISIONAL — settles over ~${SETTLE_DAYS} days)
- **Open unrealized (book mark-to-market):** $${openUnrealized.toFixed(2)}
- **Status:** ${realizedToday.pnl >= goal.target ? '[✅ ON TRACK]' : '[❌ BEHIND]'}
- **Phase stability (settled, T+3 — REPORTED ONLY, NOT the advance basis):** ${streakSettled}/${STABILITY_DAYS} consecutive days at $${goal.target}/day from ${series[settledStart].day} back — last ${SETTLE_DAYS} days excluded while they settle. Kept because the daily reviews quote it and it is the day-to-day consistency instrument; the gate above is what a phase advance is judged on.
- **Phase stability (T+0):** ${streakT0}/${STABILITY_DAYS} consecutive days at $${goal.target}/day — convention: closedAt ?? resolvedAt, read NOW, today provisional
- **Phase gate (T+0 rolling ${GATE_WINDOW_DAYS}d sum, provisional):** $${gateSumT0.toFixed(2)} vs $${gateNeed.toLocaleString()} (${gatePctT0.toFixed(1)}%) — today's bucket still settles
- **Daily realized (T+0 read, most recent first):** ${series.map((s) => `${s.day.slice(5)} ${s.pnl >= 0 ? '+' : ''}${s.pnl.toFixed(2)} (${s.legs})`).join(" · ")}${drift.length ? `
- **Settlement drift (recorded T+0 → settled now):** ${drift.join(" · ")}` : ''}${historyNote}
- **As-recorded vs now (baseline = that day's LAST read while it was still that day — not a post-settlement read; immutable \`data/phase-streak-log.jsonl\`):** ${asRecorded}${logNote}
- **Cross-check, UTC basis (what an ad-hoc \`date(ts/1000,'unixepoch')\` returns — do NOT compare it to the line above):** ${utcCrossCheck}
- **Current Bankroll (cash):** $${bankroll.cashBalance.toFixed(2)}
- **Reproduce:** \`${reproduce}\``);
}

main().finally(() => prisma.$disconnect());
