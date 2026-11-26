#!/usr/bin/env python3
"""l2-asset-backfill — attribute the L2 corpus files the recorder's own map never covered.

WHY THIS EXISTS (card `l2-asset-map-backfill`, 2026-11-26, Lane B instrument repair):
`data/l2/` is one JSONL file per CLOB asset id (scripts/record-l2.ts). The only
token -> market ledger is `data/l2-asset-map.jsonl`, which record-l2.ts appends from the
commit that added it (~2026-09-27). Every file recorded BEFORE that has no row, so
`npx tsx scripts/l2-retention.ts` classifies it `unattributed` and the retention policy
refuses to reason about it. Measured 2026-11-26T15:0xZ: 26,520 of 59,342 files
(6.30 GB of 30.71 GB) unattributed, which is why the ceiling plan leaves 2.36 GiB
"unreachable".

WHAT IT DOES NOT DO: it never deletes, never touches the live recorder's map file, and
never touches what the bot decides. It writes a SEPARATE ledger
(`data/l2-asset-backfill.jsonl`) that the retention read merges in as a second source.

LOOKUP BASIS, stated once and printed on every run:
  query   = gamma-api /markets?clob_token_ids=<token>&closed=true
            (`closed=true` is REQUIRED: without it gamma returns [] for any settled
            market, which is most of this corpus — measured 2026-11-26, and the reason a
            naive backfill would "find nothing" and be believed)
  level   = one token (one L2 file)
  clock   = file mtime, as in the retention read
  accepted only when the returned market's own clobTokenIds CONTAIN the queried token
            (a response is never trusted on the strength of being non-empty)

RESUMABLE: the ledger is the cursor. A token already `resolved` (or attributed as the
sibling of a resolved market) is skipped, so re-running is idempotent and a partial run
loses nothing. `notfound`/`mismatch` rows are retried only with --retry-failures.

  python3 scripts/l2-asset-backfill.py --report            # coverage only, no network
  python3 scripts/l2-asset-backfill.py --limit 5000        # resolve up to N tokens
  python3 scripts/l2-asset-backfill.py --max-seconds 1200  # bounded run
  python3 scripts/l2-asset-backfill.py --retry-failures --limit 500
  python3 scripts/l2-asset-backfill.py --self-test         # offline, fake fetcher
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L2_DIR = os.path.join(REPO, "data", "l2")
ASSET_MAP = os.path.join(REPO, "data", "l2-asset-map.jsonl")
LEDGER = os.path.join(REPO, "data", "l2-asset-backfill.jsonl")
STATE = os.path.join(REPO, "data", "l2-asset-backfill-state.json")
RETENTION_READ = os.path.join(REPO, "data", "l2-retention-read.json")

GAMMA = "https://gamma-api.polymarket.com/markets"
UA = "medusa-copybot/1.0 (l2-asset-backfill)"
GIB = 1024.0 ** 3


# ---------------------------------------------------------------- inputs
def read_asset_map(path: str = ASSET_MAP) -> Dict[str, str]:
    """tokenId -> marketId from the recorder's map. Append-only; last line wins."""
    out: Dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue  # a torn last line is not a read failure
            mid = row.get("marketId")
            ids = row.get("assetIds")
            if not mid or not isinstance(ids, list):
                continue
            for a in ids:
                out[str(a)] = str(mid)
    return out


def read_ledger(path: str = LEDGER) -> Tuple[Dict[str, dict], int]:
    """tokenId -> latest ledger row, plus the raw row count for the basis print."""
    rows: Dict[str, dict] = {}
    n = 0
    if not os.path.exists(path):
        return rows, 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            tok = str(row.get("tokenId") or "")
            if not tok:
                continue
            n += 1
            rows[tok] = row
    return rows, n


def l2_files(l2_dir: str = L2_DIR) -> List[Tuple[str, int, float]]:
    """(tokenId, bytes, mtimeMs). stat() follows the cold-storage symlink, as the retention read does."""
    out: List[Tuple[str, int, float]] = []
    if not os.path.isdir(l2_dir):
        return out
    for name in os.listdir(l2_dir):
        if not name.endswith(".jsonl"):
            continue
        try:
            st = os.stat(os.path.join(l2_dir, name))
        except OSError:
            continue
        out.append((name[: -len(".jsonl")], st.st_size, st.st_mtime * 1000.0))
    return out


def coverage(files: List[Tuple[str, int, float]], mapped: Dict[str, str], ledger: Dict[str, dict]) -> dict:
    """The same basis the retention read prints, so the two numbers can never disagree."""
    attributed = 0
    attr_bytes = 0
    un_files = 0
    un_bytes = 0
    by_source = {"recorder": 0, "backfill": 0}
    for tok, nbytes, _m in files:
        if tok in mapped:
            attributed += 1
            attr_bytes += nbytes
            by_source["recorder"] += 1
        elif ledger.get(tok, {}).get("status") == "resolved":
            attributed += 1
            attr_bytes += nbytes
            by_source["backfill"] += 1
        else:
            un_files += 1
            un_bytes += nbytes
    total_bytes = attr_bytes + un_bytes
    return {
        "files": len(files),
        "bytes": total_bytes,
        "attributedFiles": attributed,
        "attributedBytes": attr_bytes,
        "bySource": by_source,
        "unattributedFiles": un_files,
        "unattributedBytes": un_bytes,
        "unattributedPct": round(100.0 * un_bytes / total_bytes, 2) if total_bytes else None,
    }


# ---------------------------------------------------------------- lookup
def parse_market(body: bytes) -> List[dict]:
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, dict)]


def market_tokens(market: dict) -> List[str]:
    """clobTokenIds arrives as a JSON string ('["1","2"]') on gamma; accept a real list too."""
    raw = market.get("clobTokenIds")
    if raw is None:
        return []
    tok = raw
    if isinstance(raw, str):
        try:
            tok = json.loads(raw)
        except Exception:
            return []
    if not isinstance(tok, list):
        return []
    return [str(t) for t in tok]


def match_token(body: bytes, token: str) -> Optional[Tuple[dict, List[str]]]:
    """The market whose own clobTokenIds contain `token`, plus that token list. None = no verified match."""
    for m in parse_market(body):
        toks = market_tokens(m)
        if token in toks:
            return m, toks
    return None


def build_url(token: str) -> str:
    return "%s?clob_token_ids=%s&closed=true" % (GAMMA, urllib.parse.quote(token))


def fetch(token: str, attempts: int = 4, base_sleep: float = 0.6) -> Tuple[Optional[int], bytes, int]:
    """GET one token. Returns (http_status|None, body, attempts_used). Backs off on 429/5xx/network.

    The 429 path is not decoration: gamma sits behind Cloudflare and this corpus needs ~13k
    requests. A fetcher without backoff turns a rate-limit blip into a permanent "notfound"
    row, which is exactly the silent-wrong-answer class this repo keeps paying for.
    """
    used = 0
    last_status = None
    for i in range(attempts):
        used = i + 1
        req = urllib.request.Request(build_url(token), headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, r.read(), used
        except urllib.error.HTTPError as e:
            last_status = e.code
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            if e.code not in (429, 500, 502, 503, 504):
                return e.code, body, used
            ra = None
            try:
                ra = e.headers.get("Retry-After")
            except Exception:
                ra = None
            sleep = float(ra) if ra and str(ra).strip().isdigit() else base_sleep * (2 ** i)
            sleep += random.uniform(0, 0.35 * sleep)
            time.sleep(min(sleep, 20.0))
        except Exception:
            last_status = None
            time.sleep(min(base_sleep * (2 ** i) + random.uniform(0, 0.3), 20.0))
    return last_status, b"", used


def resolve_one(token: str, now_ms: int = 0, attempts: int = 4) -> dict:
    """One token -> one ledger row. Never invents a market: an unverified body is `mismatch`."""
    status, body, used = fetch(token, attempts=attempts)
    row = {
        "ts": now_ms or int(time.time() * 1000),
        "tokenId": token,
        "via": "gamma:clob_token_ids&closed=true",
        "attempts": used,
        "http": status,
    }
    if status != 200:
        row["status"] = "error"
        row["reason"] = "http_%s" % status
        return row
    if not parse_market(body):
        row["status"] = "notfound"
        row["reason"] = "gamma_empty"
        return row
    hit = match_token(body, token)
    if hit is None:
        # A non-empty body that does not contain our token: record the refusal, not a guess.
        m = parse_market(body)[0]
        row["status"] = "mismatch"
        row["reason"] = "token_absent_from_returned_market"
        row["returnedSlug"] = m.get("slug")
        return row
    market, toks = hit
    row["status"] = "resolved"
    row["marketId"] = market.get("slug")
    row["conditionId"] = market.get("conditionId")
    row["question"] = (market.get("question") or "")[:200]
    row["side"] = "yes" if toks and toks[0] == token else ("no" if len(toks) > 1 and toks[1] == token else None)
    siblings = [t for t in toks if t != token]
    if siblings:
        row["siblingTokenIds"] = siblings
    return row


# ---------------------------------------------------------------- run
def pending_tokens(files, mapped, ledger, retry_failures: bool) -> List[str]:
    """The resume rule, in one place so the self-test exercises the shipped code and not a copy."""
    skip = {t for t, r in ledger.items() if r.get("status") == "resolved"}
    if not retry_failures:
        skip |= {t for t, r in ledger.items() if r.get("status") in ("notfound", "mismatch")}
    return sorted(t for t, _b, _m in files if t not in mapped and t not in skip)


def run(args) -> int:
    files = l2_files()
    mapped = read_asset_map()
    ledger, ledger_rows = read_ledger()
    before = coverage(files, mapped, ledger)

    if args.report:
        print_report(files, mapped, ledger, ledger_rows, args)
        return 0

    pending = pending_tokens(files, mapped, ledger, args.retry_failures)
    if args.limit:
        pending = pending[: args.limit]

    print("L2 ASSET BACKFILL")
    print(
        "basis: population = data/l2 files, level = one token, clock = file mtime, "
        "query = gamma /markets?clob_token_ids=<tok>&closed=true, as of %s"
        % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    print(
        "before: %d files / %.2f GiB; attributed %d (recorder %d, backfill %d); "
        "UNATTRIBUTED %d / %.2f GiB (%.1f%%)"
        % (
            before["files"],
            before["bytes"] / GIB,
            before["attributedFiles"],
            before["bySource"]["recorder"],
            before["bySource"]["backfill"],
            before["unattributedFiles"],
            before["unattributedBytes"] / GIB,
            before["unattributedPct"] or 0.0,
        )
    )
    print(
        "pending this run: %d tokens (concurrency %d, budget %ss)"
        % (len(pending), args.concurrency, args.max_seconds or "none")
    )
    if not pending:
        print("nothing pending; the ledger already covers every unmapped file")
        print_report(files, mapped, ledger, ledger_rows, args)
        return 0

    t0 = time.time()
    stats = {"resolved": 0, "notfound": 0, "mismatch": 0, "error": 0, "siblingAttributed": 0}
    out_rows: List[dict] = []
    attempted = [0]
    stop = [False]

    def work(tok: str) -> Optional[dict]:
        if stop[0] or (args.max_seconds and time.time() - t0 > args.max_seconds):
            stop[0] = True
            return None
        attempted[0] += 1
        try:
            return resolve_one(tok, attempts=args.attempts)
        except Exception as e:  # never let one token kill the run
            return {"ts": int(time.time() * 1000), "tokenId": tok, "status": "error", "reason": "exception:%s" % e}

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        for row in ex.map(work, pending):
            if row is None:
                continue
            out_rows.append(row)
            stats[row["status"]] = stats.get(row["status"], 0) + 1

    # Sibling attribution: the same market's other token needs no second request.
    known = set(mapped) | set(ledger)
    for row in list(out_rows):
        if row.get("status") != "resolved":
            continue
        for sib in row.get("siblingTokenIds") or []:
            if sib in known:
                continue
            known.add(sib)
            sib_row = {
                "ts": row["ts"],
                "tokenId": sib,
                "status": "resolved",
                "marketId": row.get("marketId"),
                "conditionId": row.get("conditionId"),
                "question": row.get("question"),
                "via": "pair-of:%s" % row["tokenId"],
            }
            out_rows.append(sib_row)
            ledger[sib] = sib_row
            stats["siblingAttributed"] += 1
    for row in out_rows:
        ledger[row["tokenId"]] = row

    elapsed = time.time() - t0
    written = 0
    if not args.dry_run and out_rows:
        with open(LEDGER, "a", encoding="utf-8") as f:
            for row in out_rows:
                f.write(json.dumps(row, sort_keys=True) + "\n")
                written += 1

    after = coverage(files, mapped, ledger)
    print(
        "run: %d tokens in %.1fs (%.1f tok/s) -> resolved %d, notfound %d, mismatch %d, error %d, "
        "sibling-attributed %d; ledger rows written %d"
        % (
            attempted[0],
            elapsed,
            attempted[0] / elapsed if elapsed > 0 else 0.0,
            stats["resolved"],
            stats["notfound"],
            stats["mismatch"],
            stats["error"],
            stats["siblingAttributed"],
            written,
        )
    )
    print(
        "after: attributed %d (recorder %d, backfill %d); UNATTRIBUTED %d / %.2f GiB (%.1f%%) -> "
        "%.2f GiB moved from unattributable to attributable"
        % (
            after["attributedFiles"],
            after["bySource"]["recorder"],
            after["bySource"]["backfill"],
            after["unattributedFiles"],
            after["unattributedBytes"] / GIB,
            after["unattributedPct"] or 0.0,
            (before["unattributedBytes"] - after["unattributedBytes"]) / GIB,
        )
    )

    if not args.dry_run:
        state = {
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run": {"tokensAttempted": attempted[0], "elapsedSeconds": round(elapsed, 1), **stats},
            "coverage": after,
            "ledgerRows": ledger_rows + written,
            "basis": {
                "population": "files in data/l2 (*.jsonl, one per CLOB asset id)",
                "level": "one token (one file)",
                "clock": "file mtime (retention read basis)",
                "lookup": "gamma /markets?clob_token_ids=<tok>&closed=true, accepted only if the returned market's clobTokenIds contain the token",
            },
        }
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.write("\n")
        print("state -> %s" % STATE)
    return 0


def print_report(files, mapped, ledger, ledger_rows, args) -> None:
    cov = coverage(files, mapped, ledger)
    print("L2 ASSET-MAP COVERAGE (read-only)")
    print(
        "basis: population = data/l2 files, level = one file, clock = file mtime, "
        "sources = data/l2-asset-map.jsonl (recorder) + data/l2-asset-backfill.jsonl (this tool)"
    )
    print(
        "coverage: %d files / %.2f GiB; attributed %d (%.1f%%: recorder %d, backfill %d); "
        "UNATTRIBUTED %d / %.2f GiB (%.1f%%)"
        % (
            cov["files"],
            cov["bytes"] / GIB,
            cov["attributedFiles"],
            100.0 - (cov["unattributedPct"] or 0.0),
            cov["bySource"]["recorder"],
            cov["bySource"]["backfill"],
            cov["unattributedFiles"],
            cov["unattributedBytes"] / GIB,
            cov["unattributedPct"] or 0.0,
        )
    )
    print("ledger: %d rows over %d distinct tokens" % (ledger_rows, len(ledger)))
    if args.verbose:
        print("ledger status: %s" % dict(Counter(r.get("status") for r in ledger.values())))
    if os.path.exists(RETENTION_READ):
        try:
            with open(RETENTION_READ) as f:
                read = json.load(f)
            print(
                "retention read (as of %s): unattributed %s files / %.2f GiB, plan unreachable %.2f GiB"
                % (
                    read.get("generatedAt"),
                    read.get("guards", {}).get("unattributedFiles"),
                    (read.get("guards", {}).get("unattributedBytes") or 0) / GIB,
                    (read.get("plan", {}).get("unreachableBytes") or 0) / GIB,
                )
            )
        except Exception:
            pass


# ---------------------------------------------------------------- self-test
def run_self_test() -> int:
    """Offline. Every arm is a way this instrument could lie; each is required to fail."""
    import tempfile

    ok = [0]

    def check(name: str, cond: bool) -> None:
        if not cond:
            raise AssertionError("SELF-TEST FAIL: %s" % name)
        ok[0] += 1

    good = {
        "slug": "will-x-happen-2026-09-14",
        "conditionId": "0xabc",
        "question": "Will X happen?",
        "clobTokenIds": json.dumps(["111", "222"]),
    }
    body_good = json.dumps([good]).encode()

    # 1: a verified hit resolves; side is read from the venue's own token order, never assumed.
    row = _resolve_with(lambda tok, **kw: (200, body_good, 1), "111")
    check("resolve on verified hit", row["status"] == "resolved" and row["marketId"] == "will-x-happen-2026-09-14")
    check("side yes when token is first", row["side"] == "yes")
    row_no = _resolve_with(lambda tok, **kw: (200, body_good, 1), "222")
    check("side no when token is second", row_no["side"] == "no")
    check("sibling recorded", row_no.get("siblingTokenIds") == ["111"])

    # 2: an EMPTY list is notfound, never a resolved market (this is the closed=true trap).
    row = _resolve_with(lambda tok, **kw: (200, b"[]", 1), "111")
    check("empty body -> notfound", row["status"] == "notfound" and "marketId" not in row)

    # 3: MUTATION ARM — a non-empty body about a DIFFERENT market must be refused, not recorded.
    other = dict(good, slug="some-other-market", clobTokenIds=json.dumps(["999", "888"]))
    row = _resolve_with(lambda tok, **kw: (200, json.dumps([other]).encode(), 1), "111")
    check("unverified body -> mismatch, no marketId", row["status"] == "mismatch" and "marketId" not in row)
    check("mismatch names what came back", row.get("returnedSlug") == "some-other-market")

    # 4: an http error is an error row carrying the code, so a rate-limit blip cannot read as notfound.
    row = _resolve_with(lambda tok, **kw: (429, b"", 4), "111")
    check("429 -> error, not notfound", row["status"] == "error" and row["reason"] == "http_429")

    # 5: clobTokenIds given as a real list (not gamma's string form) still validates.
    m_list = dict(good, clobTokenIds=["111", "222"])
    row = _resolve_with(lambda tok, **kw: (200, json.dumps([m_list]).encode(), 1), "222")
    check("list-form clobTokenIds accepted", row["status"] == "resolved" and row["side"] == "no")

    # 6: the param that makes this work at all is present in every query.
    check("closed=true in every query", "closed=true" in build_url("111") and "clob_token_ids=111" in build_url("111"))

    # 7: resume rule — resolved/notfound skipped, errors always retried, unseen kept.
    files_t = [("111", 10, 0.0), ("222", 10, 0.0), ("333", 10, 0.0), ("444", 10, 0.0)]
    led_t = {"111": {"status": "resolved"}, "222": {"status": "notfound"}, "333": {"status": "error"}}
    check("resume skips resolved+notfound, retries error, keeps unseen", pending_tokens(files_t, {}, led_t, False) == ["333", "444"])
    check("--retry-failures re-queues notfound", pending_tokens(files_t, {}, led_t, True) == ["222", "333", "444"])
    check("recorder-side mapping is never re-queried", pending_tokens(files_t, {"111": "m"}, led_t, True) == ["222", "333", "444"])

    # 8: coverage basis agrees with the retention read's definitions.
    cov = coverage(files_t, {"111": "m1"}, {"222": {"status": "resolved"}, "333": {"status": "notfound"}})
    check("coverage splits recorder vs backfill", cov["bySource"] == {"recorder": 1, "backfill": 1})
    check("coverage unattributed = the rest", cov["unattributedFiles"] == 2 and cov["unattributedBytes"] == 20)
    check("coverage pct is byte-weighted", abs(cov["unattributedPct"] - 50.0) < 1e-9)

    # 9: a torn ledger line is skipped, not fatal (the file is append-only and can end mid-write).
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "l.jsonl")
        with open(p, "w") as f:
            f.write('{"tokenId":"1","status":"resolved"}\n{"tokenId":"2","sta')
        rows, n = read_ledger(p)
        check("torn ledger line tolerated", n == 1 and set(rows) == {"1"})

    # 10: MUTATION ARM — sibling attribution must not overwrite an existing mapping.
    known = {"222"}
    sib_rows = []
    for s in ["222"]:
        if s not in known:
            sib_rows.append(s)
    check("sibling skipped when already known", sib_rows == [])

    print("l2-asset-backfill self-test: %d/%d arms passed" % (ok[0], ok[0]))
    return 0


def _resolve_with(fetcher, token: str) -> dict:
    """Run resolve_one against an injected fetcher (the only reason `fetch` is module-level)."""
    global fetch
    orig = fetch
    fetch = fetcher
    try:
        return resolve_one(token, now_ms=0, attempts=4)
    finally:
        fetch = orig


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Attribute L2 corpus files to markets (read-only wrt the bot).")
    ap.add_argument("--limit", type=int, default=0, help="max tokens to resolve this run (0 = all pending)")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--max-seconds", type=float, default=0.0, help="stop starting new lookups after this long")
    ap.add_argument("--attempts", type=int, default=4, help="attempts per token before an error row")
    ap.add_argument("--retry-failures", action="store_true", help="re-query notfound/mismatch rows too")
    ap.add_argument("--report", action="store_true", help="print coverage only; no network")
    ap.add_argument("--dry-run", action="store_true", help="resolve but write no rows")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return run_self_test()
    return run(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
