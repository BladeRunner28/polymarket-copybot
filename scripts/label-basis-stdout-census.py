#!/usr/bin/env python3
"""LABEL-BASIS CENSUS: does every arm that PRINTS a probability metric name its BASIS?

Card `label-integrity-stdout-basis`. Three bases, one printed figure each:
  OUTCOME  did the token we hold resolve as the winner (venue settlement / archive label)
  EXIT     did OUR leg make money (realizedPnl > 0) -- depends on the exit policy under test
  MARK     a live mark / curPrice read, never a resolution
An arm that prints "win rate 0.484" without saying which of the three it is reproduces the
2026-10-26 defect measured in scripts/label-basis-audit.py: on the SAME legs, switching the
basis moves win rate 0.484 -> 0.626, price-arm AUC 0.6508 -> 0.7427 and Brier 0.2373 -> 0.2067.

READ-ONLY: no DB, no network. It reads the printed line, not the number.
  --self-test  proves the detector can go RED (a gate that cannot fail is not a gate)
Exit 1 while ANY file in scope prints a metric arm without a basis token.

POPULATION (2026-11-26, Lane B): the GATED population is the union of the hand list CENSUS and
everything discovery() finds in scripts/, scripts/cron-scripts/, scripts/cron-gates/, src/lib/,
src/app/. Before this change discovery was advisory: the run printed "8 files / 15 arm lines
outside this census" and still said RESULT: PASS, so a new script could print an unnamed figure
and the gate would stay green. Two recall/precision defects were measured at the same time and
fixed: the detector could not see the form the profit-* scripts actually print (`hit {x:.1f}%`,
`hit%` headers -> 26 files / 79 arm lines scored as ZERO), and it counted breakeven/hurdle
arithmetic ("breakeven hit rate = mean price") and the SQL table named `hit` as if they were
label arms. A declaration banner (`print("[basis EXIT: ...]")`) now names every arm BELOW it in
the same file, and the declared family is checked against the label derivation found in the code
(a banner that says EXIT over a file that labels on the venue winner is reported as a MISMATCH).
"""
import io
import os
import re
import sys
import tokenize

VALUE = re.compile(r":\s*[^}]*[fdeg]\s*\}|%[-+ 0-9.]*[fd]|fmt\(")
# 2026-11-26 (Lane B): VALUE above only recognises a FORMAT SPEC on the same line, so six of the
# 29 hand-listed files scored 0 arms while printing win rates -- either the value sits on the next
# line of an implicitly-concatenated f-string (profit-exits.py:395) or it is a dict lookup inside
# the braces (`win_rate[...]={manifest['win_rate']}`). A line that interpolates anything renders
# a number; that is the property this census needs, not a particular format spec.
RENDERS = re.compile(r"\{[^}]*\}|%\s*[-+ 0-9.]*[dfs]|fmt\(")
TOKEN_RE = re.compile(r"basis|outcome|(?:^|[^a-z])exit(?:$|[^a-z])|(?:^|[^a-z])mark(?:$|[^a-z])", re.I)
# 2026-11-06 (self-audit, Lane B): the original pattern missed the form our cron status
# blocks actually use -- `win=46%` / `win=  49%` (copybot-kalshi-shadow.sh), `win%`-only.
# A census whose detector cannot see the printed form reports a clean screen, not a clean
# corpus: the delivered Kalshi block carried 3 such arms and scored 0 lines.
METRIC = re.compile(r"win[ _-]?rate|winrate|win%|\bwin(?:%?\[[A-Za-z_]+\]|%)?\s*=|AUC|Brier|brier|hit rate|hit%")
EMIT = re.compile("print[(]|console[.]log|console[.]warn|console[.]error")

# 2026-11-26 (Lane B): the profit-* family prints its win rate as `hit {s['hit']:.1f}%` and its
# tables as `{'hit%':>6}` headers -- neither form carried the METRIC pattern above, so 26 files
# / 79 arm lines were invisible to the detector that calls itself a census.
HITARM = re.compile(r"\bhit\b|\bwins?\b\s*[:=]\s*\{", re.I)
# A table HEADER is an arm too: `{'hit%':>6}` names the column the rows below fill.
HEADER_HIT = re.compile(r"'hit ?%'|\"hit ?%\"|'hit':|'wins':", re.I)
# Precision: `hit` as a SQLite table name, as a timing word, as prose, is not an arm.
NOT_ARM = re.compile(r"FROM\s+hit\b|hit\s+table|hit-px|100%-hit|\bhit\s+(?:the|in|by|rate of|table)", re.I)
# Precision: a printed BAR (threshold constant) is not a measured arm -- ml1-bar-restatement
# prints "AUC >= ${BAR.margin}" as a definition and would otherwise read as three unnamed arms.
NOT_ARM2 = re.compile(r"\bBAR\.|BAR_SLACK|\bin-force bar\b|absolute bar|slack check|beats_bar_", re.I)
# Precision: a breakeven/hurdle STATEMENT is arithmetic on a price, not a label read.
BREAKEVEN_ARITH = re.compile(
    r"(?:break[- ]?even|breakeven|hurdle)\s+(?:entry\s+)?(?:hit\s+rate|hit\b)|"
    r"breakeven entry|break[- ]?even hit|bnr\s*=", re.I)
# An explicit declaration banner: names the basis for every arm below it in the same file.
DECL = re.compile(r"\[\s*basis\s+(EXIT|OUTCOME|MARK)\b", re.I)
# The label derivation the code actually uses, so a declaration can be checked, not just read.
DERIV = {
    "EXIT": re.compile(r"realizedPnl[^\n]{0,24}>\s*0|\[\"pnl\"\][^\n]{0,12}>\s*0|roi_net\s*>\s*0|"
                       r"implied_exit\(|\[\"won\"\]|r\[.pnl.\] > 0", re.I),
    "OUTCOME": re.compile(r"y_side_win|finalOutcome|didOutcomeWin|tokens\[\]\.winner|"
                          r"\[\"winner\"\]|winning_outcome_label|\.upper\(\)\s*==\s*win", re.I),
}

# Files whose basis text is documented here. This list is DESCRIPTIVE, not the population:
# the gate covers the union of this list and discovery(), so a file added to scripts/ cannot
# score zero by simply being absent from this dict.
CENSUS = {
 "scripts/analyze-calibration.py": "exit+outcome (both printed)",
 "scripts/analyze-band-exit-exemption.ts": "outcome (settlementSource per row)",
 "scripts/analyze-score-separation.py": "EXIT (closed+resolved, realizedPnl>0)",
 "scripts/analyze-change2-gates.py": "EXIT (closed+resolved, pnl>0)",
 "scripts/drift-band-winrate-read.py": "OUTCOME (resolved token value)",
 "scripts/entry-floor-replay.py": "EXIT (replay pnl>0)",
 "scripts/fit-price-edge.py": "EXIT (y_win = pnl>0)",
 "scripts/jev-arm-read.py": "OUTCOME (resolved value vs entry)",
 "scripts/kalshi-lane-status.py": "OUTCOME (window direction)",
 "scripts/measure-category-fit-basis.py": "EXIT (pnl>0 on closed+resolved)",
 "scripts/ml-near-certainty-read.py": "EXIT (roi_net>0)",
 "scripts/ml-online.py": "OUTCOME (y_side_win)",
 "scripts/ml-prepare.py": "OUTCOME (y_side_win)",
 "scripts/ml-train.py": "OUTCOME (y_side_win)",
 "scripts/ml-train-market.py": "EXIT (roi_net>0)",
 "scripts/ml1-bar-restatement.ts": "EXIT (pnl_net_entry>0)",
 "scripts/pilot-score-separation.py": "OUTCOME (finalOutcome vs outcome)",
 "scripts/pilot-score-separation-papers.py": "EXIT (realizedPnl>0, stated in header)",
 "scripts/profit-exits.py": "EXIT (realizedPnl>0)",
 "scripts/profit-velocity.py": "EXIT (realizedPnl>0)",
 "scripts/rag-vs-price-baseline.py": "EXIT, resolvedAt-only subset (caveat printed)",
 "scripts/skip-edge-probe.py": "OUTCOME proxy for skips, EXIT for copies",
 "scripts/wallet-concentration-test.py": "EXIT (pnl>0, printed as leg won)",
 "scripts/wallet-depth-floor-test.py": "EXIT (pnl>0, printed as leg won)",
 "scripts/wallet-selection-test.py": "EXIT (y_win and net>0)",
 "scripts/wallet-selection-score-information.py": "EXIT (states basis at L291)",
 "scripts/build-decision-dataset.py": "EXIT (y_win = pnl>0)",
 "scripts/archive-wallet-persistence-bandneutral.py": "OUTCOME (archive outcome_label)",
 "scripts/label-basis-audit.py": "all three, side by side (this is the oracle)",
}

DISCOVERY_DIRS = ("scripts", "scripts/cron-scripts", "scripts/cron-gates", "src/lib", "src/app")
DISCOVERY_EXTS = (".py", ".ts", ".sh", ".js")


def depth_delta(s):
    """Bracket depth change of one physical line, ignoring quoted text."""
    d, q = 0, None
    for ch in s:
        if q:
            if ch == q:
                q = None
            continue
        if ch in ("'", '"', "`"):
            q = ch
        elif ch in "([{":
            d += 1
        elif ch in ")]}":
            d -= 1
    return d


def logical(lines, skip=None):
    """(first physical line, joined text) -- an implicit concatenation as ONE printed arm.

    MEASURED AND REJECTED as the default, 2026-11-26 (Lane B). It does raise recall (170 -> 210
    arms, 61 -> 99 files) but it mis-joins regions the depth counter cannot see (brackets inside
    comments and unbalanced quotes), which both invented rows and HID ones -- 18 files still
    scored zero arms and profit-velocity.py, which has 2 arms unjoined, came out empty. A recall
    change whose failures are opaque is worse than a named blind spot: the census now REPORTS the
    files it cannot see (BLIND) rather than merging lines until the count looks better. Kept for
    the next pass to fix properly (join on tokenize's LOGICAL-line information, not on a regex).
    """
    skip = skip or set()
    out, buf, first, depth = [], [], None, 0
    for i, l in enumerate(lines, 1):
        if i in skip:
            continue
        if first is None:
            if not l.strip():
                continue
            first = i
        buf.append(l)
        depth += depth_delta(l)
        cont = l.rstrip().endswith(("\\", ",", "(", "[", "{", "+", "and", "or"))
        if depth <= 0 and not cont:
            out.append((first, " ".join(x.strip() for x in buf)))
            buf, first, depth = [], None, 0
    if buf:
        out.append((first, " ".join(x.strip() for x in buf)))
    return out


def string_lines(lines):
    """Line numbers inside a MULTI-LINE string literal.

    2026-11-26 (found in this instrument's own first draft, Lane B): a banner inserted into a
    module docstring reads exactly like a declaration and credits every arm below it, while it
    never prints. A declaration has to be executable to name anything.
    """
    out = set()
    try:
        toks = tokenize.generate_tokens(io.StringIO("\n".join(lines)).readline)
        for t in toks:
            if t.type == tokenize.STRING and t.start[0] != t.end[0]:
                out.update(range(t.start[0], t.end[0] + 1))
    except (tokenize.TokenError, IndentationError):
        return set()
    return out


def classify(lines, skip=None, join=False):
    """Arms in one file: (line, text, named?) for every printed probability metric."""
    metric, last, banner = [], -1000, None
    seq = logical(lines, skip) if join else [(i, l) for i, l in enumerate(lines, 1)
                                              if i not in (skip or set())]
    for i, l in seq:
        s = l.strip()
        if not s or s[0] in ("#", "*"):
            continue
        if EMIT.search(s):
            d = DECL.search(s)
            if d:
                banner = d.group(1).upper()
                last = i
        if EMIT.search(s) and TOKEN_RE.search(s):
            last = i
        if not EMIT.search(s):
            continue
        header = HEADER_HIT.search(s)
        if not header and not (VALUE.search(s) or RENDERS.search(s)):
            continue
        if NOT_ARM.search(s) or NOT_ARM2.search(s) or BREAKEVEN_ARITH.search(s):
            continue
        if not (METRIC.search(s) or HITARM.search(s) or header):
            continue
        named = (i - last <= 12) or banner is not None
        metric.append((i, s, named))
    unnamed = [(i, s) for i, s, named in metric if not named]
    return metric, unnamed


def classify_with_banner(lines):
    """Same as classify(), plus the declared family in effect at the last arm."""
    banner = None
    skip = string_lines(lines)
    for i, l in enumerate(lines, 1):
        if i in skip:
            continue
        s = l.strip()
        if s and s[0] not in ("#", "*") and EMIT.search(s):
            d = DECL.search(s)
            if d:
                banner = d.group(1).upper()
    metric, unnamed = classify(lines, skip)
    return metric, unnamed, banner


def derive(lines):
    """Label family the file's own code computes from -- so a banner can be CHECKED."""
    text = "\n".join(lines)
    fams = [k for k, rx in DERIV.items() if rx.search(text)]
    return fams


def discover(root, extra=None, dirs=None, exts=None):
    """Every file in scope that prints a metric, whether or not it is in CENSUS."""
    out = {}
    for sub in (dirs or DISCOVERY_DIRS):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(exts or DISCOVERY_EXTS):
                continue
            rel = (sub + "/" + fn)
            try:
                lines = open(os.path.join(d, fn), errors="replace").read().split("\n")
            except OSError:
                continue
            metric, unnamed = classify(lines, string_lines(lines))
            # A file that PRINTS a metric word but yields no arm is still in scope -- otherwise
            # the one class the detector cannot join (word and value on different physical lines)
            # would also be the one class discovery never reports.
            word = any(EMIT.search(l) and (METRIC.search(l) or HITARM.search(l)) for l in lines)
            if metric or word:
                out[rel] = (len(metric), len(unnamed))
    return out


def audit(root):
    """Full run: (rows, failures, totals). rows = (rel, basis, arms, named, unnamed, banner, fams)."""
    pop = dict(discover(root))
    for rel, basis in CENSUS.items():
        if rel not in pop:
            pop[rel] = (0, 0)
    rows, failures, blind = [], [], []
    total = named = unnamed_n = 0
    for rel in sorted(pop):
        p = os.path.join(root, rel)
        basis = CENSUS.get(rel)
        if not os.path.exists(p):
            rows.append((rel, basis or "", "-", "-", "-", None, []))
            failures.append((rel, "MISSING"))
            continue
        lines = open(p, errors="replace").read().split("\n")
        skip = string_lines(lines)
        metric, unnamed = classify(lines, skip)
        banner = None
        for i, l in enumerate(lines, 1):
            if i in skip:
                continue
            s = l.strip()
            if s and s[0] not in ("#", "*") and EMIT.search(s):
                d = DECL.search(s)
                if d:
                    banner = d.group(1).upper()
        fams = derive(lines)
        total += len(metric)
        named += len(metric) - len(unnamed)
        unnamed_n += len(unnamed)
        rows.append((rel, basis or "", len(metric), len(metric) - len(unnamed), len(unnamed),
                     banner, fams))
        # A file with a metric WORD but no detected arm is the remaining blind spot: the word and
        # its rendered value can sit on different physical lines of an implicit concatenation, which
        # this detector (one physical line at a time) cannot join. Named here rather than counted
        # as coverage -- 4 of the 29 hand-listed files already sit in this bucket.
        if not metric and any(EMIT.search(l) and (METRIC.search(l) or HITARM.search(l)) for l in lines):
            blind.append(rel)
        if unnamed:
            failures.append((rel, "UNNAMED"))
        if banner and fams and banner not in fams:
            failures.append((rel, "MISMATCH:%s-vs-%s" % (banner, "+".join(fams))))
    return rows, failures, (total, named, unnamed_n), blind


def self_test():
    """Prove the detector and the GATE can each go RED -- presence checks are not gates."""
    ok = True
    def arm(name, cond):
        nonlocal ok
        print("  %-58s %s" % (name, "PASS" if cond else "FAIL"))
        ok = ok and cond
    good, ug = classify(['print(f"  win rate[EXIT: pnl>0] {x:.3f}")'])
    arm("named arm line is counted and clean", len(good) == 1 and not ug)
    bad, ub = classify(['print(f"  win rate {x:.3f}")'])
    arm("unnamed arm line is flagged", len(bad) == 1 and len(ub) == 1)
    hit, hu = classify(['print(f"  hit {s[\'hit\']:.1f}% be {s[\'be\']:.1f}%")'])
    arm("hit-form arm (invisible before 2026-11-26) is counted", len(hit) == 1 and len(hu) == 1)
    hdr, hd = classify(['print(f"  {\'band\':<10} {\'hit%\':>6} {\'edge_pp\':>8}")'])
    arm("hit% header arm is counted", len(hdr) == 1 and len(hd) == 1)
    tbl, _ = classify(['print(f"  our fills: {con.sql(\'SELECT COUNT(*) FROM hit\').fetchone()[0]:,}")'])
    arm("SQL table named hit is NOT an arm", not tbl)
    be, _ = classify(['print(f"  breakeven hit rate = the entry paid = {100*sum(a)/len(legs):.1f}%")'])
    arm("breakeven arithmetic is NOT an arm", not be)
    dec, du = classify(['print("[basis EXIT: realizedPnl>0]")',
                        'x = 1', 'x = 2', 'y = 3', 'z = 4',
                        'print(f"  hit {s[\'hit\']:.1f}%")'])
    arm("a declaration banner names a distant arm", len(dec) == 1 and not du)
    doc, _, _ = classify_with_banner(['"""', 'print("[basis EXIT: docstring, never runs]")', '"""',
                                      'print(f"  hit {h:.1f}%")'])
    arm("a banner inside a docstring names nothing", len(doc) == 1 and not doc[0][2])
    nm, nu = classify(['print(f"  hit {s[\'hit\']:.1f}%")'])
    arm("without a banner the same arm is UNNAMED", len(nm) == 1 and len(nu) == 1)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "scripts"))
        open(os.path.join(td, "scripts", "zz-new-instrument.py"), "w").write(
            'print(f"  AUC {auc:.4f} hit {hit:.1f}%")\n')
        rows, fails = audit(td)[:2]
        rels = [r[0] for r in rows]
        arm("a file NOT in the hand list enters the gated population",
            "scripts/zz-new-instrument.py" in rels)
        arm("...and FAILS the gate while unnamed", any("zz-new" in f[0] for f in fails))
        open(os.path.join(td, "scripts", "zz-new-instrument.py"), "w").write(
            'print("[basis OUTCOME: venue winner]")\nprint(f"  AUC {auc:.4f} hit {hit:.1f}%")\n')
        _, fails2 = audit(td)[:2]
        arm("...and PASSES once the banner names it",
            not [f for f in fails2 if "zz-new" in f[0]])
        open(os.path.join(td, "scripts", "zz-new-instrument.py"), "w").write(
            'won = 1 if realizedPnl > 0 else 0\n'
            'print("[basis OUTCOME: venue winner]")\nprint(f"  hit {hit:.1f}%")\n')
        _, fails3 = audit(td)[:2]
        arm("a banner that contradicts the code is a MISMATCH",
            any("MISMATCH" in f[1] for f in fails3 if "zz-new" in f[0]))
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "scripts"))
        with open(os.path.join(td, "scripts", "zz-blind.py"), "w") as fh:
            fh.write('print(f"  win rate on the settled subset: ")\n')
            fh.write('print(f"      {w:.3f}")\n')
        blind = audit(td)[3]
        arm("a metric word with no detected arm is reported BLIND, not clean",
            "scripts/zz-blind.py" in blind)
    print("SELF-TEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv):
    if "--self-test" in argv:
        return self_test()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rows, failures, (total, named, unnamed_n), blind = audit(root)
    print("LABEL-BASIS CENSUS -- every arm that PRINTS a win-rate/AUC/Brier/hit-rate line")
    print("%-54s %-42s %5s %5s %5s %-8s" % ("file", "basis", "arms", "named", "UNNAMED", "decl"))
    for rel, basis, arms, nm, un, banner, fams in rows:
        print("%-54s %-42s %5s %5s %5s %-8s" % (rel, basis[:42], arms, nm, un, banner or "-"))
    bad = {}
    for rel, why in failures:
        bad.setdefault(rel, []).append(why)
    if bad:
        print("")
        for rel in sorted(bad):
            print("  FAIL %-46s %s" % (rel, ", ".join(bad[rel])))
    hand = sum(1 for r in rows if r[0] in CENSUS)
    print("")
    print("ARM LINES %d | NAMED %d | UNNAMED %d" % (total, named, unnamed_n))
    print("POPULATION %d files = %d hand-listed + %d found by discovery (all of them GATED now)"
          % (len(rows), hand, len(rows) - hand))
    if blind:
        print("BLIND %d file(s) print a metric WORD but no arm was detected (word and value on"
              " different physical lines): %s" % (len(blind), ", ".join(sorted(blind))))
    print("An UNNAMED arm is not by itself a wrong NUMBER -- it is a printed figure that does not")
    print("say what it measures, which is the exact class this card closed. Any UNNAMED line is FAIL.")
    print("A MISMATCH is worse than an UNNAMED: the file says one basis and computes another.")
    print("RESULT: " + ("FAIL" if failures else "PASS"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
