/**
 * research:source-liveness — does the sentiment layer still GET its supply?
 *
 * READ-ONLY apart from the alarm state file. Card `research-source-silent-death`
 * (2026-11-15, Lane B). The card was written after measuring that
 * `quiver_congress_trade` had emitted nothing for 70 days and
 * `govinfo_fr_notice` had emitted 1,210 rows of pure 0.0 — and that neither fact
 * was on any surface. `research:source-supply-read` answers "what does the set
 * contain"; this answers "is it still arriving, and can it move a number at all".
 *
 * BASIS printed with every run: population = RegulatorySignal rows (this table
 * has no demo concept — the layer reads every row), clock = processedAt UTC,
 * level = one source. "opinionated" = |sentimentScore| >= 0.30, the same
 * threshold the aggregation uses, so "inert" means "cannot change the delta",
 * not "looks boring".
 *
 * Usage:
 *   npx tsx scripts/research-source-liveness-check.ts [--days 7] [--self-test] [--json] [--page] [--strict]
 *
 *   --page    deliver a Discord page for paging sources (deduped: on entry, on
 *             state change, then at most once per 24h)
 *   --strict  exit 1 when any source is paging, so a cron can gate on it
 */
import { prisma } from "../src/lib/db";
import { sendDiscord } from "../src/lib/discord";
import { logError } from "../src/lib/redact";
import {
  DEFAULT_RE_PAGE_HOURS,
  LIVENESS_OPINIONATED_THRESHOLD as T,
  classifyAll,
  livenessLine,
  markPaged,
  planPages,
  type AlarmState,
  type SourceEmission,
} from "../src/lib/source-liveness";
import { readSourceEmissions } from "../src/lib/source-liveness-read";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const args = process.argv.slice(2);
const SELF_TEST = args.includes("--self-test");
const JSON_OUT = args.includes("--json");
const PAGE = args.includes("--page");
const STRICT = args.includes("--strict");
const daysIdx = args.indexOf("--days");
const WINDOW_DAYS = daysIdx >= 0 ? Number(args[daysIdx + 1]) : 7;

const DATA_DIR = join(__dirname, "..", "data");
const STATE_FILE = join(DATA_DIR, "source-liveness-alarm.json");
const ARTIFACT = join(DATA_DIR, "research-source-liveness.json");

function pct(n: number, d: number): string {
  return d === 0 ? "n/a" : `${((100 * n) / d).toFixed(1)}%`;
}

function readState(): AlarmState {
  if (!existsSync(STATE_FILE)) return {};
  try {
    const v = JSON.parse(readFileSync(STATE_FILE, "utf8"));
    return v && typeof v === "object" ? (v as AlarmState) : {};
  } catch {
    // A corrupt state file must not silence the alarm: treat it as "no history",
    // which re-pages everything still in a paging state.
    console.log("  ⚠️  alarm state unreadable — treating as no history (will re-page)");
    return {};
  }
}

/**
 * Self-test: proves the detector can FAIL, on both cases the card names.
 *
 * The negative control is the one that matters — feeding the same govinfo set
 * through the OLD reading (rows only, i.e. opinionatedRows := rows) makes it
 * read OK. That is the defect with a demonstration attached: a row count cannot
 * distinguish a contributing source from an inert one.
 */
function selfTest(): void {
  const now = new Date("2026-11-16T02:00:00Z");
  const h = (n: number) => new Date(now.getTime() - n * 3_600_000);
  const checks: Array<[string, boolean, string]> = [];

  const live: SourceEmission = {
    source: "congress_gov_api", rows: 1_520, opinionatedRows: 1_520, windowRows: 20, windowOpinionated: 20, lastEmitAt: h(4.2),
  };
  const dead: SourceEmission = {
    source: "quiver_congress_trade", rows: 190, opinionatedRows: 190, windowRows: 0, windowOpinionated: 0,
    lastEmitAt: new Date("2026-09-06T22:46:13Z"),
  };
  const inert: SourceEmission = {
    source: "govinfo_fr_notice", rows: 1_210, opinionatedRows: 0, windowRows: 13, windowOpinionated: 0, lastEmitAt: h(4.2),
  };

  const [cls] = classifyAll([live], now);
  checks.push(["live source reads OK", cls.status === "OK" && !cls.pageRequired, cls.status]);

  const [deadRead] = classifyAll([dead], now);
  checks.push(["STOPPED source pages (SILENT)", deadRead.status === "SILENT" && deadRead.pageRequired, deadRead.status]);
  checks.push(
    ["silent reason carries the clock", deadRead.reasons.join().includes("2026-09-06T22:46:13.000Z"), deadRead.reasons[0]],
  );

  const [inertRead] = classifyAll([inert], now);
  checks.push(["NEVER-CONTRIBUTING source pages (INERT)", inertRead.status === "INERT" && inertRead.pageRequired, inertRead.status]);

  // NEGATIVE CONTROL: the old rows-only reading of the same inert source.
  const [oldReading] = classifyAll([{ ...inert, opinionatedRows: inert.rows }], now);
  checks.push(
    ["control: a rows-only reading MISSES the inert source", oldReading.status === "OK" && !oldReading.pageRequired, oldReading.status],
  );

  const line = livenessLine(classifyAll([live, dead, inert], now), now);
  // 2026-11-21: the header no longer says "NOT SUPPLYING" for every paging source — an INERT source
  // emits and still pages. Assert the split AND the source name, which is what the reader needs.
  checks.push([
    "report line names the alarm",
    line.includes("1/3 SILENT (not supplying)") && line.includes("1 INERT (supplying, zero weight)") &&
      line.includes("quiver_congress_trade"),
    line.slice(0, 80),
  ]);
  checks.push(["report line keeps its basis", line.includes("clock=processedAt UTC") && line.includes("level=source"), ""]);

  // Paging: entry pages, repeat within 24h does not, relapse after recovery does.
  const readings = classifyAll([dead], now);
  const first = planPages(readings, {}, now);
  checks.push(["entry pages", first.pages[0]?.send === true, first.pages[0]?.why]);
  const afterPage = markPaged(first.nextState, "quiver_congress_trade", now);
  const again = planPages(readings, afterPage, new Date(now.getTime() + 3 * 3_600_000));
  checks.push(["repeat within 24h is suppressed", again.pages[0]?.send === false, again.pages[0]?.why]);
  const later = planPages(readings, afterPage, new Date(now.getTime() + (DEFAULT_RE_PAGE_HOURS + 1) * 3_600_000));
  checks.push(["re-page after the window", later.pages[0]?.send === true, later.pages[0]?.why]);
  const recovered = planPages(classifyAll([live], now), afterPage, now);
  checks.push(["recovery drops the entry", recovered.pages.length === 0 && Object.keys(recovered.nextState).length === 0, ""]);

  let failed = 0;
  for (const [name, ok, detail] of checks) {
    if (!ok) failed++;
    console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` (${String(detail).slice(0, 90)})` : ""}`);
  }
  console.log(`\nself-test ${checks.length - failed}/${checks.length}`);
  if (failed > 0) process.exit(1);
}

async function main() {
  if (SELF_TEST) return selfTest();

  const now = new Date();
  const since = new Date(now.getTime() - WINDOW_DAYS * 86_400_000);

  console.log(
    `BASIS  population=RegulatorySignal rows (all sources; the layer reads every row)  ` +
      `clock=processedAt UTC  level=one source  window=${WINDOW_DAYS}d to ${now.toISOString()}`
  );
  console.log(
    `       "opinionated" = |sentimentScore| >= ${T} (the aggregation's own threshold)  ` +
      `|  silence policy per source: 24h = 4x the 6h poller cadence measured 2026-11-15\n`
  );

  const emissions = await readSourceEmissions(since);

  const readings = classifyAll(emissions, now);

  console.log("-- SOURCES");
  console.log(
    `   ${"source".padEnd(24)}${"rows".padStart(7)}${"opin".padStart(7)}${"op%".padStart(7)}` +
      `${"win".padStart(6)}${"win op".padStart(7)}  ${"last emit".padEnd(26)}status`
  );
  for (const r of readings) {
    console.log(
      `   ${r.source.padEnd(24)}${String(r.rows).padStart(7)}${String(r.opinionatedRows).padStart(7)}` +
        `${pct(r.opinionatedRows, r.rows).padStart(7)}${String(r.windowRows).padStart(6)}` +
        `${String(r.windowOpinionated).padStart(7)}  ${(r.lastEmitAt ?? "never").padEnd(26)}` +
        `${r.status}${r.policyMeasured ? "" : " (unmeasured policy)"}`
    );
  }
  console.log();

  console.log(livenessLine(readings, now));
  for (const r of readings) {
    if (r.pageRequired) console.log(`[ALARM] ${r.source}: ${r.reasons.join("; ")}`);
  }
  if (!readings.some((r) => r.pageRequired)) console.log("[ALARM] none — every source is emitting and can carry a sign");

  // ---- paging ----
  const state = readState();
  const { pages, nextState } = planPages(readings, state, now);
  for (const p of pages) {
    console.log(`[PAGE] ${p.source} ${p.status} — ${p.why}`);
  }

  let delivered = nextState;
  if (PAGE && pages.some((p) => p.send)) {
    const toSend = pages.filter((p) => p.send);
    const body =
      `**⚠️ Research source not supplying (${toSend.length})**\n` +
      toSend.map((p) => `• **${p.source}** ${p.status}: ${p.reason}`).join("\n") +
      `\n_Basis: RegulatorySignal, clock=processedAt UTC, level=source; ` +
      `opinionated = |polarity| >= ${T}; silence policy 24h (4x the measured 6h poller cadence)._`;
    const ok = await sendDiscord(body);
    if (!ok) {
      // A failed page must not look like a delivered one (2026-11-13 defect class).
      logError("❌ research:source-liveness page FAILED — alarm is real and undelivered");
      if (!STRICT) process.exitCode = 1;
    } else {
      for (const p of toSend) delivered = markPaged(delivered, p.source, now);
    }
  }

  writeFileSync(
    STATE_FILE,
    JSON.stringify(
      {
        generatedAt: now.toISOString(),
        rePageHours: DEFAULT_RE_PAGE_HOURS,
        sources: delivered,
      },
      null,
      2
    ) + "\n"
  );

  if (JSON_OUT) {
    const out = {
      generatedAt: now.toISOString(),
      windowDays: WINDOW_DAYS,
      basis: {
        population: "RegulatorySignal rows",
        clock: "processedAt UTC",
        level: "one source",
        opinionatedThreshold: T,
      },
      readings,
      pages,
    };
    writeFileSync(ARTIFACT, JSON.stringify(out, null, 2) + "\n");
    console.log(`\nwrote ${ARTIFACT}`);
  }

  if (STRICT && readings.some((r) => r.pageRequired)) process.exitCode = 1;
}

main()
  .catch((e) => {
    logError("research:source-liveness FAILED:", e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
