# Autoresearch Audit — uditgoenka/autoresearch

**Date:** 2026-09-04 · **Author:** Hermes · **License:** MIT ✅ (borrowable w/ attribution)

## What it is

A **meta-skill** (v2.2.2) that turns Claude Code / OpenCode / Codex agents into
an autonomous "improvement engine": *goal + mechanical metric + bounded
iteration loop = compounding gains* (Karpathy's autoresearch formula,
productionized). ~2.4 MB of skill prompts, shell scripts, guides, and
Claude-Code hook guardrails. 6,073★, pushed 2026-08-12. Not a quant/data repo —
there is **zero domain content** (no market math, no research IP). All value is
*process*.

Core machinery (read in source):
1. **Classic metric loop** — `Modify → Verify → Keep/Discard → repeat`,
   bounded (25 default), every run logged to `autoresearch/<cmd>-<ts>/`,
   chain handoff via `handoff.json`.
2. **`/autoresearch:regression`** — baseline vs candidate verdict
   `STABLE/UNSTABLE` gate before anything is kept.
3. **`/autoresearch:evals`** — mid-loop checkpoints + final summary over
   `*-results.tsv`; detects trends, plateaus, regressions.
4. **Orchestrator (v2.2)** — plain-language goal → archetype classify →
   **mechanical Success predicate pinned verbatim** (exact shell command +
   expected output, reproducible across resets) → routed subcommand hops →
   stop on CONVERGED / PLATEAU / CEILING / BLOCKED.
5. **Safety invariants (genuinely good)** — no auto ship/deploy/push; every
   derived command passes `screen-cmd`; persisted commands re-screened on
   resume; DB-migration URL allowlist (localhost/_test/_ci only); high-impact
   changes held as `pending_verify` until an independent verify hop runs.

Subcommands: plan, debug, fix, security, ship, scenario, predict, learn,
reason, probe, improve, evals, regression.

## Fit vs this project's research & tuning

The project already operationalizes the same formula **with a human in the
loop by design**: tuning-review-daily (cron, recommendations-only → user
"approved" → implement), RuleChange versioned audit trail, shadow A/B
(sentiment, local-LLM), calibration refits, 7-day phase-gate stability,
walk-forward-style band calibration. That is a deliberate, working
constraint+metric+iteration system — autoresearch's autonomous keep/discard
would *violate* the HITL gate that protects a paper-trading research process
from self-overfitting.

But three of its patterns are directly portable and would measurably sharpen
the existing tuning loop:

| Pattern | Where it fits | Verdict |
|---|---|---|
| **Pinned mechanical Success predicate** (exact command + expected output per goal, reproducible) | Tuning-review recommendations: each one should carry a concrete verify command + expected value (the review prompt already embeds SQL snippets — formalize into a "Verify:" line per recommendation) | ✅ adopt as process |
| **Regression gate** (baseline vs candidate → STABLE/UNSTABLE) | Rule changes: formalize the existing shadow/AB into an explicit baseline-vs-candidate verdict on the 7-day window before a RuleChange is proposed | ⚪ concept (largely present; make explicit) |
| **Plateau detection** (stop when N consecutive candidates fail to move the metric) | Tuning churn control: hard rule that after N consecutive rejected/no-improvement proposals on the same axis, the axis goes quiet for M days | ⚪ concept — adoptable |
| Orchestrator + handoff.json + state ledger | Already covered by roadmap.json cards + drafts/ artifacts + RuleChange rows | ❌ redundant |
| Claude hooks / plugin scaffolding (.cjs guardrails) | Hermes cron agents don't run Claude hooks; equivalent guards are the HITL gate + approval step | ❌ not portable |
| ship/debug/fix/security/scenario subcommands | Engineering-ops value for general code work, not for research/tuning | ❌ out of scope |

## Integration proposal

**Verdict: concept donor for the tuning *process* — adopt 2 small things now,
run the tool itself nowhere.**

1. **Adopt pattern 1 immediately (no code):** update the tuning-review prompt
   so every recommendation carries a `Verify:` line — the exact command +
   expected output that would prove the change worked (the review already runs
   concrete SQL; this pins "done" per recommendation). ~15 min, flag-revertible.
2. **Adopt pattern 3 (plateau) into the same prompt:** after 3 consecutive
   no-improvement proposals on one axis (copy-score thresholds, size bands,
   exposure caps), auto-quiet that axis for 7 days. Kills churn the review is
   prone to when a config is already near-optimal.
3. **Do NOT wire autoresearch's autonomous loop into the trading system** —
   the keep/discard authority stays with the user (existing policy). If the
   user ever wants CLI-agent experimentation on scoped engineering problems,
   the repo runs as-is via the existing claude-code/codex delegation skills in
   a sandbox — but that is engineering tooling, not research enhancement.

## Honest caveats

- Rapid-churn marketing repo (v2.2.x cadence, donation links); treat guides as
  opinionated prompt engineering, not canon.
- Its "regression gate" and "held-out verify" concepts are exactly the
  anti-overfitting machinery the trading system needs — but implementing them
  inside the existing review process (patterns 1–3) delivers ~all of the value
  with none of the porting cost or autonomy risk.
- No domain value: nothing about prediction markets, scoring, calibration, or
  PnL measurement exists in the repo.
