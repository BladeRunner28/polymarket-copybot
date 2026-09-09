# Tuning recommendation — congressional "referral" sentiment semantics (research-bot rules)

**Date:** 2026-09-08 · **Status:** RECOMMENDATIONS ONLY — no rules/code changed · **Source:** Phase Local-1 sentiment A/B (qwen2.5:7b → qwen3.5:9b backtest, 54 unique items)
**Owner decision needed:** whether a committee referral should be a bearish signal for bill-passage items — and how to settle it empirically.

---

## Key insight

The research-bot rule engine has **no stall semantics for legislative referrals**. In `political-research-bot/src/congress_api.py`, the only action-aware logic is:

- "became public law" / "signed by president" → sentiment ±1.0 (direction from title polarity)
- "passed senate/house" → ±0.9 (direction from title polarity)
- **"committee" in action → confidence bump to 0.70 only — sentiment untouched**

So the sentiment score for every "Referred to committee/subcommittee" item is whatever the *title keyword polarity* said. Evidence from the A/B log (identical action type, opposite scores):

| Bill | Latest action | Rule score | Why |
|---|---|---|---|
| HR3206 Senior Citizens Tax **Elimination** Act | Referred to Subcommittee on Social Security | **-0.7** | "Elimination" keyword |
| S1211 Social Security Caregiver Credit Act | Referred to Committee on Finance | **-0.9** | title/subject polarity |
| HR7084 You Earned It, You Keep It Act | Referred to Subcommittee on Social Security | **+0.5** | positive title |
| HR10447 CCP Fentanyl Sanctions Act | Referred to committee | **+0.5** | positive title |

The new qwen3.5:9b lane (prompt: "referred / read twice / held at desk = not advancing, bearish for passage odds") now scores **all** referrals negative — which is *more internally consistent* than the rule, hence 5 fixed / 7 "regressed" vs a rule that disagrees with itself on the same action.

## Options

**A. Keep rules as-is (title polarity on referrals).** No change; the A/B's rule-agreement metric stays the target and qwen3.5 remains "tied" with 2.5 on bills. Cost: the incoherence stays — same action, ±0.5–0.9 by keywords. Acceptable only if referral events are noise we don't care about (see reality check: they're a large share of congress.gov rows).

**B. Adopt referral-bearishness in the rules (align with the 3.5 rubric).** Add a negative action-branch: `"referr" in action or "read twice" or "held at desk"` → sentiment toward bearish for passage-odds items (small magnitude, e.g. -0.2..-0.4 — a referral is weak evidence, not a kill shot), keep title only for sector context. Risk: changes live signal direction on ~half the congress.gov rows; must be validated before going live.

**C. Settle it empirically first (recommended).** Extend the shadow harness: for each bill row, record (a) rule title-polarity score, (b) referral-adjusted score, and later compare both against ground truth — bill's actual trajectory (did it advance/pass within N months? resolve against congress.gov follow-up actions or a resolved bill-passage market). Whoever predicts better wins; then apply A or B with data. No live change; adds a few columns to the existing AB log.

## Reality checks

- Blast radius is small today: sentiment evidence touches ~0.08% of decisions (148/191k, gdelt_shadow note) — safe to experiment, but also means the *urgency* is low; nothing is burning.
- Referral rows are a large share of the congress.gov stream (~half of the 40 A/B flips), so the incoherence isn't rare — it's the modal case for bills that haven't advanced.
- The rule's title-polarity origin is keyword-based (`analyze_bill_title`); fixing it properly means deciding whether bill sentiment should encode *passage odds* (action-driven) or *subject favorability* (title-driven). These are different signals — the current code mixes them.
- Pre-registered expectation (option C): if referral-bearishness predicts bill non-advancement better than title polarity, the rules branch B for passage-type categories; if title polarity wins or it's a wash, rules stay and the 3.5 prompt's referral clause should be softened to match.

## Recommendation

**Option C now** (shadow columns + 3-month follow-up resolution), **Option B as the conditional follow-up** if the data supports it — and a prompt note to the research-bot: the "referred = bearish" clause should be gated on category (passage-odds items) until C resolves, to keep the A/B clean.

Steering question that would flip it: do you consider congressional bill items **passage-odds signals** (referral matters, title is context) or **subject-favorability signals** (title matters, action is context)? If the latter, the answer is A and the qwen3.5 prompt clause comes out.
