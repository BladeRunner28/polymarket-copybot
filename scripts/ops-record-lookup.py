#!/usr/bin/env python3
"""ops-record-lookup — ask the record before designing anything.

WHY (card `jev-ops-retrieval`, approved 2026-10-06, never built): the review crons
re-propose shipped work because their evidence is invented SQL, not the record of
what landed. Two duplicate-work incidents on this repo were caused by skipping the
grep — a duplicate pre-registration and a claim that had already been fixed. The
record already exists: data/roadmap.json card notes (which already carry the
measured numbers, the population and the reproduce command), drafts/*.md, and the
ops skill. It was simply not queryable in one step.

SCOPE, and what this is NOT: read-only retrieval. It answers "has this been done or
measured already, and where does the record say so" WITH PATHS. It has no edge, it
changes no decision, it writes nothing but its own JSON artifact. It is not a
predictor — that route was measured and closed on `jev-rag-corpus-index` (retrieval
base rates lost to the price arm out of sample: Brier 0.2607 vs 0.2165).

A status column is not a claim. Every hit prints the card's COLUMN, because the
failure mode this tool exists for is reading a Done card's number as an open
question, or re-deriving a measurement that is already in the note.

ARMS measured by --eval on the fixed eval set data/ops-record-eval.json (16
queries, every one drawn from a real incident on this board):
  A  bm25-doc     title (3x) + tags + whole note, doc-level  <- PRE-REGISTERED
  A1 bm25-hybrid  A plus an independently scored key field (id+title+tags, 2.5x)
  A2 bm25-passage notes split into ~350-char passages, max passage per doc
  B  bm25-title   titles only                                <- mutation control
  C  literal-AND  what a reviewer's `grep -l` gives: every query stem present,
                  ranked by first occurrence                 <- the incumbent habit

MEASURED 2026-11-22T02:05Z, corpus 309 cards + 503 drafts = 812 docs (`--eval --json`):
  A 0.500 @1 / 0.875 @3 / 0.938 @5 / MRR 0.690
  A1 0.625 @1 / 0.750 @3 / 0.875 @5 / MRR 0.714
  A2 0.250 @1 / 0.625 @3 / 0.625 @5 / MRR 0.448   <- REFUTED, do not re-propose
  B 0.562 @1 / 0.750 @3 / 0.750 @5 / MRR 0.634
  C 0.125 @1 / 0.188 @3 / 0.188 @5 / MRR 0.156
Gate PASS on A (0.875 >= 0.875, beats literal on 13 queries, A > B). Two honest
weaknesses: A's rank-1 rate is no better than titles alone (the note index pays off
at rank 3, which is what a reviewer reads), and passage-level retrieval LOSES on
this corpus by 4 queries — a negative that was measured, not assumed. Of the two
queries not in A's top 3, one is rank 5 and one is rank 236 — the second is a true
lexical miss, not a near one.

PRE-REGISTERED GATE (GATE, declared before the first run, not moved after):
  A recall@3 >= 0.875  AND  A beats C by >= 2 queries  AND  A > B strictly.
  If any clause fails the honest report is "does not beat grep", and the card
  stays open with this number rather than a claim that it works.

Usage:
  python3 scripts/ops-record-lookup.py --query "how far back does kalshi serve settled markets"
  python3 scripts/ops-record-lookup.py --eval
  python3 scripts/ops-record-lookup.py --self-test
"""
import argparse
import glob
import json
import math
import os
import re
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROADMAP = os.path.join(ROOT, "data", "roadmap.json")
DRAFTS = os.path.join(ROOT, "drafts")
EVAL_FILE = os.path.join(ROOT, "data", "ops-record-eval.json")
ARTIFACT = os.path.join(ROOT, "data", "ops-record-lookup.json")
SKILLS_GLOB = os.path.expanduser("~/.hermes/skills/*")
DRAFT_CHARS = 6000
SKILL_CHARS = 4000

# Pre-registered, before the first run.
GATE = {"recall3": 0.875, "beat_literal_by": 2}

STOP = set("""a an the and or of to in on at by for with from is are was were be been
being this that these those it its as into than then so if not no any all can could
should would will may might must do does did done have has had we our us you your they
their he she his her which what who whom whose how why when where there here about over
under more most less least up down out off again also just only very much many such same
other another each both few some none nor but however because while during before after
above below between within without against per via etc n b c d e g h i j k l m o p q r s t u v w x y z""".split())


def as_text(v):
    """Roadmap notes are strings except one legacy array row (tr39-print-type-ingest-guard)."""
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return v or ""


def stem(t):
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def tokenize(text):
    raw = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = []
    for w in raw:
        if w in STOP or (len(w) < 3 and not w.isdigit()):
            continue
        out.append(stem(w))
    return out


def split_passages(text, width=350, max_passages=80):
    """Long notes (the queue card is ~100KB) dilute a doc-level BM25 score: the one
    sentence that answers a query competes with hundreds that do not. Score passages
    and aggregate to the doc, which is the standard fix and not a query tweak."""
    parts = [p.strip() for p in re.split(r"(?<=[.;:])\s+|\n+", text or "") if p.strip()]
    out, buf = [], ""
    for p in parts:
        if len(buf) + len(p) + 1 <= width:
            buf = (buf + " " + p).strip()
        else:
            if buf:
                out.append(buf)
            buf = p[:width]
            if len(p) > width:
                out.append(buf)
                buf = ""
        if len(out) >= max_passages:
            break
    if buf:
        out.append(buf)
    return out[:max_passages] or [""]


class Index(object):
    def __init__(self, docs, title_boost=3, k1=1.2, b=0.75, passage_level=False):
        self.docs = docs
        self.k1, self.b = k1, b
        self.passage_level = passage_level
        self.tfs, self.lens, self.stemsets, self.unit_doc = [], [], [], []
        for di, d in enumerate(docs):
            units = split_passages(d["text"]) if passage_level else [d.get("text") or ""]
            for ui, u in enumerate(units):
                tf = Counter(tokenize(u))
                if ui == 0:
                    for t in tokenize(d.get("title", "")):
                        tf[t] += title_boost
                self.tfs.append(tf)
                self.lens.append(sum(tf.values()) or 1)
                self.stemsets.append(set(tf))
                self.unit_doc.append(di)
        self.avg = sum(self.lens) / float(max(1, len(self.lens)))
        self.df = Counter()
        for tf in self.tfs:
            for t in tf:
                self.df[t] += 1
        self.N = len(docs)

    def idf(self, t):
        df = self.df.get(t, 0)
        return math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def rank(self, query):
        """Full ranking: list of (score, doc_index), best first, score > 0 only."""
        qt = tokenize(query)
        scored = []
        for i, tf in enumerate(self.tfs):
            s = 0.0
            for t in qt:
                f = tf.get(t, 0)
                if not f:
                    continue
                s += self.idf(t) * (f * (self.k1 + 1.0)) / (
                    f + self.k1 * (1.0 - self.b + self.b * self.lens[i] / self.avg))
            if s > 0:
                scored.append((s, i))
        if self.passage_level:
            best = {}
            for s, ui in scored:
                di = self.unit_doc[ui]
                if s > best.get(di, -1.0):
                    best[di] = s
            scored = [(s, di) for di, s in best.items()]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored

    def literal_rank(self, query):
        """grep-like arm: every query stem must be present; ordered by first offset."""
        qt = sorted(set(tokenize(query)))
        if not qt:
            return []
        scored = []
        for i, d in enumerate(self.docs):
            qset = set(qt)
            if not qset.issubset(self.stemsets[i]):
                continue
            low = (d["text"] or "").lower()
            first = min([low.find(t) if low.find(t) >= 0 else 10 ** 9 for t in qt])
            scored.append((float(-first), i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored


def build_docs(include_skills=False):
    docs = []
    with open(ROADMAP) as fh:
        rm = json.load(fh)
    for c in rm.get("cards", []):
        tags = c.get("tags") or []
        docs.append({
            "kind": "card",
            "id": c.get("id"),
            "title": c.get("title") or c.get("id"),
            "column": c.get("column"),
            "tags": tags,
            "path": "data/roadmap.json",
            "text": " ".join([c.get("id") or "", c.get("title") or "",
                              " ".join(tags), as_text(c.get("note"))]),
        })
    for p in sorted(glob.glob(os.path.join(DRAFTS, "*.md"))):
        try:
            with open(p, errors="replace") as fh:
                body = fh.read(DRAFT_CHARS)
        except OSError:
            continue
        head = next((ln.strip("# ").strip() for ln in body.splitlines() if ln.strip()), "")
        docs.append({
            "kind": "draft",
            "id": os.path.basename(p),
            "title": head or os.path.basename(p),
            "column": None,
            "tags": [],
            "path": "drafts/" + os.path.basename(p),
            "text": body,
        })
    if include_skills:
        for p in sorted(glob.glob(os.path.join(SKILLS_GLOB, "**", "*.md"), recursive=True)):
            try:
                with open(p, errors="replace") as fh:
                    body = fh.read(SKILL_CHARS)
            except OSError:
                continue
            head = next((ln.strip("# ").strip() for ln in body.splitlines() if ln.strip()), "")
            docs.append({
                "kind": "skill",
                "id": os.path.basename(p),
                "title": head or os.path.basename(p),
                "column": None,
                "tags": [],
                "path": p,
                "text": body,
            })
    return docs


def snippet(doc, query, width=240):
    qt = set(tokenize(query))
    body = doc["text"]
    parts = re.split(r"(?<=[.;])\s+|\n+", body)
    # the first chunk is the id/title/tags header, which trivially contains query
    # terms; quote it only when nothing else matches.
    rest = [p for p in parts[1:] if p.strip() and not p.strip().startswith(doc["id"])]
    parts = rest or parts
    best, best_n = "", -1
    for p in parts:
        n = len(qt & set(tokenize(p)))
        if n > best_n and p.strip():
            best, best_n = p.strip(), n
    out = re.sub(r"\s+", " ", best or body)[:width]
    return out


def fmt_hit(doc, score, rank):
    status = doc.get("column") or doc["kind"]
    flag = " !awaiting-approval" if "awaiting-approval" in (doc.get("tags") or []) else ""
    return " %2d. [%s] %s  (%.1f)%s\n     %s :: %s" % (
        rank, status, doc["id"], score, flag, doc["path"], doc["kind"])


def run_query(docs, query, k=5, arm="full", kind="all"):
    """`kind` filters the CORPUS, it never re-ranks: a card prior would be
    self-fulfilling, because every eval answer is itself a card."""
    if kind != "all":
        docs = [d for d in docs if d["kind"] == kind]
    idx = Index(docs)
    if arm == "hybrid":
        ranked = hybrid_rank(docs, query)
    elif arm == "literal":
        ranked = idx.literal_rank(query)
    else:
        ranked = idx.rank(query)
    hits = [(s, docs[i]) for s, i in ranked[:k]]
    lines = ["Q: %s" % query]
    if not hits:
        lines.append("  (no hit — nothing in the record shares a term with this query)")
    for n, (s, d) in enumerate(hits, 1):
        lines.append(fmt_hit(d, s, n))
        lines.append("     \"%s\"" % snippet(d, query))
    return "\n".join(lines)


def load_eval(docs):
    with open(EVAL_FILE) as fh:
        ev = json.load(fh)
    ids = set(d["id"] for d in docs if d["kind"] == "card")
    bad = [q["expect"] for q in ev["queries"] if q["expect"] not in ids]
    if bad:
        raise SystemExit("REFUSED: eval queries name card ids that do not exist: %s" % bad)
    return ev


def hybrid_rank(docs, query, weight=2.5):
    """Field-weighted: the note field alone drowns a 6-token title in 3-10k tokens
    (BM25 title boost inside one concatenated doc is length-diluted), so score the
    short key field (id + title + tags) with its own statistics and add it."""
    note = Index(docs)
    key = Index([dict(d, text=" ".join([d["id"] or "", d.get("title") or "",
                                        " ".join(d.get("tags") or [])])) for d in docs])
    ns = dict((i, sc) for sc, i in note.rank(query))
    ks = dict((i, sc) for sc, i in key.rank(query))
    comb = [(ns.get(i, 0.0) + weight * ks.get(i, 0.0), i) for i in set(ns) | set(ks)]
    comb.sort(key=lambda x: (-x[0], x[1]))
    return comb


def arm_ranks(docs, queries, arm):
    idx = Index(docs, passage_level=(arm == "passage"))
    ranks = []
    for q in queries:
        if arm == "literal":
            ranked = idx.literal_rank(q["q"])
        elif arm == "title":
            ranked = Index([dict(d, text=d.get("title") or d["id"]) for d in docs]).rank(q["q"])
        elif arm == "hybrid":
            ranked = hybrid_rank(docs, q["q"])
        else:
            ranked = idx.rank(q["q"])
        order = [docs[i]["id"] for _, i in ranked]
        try:
            ranks.append(order.index(q["expect"]) + 1)
        except ValueError:
            ranks.append(None)
    return ranks


def summarize(ranks, k):
    hit = sum(1 for r in ranks if r is not None and r <= k)
    return hit / float(len(ranks))


def mrr(ranks):
    return sum((1.0 / r) for r in ranks if r is not None) / float(len(ranks))


def run_eval(docs, quiet=False):
    ev = load_eval(docs)
    queries = ev["queries"]
    arms = {}
    for arm in ("full", "hybrid", "passage", "title", "literal"):
        ranks = arm_ranks(docs, queries, arm)
        arms[arm] = {
            "ranks": dict((q["expect"], r) for q, r in zip(queries, ranks)),
            "recall1": summarize(ranks, 1),
            "recall3": summarize(ranks, 3),
            "recall5": summarize(ranks, 5),
            "mrr": mrr(ranks),
        }
    a, b, c = arms["full"], arms["title"], arms["literal"]
    missed = ["%s(rank %s)" % (cid, r if r is not None else "none")
              for cid, r in a["ranks"].items() if r is None or r > 3]
    beat_c = sum(1 for q in queries
                 if (a["ranks"][q["expect"]] or 10 ** 6) < (c["ranks"][q["expect"]] or 10 ** 6))
    gate = {
        "recall3_met": a["recall3"] >= GATE["recall3"],
        "beats_literal_met": beat_c >= GATE["beat_literal_by"],
        "beats_title_met": a["recall3"] > b["recall3"],
        "queries_beating_literal": beat_c,
    }
    gate["pass"] = all([gate["recall3_met"], gate["beats_literal_met"], gate["beats_title_met"]])
    if not quiet:
        print("OPS RECORD LOOKUP — eval on %d queries (data/ops-record-eval.json), corpus %d docs"
              % (len(queries), len(docs)))
        print("  arm            recall@1  recall@3  recall@5   MRR")
        for name, label in (("full", "A bm25-doc   (pre-reg)"), ("hybrid", "A1 bm25-hybrid"),
                            ("passage", "A2 bm25-passage"), ("title", "B bm25-title"),
                            ("literal", "C literal-AND")):
            x = arms[name]
            print("  %-14s %8.3f  %8.3f  %8.3f  %5.3f"
                  % (label, x["recall1"], x["recall3"], x["recall5"], x["mrr"]))
        print("  gate: recall@3 >= %.3f %s | beats literal on >= %d queries (%d) %s | A > B %s -> %s"
              % (GATE["recall3"], "MET" if gate["recall3_met"] else "FAIL",
                 GATE["beat_literal_by"], beat_c, "MET" if gate["beats_literal_met"] else "FAIL",
                 "MET" if gate["beats_title_met"] else "FAIL",
                 "PASS" if gate["pass"] else "FAIL"))
        print("  not in the top 3: %s" % (", ".join(missed) if missed else "none"))
    return {"read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "n_queries": len(queries), "n_docs": len(docs),
            "corpus": Counter(d["kind"] for d in docs), "arms": arms,
            "gate": gate, "gate_rule": GATE, "missed": missed}


# ---------------------------------------------------------------- self-test
def self_test():
    ok = []

    def chk(name, cond, detail=""):
        ok.append((name, bool(cond), detail))

    tokens = tokenize("The CAPS of these wallets")
    chk("tokenize drops stopwords + stems plurals", tokens == ["cap", "wallet"], str(tokens))
    chk("tokenize keeps digits", "200" in tokenize("bankroll 200 cap"))

    docs = [
        {"kind": "card", "id": "x1", "title": "filled leg booking", "column": "Done",
         "tags": [], "path": "p", "text": "filled leg booking realised pnl"},
        {"kind": "card", "id": "x2", "title": "unrelated note", "column": "Backlog",
         "tags": [], "path": "p", "text": "the filled order was recorded, a leg of it"},
        {"kind": "card", "id": "x3", "title": "other", "column": "Backlog",
         "tags": [], "path": "p", "text": "nothing to do with it"},
    ]
    idx = Index(docs)
    r = [docs[i]["id"] for _, i in idx.rank("filled leg booking")]
    chk("bm25 ranks the on-topic doc first", r and r[0] == "x1", str(r))
    chk("bm25 excludes zero-score docs", "x3" not in r, str(r))
    chk("idf: rarer present term (booking df1) > filled (df2)", idx.idf("booking") > idx.idf("filled"), "")
    lit = [docs[i]["id"] for _, i in idx.literal_rank("filled booking")]
    chk("literal arm requires every token (x2 lacks 'booking')", lit == ["x1"], str(lit))
    chk("snippet picks the matching sentence",
        "realised pnl" in snippet(docs[0], "realised"), snippet(docs[0], "realised"))
    chk("gate constant is pre-registered and in range", 0.0 < GATE["recall3"] <= 1.0, str(GATE))

    # refusal arm: an eval file naming a card that does not exist must not be scored
    global EVAL_FILE
    saved = EVAL_FILE
    tmp = os.path.join(ROOT, "data", ".ops-record-eval-bad.json")
    with open(tmp, "w") as fh:
        json.dump({"queries": [{"q": "x", "expect": "no-such-card-zzz"}]}, fh)
    try:
        EVAL_FILE = tmp
        refused = False
        try:
            load_eval(docs)
        except SystemExit:
            refused = True
        chk("eval refuses an unknown expected card id", refused, "")
    finally:
        EVAL_FILE = saved
        if os.path.exists(tmp):
            os.remove(tmp)

    bad = 0
    for name, passed, detail in ok:
        if not passed:
            bad += 1
        print("%s %s%s" % ("PASS" if passed else "FAIL", name,
                           ("  [" + detail + "]") if detail and not passed else ""))
    print("-- %d/%d self-test arms green" % (len(ok) - bad, len(ok)))
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", help="question to ask the record")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--eval", action="store_true", help="run the pre-registered eval arms")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--include-skills", action="store_true",
                    help="also index ~/.hermes/skills/**/*.md (slower, outside the repo)")
    ap.add_argument("--kind", default="all", choices=("all", "card", "draft", "skill"))
    ap.add_argument("--arm", default="full", choices=("full", "hybrid", "literal"),
                    help="ranking arm; full = the pre-registered doc-level BM25")
    ap.add_argument("--json", action="store_true", help="write " + ARTIFACT)
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    docs = build_docs(include_skills=args.include_skills)
    if args.eval:
        out = run_eval(docs)
        if args.json:
            with open(ARTIFACT, "w") as fh:
                json.dump(out, fh, indent=2, sort_keys=True, default=str)
            print("wrote %s" % ARTIFACT)
        return 0 if out["gate"]["pass"] else 1
    if args.query:
        print(run_query(docs, args.query, args.k, args.arm, args.kind))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
