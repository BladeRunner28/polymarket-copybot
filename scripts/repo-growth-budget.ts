/**
 * repo-growth-budget — measure how fast this repo grows in git OBJECT bytes, and say
 * whether that is inside policy. Read-only: it never prunes, untracks, gc-s or
 * rewrites. Evidence for the `kalshi-tape-repo-size-policy` card.
 *
 *   npx tsx scripts/repo-growth-budget.ts --days 7
 *   npx tsx scripts/repo-growth-budget.ts --days 14 --quiet   # cron: prints only on warn/alarm
 *
 * WHY NOT THE TREE DELTA: the card this replaces quoted 25-35 MB/day, which is the
 * day-over-day growth of the tracked TREE. Git does not pay that. It pays for every
 * blob that ever entered the object store, so a 56 MB append-only tape rewritten on
 * each of several commits a day adds 56 MB per commit. This script attributes, for
 * each UTC day, the on-disk size of every blob NEWLY added that day (git diff-tree
 * --raw against the first parent, then one batched cat-file). It also separates
 * CHURN (a path committed more than once in the same day) from first-content, so the
 * report cannot blame the tape for bytes the commit cadence caused.
 *
 * BASIS printed on every run: window (complete UTC days), level (blob), clock
 * (commit dates at HEAD when the script ran).
 */

import { execFileSync } from "child_process";
import * as fs from "fs";
import { join } from "path";
import {
  budgetVerdict,
  churnBytes,
  classTotals,
  classifyTrackedPath,
  DEFAULT_ALARM_DAYS,
  DEFAULT_CEILING_BYTES,
  DEFAULT_DAILY_BUDGET_BYTES,
  summariseGrowth,
  topContributors,
  type PathClass,
} from "../src/lib/repo-growth-budget";

const REPO = join(__dirname, "..");
const OUT = join(REPO, "data", "repo-growth-budget-read.json");

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}
const flag = (name: string) => process.argv.includes(`--${name}`);

const DAYS = Math.max(2, Number(arg("days", "7")));
const CEILING = Math.round(Number(arg("ceiling-mb", String(DEFAULT_CEILING_BYTES / 1048576))) * 1048576);
const BUDGET = Math.round(Number(arg("budget-mb", String(DEFAULT_DAILY_BUDGET_BYTES / 1048576))) * 1048576);
const ALARM_DAYS = Number(arg("alarm-days", String(DEFAULT_ALARM_DAYS)));
const QUIET = flag("quiet");

function git(args: string[], input?: string): string {
  return execFileSync("git", args, {
    cwd: REPO,
    encoding: "utf8",
    maxBuffer: 256 * 1024 * 1024,
    input,
  });
}

const mib = (b: number) => `${(b / 1048576).toFixed(1)} MiB`;
const mb = (b: number) => `${(b / 1048576).toFixed(0)} MB`;

type Entry = { path: string; bytes: number };
type Write = { sha: string; path: string; date: string };

// --- 1. tracked tree at HEAD, with sizes -------------------------------------
const headEntries: Entry[] = git(["ls-tree", "-r", "-l", "HEAD"])
  .split("\n")
  .filter(Boolean)
  .map((line) => {
    const tab = line.indexOf("\t");
    const meta = line.slice(0, tab).split(/ +/);
    return { path: line.slice(tab + 1), bytes: Number(meta[3]) || 0 };
  });
const headTrackedBytes = headEntries.reduce((a, e) => a + e.bytes, 0);
const headClasses = classTotals(headEntries);

// --- 2. commits in the window (skip merges: their diff is not a single write) --
type Commit = { sha: string; date: string; parents: string[] };
const commits: Commit[] = git(["log", `--since=${DAYS + 3}.days`, "--date=short", "--pretty=format:%H %ad %P"])
  .split("\n")
  .filter(Boolean)
  .map((l) => {
    const [sha, date, ...parents] = l.trim().split(/ +/);
    return { sha, date, parents };
  })
  .filter((c) => c.parents.length === 1);

const nowLocal = new Date();
const todayLocal = `${nowLocal.getFullYear()}-${String(nowLocal.getMonth() + 1).padStart(2, "0")}-${String(nowLocal.getDate()).padStart(2, "0")}`;
const allDates = [...new Set(commits.map((c) => c.date))].sort();
const completeDates = allDates.filter((d) => d !== todayLocal).slice(-DAYS);
const windowStart = completeDates[0];
const windowEnd = completeDates[completeDates.length - 1];

// --- 3. every blob newly added inside the window ------------------------------
const writes: Write[] = [];
for (const c of [...commits].reverse()) { // oldest first so churn treats the first write as content
  if (c.date < windowStart || c.date > windowEnd) continue;
  let raw = "";
  try {
    raw = git(["diff-tree", "-r", "--raw", "--no-commit-id", c.sha]);
  } catch {
    continue;
  }
  for (const line of raw.split("\n")) {
    if (!line.startsWith(":")) continue;
    const tab = line.indexOf("\t");
    if (tab < 0) continue;
    const meta = line.slice(0, tab).split(/ +/);
    const newSha = meta[3];
    if (!newSha || /^0+$/.test(newSha)) continue; // deletion, not an addition
    if (meta[0] === ":160000" || meta[1] === "160000") continue; // submodule pointer
    writes.push({ sha: newSha, path: line.slice(tab + 1), date: c.date });
  }
}

// --- 4. one batched size lookup for every distinct blob -----------------------
const distinct = [...new Set(writes.map((w) => w.sha))];
const sizeOf = new Map<string, { raw: number; disk: number }>();
if (distinct.length > 0) {
  const out = git(["cat-file", "--batch-check=%(objectname) %(objectsize) %(objectsize:disk)"], distinct.join("\n") + "\n");
  for (const line of out.split("\n")) {
    const parts = line.trim().split(" ");
    if (parts.length < 3) continue;
    sizeOf.set(parts[0], { raw: Number(parts[1]) || 0, disk: Number(parts[2]) || 0 });
  }
}

// --- 5. per-day aggregates ----------------------------------------------------
const dayBlobs = new Map<string, Set<string>>();
for (const w of writes) {
  if (!dayBlobs.has(w.date)) dayBlobs.set(w.date, new Set());
  dayBlobs.get(w.date)!.add(w.sha);
}
const bytesFor = (date: string, kind: "raw" | "disk"): number => {
  let total = 0;
  for (const sha of dayBlobs.get(date) ?? []) total += sizeOf.get(sha)?.[kind] ?? 0;
  return total;
};
const dayRows = completeDates.map((date) => {
  const dayWrites = writes.filter((w) => w.date === date);
  const churn = churnBytes(dayWrites.map((w) => ({ path: w.path, bytes: sizeOf.get(w.sha)?.disk ?? 0 })));
  return { date, raw: bytesFor(date, "raw"), disk: bytesFor(date, "disk"), churn };
});

// --- 6. the object store as it stands -----------------------------------------
function dirBytes(dir: string): number {
  let total = 0;
  for (const name of fs.readdirSync(dir)) {
    const p = join(dir, name);
    const st = fs.lstatSync(p);
    if (st.isDirectory()) total += dirBytes(p);
    else if (st.isFile()) total += st.size;
  }
  return total;
}
const gitBytes = dirBytes(join(REPO, ".git"));
const countObjects = git(["count-objects", "-v"]);
const looseBytes = Number((countObjects.match(/^size:\s*(\d+)/m) ?? [])[1] ?? 0) * 1024;
const packBytes = Number((countObjects.match(/^size-pack:\s*(\d+)/m) ?? [])[1] ?? 0) * 1024;
const looseCount = Number((countObjects.match(/^count:\s*(\d+)/m) ?? [])[1] ?? 0);

// --- 7. verdict ---------------------------------------------------------------
const dailyDisk = dayRows.map((r) => r.disk);
const dailyRaw = dayRows.map((r) => r.raw);
const summary = summariseGrowth(dailyDisk);
const summaryRaw = summariseGrowth(dailyRaw);
const churnTotal = dayRows.reduce((a, r) => a + r.churn, 0);
const rawTotal = dailyRaw.reduce((a, b) => a + b, 0);
const verdict = budgetVerdict({
  currentGitBytes: gitBytes,
  daily: dailyDisk,
  ceilingBytes: CEILING,
  dailyBudgetBytes: BUDGET,
  alarmDaysToCeiling: ALARM_DAYS,
});
const contributors = topContributors(writes.map((w) => ({ path: w.path, bytes: sizeOf.get(w.sha)?.raw ?? 0 })), 10);

const lines: string[] = [];
lines.push("repo growth budget — " + REPO.split("/").pop() + " (kalshi-tape-repo-size-policy)");
lines.push("  basis: " + completeDates.length + " complete UTC days " + windowStart + ".." + windowEnd + ", level=blob, clock=commit dates; " + todayLocal + " excluded as partial");
lines.push("  .git on disk " + mib(gitBytes) + " (pack " + mib(packBytes) + ", loose " + mib(looseBytes) + " / " + looseCount + " objects)");
lines.push("  tracked at HEAD " + mib(headTrackedBytes) + " over " + headEntries.length + " files");
lines.push("  added to the object store, per day (disk = what .git actually gained, raw = uncompressed):");
for (const r of dayRows) {
  lines.push("    " + r.date + "  disk " + mb(r.disk).padStart(6) + "   raw " + mb(r.raw).padStart(7) + "   churn " + mb(r.churn).padStart(6));
}
lines.push("  daily median " + mb(summary.median) + " · mean " + mb(summary.mean) + " · trimmed " + mb(summary.trimmedMean) + " · p90 " + mb(summary.p90) + " · max " + mb(summary.max) + " · ex-top-1 " + mb(summary.exTop1Mean) + " · idle " + summary.idleDays);
lines.push("  raw median " + mb(summaryRaw.median) + "/day; disk/raw ratio " + (summary.median / Math.max(1, summaryRaw.median)).toFixed(2));
lines.push("  churn " + mb(churnTotal) + " of " + mb(rawTotal) + " raw (" + ((churnTotal / Math.max(1, rawTotal)) * 100).toFixed(0) + "%) is a path re-committed within the same day");
if (dailyDisk.length >= 4) {
  const half = Math.floor(dailyDisk.length / 2);
  const early = summariseGrowth(dailyDisk.slice(0, half)).median;
  const late = summariseGrowth(dailyDisk.slice(dailyDisk.length - half)).median;
  const delta = early > 0 ? ((late - early) / early) * 100 : 0;
  lines.push("  trend: first-half median " + mb(early) + " -> second-half median " + mb(late) + " (" + (delta > 0 ? "+" : "") + delta.toFixed(0) + "%)");
}
lines.push("  top contributors in the window (raw bytes, class):");
for (const c of contributors) {
  const cls: PathClass = classifyTrackedPath(c.path);
  lines.push("    " + (c.share * 100).toFixed(1).padStart(5) + "%  " + mb(c.bytes).padStart(7) + "  " + cls.padEnd(12) + " " + c.path);
}
const classLine = (Object.keys(headClasses) as PathClass[])
  .sort((a, b) => headClasses[b].bytes - headClasses[a].bytes)
  .map((k) => k + " " + mib(headClasses[k].bytes))
  .join(" · ");
lines.push("  tracked by class: " + classLine);
lines.push("  VERDICT: " + verdict.level.toUpperCase() + " — " + verdict.reasons.join("; "));

const report = {
  generatedAt: new Date().toISOString(),
  card: "kalshi-tape-repo-size-policy",
  basis: {
    window: { start: windowStart, end: windowEnd, days: completeDates.length, partialDayExcluded: todayLocal },
    level: "blob",
    clock: "commit dates (UTC) at HEAD when the script ran",
    bytes: "on-disk object size of every blob newly added by that day diffs (loose zlib / delta-packed)",
  },
  objectStore: { gitBytes, packBytes, looseBytes, looseCount },
  head: { trackedBytes: headTrackedBytes, files: headEntries.length, classes: headClasses },
  daily: dayRows,
  summary,
  summaryRaw,
  churn: { bytes: churnTotal, rawTotal, share: churnTotal / Math.max(1, rawTotal) },
  policy: { ceilingBytes: CEILING, dailyBudgetBytes: BUDGET, alarmDaysToCeiling: ALARM_DAYS },
  verdict: { level: verdict.level, reasons: verdict.reasons, daysAtMedian: verdict.daysAtMedian, daysAtMax: verdict.daysAtMax, overBudget: verdict.overBudget },
  topContributors: contributors,
};
fs.writeFileSync(OUT, JSON.stringify(report, null, 2));

if (QUIET) {
  if (verdict.level !== "ok") console.log("⚠️ repo growth " + verdict.level.toUpperCase() + ": " + verdict.reasons.join("; ") + " | .git " + mib(gitBytes) + ", median " + mb(summary.median) + "/day");
} else {
  console.log(lines.join("\n"));
  console.log("  wrote " + OUT.replace(REPO + "/", ""));
}
process.exit(verdict.level === "alarm" ? 1 : 0);
