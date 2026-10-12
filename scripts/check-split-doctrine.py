#!/usr/bin/env python3
"""Split-doctrine checker — makes "no random row folds" machine-enforced.

Card: `ml-doctrine-time-and-era-splits`. Gate text: *"one shared split utility used by
every fit/eval script in scripts/; any report whose folds are random rows is rejected"*.
Prose cannot enforce that, so this script is the enforcement:

  1. FAIL on any script that imports or calls a random/row-level fold API from
     scikit-learn (`KFold`, `StratifiedKFold`, `ShuffleSplit`, `GroupShuffleSplit`,
     `train_test_split`, `cross_val_score`, `cross_validate`). `random.shuffle` is NOT
     flagged: every use of it in this repo is a permutation/null test or a bootstrap,
     which is legitimate — the ban is on random folds for MODEL SELECTION.
  2. FAIL if the shared helper is missing, or if its fold assignment disagrees with the
     TypeScript `crc32()` (pinned values below, same ones `tests/splits.test.ts`
     asserts). A helper that silently renumbers folds makes every cross-language read
     unreproducible, so the agreement is checked, not assumed.
  3. REPORT which fit/eval scripts are imported onto the helper and which still carry
     their own fold logic (a warning list, not a failure — the migration is the card's
     7-day verify).

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

# Fit/eval scripts that own fold logic today. Once each imports scripts/lib/splits.py
# the card's 7-day verify is met; until then they are listed so the gap is visible.
FOLD_OWNERS = [
    "fit-price-edge.py",
    "fit-fill-model.py",
    "shadow-expectancy-model.py",
    "wallet-selection-test.py",
    "wallet-feature-priors.py",
    "rag-vs-price-baseline.py",
    "skip-edge-probe.py",
    "label-basis-audit.py",
]


def main() -> int:
    failures: list[str] = []
    warns: list[str] = []

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
        if not name.endswith(".py") or name in ALLOW_MENTION:
            continue
        path = os.path.join(SCRIPTS, name)
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for banned in BANNED:
            # import of the symbol, or a call to it
            if re.search(rf"\b{banned}\s*\(", text) or re.search(rf"import[^\n]*\b{banned}\b", text):
                failures.append(f"{name}: uses the random/row-level fold API {banned}() — use scripts/lib/splits.py instead")

    for name in FOLD_OWNERS:
        path = os.path.join(SCRIPTS, name)
        if not os.path.exists(path):
            warns.append(f"{name}: listed as a fold owner but the file is gone (update FOLD_OWNERS)")
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if "lib.splits" in text or "lib import splits" in text:
            print(f"OK   {name} is on the shared helper")
        else:
            warns.append(f"{name}: still carries its own fold logic (not yet on the shared helper)")

    for w in warns:
        print(f"WARN {w}")
    for f in failures:
        print(f"FAIL {f}")
    if failures:
        print(f"\n{len(failures)} violation(s) — random row folds are banned for model selection.")
        return 1
    print(f"\nPASS no random/row-level fold APIs in scripts/ ({len(warns)} migration warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
