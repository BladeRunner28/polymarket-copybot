#!/usr/bin/env python3
"""factsheet_status.py — typed per-block input-health sidecar for the research fact sheet.

WHY THIS EXISTS (source candidate: xyonium/reach-mcp, audited 2026-10-23, WATCH; only its
status taxonomy was transferable — `drafts/asset-audit-reach-mcp-20261023.md`):

    A dead or gated feed and a genuinely empty listing parse to the same zero, so venue-health
    blindness is invisible in every current read. The fact sheet prints `SOURCE FAILED` prose, but
    there is no history (only `factsheet-latest.md`, overwritten each run) and no machine-readable
    state, so "0 new this week" over an 11-day stale feed reads identically to a quiet week and a
    plan-gated 403 is indistinguishable from a broken endpoint.

WHAT IT IS: one append-only JSONL row per collector block per run, with a CLOSED state vocabulary:

    ok           the block ran and produced its normal output
    no_results   the source was asked and answered EMPTY (a measurement of a quiet source)
    rate_limited 429, or a feed skipped so as not to deepen one; a stale cache served after a
                 429 is rate_limited too, with `n` > 0 recording the rows that came from it
    gated_off    the block is blocked on US, not broken: a --skip flag, or HTTP 401/402/403
    void         the block was attempted and produced NO usable measurement (timeout, DNS,
                 parse error, unexpected shape, missing table/series)

`no_results` and `void` are the pair that used to be the same zero. A row with `state=void` and
`n > 0` is the shape the gate is looking for: the block was not OK yet the same run still carried
numbers from it.

INVARIANTS (each is asserted in scripts/test-factsheet-status.py):
  - keys are CLOSED: exactly KEYS, no more no less. An unknown key, an unknown state or an unknown
    block id raises StatusSchemaError and the WHOLE run's rows are refused (never a partial series
    under one run id — a half-written health record is worse than none).
  - append-only: rows are only ever added; nothing here rewrites or truncates the file.
  - `n` is items/rows the block actually saw, or None when the block has no item count.

REVERSIBILITY: delete the writer's call in scripts/research-collect.py and the JSONL; no other
reader depends on it.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
STATES = ("ok", "no_results", "rate_limited", "gated_off", "void")
KEYS = ("v", "ts", "run", "block", "state", "note", "n")
NOTE_MAX = 300
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

# Block ids are closed by shape: the fixed blocks the collector owns, plus one id per GitHub query
# and per Reddit feed (those are derived from the live query lists, so the suffix is a slug).
_FIXED_BLOCKS = (
    "db.open",
    "db.ruleset",
    "db.papertrade",
    "db.decision_journal",
    "db.daily_report",
    "prereg.entry_floor",
    "polymarket.gamma",
    "kalshi.markets",
)
BLOCK_RE = re.compile(r"^(github|reddit)\.[a-z0-9][a-z0-9-]*$")


class StatusSchemaError(ValueError):
    """A row does not match the closed schema. Refusing the write is the point."""


REPO = Path(__file__).resolve().parent.parent


def status_path() -> Path:
    """Where the JSONL lives. `FACTSHEET_STATUS_PATH` overrides it for tests and probes only."""
    override = os.environ.get("FACTSHEET_STATUS_PATH")
    if override:
        return Path(override)
    return (REPO
            / "data" / "cache" / "research-recon" / "factsheet-status.jsonl")


def display_path() -> str:
    """The path as printed in the sheet: repo-relative when it lives in the repo."""
    p = status_path()
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def slug(label: str) -> str:
    """The one label -> id mapping, shared by the cache filename and the status block id."""
    return re.sub(r"\W+", "-", label.lower()).strip("-")


def utc_stamp(dt: datetime | None = None) -> str:
    return (dt or datetime.now(timezone.utc)).strftime(TS_FMT)


def classify_fetch_note(note: str) -> str:
    """Map a fetch/cache note onto a state. Checked in order, so 429 wins over a generic HTTP code.

    Anything unrecognised is `void`: an error we could not attribute is a MISSING measurement, not
    a quiet source. Never default to `no_results` here — that is the defect this file exists for.
    """
    n = (note or "").lower()
    if n.strip() == "ok":
        return "ok"
    if "429" in n or "rate limit" in n or "rate-limit" in n:
        return "rate_limited"
    for code in ("401", "402", "403"):
        if "http " + code in n or "http error " + code in n:
            return "gated_off"
    return "void"


def is_stale_cache(note: str) -> bool:
    return (note or "").upper().startswith("STALE")


def valid_block(block: str) -> bool:
    return block in _FIXED_BLOCKS or bool(BLOCK_RE.match(block or ""))


def validate_row(row: dict) -> dict:
    """Enforce the closed schema. Raises StatusSchemaError; returns the row unchanged when valid."""
    if not isinstance(row, dict):
        raise StatusSchemaError("row is not a dict: %r" % (row,))
    got, want = set(row), set(KEYS)
    unknown = sorted(got - want)
    missing = sorted(want - got)
    if unknown:
        raise StatusSchemaError("unknown key(s) %s — the key set is closed (%s)"
                                % (", ".join(unknown), ", ".join(KEYS)))
    if missing:
        raise StatusSchemaError("missing key(s) %s" % ", ".join(missing))
    if row["v"] != SCHEMA_VERSION:
        raise StatusSchemaError("v must be %r, got %r" % (SCHEMA_VERSION, row["v"]))
    for k in ("ts", "run"):
        if not isinstance(row[k], str):
            raise StatusSchemaError("%s must be a string" % k)
        try:
            datetime.strptime(row[k], TS_FMT)
        except ValueError:
            raise StatusSchemaError("%s must be %s, got %r" % (k, TS_FMT, row[k]))
    if not valid_block(row["block"]):
        raise StatusSchemaError("unknown block %r — not a collector block id" % (row["block"],))
    if row["state"] not in STATES:
        raise StatusSchemaError("unknown state %r — vocabulary is %s"
                                % (row["state"], "|".join(STATES)))
    if not isinstance(row["note"], str):
        raise StatusSchemaError("note must be a string")
    n = row["n"]
    if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n < 0):
        raise StatusSchemaError("n must be None or a non-negative int, got %r" % (n,))
    return row


def expected_blocks(gh_labels: list[str], reddit_labels: list[str]) -> list[str]:
    """Every block id a full run is required to emit a row for."""
    return (list(_FIXED_BLOCKS)
            + ["github." + slug(x) for x in gh_labels]
            + ["reddit." + slug(x) for x in reddit_labels])


def _group_not_ok(bad: list[dict]) -> str:
    """`state=n (blocks "note"; blocks "note") | ...` — complete, but grouped so a shared reason
    is stated once instead of thirteen times."""
    by_state: dict = {}
    for r in bad:
        by_state.setdefault(r["state"], {}).setdefault(r["note"] or "no note", []).append(r)
    parts = []
    for state, notes in by_state.items():
        total = sum(len(v) for v in notes.values())
        segs = []
        for note, rs in notes.items():
            who = ", ".join(x["block"] + ("" if not x["n"] else " n=%d" % x["n"]) for x in rs)
            segs.append('%s "%s"' % (who, note))
        parts.append("%s=%d (%s)" % (state, total, "; ".join(segs)))
    return " | ".join(parts)


class Recorder:
    """Collects one row per block for ONE run, then appends them in a single write."""

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id or utc_stamp()
        self._rows: list[dict] = []
        self._seen: set[str] = set()
        self.expected: list[str] = []

    def expect(self, blocks: list[str]) -> None:
        self.expected = list(blocks)

    def mark(self, block: str, state: str, note: str = "", n: int | None = None) -> None:
        if block in self._seen:
            raise StatusSchemaError("block %r already recorded this run — one row per block"
                                    % (block,))
        self._rows.append({
            "v": SCHEMA_VERSION,
            "ts": utc_stamp(),
            "run": self.run_id,
            "block": block,
            "state": state,
            "note": (note or "")[:NOTE_MAX],
            "n": n,
        })
        self._seen.add(block)

    def rows(self) -> list[dict]:
        return [dict(r) for r in self._rows]

    def missing(self) -> list[str]:
        return [b for b in self.expected if b not in self._seen]

    def counts(self) -> dict:
        c = Counter(r["state"] for r in self._rows)
        return {s: c.get(s, 0) for s in STATES}

    def audit_line(self) -> str:
        c = self.counts()
        return ("- run %s: %d blocks — %s"
                % (self.run_id, len(self._rows),
                   ", ".join("%s=%d" % (s, c[s]) for s in STATES)))

    def not_ok(self) -> list[dict]:
        return [r for r in self._rows if r["state"] != "ok"]

    def sheet_block(self, rel_path: str) -> list[str]:
        """The fact-sheet section: the audit count plus every block that was not `ok`.

        This is what makes the gate answerable later: a non-ok block is NAMED in the same run it
        happened, so "did the same run's fact sheet carry a line about it?" stops being a guess.
        Blocks are grouped by state then by note, because a skip flag produces thirteen identical
        reasons and repeating each on its own would bury the one block that actually failed.
        """
        out = ["## Input health — typed per block (%s)" % rel_path, self.audit_line()]
        bad = self.not_ok()
        if bad:
            out.append("- not ok: " + _group_not_ok(bad))
        else:
            out.append("- not ok: none — every block answered")
        missing = self.missing()
        if missing:
            out.append("- **NO ROW EMITTED** (instrument defect, not a quiet venue): "
                       + ", ".join(missing))
        out.append("- A `no_results` row means the source was asked and answered EMPTY; `void` "
                   "means it produced no measurement at all. `void`/`rate_limited` with n>0 means "
                   "numbers under it came from a stale or partial copy.")
        return out


def write_rows(rows: list[dict], path: Path | None = None) -> Path:
    """Validate EVERY row, then append them in one write. All-or-nothing per run."""
    for r in rows:
        validate_row(r)
    target = path or status_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    blob = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    return target


def load_rows(path: Path | None = None) -> tuple[list[dict], int]:
    """All rows, plus the count of unparseable lines (never silently dropped)."""
    target = path or status_path()
    rows, bad = [], 0
    if not target.exists():
        return rows, bad
    with target.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            rows.append(r)
    return rows, bad


def runs(rows: list[dict]) -> dict:
    """Group rows by run id, preserving file order (append order == run order)."""
    out: dict = {}
    for r in rows:
        out.setdefault(r.get("run") or "?", []).append(r)
    return out
