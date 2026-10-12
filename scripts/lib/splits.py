#!/usr/bin/env python3
"""Shared split utility (Python mirror of `src/lib/splits.ts`).

Card: `ml-doctrine-time-and-era-splits`. Same rules, same fold numbers:

  * time-ordered holdout with a PINNED boundary (a fraction-derived cut moves as the
    book grows, and a bar measured on a moving holdout is not a bar);
  * PURGE — a train row whose label was not knowable before the test window opened is
    dropped and counted. Without it, a leg that settled inside the test window can be
    trained on;
  * era provenance on every split (per-era train/test counts + which eras sit on both
    sides), so a report can quote its era mix instead of implying homogeneity;
  * `assign_blocked_fold` is `zlib.crc32(key) % k` — the SAME assignment as
    `folds_wallet()` in scripts/fit-price-edge.py and as the TypeScript `crc32()`, so a
    fold reported in one language is reproducible in the other.

There is deliberately no shuffled/random-row fold function here. Bootstrap RESAMPLING
(with replacement, clustered by market/wallet) is legitimate and lives with the metric
code; the ban is on random folds for model selection.

No third-party imports: these fit scripts run under several interpreters
(venv-calib py3.9, system python3), so stdlib-only is a requirement, not a taste.
"""

from __future__ import annotations

import zlib


def crc32(s: str) -> int:
    """zlib/IEEE CRC-32 of a UTF-8 string — identical to the TS `crc32()`."""
    return zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF


def assign_blocked_fold(key: str, k: int) -> int:
    if not isinstance(k, int) or k < 2:
        raise ValueError("assign_blocked_fold: k must be an integer >= 2 (got %r)" % (k,))
    return crc32(key) % k


def blocked_folds(rows, key, k=5):
    """k group-blocked folds. Returns (folds, sizes); every row of a group stays together."""
    folds = [[] for _ in range(k)]
    for r in rows:
        folds[assign_blocked_fold(key(r), k)].append(r)
    return folds, [len(f) for f in folds]


def format_provenance(design, boundary_iso, train_n, test_n, era_train, era_test, overlap, purge_note=""):
    def eras(m):
        return ",".join(f"{e}:{n}" for e, n in sorted(m.items(), key=lambda kv: -kv[1])) or "none"

    return (
        f"{design} | boundary {boundary_iso} | train n={train_n} | test n={test_n}"
        f" | eras train [{eras(era_train)}] test [{eras(era_test)}]"
        f" | eras on both sides: {','.join(overlap) if overlap else 'none'}"
        + (f" | {purge_note}" if purge_note else "")
    )


def _count_eras(rows, era):
    m = {}
    if era is None:
        return m
    for r in rows:
        e = era(r) or "unknown"
        m[e] = m.get(e, 0) + 1
    return m


def time_ordered_holdout(rows, at, boundary, era=None, label_ready_at=None, purge=True, design="time-ordered holdout"):
    """Sort by `at`, cut once at `boundary` (ms epoch), optionally purge leaking train rows.

    Rows tied ON the boundary go to TEST, so a tie group never straddles the cut.
    Returns a dict with train/test plus the provenance line a report must quote.
    """
    from datetime import datetime, timezone

    rows = list(rows)
    if not rows:
        raise ValueError("time_ordered_holdout: no rows")
    indexed = sorted(enumerate(rows), key=lambda p: (at(p[1]), p[0]))

    test = [r for _, r in indexed if at(r) >= boundary]
    train_all = [(i, r) for i, r in indexed if at(r) < boundary]
    if not test:
        raise ValueError(f"time_ordered_holdout: boundary {boundary} puts every row in train")
    if not train_all:
        raise ValueError(f"time_ordered_holdout: boundary {boundary} puts every row in test")

    dropped = 0
    train = []
    for _, r in train_all:
        if purge and label_ready_at is not None:
            ready = label_ready_at(r)
            if ready is not None and ready > boundary:
                dropped += 1
                continue
        train.append(r)

    era_train, era_test = _count_eras(train, era), _count_eras(test, era)
    overlap = [e for e in era_train if e in era_test]
    iso = datetime.fromtimestamp(boundary / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    note = (
        f"purged {dropped} train rows labelled after the boundary"
        if label_ready_at is not None
        else "purge: n/a (no label timestamp given)"
    )
    return {
        "train": train,
        "test": test,
        "boundary": boundary,
        "trainN": len(train),
        "testN": len(test),
        "purged": dropped,
        "tiedAtBoundary": sum(1 for r in test if at(r) == boundary),
        "eraTrain": era_train,
        "eraTest": era_test,
        "overlapEras": overlap,
        "provenance": format_provenance(design, iso, len(train), len(test), era_train, era_test, overlap, note),
    }


def walk_forward(rows, at=None, slice_of=None, era=None, label_ready_at=None, min_train=100, min_eval=50):
    """Expanding-window walk-forward: fit on strictly earlier slices, evaluate on the next.

    Mirrors `folds_time()` in scripts/fit-price-edge.py (min 100 train / 50 eval) but
    adds the purge that version did not have. Returns dicts carrying the caller's own
    row objects, in slice order.

    `at` is required only when `label_ready_at` is given: without a timestamp there is
    no window start to purge against, and silently skipping the purge would be a
    leakage the caller never asked for. A caller whose rows carry a slice label but no
    timestamp (the month-string folds) may pass at=None.
    """
    if label_ready_at is not None and at is None:
        raise ValueError("walk_forward: label_ready_at requires at (no window start to purge against)")
    rows = list(rows)
    if slice_of is None:
        if at is None:
            raise ValueError("walk_forward: without slice_of, at is required")
        from datetime import datetime, timezone

        slice_of = lambda r: datetime.fromtimestamp(at(r) / 1000, tz=timezone.utc).strftime("%Y-%m")
    labels = sorted({slice_of(r) for r in rows})
    out = []
    for label in labels:
        test_all = [r for r in rows if slice_of(r) == label]
        if len(test_all) < min_eval:
            continue
        window_start = min(at(r) for r in test_all) if at is not None else None
        train = [r for r in rows if slice_of(r) < label]
        dropped = 0
        if label_ready_at is not None:
            kept = []
            for r in train:
                ready = label_ready_at(r)
                if ready is not None and ready > window_start:
                    dropped += 1
                    continue
                kept.append(r)
            train = kept
        if len(train) < min_train:
            continue
        out.append({"label": label, "train": train, "test": test_all, "purged": dropped})
    return out


def era_groups(rows, era):
    """Per-era subsets — the per-era sign read (ML-1 gate criterion (d))."""
    m = {}
    for r in rows:
        m.setdefault(era(r) or "unknown", []).append(r)
    return m
