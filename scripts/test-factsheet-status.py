#!/usr/bin/env python3
"""Prove the input-health sidecar's closed schema and its two-way zero.

2026-11-09 (Lane B, card reach-mcp-input-health). The defect class being repaired: a dead or gated
feed and a genuinely empty listing parse to the same zero. So the assertions here are about the
PROPERTIES that make the two distinguishable, not about a printing format:

  1. keys/state/block ids are CLOSED — an unknown key is refused, and refusing it writes NOTHING
     (a half-written run is worse than no run: the audit counts would be a partial series).
  2. a fetch note maps to the right state, with `no_results` never being the fallback for an error.
  3. a stale cache served after a failed fetch is NOT `ok` when it carries rows — that is the
     "void-with-rows" shape the card's gate looks for.
  4. a run where a block never marked itself is reported as a missing row (instrument defect),
     not silently counted as healthy.
  5. appends accumulate: two runs, one file, counts per state per run.

Run: python3 scripts/test-factsheet-status.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import factsheet_status as fs  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("research_collect", HERE / "research-collect.py")
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("  %s  %s: got %r want %r" % ("PASS" if ok else "FAIL", name, got, want))
    return ok


def check_raises(name, fn, needle):
    try:
        fn()
    except fs.StatusSchemaError as e:
        ok = needle in str(e)
        RESULTS.append(ok)
        print("  %s  %s: refused with %r" % ("PASS" if ok else "FAIL", name, str(e)[:120]))
        return ok
    RESULTS.append(False)
    print("  FAIL  %s: no StatusSchemaError raised" % name)
    return False


def good_row(**over):
    r = {"v": 1, "ts": "2026-11-08T15:00:00Z", "run": "2026-11-08T15:00:00Z",
         "block": "kalshi.markets", "state": "ok", "note": "", "n": 200}
    r.update(over)
    return r


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="factsheet-status-test-"))
    target = tmp / "factsheet-status.jsonl"

    print("closed schema")
    fs.validate_row(good_row())
    check_raises("unknown key rejected", lambda: fs.validate_row(good_row(extra=1)), "unknown key")
    check_raises("missing key rejected", lambda: fs.validate_row(
        {k: v for k, v in good_row().items() if k != "note"}), "missing key")
    check_raises("unknown state rejected", lambda: fs.validate_row(good_row(state="errored")),
                 "unknown state")
    check_raises("unknown block rejected", lambda: fs.validate_row(good_row(block="venue.kalshi")),
                 "unknown block")
    check_raises("bad n rejected", lambda: fs.validate_row(good_row(n=-1)), "non-negative")

    # all-or-nothing: one bad row means the file is not touched
    fs.write_rows([good_row()], target)
    before = target.read_text()
    try:
        fs.write_rows([good_row(), good_row(block="polymarket.gamma", surprise=2)], target)
        check("invalid batch refused", "no error", "StatusSchemaError")
    except fs.StatusSchemaError:
        check("invalid batch refused", target.read_text(), before)

    print("\nfetch note -> state (the two-way zero)")
    cases = {
        "ok": "ok",
        "HTTP 429": "rate_limited",
        'HTTP 403 {"message": "API rate limit exceeded for 1.2.3.4"}': "rate_limited",
        "HTTP 403 (plan does not include this endpoint)": "gated_off",
        "HTTP 401": "gated_off",
        "HTTP 402": "gated_off",
        "HTTP 502": "void",
        "TimeoutError: timed out": "void",
        "URLError: <urlopen error [Errno 8] nodename nor servname provided>": "void",
        "STALE cache (25.2h old) after HTTP 429": "rate_limited",
        "STALE cache (3.0h old) after TimeoutError: timed out": "void",
    }
    for note, want in cases.items():
        check("classify(%r)" % note[:48], fs.classify_fetch_note(note), want)

    print("\none row per block, one file, append-only")
    rec = fs.Recorder(run_id="2026-11-09T15:00:00Z")
    rec.expect(fs.expected_blocks(["newest Polymarket tooling"], ["r/Kalshi top/week"]))
    rec.mark("db.open", "ok")
    for b in ("db.ruleset", "db.papertrade", "db.decision_journal", "db.daily_report"):
        rec.mark(b, "ok")
    rec.mark("prereg.entry_floor", "no_results", "series is empty")
    rec.mark("polymarket.gamma", "ok", n=60)
    rec.mark("kalshi.markets", "void", "HTTP 502", n=0)
    rec.mark("github.newest-polymarket-tooling", "ok", n=5)
    # the stale-cache-with-rows shape: input failed, rows still published
    rec.mark("reddit.r-kalshi-top-week", "rate_limited", "STALE cache (25.2h old) after HTTP 429",
             n=25)
    check("a repeated mark for one block is refused",
          "already recorded" in _dup(rec), True)
    check("no missing blocks", rec.missing(), [])

    path = fs.write_rows(rec.rows(), target)
    rows, bad = fs.load_rows(path)
    check("rows appended after the earlier single row", len(rows), 11)
    check("no unparseable lines", bad, 0)
    check("audit counts", rec.counts(),
          {"ok": 7, "no_results": 1, "rate_limited": 1, "gated_off": 0, "void": 1})
    check("not_ok names exactly the three", [r["block"] for r in rec.not_ok()],
          ["prereg.entry_floor", "kalshi.markets", "reddit.r-kalshi-top-week"])

    second = fs.Recorder(run_id="2026-11-10T15:00:00Z")
    second.mark("db.open", "ok")
    fs.write_rows(second.rows(), target)
    rows, _ = fs.load_rows(target)
    check("three runs, one file", len(fs.runs(rows)), 3)
    check("the new run is last", rows[-1]["run"], "2026-11-10T15:00:00Z")

    print("\nsheet block names what is not ok")
    block = rec.sheet_block("data/cache/research-recon/factsheet-status.jsonl")
    text = "\n".join(block)
    check("audit count printed", bool([l for l in block if l.startswith("- run ")]), True)
    check("void block named in the same run", 'void=1 (kalshi.markets "HTTP 502")' in text, True)
    check("stale cache named with its rows", 'rate_limited=1 (reddit.r-kalshi-top-week n=25' in text,
          True)
    check("a shared reason is stated once", text.count("HTTP 502"), 1)
    check("a missing row is called an instrument defect",
          "NO ROW EMITTED" in "\n".join(
              _missing_block()), True)

    print("\nthe collector still marks every block it prints")
    # --skip flags must still produce a row per block (gated_off), never a silent absence. The db
    # blocks are covered by bot_facts itself, which this probe deliberately does not call (it would
    # need the live book); what is under test here is that a SKIP cannot read as a healthy run.
    rc.REC = fs.Recorder(run_id="2026-11-09T16:00:00Z")
    rc.REC.expect([b for b in fs.expected_blocks([q[0] for q in rc.GH_QUERIES],
                                                 [f[0] for f in rc.reddit_feeds()])
                   if not b.startswith("db.")])
    rc.prereg_reads(skipped=True)
    rc.polymarket_snapshot(skipped=True)
    rc.kalshi_snapshot(skipped=True)
    rc.github_recon(skipped=True)
    rc.reddit_recon(skipped=True)
    check("every skipped block still emits a row", rc.REC.missing(), [])
    check("skips are gated_off, not void",
          sorted(set(r["state"] for r in rc.REC.rows())), ["gated_off"])
    check("row count equals the expected block count",
          len(rc.REC.rows()), len(rc.REC.expected))

    print("\nreddit block: stale cache / empty / hard failure are three DIFFERENT states")
    atom = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
            + "".join("<entry><title>post %d on polymarket api</title>"
                      "<updated>2026-11-09T00:00:00Z</updated></entry>" % i for i in range(2))
            + "</feed>")
    empty_atom = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>')

    def run_reddit(ret):
        rc.REC = fs.Recorder(run_id="2026-11-09T18:00:00Z")
        rc.REC.expect([b for b in fs.expected_blocks([q[0] for q in rc.GH_QUERIES],
                                                     [f[0] for f in rc.reddit_feeds()])
                       if b.startswith("reddit.")])
        rc.REDDIT_PAUSE_S = 0
        rc.cached_text = lambda slug, url, ttl: ret
        rc.reddit_recon()
        return rc.REC.rows(), rc.REC.missing()

    rows_, missing_ = run_reddit((atom, "STALE cache (25.2h old) after HTTP 429"))
    check("stale cache carrying rows is rate_limited (not ok)", sorted(
        set(r["state"] for r in rows_)), ["rate_limited"])
    check("...and the rows it carried are recorded", sorted(set(r["n"] for r in rows_)), [2])
    check("...without a missing row", missing_, [])

    rows_, _ = run_reddit((empty_atom, "fresh"))
    check("an empty feed that ANSWERED is no_results", sorted(set(r["state"] for r in rows_)),
          ["no_results"])
    check("...with n=0, never a null", sorted(set(r["n"] for r in rows_)), [0])

    rows_, _ = run_reddit((None, "TimeoutError: timed out"))
    check("a failed fetch is void, never no_results", sorted(set(r["state"] for r in rows_)),
          ["void"])

    print("\n%d assertion(s), %d passed" % (len(RESULTS), sum(RESULTS)))
    return 0 if all(RESULTS) else 1


def _dup(rec):
    try:
        rec.mark("db.open", "ok")
    except fs.StatusSchemaError as e:
        return str(e)
    return "no error"


def _missing_block():
    r = fs.Recorder(run_id="2026-11-09T17:00:00Z")
    r.expect(["db.open", "kalshi.markets"])
    r.mark("db.open", "ok")
    return r.sheet_block("x.jsonl")


if __name__ == "__main__":
    sys.exit(main())
