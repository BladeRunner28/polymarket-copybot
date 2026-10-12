#!/usr/bin/env python3
"""Split-doctrine checker — makes "no random row folds, one shared fold implementation"
machine-enforced instead of prose.

Card: `ml-doctrine-time-and-era-splits`. Gate text: *"one shared split utility used by
every fit/eval script in scripts/; any report whose folds are random rows is rejected"*.

  1. FAIL on any script that imports or calls a random/row-level fold API from
     scikit-learn (`KFold`, `StratifiedKFold`, `ShuffleSplit`, `GroupShuffleSplit`,
     `train_test_split`, `cross_val_score`, `cross_validate`). `random.shuffle` is NOT
     flagged: every use in this repo is a permutation/null test or a bootstrap, which is
     legitimate — the ban is on random folds for MODEL SELECTION.
  2. FAIL if the shared helper is missing, or if its fold assignment disagrees with the
     TypeScript `crc32()` (pinned values below, same ones `tests/splits.test.ts`
     asserts). A helper that silently renumbers folds makes every cross-language read
     unreproducible, so the agreement is checked, not assumed.
  3. FAIL on any script that re-derives the fold arithmetic inline
     (`crc32(<key>) % k`) instead of calling `lib/splits.assign_blocked_fold`. "One
     shared implementation" is only true if the implementation is not copy-pasted.
  4. DISCOVER the fold owners instead of naming them. A script is an owner when it shows
     evidence of fold logic (fold-count constant, fold array, per-fold slicing, holdout
     or purge language, call into a split helper). Every discovered owner must be either
       (a) wired to `scripts/lib/splits.py`, or
       (b) marked `split-doctrine: compliant-inline` inside the owning function's
           docstring, with a justification of its own — the justification is echoed in
           this report on every run, so the claim is reviewed, not buried.
     Anything else FAILS. The previous hand-written owner list was a guess: it named 7
     owners, of which only 3 had any fold logic at all (2 of them re-derived the
     arithmetic). Detection replaces the guess, so a new fit script cannot appear
     un-noticed.

Exit codes: 0 = clean, 1 = violation.

Usage: python3 scripts/check-split-doctrine.py
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
LIB = os.path.join(SCRIPTS, "lib", "splits.py")

BANNED = [
    "train_test_split",
    "StratifiedKFold",
    "KFold",
    "ShuffleSplit",
    "GroupShuffleSplit",
    "cross_val_score",
    "cross_validate",
]
# Files that legitimately MENTION a banned name: this checker itself, and any doc that
# quotes the ban. Kept explicit so a new exception has to be justified.
ALLOW_MENTION = {"check-split-doctrine.py"}

# Pinned in tests/splits.test.ts — the same wallet->fold numbers must come out here.
PINNED = [
    ("0x85f031d069de3000", 5, 4),
    ("0xe0e637b08c971c2f", 5, 3),
    ("0xb0c85813a7a4428f", 5, 3),
    ("hello", 5, 0),
]

# Evidence of fold/split logic. Names alone are not evidence: `mode_split()` below splits a
# parquet scan and `vendor_split()` splits wallets by a category share, and neither is a
# fold — so these patterns look for fold ARITHMETIC and fold-SHAPED data, not for the
# substring "split".
OWNER_EVIDENCE = [
    (re.compile(r"\b(assign_blocked_fold|keyed_holdout|time_holdout|walk_forward|era_groups|hash_split)\s*\("),
     "calls a split helper"),
    (re.compile(r"\b[A-Za-z_]*FOLDS\b"), "fold-count constant"),
    (re.compile(r"\bfolds\b\s*="), "builds a fold array"),
    (re.compile(r"\bfolds\b\s*=="), "slices rows by fold"),
    (re.compile(r"\bfold_arr\b"), "carries a fold array"),
    (re.compile(r"\bholdout\b"), "holdout"),
    (re.compile(r"(?i)\bpurged\b"), "purged train rows"),
]

# Inline re-derivation of the shared fold arithmetic. `[^\n]*` (not `[^)]*`) so nested
# calls like `zlib.crc32(r["market"].encode()) % K_FOLDS` are caught — that is exactly the
# shape the migration removed, and a nested-blind pattern misses it.
INLINE_ARITH = re.compile(r"crc32\([^\n]*\)[^\n]*%\s*\w+")

# (a) wired to the shared module.
HELPER_REF = re.compile(r"lib\.splits|from lib import splits|lib[/\"', ]+splits\.py|[\"']lib[\"'],\s*[\"']splits\.py[\"']")

# (b) justified inline. The marker must sit inside a fold-owned function's docstring.
MARKER = re.compile(r"split-doctrine:\s*compliant-inline", re.I)
FOLD_DEF = re.compile(r"^def\s+(\w*(?:fold|split|holdout|walk)\w*)\s*\(", re.M)
MARKER_MAX_DISTANCE = 500
MIN_JUSTIFICATION = 100


def lineno(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def owner_evidence(text: str) -> list[str]:
    return [why for pat, why in OWNER_EVIDENCE if pat.search(text)]


def compliant_inline(text: str) -> tuple[bool, str, str]:
    """(ok, reason-if-not-ok, justification-to-echo)"""
    m = MARKER.search(text)
    if not m:
        return False, "no `split-doctrine: compliant-inline` marker", ""
    defs = [d for d in FOLD_DEF.finditer(text) if 0 <= m.start() - d.start() <= MARKER_MAX_DISTANCE]
    if not defs:
        return False, ("marker is not inside a fold-owned function's docstring (must follow the "
                       "def it justifies)"), ""
    tail = text[m.end():m.end() + 900]
    justification = " ".join(tail.split())[:400]
    if len(justification) < MIN_JUSTIFICATION:
        return False, "marker carries no justification", justification
    return True, "", justification


def main() -> int:
    failures: list[str] = []
    owners_on_helper: list[str] = []
    owners_inline: list[tuple[str, str, int, str]] = []
    scanned = 0

    if not os.path.exists(LIB):
        failures.append(f"shared split helper missing: {LIB}")
    else:
        sys.path.insert(0, SCRIPTS)
        from lib.splits import assign_blocked_fold, crc32  # type: ignore

        for key, k, want in PINNED:
            got = assign_blocked_fold(key, k)
            if got != want:
                failures.append(
                    f"fold assignment disagrees with the TypeScript value: {key!r} k={k} "
                    f"-> {got}, tests/splits.test.ts expects {want}"
                )
        if crc32("hello") != 907060870:
            failures.append(f"crc32('hello') = {crc32('hello')}, expected 907060870 (zlib/IEEE)")
        else:
            print(f"OK   shared helper {os.path.relpath(LIB, ROOT)} pins match the TS crc32 values")

    for name in sorted(os.listdir(SCRIPTS)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(SCRIPTS, name)
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if name in ALLOW_MENTION:
            continue
        scanned += 1

        for banned in BANNED:
            # import of the symbol, or a call to it
            if re.search(rf"\b{banned}\s*\(", text) or re.search(rf"import[^\n]*\b{banned}\b", text):
                failures.append(f"{name}: uses the random/row-level fold API {banned}() — use scripts/lib/splits.py instead")

        inline = INLINE_ARITH.search(text)
        if inline:
            failures.append(
                f"{name}:{lineno(text, inline.start())}: re-derives the fold "
                f"arithmetic inline (crc32(...) % k) — call lib/splits.assign_blocked_fold instead"
            )

        evidence = owner_evidence(text)
        if not evidence:
            continue
        if HELPER_REF.search(text):
            owners_on_helper.append(f"{name} ({', '.join(evidence)})")
            continue
        ok, why, justification = compliant_inline(text)
        marker = MARKER.search(text)
        if ok and marker:
            owners_inline.append((name, ", ".join(evidence), lineno(text, marker.start()), justification))
        else:
            failures.append(
                f"{name}: fold owner ({', '.join(evidence)}) with neither the shared helper nor a "
                f"justified inline exemption — {why}"
            )

    for name in owners_on_helper:
        print(f"OK   {name} — on the shared helper")
    for name, evidence, ln, justification in owners_inline:
        print(f"OK   {name}:{ln} — compliant-inline ({evidence})")
        print(f"       reason: {justification}")

    for f in failures:
        print(f"FAIL {f}")
    if failures:
        print(f"\n{len(failures)} violation(s) — random row folds and copy-pasted fold arithmetic "
              f"are banned for model selection.")
        return 1
    print(f"\nPASS scanned {scanned} script(s) in scripts/: no random/row-level fold APIs, no inline "
          f"fold arithmetic")
    print(f"     {len(owners_on_helper) + len(owners_inline)} fold owner(s): "
          f"{len(owners_on_helper)} on the shared helper, {len(owners_inline)} justified inline, "
          f"0 unaccounted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
