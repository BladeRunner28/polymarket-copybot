const { PrismaClient } = require('@prisma/client');
const fs = require('fs');
const path = require('path');
const prisma = new PrismaClient();

// C-200 phase goals — each phase requires STABILITY_DAYS consecutive days at
// target before advancing to the next (user policy, 2026-08-31).
const PHASES = [
  { name: "Phase 1", target: 500 },
  { name: "Phase 2", target: 1000 },
  { name: "Phase 3", target: 2000 },
  { name: "Ultimate", target: 5000 },
];
const STABILITY_DAYS = 7;

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

  // Current goal: a phase is CLEARED only after its target held for
  // STABILITY_DAYS consecutive days; the goal advances accordingly. Judged on the
  // SETTLED window (the 7 days ending SETTLE_DAYS back) — the T+0 window is
  // reported when the two disagree.
  const goalFrom = (arr) => {
    let idx = 0;
    for (let i = 0; i < PHASES.length; i++) {
      if (arr.length === STABILITY_DAYS && arr.every((d) => d >= PHASES[i].target)) idx = i + 1;
      else break;
    }
    return Math.min(idx, PHASES.length - 1);
  };
  const settledStart = SETTLE_DAYS; // index of the youngest settled day
  const settledWindow = dailyPnl.slice(settledStart, settledStart + STABILITY_DAYS);
  const goalIdx = goalFrom(settledWindow);
  const goalIdxT0 = goalFrom(dailyPnl.slice(0, STABILITY_DAYS));
  const goal = PHASES[goalIdx];

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

  // As-recorded vs now: the FIRST row logged for a day is what it read when the log
  // first saw it (T+0); the live value is the re-read. Days with no row predate the
  // log and are reported as such rather than silently omitted.
  const firstByDay = new Map();
  for (const r of priorLog) {
    if (!firstByDay.has(r.day)) firstByDay.set(r.day, r);
  }
  const asRecorded = series
    .slice(0, 4)
    .map((s) => {
      const f = firstByDay.get(s.day);
      if (!f)
        return `${s.day.slice(5)} baseline (first row recorded now: ${s.pnl >= 0 ? '+' : ''}${s.pnl.toFixed(2)} (${s.legs}))`;
      const when = new Date(f.ts).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/Chicago' });
      const moved = Math.abs(f.localPnl - s.pnl) >= 0.01 || f.localLegs !== s.legs;
      return (
        `${s.day.slice(5)} as-recorded ${when} ${f.localPnl >= 0 ? '+' : ''}${f.localPnl.toFixed(2)} (${f.localLegs}) → ` +
        `now ${s.pnl >= 0 ? '+' : ''}${s.pnl.toFixed(2)} (${s.legs})${moved ? ' ⇐ MOVED' : ''}`
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
  // must carry this machine's UTC offset — a bare `date(ts/1000,'unixepoch')`
  // reproduces the UTC-day numbers instead and silently disagrees (the documented
  // "day boundaries differ by query" trap).
  const offSec = -new Date().getTimezoneOffset() * 60; // CDT = -18000
  const offsetExpr = offSec === 0 ? '' : `${offSec > 0 ? '+' : '-'}${Math.abs(offSec)}`;
  const reproduce = `sqlite3 prisma/dev.db "SELECT date((COALESCE(closedAt,resolvedAt)/1000)${offsetExpr},'unixepoch') d, COUNT(*) legs, ROUND(SUM(realizedPnl),2) pnl FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved') GROUP BY d ORDER BY d DESC LIMIT 14;"`;

  console.log(`**C-200 Daily Progress Report**
- **Goal:** $${goal.target}/day (${goal.name}${goalIdx > 0 ? " — CLEARED" : ""})${goalIdx !== goalIdxT0 ? ` — ⚠️ T+0 window would read ${PHASES[goalIdxT0].name}` : ""}
- **Today's realized PnL:** $${realizedToday.pnl.toFixed(2)} (${realizedToday.legs} legs, PROVISIONAL — settles over ~${SETTLE_DAYS} days)
- **Open unrealized (book mark-to-market):** $${openUnrealized.toFixed(2)}
- **Status:** ${realizedToday.pnl >= goal.target ? '[✅ ON TRACK]' : '[❌ BEHIND]'}
- **Phase stability (T+0):** ${streakT0}/${STABILITY_DAYS} consecutive days at $${goal.target}/day — convention: closedAt ?? resolvedAt, read NOW, today provisional
- **Phase stability (settled, T+3):** ${streakSettled}/${STABILITY_DAYS} consecutive days at $${goal.target}/day from ${series[settledStart].day} back — last ${SETTLE_DAYS} days excluded while they settle; THIS is the basis a phase advance is judged on
- **Daily realized (T+0 read, most recent first):** ${series.map((s) => `${s.day.slice(5)} ${s.pnl >= 0 ? '+' : ''}${s.pnl.toFixed(2)} (${s.legs})`).join(" · ")}${drift.length ? `
- **Settlement drift (recorded T+0 → settled now):** ${drift.join(" · ")}` : ''}${historyNote}
- **As-recorded vs now (declared basis = local, immutable \`data/phase-streak-log.jsonl\`):** ${asRecorded}${logNote}
- **Cross-check, UTC basis (what an ad-hoc \`date(ts/1000,'unixepoch')\` returns — do NOT compare it to the line above):** ${utcCrossCheck}
- **Current Bankroll (cash):** $${bankroll.cashBalance.toFixed(2)}
- **Reproduce:** \`${reproduce}\``);
}

main().finally(() => prisma.$disconnect());
