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

BLIND CLASS CLOSED (2026-11-27, Lane B, card label-basis-census-blind-join): 18 files were named
BLIND because the detector read ONE PHYSICAL LINE, and a `.py` print split as
`print(f"  hit rate ...: " f"{x:.1f}%")` puts the word and its value on different lines. Python is
now joined on tokenize's LOGICAL statements (NL vs NEWLINE), which is exact; the depth-counter
joiner is kept above only as the record of a measured rejection. `.ts/.js/.sh` are deliberately NOT
joined -- a line that visibly continues is reported BLIND instead. And every line that carries a
metric word and is NOT an arm now prints the RULE that excluded it (no rendered value, breakeven
arithmetic, SQL table `hit`, slug/path, bar constant), so removing a file from BLIND can never be a
silent edit. BLIND is a FAILURE, not a footnote: printing the list under RESULT: PASS is exactly how
18 files sat unexplained.
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
# 2026-11-27 (Lane B): a string literal followed by a COMMA is a call passing further arguments,
# i.e. a rendered value in the form .ts actually uses. A lone label string is not.
RENDERS_ARG = re.compile(r"""["'`]\s*,""")
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
NOT_ARM = re.compile(r"FROM\s+hit\b|hit\s+table|hit-px\s*==|100%-hit|\bhit\s+(?:the|in|by|rate of|table)", re.I)
# Precision: a printed BAR (threshold constant) is not a measured arm -- ml1-bar-restatement
# prints "AUC >= ${BAR.margin}" as a definition and would otherwise read as three unnamed arms.
NOT_ARM2 = re.compile(r"\bBAR\.|BAR_SLACK|\bin-force bar\b|absolute bar|slack check|beats_bar_", re.I)
# Precision: a breakeven/hurdle STATEMENT is arithmetic on a price, not a label read.
BREAKEVEN_ARITH = re.compile(
    r"(?:break[- ]?even|breakeven|hurdle)\s+(?:entry\s+)?(?:hit\s+rate|hit\b)|"
    r"breakeven entry|break[- ]?even hit|bnr\s*=", re.I)
# An explicit declaration banner: names the basis for every arm below it in the same file.
# 2026-11-27 (Lane B, card label-basis-census-blind-join): deciding BLIND needs to see a metric
# WORD, not a substring of a slug or a filename. `band_winrate` is a variable and
# `data/gate-winrate-basis.json` is a path: neither prints a win rate. Arm COUNTING keeps the
# looser METRIC/HITARM above so no arm changes population on a detector tweak.
METRIC_STRICT = re.compile(
    r"(?<![A-Za-z0-9_])win[ _-]?rate(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])win%(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])win(?:%?\[[A-Za-z_]+\]|%)?\s*="
    r"|(?<![A-Za-z0-9])AUC(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])[Bb]rier(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])hit rate(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])hit%(?![A-Za-z0-9_])")
HITARM_STRICT = re.compile(r"(?<![A-Za-z0-9_])(?:hit|hits|wins?)(?![A-Za-z0-9_])", re.I)
PATHLIKE = re.compile(r"[A-Za-z0-9_./-]*(?:winrate|win-rate|win_rate)[A-Za-z0-9_./-]*"
                      r"\.(?:json|jsonl|ts|js|py|sh|csv|md)\b", re.I)
# A hyphen/underscore SLUG is a NAME, not a metric mention: `band_winrate`,
# `gate-winrate-basis-read`, `win-rate-by-price`. Prose writes "win rate" with a space; a bare
# `winrate` / `win rate` / `hit%` is a metric. This is what separates L229 of
# gate-winrate-basis-read.ts (a path it wrote) from an arm.
SLUG = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z0-9]+[-_]){1,}(?:win[-_]?rate|winrate)(?:[-_][A-Za-z0-9]+)*"
    r"|(?<![A-Za-z0-9_])(?:win[-_]?rate|winrate)(?:[-_][A-Za-z0-9]+)+(?![A-Za-z0-9_])")


def looks_continued(s):
    """A physical line that cannot have ENDED its statement (unjoined .ts/.js/.sh only).

    It chooses a REASON; it never joins anything (the depth joiner was rejected on measurement).
    A trailing `;` CLOSES a JS statement, so the closed forms are NO-RENDERED-VALUE, not blind.
    """
    t = s.rstrip()
    return t.endswith((",", "(", "[", "{", "+", "`", "&&", "||", "?"))


def has_metric_word(s):
    """Does this text print a metric WORD once names/paths are removed?"""
    return bool(METRIC_STRICT.search(SLUG.sub(" ", PATHLIKE.sub(" ", s)))
                or HITARM_STRICT.search(SLUG.sub(" ", PATHLIKE.sub(" ", s))))


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


def logical_py(lines, skip=None):
    """(first physical line, joined text, last physical line) per LOGICAL statement.

    2026-11-27 (Lane B): the depth-counter joiner above was REJECTED on measurement because it
    GUESSES where a statement ends (brackets inside comments, unbalanced quotes) and both invented
    and hid rows. tokenize does not guess -- it emits NL for a line that continues inside brackets
    and NEWLINE only when the statement is complete -- so a multi-line print joins exactly and
    nothing else can merge. A statement whose tokens are all STRING (a module docstring, which may
    well QUOTE a print call) is skipped: text in a docstring never runs.
    Python only; .ts/.js/.sh are deliberately NOT joined (see audit()).
    """
    out = []
    ign = {tokenize.INDENT, tokenize.DEDENT, tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
           tokenize.ENCODING, tokenize.ENDMARKER}
    start, kinds, names = None, set(), set()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO("\n".join(lines)).readline))
    except (tokenize.TokenError, IndentationError):
        return out
    for t in toks:
        if t.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            if start is not None and kinds - {tokenize.STRING}:
                txt = " ".join(lines[r - 1].strip() for r in range(start[0], t.start[0] + 1)
                                if 0 < r <= len(lines))
                out.append((start[0], txt, t.start[0], names))
            start, kinds, names = None, set(), set()
            continue
        if t.type in ign:
            continue
        if start is None:
            start = t.start
        kinds.add(t.type)
        if t.type == tokenize.NAME:
            names.add(t.string)
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
    seq = logical_py(lines, skip) if join else [(i, l, i, None) for i, l in enumerate(lines, 1)
                                                if i not in (skip or set())]
    for i, l, _end, names in seq:
        s = l.strip()
        if not s or s[0] in ("#", "*"):
            continue
        # A joined .py statement emits only when `print` is a real NAME token: a triple-quoted
        # string that happens to CONTAIN the text of a print call is not one (2026-11-27).
        emits = ("print" in names) if names is not None else bool(EMIT.search(s))
        if emits:
            d = DECL.search(s)
            if d:
                banner = d.group(1).upper()
                last = i
        if emits and TOKEN_RE.search(s):
            last = i
        if not emits:
            continue
        header = HEADER_HIT.search(s)
        if not header and not (VALUE.search(s) or RENDERS.search(s)
                               or (RENDERS_ARG.search(s) and has_metric_word(s))):
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


def explain(lines, skip, py, metric):
    """One DISPOSITION per statement that carries a metric word: why it is not an arm.

    2026-11-27 (Lane B, card label-basis-census-blind-join): the old blind test asked only 'does a
    printed line contain a metric word and yield no arm', which flagged 18 files -- 14 of which are
    prose, a section heading, breakeven arithmetic, a SQLite table named `hit`, a filename, or a
    sentence ABOUT a metric. A list of 18 pseudo-defects teaches the reader to ignore the list.
    Every excluded line now names the RULE that excluded it, and the only line with no rule left is
    reported BLIND -- which fails the gate instead of being a footnote.
    """
    arms = {i for i, _s, _n in metric}
    out = []
    if py:
        seq = logical_py(lines, skip)
    else:
        seq = [(i, l, i, None) for i, l in enumerate(lines, 1) if i not in (skip or set())]
    for i, s, _end, names in seq:
        t = s.strip()
        if not t or t[0] in ("#", "*"):
            continue
        emits = ("print" in names) if names is not None else bool(EMIT.search(s))
        if not (emits and (METRIC.search(s) or HITARM.search(s))):
            continue
        if i in arms:
            continue
        m = NOT_ARM.search(s)
        if m:
            why = "NOT_ARM (%s)" % m.group(0)[:26]
        elif NOT_ARM2.search(s):
            why = "BAR CONSTANT"
        elif BREAKEVEN_ARITH.search(s):
            why = "BREAKEVEN ARITHMETIC"
        elif not has_metric_word(s):
            why = "SLUG/PATH, not a metric word"
        elif not (VALUE.search(s) or RENDERS.search(s)):
            # Python: the statement is complete, so no value can be hiding on another line.
            # .ts/.js/.sh: nothing is joined, so a line that visibly continues (trailing comma or
            # open bracket) MIGHT carry the value below -- reported BLIND rather than assumed clean.
            why = "NO RENDERED VALUE" if py else ("BLIND" if looks_continued(s) else
                                                  "NO RENDERED VALUE")
        else:
            why = "BLIND"
        out.append((i, why, t[:110]))
    return out


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
    rows, failures, blind, explained = [], [], [], []
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
        py = rel.endswith(".py")
        metric, unnamed = classify(lines, skip, join=py)
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
        # Every statement that carries a metric word now gets a DISPOSITION. A statement this
        # detector cannot join to a value is BLIND and FAILS the gate (2026-11-27): printing the
        # list while calling the run PASS is what let 18 files sit unexplained.
        for ln, why, txt in explain(lines, skip, py, metric):
            if why == "BLIND":
                blind.append((rel, ln, txt))
            else:
                explained.append((rel, ln, why))
        if unnamed:
            failures.append((rel, "UNNAMED"))
        if any(b[0] == rel for b in blind):
            for ln, txt in [(b[1], b[2]) for b in blind if b[0] == rel]:
                failures.append((rel, "BLIND:L%d" % ln))
        if banner and fams and banner not in fams:
            failures.append((rel, "MISMATCH:%s-vs-%s" % (banner, "+".join(fams))))
    return rows, failures, (total, named, unnamed_n), blind, explained


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
    # ---- 2026-11-27 arms: the BLIND class is closed on RULES, not on a curated exemption list
    j, ju = classify(['print(f"   settle win rate [EXIT: realizedPnl>0] on the settled subset: "',
                      '      f"{100 * n / m:.1f}% vs mean entry price")'], join=True)
    arm("a multi-line print joins into ONE arm (tokenize, not bracket depth)",
        len(j) == 1 and not ju)
    j2, j2u = classify(['print(f"   settle win rate on the settled subset: "',
                        '      f"{100 * n / m:.1f}%")'], join=True)
    arm("...and stays UNNAMED when the joined statement names no basis",
        len(j2) == 1 and len(j2u) == 1)
    doc2, _ = classify(['"""', 'print(f"  win rate {x:.2f}")', '"""'], join=True)
    arm("a docstring that QUOTES a print is not an arm", len(doc2) == 0)
    arm("a slug is not a metric word (band_winrate)", not has_metric_word("skill as band_winrate"))
    arm("a path is not a metric word (data/gate-winrate-basis.json)",
        not has_metric_word("wrote data/gate-winrate-basis.json"))
    arm("an error envelope naming the script is not a metric word",
        not has_metric_word('console.error("gate-winrate-basis-read FAILED:", e)'))
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "scripts"))
        # two SEPARATE prints are two statements: the census joins one statement, never neighbours
        with open(os.path.join(td, "scripts", "zz-split.py"), "w") as fh:
            fh.write('print("  win rate on the settled subset: ")\n')
            fh.write('print("      {:.3f}".format(w))\n')
        rows4, fails4, _t4, blind4, expl4 = audit(td)
        arm("two separate prints are NOT merged into one arm",
            _t4[0] == 0 and not blind4)
        arm("...and the word-only label still gets a printed disposition",
            any(e[0] == "scripts/zz-split.py" for e in expl4))
            # a metric line this detector cannot join is BLIND and RED
        os.makedirs(os.path.join(td, "src", "lib"))
        with open(os.path.join(td, "src", "lib", "zz-blind.ts"), "w") as fh:
            fh.write('console.log("  win rate on the settled subset:",\n')
            fh.write("            x.toFixed(3));\n")
        _r5, fails5, _t5, blind5, _e5 = audit(td)
        arm("a .ts call split after its comma is caught (arm, unnamed)",
            any(f[0] == "src/lib/zz-blind.ts" for f in fails5))
        # BLIND itself: a word and a concatenation that carries the value below, no console.log
        # on the value line, so nothing can attach a basis to it.
        with open(os.path.join(td, "src", "lib", "zz-blind.ts"), "w") as fh:
            fh.write('console.log("  hit rate " +\n')
            fh.write("            x.toFixed(3));\n")
        _r5b, fails5b, _t5b, blind5b, _e5b = audit(td)
        arm("a .ts line that visibly continues with no value is BLIND",
            any(b[0] == "src/lib/zz-blind.ts" for b in blind5b))
        arm("...and BLIND FAILS the gate (a footnote in a PASS run shipped 18 files)",
            any(f[0] == "src/lib/zz-blind.ts" for f in fails5b))
        with open(os.path.join(td, "src", "lib", "zz-blind.ts"), "w") as fh:
            fh.write('console.log("  hit rate [EXIT: pnl>0] " + x.toFixed(3));\n')
        _r6, fails6, _t6, blind6, _e6 = audit(td)
        arm("...and PASSES once the value and the basis are on one line",
            not any(f[0] == "src/lib/zz-blind.ts" for f in fails6) and not blind6)
        with open(os.path.join(td, "src", "lib", "zz-blind.ts"), "w") as fh:
            fh.write('console.log("   ranker    AUC(win)  wallet-clustered CI");\n')
        _r7, fails7, _t7, blind7, _e7 = audit(td)
        arm("a .ts column header prints no figure, so it is not blind",
            not blind7 and not any(f[0] == "src/lib/zz-blind.ts" for f in fails7))
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "scripts"))
        with open(os.path.join(td, "scripts", "zz-det.py"), "w") as fh:
            fh.write('print("  AUC {:.4f} hit {:.1f}%".format(a, h))\n')
        a1, f1, t1, b1, e1 = audit(td)
        a2, f2, t2, b2, e2 = audit(td)
        arm("the census is deterministic across two consecutive runs",
            t1 == t2 and f1 == f2 and b1 == b2)
    print("SELF-TEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv):
    if "--self-test" in argv:
        return self_test()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rows, failures, (total, named, unnamed_n), blind, explained = audit(root)
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
    # 2026-11-27 (Lane B): every line that carries a metric WORD and is not an arm now names the
    # rule that excluded it. The list is printed in full, so removing a file from BLIND can never be
    # a silent edit: either a basis token appeared, or one of these named rules applies.
    byrule = {}
    for rel, ln, why in explained:
        byrule.setdefault(why, []).append("%s:L%d" % (rel, ln))
    print("WORD LINES THAT ARE NOT ARMS %d, each with the rule that excludes it:" % len(explained))
    for why in sorted(byrule, key=lambda w: (-len(byrule[w]), w)):
        print("  %-34s %4d  %s" % (why[:34], len(byrule[why]), ", ".join(byrule[why])[:150]))
    if blind:
        print("BLIND %d statement(s) print a metric WORD and a VALUE this detector cannot join:"
              % len(blind))
        for rel, ln, txt in blind:
            print("  %-46s L%-5d %s" % (rel, ln, txt[:110]))
    print("An UNNAMED arm is not by itself a wrong NUMBER -- it is a printed figure that does not")
    print("say what it measures, which is the exact class this card closed. Any UNNAMED line is FAIL.")
    print("A MISMATCH is worse than an UNNAMED: the file says one basis and computes another.")
    print("A BLIND statement is a printed figure this detector could not attach to a basis at all;")
    print("since 2026-11-27 it FAILS the gate instead of being a footnote in a PASS run.")
    print("RESULT: " + ("FAIL" if failures else "PASS"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
