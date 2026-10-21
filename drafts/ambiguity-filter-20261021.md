# Ambiguity filter: priced, and it does not clear zero

**Date:** 2026-10-21 · **Lane:** measurement only · **Verdict:** NOT ESTABLISHED — do not build

Pre-registered before the run: ambiguous resolution criteria make YES overpriced (rules resolve YES
less often than price implies), measured as `y_yes − implied yesPrice` with a market-clustered CI,
tradeable form buy-NO at the ask. Falsified if the ambiguous CI includes zero or the buy-NO ROI does
not clear zero.

---

## 1. The premise had no data behind it locally

`MarketSnapshot` stores 15,889,482 rows and **zero** carry resolution criteria. `rawMarketJson` is
`'{}'` in 100 % of them; the only text is a ~63-char question title ("Jets vs. Stars"). A filter whose
entire input is the rules text had nothing to read.

Acquiring it took three attempts, and two of the obvious routes are dead:

- **Gamma `condition_ids` — returns 0 rows**, even with `closed=true`. These markets are archived out
  of that index.
- **Gamma `slug=<marketId>` — only resolves still-listed markets.** On a random sample of archived
  candidates: **3 of 20 (15 %)**.
- **CLOB `/markets/<conditionId>` — the working route.** Full descriptions, **600 of 600 (100 %)**,
  typically **773–2,569 chars**, and they genuinely carry the contingency clauses the filter exists
  to catch ("If the game is postponed…", "includes any potential second round").

## 2. The judge is the blocker, and it is not close

The classification step is the whole measurement, so it has to be reproducible. The local stack cannot
do it:

- **`qwen3.5:9b` never terminates its reasoning.** Given 1,600 output tokens it spent all 1,600 in the
  `thinking` field (5,505 chars), returned `done_reason: length` with an **empty `response`**, at
  **42.5 s per market**. At that rate a 240-market read is ~80 minutes and produces nothing.
- **`qwen2.5:7b-instruct` answers in 6 tokens but is prompt-suggestible.** Same 20 markets, same
  rubric: **95 % flagged ambiguous**, all "resolution source unnamed". Reword the prompt to warn that
  an empty metadata field is not ambiguity and it returns **0 % flagged at confidence 1.00**. A
  classifier that moves between 95 % and 0 % on wording alone is measuring its own agreeableness.

An abort guard (flag rate outside a sane band ⇒ refuse to report) caught both extremes, which is why
neither produced a number that got quoted.

## 3. So the economic question was answered with a deterministic proxy

`--judge regex` detects **structural** ambiguity markers only — no named provenance, a vague standard
("considered", "widely", "at their discretion"), unaddressed contingencies (postponed/cancelled/second
round). It cannot see semantic vagueness; that is its limitation. It is also free, auditable, and
identical on every run.

**600 markets, 64.7 % flagged ambiguous:**

| group | n | mean residual | 95 % CI | buy-NO net ROI | 95 % CI |
|---|---|---|---|---|---|
| ambiguous | 388 | −0.73 pp | [−4.14, +2.61] | −3.36 % | [−10.50, +3.81] |
| clean | 212 | −1.47 pp | [−5.34, +2.53] | −5.58 % | [−13.67, +2.63] |

**Both intervals span zero.** The pre-registered hypothesis is not supported, and the point estimate
runs the *opposite* way — ambiguous markets were marginally less negative than clean ones — though not
significantly. Buy-NO loses money in both groups, consistent with the baseline being negative net of
fee and spread.

## 4. What this does and does not rule out

- It rules out a **large** ambiguity effect: with ±4 pp intervals, a 10 pp mispricing would have shown.
- It does **not** rule out a small one, and the proxy cannot see semantic vagueness — a strong judge
  might find structure this cannot.
- The honest reading: this is the third market-only text-side hypothesis to fail at the execution
  price, alongside the model's deciles and the EV-ranked arms. The pattern is consistent — **the
  price already contains the outcome information at the precision that matters.**

## 5. If text is ever pursued again

The unblock is a **paid judge with the checklist rubric** already written in
`scripts/ml-ambiguity-read.py` (four auditable yes/no checks, ambiguity derived rather than asserted).
240 markets ≈ 360 K prompt tokens ≈ **$1–2** — cheap, but it needs a key, and it would be buying a
look at an effect this proxy says is small.

Recommendation: **do not build the ambiguity lane.** Spend on wallet behaviour, where the measured
alpha is (+47.75 % with wallet selection vs −50.64 % without on the identical band).

## Reproduce

```
.venv-ml/bin/python scripts/ml-ambiguity-read.py --limit 600 --judge regex --concurrency 8
```

Writes `data/ml/ambiguity-report.json` (includes the pre-registration block and per-check breakdown).
