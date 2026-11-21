/**
 * Research-source liveness — a source that stops, or that never starts
 * contributing, must PAGE, not vanish.
 *
 * Card `research-source-silent-death` (2026-11-15, Lane B instrument repair).
 * Measured when the card was written (population = RegulatorySignal, clock =
 * processedAt UTC, level = one source): `quiver_congress_trade` had emitted
 * nothing for 70 days and `govinfo_fr_notice` had emitted 1,210 rows whose
 * polarity is 0.0 on every one of them. Neither fact appeared anywhere: the
 * arm that consumes this layer prints ROW counts, and a row count cannot tell
 * a live feed from a dead one or from a feed that is structurally incapable of
 * moving a number. The layer's own audit (`research:source-supply-read`) also
 * could not say it, because it reports what the set CONTAINS, never whether
 * the set is still arriving.
 *
 * Three independent questions, three independent answers:
 *
 *   is it still emitting?     silence vs a policy derived from the poller's
 *                             measured cadence (see SOURCE_LIVENESS_POLICY)
 *   can it move a number?     has it EVER emitted a row with |polarity| >= the
 *                             aggregation threshold (0.3)? A feed at 0.0 forever
 *                             is neutrally-weighted by construction: zero weight
 *   therefore: page?          every state except OK carries a reason and pages
 *
 * Pure functions only: no DB, no clock of its own, no Discord. The script
 * `scripts/research-source-liveness-check.ts` supplies the rows and delivers
 * the page; `src/lib/report.ts` renders the same reading into the EOD report so
 * the state is visible even on a day nobody opens the dashboard.
 */

export type LivenessStatus = "OK" | "NEVER_EMITTED" | "SILENT" | "INERT" | "SILENT_INERT";

/** The aggregation's opinionated threshold (matches forecasting/sentiment). */
export const LIVENESS_OPINIONATED_THRESHOLD = 0.3;

export interface SourcePolicy {
  /** Expected poll interval, hours — the cadence a silence is measured against. */
  cadenceHours: number;
  /** Silence beyond this is an alarm. */
  maxSilenceHours: number;
}

/**
 * Per-source policy. BASIS for the numbers, measured 2026-11-15 over the last
 * 30 complete days of RegulatorySignal cycles (a cycle = rows separated by less
 * than 30 min): congress_gov_api 110 cycles, min gap 6.01 h, mean 6.51 h, max
 * 18.05 h; govinfo_fr_notice 118 cycles, min 6.01 h, mean 6.07 h, max 12.04 h.
 * The poller is therefore a 6 h job, and its own worst observed gap (18.05 h =
 * one missed cycle) sets the floor: 24 h = 4 cycles is above every gap this
 * source has produced in 30 days, so a 24 h alarm is a real failure, not a
 * missed cycle. A source added later inherits DEFAULT_SOURCE_POLICY and says
 * so (its cadence has not been measured, and the reading is labelled assumed).
 */
export const SOURCE_LIVENESS_POLICY: Record<string, SourcePolicy> = {
  congress_gov_api: { cadenceHours: 6, maxSilenceHours: 24 },
  govinfo_fr_notice: { cadenceHours: 6, maxSilenceHours: 24 },
  quiver_congress_trade: { cadenceHours: 6, maxSilenceHours: 24 },
  reddit_trumpstrades: { cadenceHours: 6, maxSilenceHours: 24 },
};

export const DEFAULT_SOURCE_POLICY: SourcePolicy = { cadenceHours: 6, maxSilenceHours: 24 };

/** What one source looks like from the DB right now. */
export interface SourceEmission {
  source: string;
  /** All-time rows from this source. */
  rows: number;
  /** All-time rows with |sentimentScore| >= LIVENESS_OPINIONATED_THRESHOLD. */
  opinionatedRows: number;
  /** Rows inside the reporting window. */
  windowRows: number;
  /** Rows inside the window with |sentimentScore| >= the threshold. */
  windowOpinionated: number;
  /** Newest processedAt, or null if the source has never written. */
  lastEmitAt: Date | null;
}

export interface SourceLiveness {
  source: string;
  status: LivenessStatus;
  /** Hours since the newest emit; null when the source has never emitted. */
  silentHours: number | null;
  policy: SourcePolicy;
  /** False when the policy was inherited rather than measured for this source. */
  policyMeasured: boolean;
  rows: number;
  opinionatedRows: number;
  windowRows: number;
  windowOpinionated: number;
  lastEmitAt: string | null;
  /** Human-readable cause(s), always naming the numbers they rest on. */
  reasons: string[];
  pageRequired: boolean;
}

function hoursBetween(from: Date, to: Date): number {
  return (to.getTime() - from.getTime()) / 3_600_000;
}

/** One source → one reading. Never throws; an unreadable input is a reason, not a crash. */
export function classifySource(
  e: SourceEmission,
  now: Date,
  policy?: SourcePolicy
): SourceLiveness {
  const measured = Object.prototype.hasOwnProperty.call(SOURCE_LIVENESS_POLICY, e.source);
  const p = policy ?? (measured ? SOURCE_LIVENESS_POLICY[e.source] : DEFAULT_SOURCE_POLICY);

  // A last emit in the future (clock skew between the poller and this host) is
  // reported as 0 hours, not as a negative age that silently passes every test.
  const silentHoursRaw = e.lastEmitAt ? hoursBetween(e.lastEmitAt, now) : null;
  const silentHours = silentHoursRaw === null ? null : Math.max(0, silentHoursRaw);

  const reasons: string[] = [];

  const neverEmitted = e.rows === 0 || e.lastEmitAt === null;
  if (neverEmitted) {
    reasons.push(`has never emitted a row (0 rows all-time)`);
  } else if (silentHours !== null && silentHours > p.maxSilenceHours) {
    const days = silentHours / 24;
    reasons.push(
      `SILENT ${silentHours.toFixed(1)}h (${days.toFixed(1)}d) since ${e.lastEmitAt!.toISOString()} ` +
        `— policy ${p.maxSilenceHours}h (${(p.maxSilenceHours / p.cadenceHours).toFixed(0)}× its ${p.cadenceHours}h cadence)`
    );
  }

  // "can it move a number at all": the aggregation weights a row by its polarity,
  // so a source whose every row is 0.0 is in the set and worth nothing in it.
  const inert = e.rows > 0 && e.opinionatedRows === 0;
  if (inert) {
    reasons.push(
      `INERT — ${e.rows.toLocaleString("en-US")} rows all-time (${e.windowRows.toLocaleString("en-US")} in the window) and 0 with |polarity| >= ` +
        `${LIVENESS_OPINIONATED_THRESHOLD}, so it can never change the aggregated delta`
    );
  }

  let status: LivenessStatus;
  if (neverEmitted) status = "NEVER_EMITTED";
  else if (inert && reasons.length > 1) status = "SILENT_INERT";
  else if (inert) status = "INERT";
  else if (reasons.length > 0) status = "SILENT";
  else status = "OK";

  return {
    source: e.source,
    status,
    silentHours,
    policy: p,
    policyMeasured: measured,
    rows: e.rows,
    opinionatedRows: e.opinionatedRows,
    windowRows: e.windowRows,
    windowOpinionated: e.windowOpinionated,
    lastEmitAt: e.lastEmitAt ? e.lastEmitAt.toISOString() : null,
    reasons,
    pageRequired: status !== "OK",
  };
}

export function classifyAll(
  emissions: SourceEmission[],
  now: Date,
  policies: Record<string, SourcePolicy> = SOURCE_LIVENESS_POLICY
): SourceLiveness[] {
  return emissions
    .map((e) => {
      const p = Object.prototype.hasOwnProperty.call(policies, e.source)
        ? policies[e.source]
        : undefined;
      return classifySource(e, now, p);
    })
    .sort((a, b) => {
      // Alarm first, then by silence (worst first) so the reader sees the problem
      // before the healthy line.
      if (a.pageRequired !== b.pageRequired) return a.pageRequired ? -1 : 1;
      return (b.silentHours ?? Number.MAX_SAFE_INTEGER) - (a.silentHours ?? Number.MAX_SAFE_INTEGER);
    });
}

function ageText(h: number | null): string {
  if (h === null) return "never";
  if (h < 1) return `${Math.round(h * 60)}m ago`;
  if (h < 48) return `${h.toFixed(1)}h ago`;
  return `${(h / 24).toFixed(1)}d ago`;
}

/**
 * The one-line reading for a report. Named bases, per HERMES.md: population,
 * clock and level are all in the text, and a paging source is named rather
 * than averaged into a healthy-looking total.
 */
export function livenessLine(readings: SourceLiveness[], now: Date): string {
  void now;
  if (readings.length === 0) {
    return `• ⚠️ Research sources (RegulatorySignal, clock=processedAt UTC, level=source): NONE readable — the layer's supply cannot be judged`;
  }
  const parts = readings.map((r) => {
    const head =
      r.status === "OK"
        ? `${r.source} ✅`
        : `${r.source} ⚠️ ${r.status}`;
    return (
      `${head} (${r.windowRows} rows/win, ${r.opinionatedRows.toLocaleString("en-US")} opinionated ` +
      `all-time, last ${ageText(r.silentHours)})`
    );
  });
  const alarms = readings.filter((r) => r.pageRequired);
  if (alarms.length === 0) {
    return `• Research sources (RegulatorySignal, clock=processedAt UTC, level=source): ${parts.join(" · ")}`;
  }
  // The reason is the page: a status word alone would be the same silent label
  // the card exists to kill.
  const why = alarms.map((r) => `${r.source}: ${r.reasons.join("; ")}`).join(" | ");
  const ok = readings.length - alarms.length;
  // 2026-11-21 self-audit: the header read `${alarms.length}/${readings.length} NOT SUPPLYING`,
  // and `alarms` includes INERT — a source that IS emitting on schedule but whose every row has
  // zero weight. Live that day: govinfo_fr_notice had written 96 rows in the 7d window and last
  // emitted 2.6h earlier, and the EOD said "3/4 NOT SUPPLYING" about it. Two different faults
  // (stopped emitting, cannot move a number) with one label is the same lie in a new costume;
  // each is counted and named separately here, and the INERT reason now prints its window rows so
  // "supplying but worth nothing" can be read off the line.
  const silentAlarms = alarms.filter((r) => r.status !== "INERT");
  const inertAlarms = alarms.filter((r) => r.status === "INERT");
  const head: string[] = [];
  if (silentAlarms.length > 0) {
    head.push(`${silentAlarms.length}/${readings.length} SILENT (not supplying)`);
  }
  if (inertAlarms.length > 0) {
    head.push(`${inertAlarms.length} INERT (supplying, zero weight)`);
  }
  return (
    `• ⚠️ Research sources — ${head.join(" + ")} ` +
    `(RegulatorySignal, clock=processedAt UTC, level=source): ${why}` +
    (ok > 0 ? ` | OK: ${ok}` : "")
  );
}

// ---------------------------------------------------------------------------
// Paging decision — pure, so "did the page go out?" is a test and not a hope.
//
// The defect class this closes is the SILENT ALERT: an alarm that fires once,
// gets read past, and never repeats is indistinguishable from no alarm, and an
// alarm that repeats every run is noise nobody reads. The rule here is: page on
// ENTRY to a paging state, on CHANGE of state, and then repeat at most once per
// window. Recovery removes the entry, so a source that dies again pages again
// immediately.
// ---------------------------------------------------------------------------

export interface AlarmStateEntry {
  status: LivenessStatus;
  /** When this source was first seen in this status. */
  firstSeenAt: string;
  /** When a page for this status was last actually DELIVERED (null = never). */
  lastPagedAt: string | null;
}

export type AlarmState = Record<string, AlarmStateEntry>;

export interface PageDecision {
  source: string;
  status: LivenessStatus;
  reason: string;
  /** True when this run must deliver a page. */
  send: boolean;
  /** Why — printed either way, so a suppressed page is visible as suppressed. */
  why: string;
}

export const DEFAULT_RE_PAGE_HOURS = 24;

export function planPages(
  readings: SourceLiveness[],
  state: AlarmState,
  now: Date,
  rePageHours = DEFAULT_RE_PAGE_HOURS
): { pages: PageDecision[]; nextState: AlarmState } {
  const pages: PageDecision[] = [];
  const nextState: AlarmState = {};

  for (const r of readings) {
    const prev = state[r.source];
    if (!r.pageRequired) {
      // Recovered (or never alarmed): the entry is dropped so a relapse is a NEW
      // alarm, not a suppressed repeat of an old one.
      continue;
    }
    const reason = r.reasons.join("; ");
    const firstSeenAt = prev && prev.status === r.status ? prev.firstSeenAt : now.toISOString();
    let send = false;
    let why: string;
    if (!prev) {
      send = true;
      why = "new alarm";
    } else if (prev.status !== r.status) {
      send = true;
      why = `state changed ${prev.status} -> ${r.status}`;
    } else if (!prev.lastPagedAt) {
      send = true;
      why = "never delivered";
    } else {
      const sinceH = (now.getTime() - new Date(prev.lastPagedAt).getTime()) / 3_600_000;
      if (sinceH >= rePageHours) {
        send = true;
        why = `re-page after ${sinceH.toFixed(1)}h`;
      } else {
        why = `suppressed — paged ${sinceH.toFixed(1)}h ago, window ${rePageHours}h`;
      }
    }
    nextState[r.source] = { status: r.status, firstSeenAt, lastPagedAt: prev?.lastPagedAt ?? null };
    pages.push({ source: r.source, status: r.status, reason, send, why });
  }

  return { pages, nextState };
}

/** Records a DELIVERED page. Call only after the transport returned success. */
export function markPaged(state: AlarmState, source: string, now: Date): AlarmState {
  const entry = state[source];
  if (!entry) return state;
  return { ...state, [source]: { ...entry, lastPagedAt: now.toISOString() } };
}
