#!/usr/bin/env python3
"""printer-failure-ledger -- persist every Voron job outcome, and rescue the log window of a failure.

WHY THIS EXISTS (2026-11-12): the job history showed 38 klippy_shutdowns with **no recoverable cause**.
The current klippy.log held none of them, the dated archives skipped the failure dates (no 2026-10-18,
no August), and Moonraker does not retain klippy.log.1..N. A failure whose log rotates away is a
permanent unknown. This records the outcome AND copies the log evidence while it still exists.

SECOND REASON, the bigger one: the operator cancels prints when he SEES a defect (delamination,
warping). Measured on 500 jobs: 44 cancels ran >=0.1h, costing 23.85h, 96% of them ASA, caught at a
median 24% progress. Those are quality failures, not noise, and Moonraker does not store the reason.
This records how far the job got, so the cancel reason can be attached afterwards.

READ-ONLY against the printer. Writes only under data/printer/.
Exit 1 on a probe failure -- a zero from a failed request and a zero from an empty history are
identical once parsed, so failure must be loud.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

MOONRAKER = os.environ.get("MOONRAKER_URL", "http://192.168.1.100:7125")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "printer")
LEDGER = os.path.join(OUT_DIR, "job-ledger.jsonl")
FAIL_DIR = os.path.join(OUT_DIR, "failures")
PROGRESS = os.path.join(OUT_DIR, "in-progress.json")

MATERIALS = ("PET-CF", "PETG", "ASA", "ABS", "TPU", "PLA")


def get(path: str, timeout: int = 20):
    """Return (ok, payload, http_status, nbytes). Never treat a failed request as empty data."""
    url = MOONRAKER + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
            status = r.status
        if status != 200 or not body:
            return False, None, status, len(body)
        return True, json.loads(body.decode("utf-8", "replace")), status, len(body)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
        return False, None, getattr(e, "code", 0), 0


def material_of(name: str) -> str:
    up = (name or "").upper()
    for m in MATERIALS:
        if m in up:
            return m
    return "?"


def estimate_hours(name: str):
    """Orca embeds its own estimate in the filename: _<n>h<n>m or _<n>m<n>s."""
    m = re.search(r"_(\d+)h(\d+)m", name or "")
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60.0
    m = re.search(r"_(\d+)m(\d+)s", name or "")
    if m:
        return int(m.group(1)) / 60.0 + int(m.group(2)) / 3600.0
    return None


def capture_log_evidence(job_key: str, filename: str) -> str:
    """Copy the error lines out of the live klippy.log before it rotates away."""
    ok, _, status, nbytes = get_log()
    if not ok:
        return f"LOG-CAPTURE FAILED (http {status}, {nbytes} bytes)"
    text = open("/tmp/_klippy_capture.log", "r", errors="replace").read()
    keep = []
    for line in text.splitlines():
        if re.search(r"Transition to shutdown state|Lost communication|Timer too close|"
                     r"MCU .* shutdown|Heater .* not heating|Thermistor|Move out of range|"
                     r"Must home axis first|Error |error -71|-EPROTO", line):
            keep.append(line[:300])
    os.makedirs(FAIL_DIR, exist_ok=True)
    path = os.path.join(FAIL_DIR, f"{job_key}.txt")
    with open(path, "w") as fh:
        fh.write(f"# job: {filename}\n# klippy.log captured while live ({nbytes} bytes downloaded)\n")
        fh.write("\n".join(keep[-200:]) if keep else "# no matching error lines in the LIVE log\n"
                 "# (the failure session may already have rotated; absence here is not proof of a clean run)\n")
    return f"{len(keep)} evidence lines -> {os.path.relpath(path, ROOT)}"


def get_log():
    """Download the live klippy.log to /tmp, bounded. Returns (ok, path, http_status, bytes)."""
    url = MOONRAKER + "/server/files/logs/klippy.log"
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            body = r.read()
            status = r.status
        if status != 200 or len(body) < 1000:
            return False, None, status, len(body)
        with open("/tmp/_klippy_capture.log", "wb") as fh:
            fh.write(body)
        return True, "/tmp/_klippy_capture.log", status, len(body)
    except Exception as e:  # noqa: BLE001 - probe must report, never raise
        return False, None, getattr(e, "code", 0), 0


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    ok, hist, status, nbytes = get("/server/history/list?limit=60&order=desc")
    if not ok or hist is None:
        print(f"PROBE-FAILED: history http={status} bytes={nbytes} -- refusing to report an empty history")
        return 1
    jobs = (hist.get("result") or {}).get("jobs") or []
    if not jobs:
        print(f"PROBE-FAILED: history parsed to 0 jobs (http={status} bytes={nbytes})")
        return 1

    known = set()
    if os.path.exists(LEDGER):
        with open(LEDGER) as fh:
            for line in fh:
                try:
                    known.add(json.loads(line)["job_key"])
                except Exception:  # noqa: BLE001 - a torn line must not stop the ledger
                    continue

    # sample the in-progress job so a cancel's progress is known
    progress = None
    okp, ps, _, _ = get("/printer/objects/query?print_stats&virtual_sdcard")
    if okp and ps is not None:
        st = (ps.get("result") or {}).get("status") or {}
        stats = st.get("print_stats") or {}
        sdcard = st.get("virtual_sdcard") or {}
        if stats.get("state") == "printing":
            size = sdcard.get("file_size") or 0
            pos = sdcard.get("file_position") or 0
            progress = (pos / size) if size else None
            with open(PROGRESS, "w") as fh:
                json.dump({"file": stats.get("filename"), "fraction": progress}, fh)

    added, failures = 0, []
    with open(LEDGER, "a") as fh:
        for j in jobs:
            key = f"{j.get('start_time')}"
            if key in known:
                continue
            name = str(j.get("filename") or "")
            duration_h = (j.get("print_duration") or 0) / 3600.0
            est = estimate_hours(name)
            rec = {
                "job_key": key,
                "file": name,
                "material": material_of(name),
                "status": j.get("status"),
                "duration_h": round(duration_h, 3),
                "estimated_h": round(est, 3) if est else None,
                "progress_at_end": round(duration_h / est, 3) if est else None,
                "started": j.get("start_time"),
                "ran_at_least_0_1h": duration_h >= 0.1,
            }
            fh.write(json.dumps(rec) + "\n")
            known.add(key)
            added += 1
            if j.get("status") not in ("completed", "in_progress") and duration_h >= 0.1:
                failures.append(rec)

    evidence = []
    for rec in failures:
        note = capture_log_evidence(rec["job_key"], rec["file"])
        evidence.append((rec, note))

    print(f"ledger: {len(jobs)} jobs seen | new {added} | failures>=0.1h {len(failures)}")
    if progress is not None:
        print(f"in progress: {progress * 100:.1f}%")
    for rec, note in evidence:
        pct = f"{rec['progress_at_end'] * 100:.0f}%" if rec["progress_at_end"] else "?"
        print(f"  FAIL {rec['status']:16s} {rec['material']:6s} {rec['duration_h']:.2f}h "
              f"(~{pct} of estimate) {rec['file'][:50]} | {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
