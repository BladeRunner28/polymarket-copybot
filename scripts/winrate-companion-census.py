#!/usr/bin/env python3
"""WIN-RATE COMPANION CENSUS: does every surface that PRINTS a win rate print its payoff beside it?

Card `winrate-payoff-companion-reporting` (queue item 15, done 2026-11-03).

WHY: on 2026-10-27 a win-rate drop was read as a profitability collapse. It was neither. Win rate fell
71.7% (Jul) -> 41.2% (Oct) while ROI rose to the best month on record, because average win went
$6.67 -> $23.30 against average loss -$9.05 -> -$12.80. The same trap is structural on the live book:
BANKROLL_200 wins 47.0% of settled legs and earns +29.1% ROI on stake, while STANDARD wins 63.3% and
earns +7.9% — the two lanes rank the OPPOSITE way by the two measures. A bare win rate cannot rank
them, let alone call a collapse.

WHAT THIS CHECKS, per surface and explicitly (a universal regex scanner would be guesswork):
  - every line that renders a win rate must ALSO render the shared companion helper on that line;
  - and each surface must still contain the companion machinery (`must_contain`), so the route cannot
    be quietly deleted while the call sites keep compiling.

THE OTHER HALF OF THE GUARD lives in tests/report-win-rate-basis.test.ts: it pins that the shared
renderer (`winRateLine` -> `payoffCompanionText`) physically puts avg win / avg loss / ROI on the SAME
line as the rate, with no newline.

A CENSUS THAT FINDS NOTHING IS NOT A CLEAN CENSUS. Each entry declares `min_sites`; if a pattern stops
matching (file refactored, line renamed) the census goes RED rather than quietly reporting zero.
`--self-test` proves the detector can fail for every entry.

READ-ONLY: no DB, no network, no writes.
Exit 0 = every declared surface prints its companions; 1 = at least one does not (or a pattern died).
"""
import re
import sys

# path, site pattern, same-line companion pattern (None = presence-only), min_sites, must_contain, note
MANIFEST = [
    [
        "src/lib/report.ts",
        re.compile(r"winRateLine\("),
        None,
        2,
        re.compile(r"payoffCompanionText\(p"),
        "EOD Discord report: both lanes call the shared renderer; tests/report-win-rate-basis.test.ts "
        "pins that the renderer's output carries avg win / avg loss / ROI on the same line",
    ],
    [
        "src/app/page.tsx",
        re.compile(r'label="Win Rate'),
        re.compile(r"payoffCompanionText\("),
        2,
        None,
        "dashboard home: Win Rate / Win Rate (C-200) cards",
    ],
    [
        "src/lib/rule-updater.ts",
        re.compile(r"win rate \$\{"),
        re.compile(r"payoffCompanionText\("),
        2,
        None,
        "rule-change evidence: the number that justifies a threshold move (Rules page + EOD line)",
    ],
    [
        "scripts/research-collect.py",
        re.compile(r"\| win \{"),
        re.compile(r"\{companion\}"),
        1,  # one out.append inside a per-lane loop renders BOTH lanes
        re.compile(r"avg win \{"),
        "fact sheet: per-lane lifetime win rate (the artifact the pre-read briefing is built on)",
    ],
]

# Surfaces that print a win rate but are deliberately NOT line-censused: each carries its population
# and a payoff aggregate in the SAME ROW (n + realizedPnl / n + avgEntry), so a rate cannot be read
# alone there. Listed rather than silently skipped.
EXEMPT = {
    "src/app/performance/page.tsx": "band/hour tables: every row prints n, excess return and realizedPnl",
    "src/app/analytics/page.tsx": "calibration + wallet-scatter plots: x/y pairs, no standalone headline rate",
}


def is_comment(line: str) -> bool:
    s = line.strip()
    return not s or s[0] in ("#", "*") or s.startswith("//")


def census(files):
    """files: dict path -> list of lines (or None). Returns (failures, counts)."""
    failures, counts = [], {}
    for path, site, need, min_sites, must_contain, note in MANIFEST:
        lines = files.get(path)
        if lines is None:
            failures.append(f"{path}: MISSING — a surface this gate covers is gone")
            continue
        hits, bad = 0, []
        for i, line in enumerate(lines, 1):
            if is_comment(line):
                continue
            if site.search(line):
                hits += 1
                if need is not None and not need.search(line):
                    bad.append((i, line.strip()[:110]))
        counts[path] = hits
        if hits < min_sites:
            failures.append(
                f"{path}: only {hits} win-rate site(s), expected >= {min_sites} ({note}) — the "
                f"pattern died; that is a broken gate, not a clean file"
            )
        if must_contain is not None and not any(must_contain.search(l) for l in lines):
            failures.append(
                f"{path}: the companion machinery ({must_contain.pattern}) is gone — the surface still "
                f"prints a win rate, so the rate is now bare"
            )
        for i, snippet in bad:
            failures.append(f"{path}:{i}: win rate printed WITHOUT its companions -> {snippet}")
    return failures, counts


def load(paths):
    files = {}
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                files[p] = fh.read().splitlines()
        except OSError:
            files[p] = None
    return files


CLEAN = {
    "src/lib/report.ts": ["winRateLine(p, 1),", "  const basis = payoffCompanionText(p, localDate);"],
    "src/app/page.tsx": ['<Stat label="Win Rate" value={`x`} sub={`${payoffCompanionText(p)}`} />'],
    "src/lib/rule-updater.ts": ["evidence: `win rate ${w}% — ${payoffCompanionText(e)}`,"],
    "scripts/research-collect.py": ['out.append(f"  - X: n=2 | win {w:.1f}% | {companion}")', "  f\"avg win {a}\""],
}
BARE = {
    # report.ts: keep the call sites, DELETE the companion inside the renderer
    "src/lib/report.ts": ["winRateLine(p, 1),", "  const basis = 'LIFETIME settled';"],
    "src/app/page.tsx": ['<Stat label="Win Rate" value={`x`} sub={`${n} resolved trades`} />'],
    "src/lib/rule-updater.ts": ["evidence: `total PnL 1, win rate ${w}% across 3 resolved trades`,"],
    "scripts/research-collect.py": ['out.append(f"  - X: n=2 | win {w:.1f}%")', "  f\"avg win {a}\""],
}


def fixture(overrides):
    files = {}
    for path, _site, _need, min_sites, _must, _note in MANIFEST:
        base = CLEAN[path]
        times = max(min_sites, 1)
        files[path] = [line for line in base * times] if path not in overrides else overrides[path] * times
    return files


def self_test() -> int:
    """Prove the detector can go RED on every entry. A gate that cannot fail is not a gate."""
    f_clean, _ = census(fixture({}))
    if f_clean:
        print(f"self-test FAILED: the clean fixture is already red: {f_clean}")
        return 1
    for path, _site, _need, _min, _must, _note in MANIFEST:
        f_bare, _ = census(fixture({path: BARE[path]}))
        if not any(path in f for f in f_bare):
            print(f"self-test FAILED: the bare fixture for {path} was NOT detected: {f_bare}")
            return 1
    print(f"self-test OK: clean fixture green; {len(MANIFEST)}/{len(MANIFEST)} bare fixtures detected")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    files = load(p for p, *_rest in MANIFEST)
    failures, counts = census(files)
    print("win-rate companion census — every printed win rate carries its payoff\n")
    for path, n in counts.items():
        print(f"  {n:>2} site(s)  {path}")
    print("\nexempt (population + a payoff aggregate printed per row, so the rate cannot be read alone):")
    for path, why in EXEMPT.items():
        print(f"   - {path}: {why}")
    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  x {f}")
        return 1
    print("\nPASS: 0 win-rate print sites without a companion reference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
