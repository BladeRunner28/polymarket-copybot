# REC 2 and REC 3 — what only you can do

**Date:** 2026-10-29 · All four recommendations approved. This is the split between what is now mine and
what is genuinely yours. REC 4 needs nothing (dispatching). REC 1 is mine (offline measurement first).

---

## REC 2 — bookmaker consensus odds

### What I already did (free tier, no key, no action from you)

- **Read the sample properly.** 186 events, 15,820 matched prices, **66 bookmakers**, snapshot
  `2026-10-11T20:16:34Z`, CC BY 4.0.
- **Built the recorder** — `scripts/bookmaker-odds-record.py`. Three modes: `sample` (CSV, keyless),
  `board-json` (the API's *own* JSON shape, validated now against the sample's `standard_board.json`),
  and `api` (staged, refuses rather than inventing an endpoint).
- **Solved the vig.** This is the part that decides whether the whole idea works. A 1.65 decimal price
  implies 60.6%, but that is 1.65 *including* margin — median soccer margin 8.7%, american football 6.2%,
  baseball 7.0%, ice hockey 7.8%, basketball 8.1%. Comparing a raw implied probability to a Polymarket
  price would make Polymarket look better on essentially every market, and that "finding" would be
  nothing but the vig. Every price is now **de-vigged** per bookmaker (normalized so their own outcomes
  sum to 1), then the **median across books** is taken — median, not mean, so one stale quote can't move it.
- **Seeded the corpus:** 402 rows across 261 markets and 110 events. Consensus sums land within
  **0.0047** of 1.0, which is the check that the de-vig is right.
- **Measured the coverage question**, which is what decides whether this is worth paying for:

  | | |
  |---|---|
  | our distinct traded markets | **4,091** |
  | of those, sport (keyword-classified) | **890 = 21.8 %** |
  | sport markets in families this feed covers | **890 / 890 = 100 %** |

  Baseball 6.6 %, esports 6.0 %, soccer 2.7 %, basketball 2.6 %, NFL 1.8 %, NHL 1.4 %, tennis 0.6 %.

### Correction to what I told you earlier

I warned that the coverage was a mismatch — "UK/Irish football, tennis, horse racing, darts versus our
mostly US sports". **That was wrong**, and I got it from the vendor's Reddit post rather than the data.
The actual sample carries **american football, baseball, basketball, ice hockey, cricket, esports**,
table tennis, volleyball, golf and more. The feed covers **every sport family we trade**. That makes
REC 2 materially stronger than I priced it.

Two things I also confirmed from their own files, which cost them nothing to say and would have cost me
dear to discover later: **one fixture appears as two event records** (raw board `SEA Seahawks` /
matched board `Seattle`), and **only 110 of 186 events carry matched prices** — the other 76 are
raw-board only and are correctly excluded.

### What you have to do

**1. Create the account (only you can — it needs your identity).**
`https://oddsrelay.io` → **Free plan**: 50,000 tokens for 14 days, no card.

**2. Put the token in `.env` yourself. Never in chat.**

```
echo 'ODDSRELAY_TOKEN=<paste here>' >> ~/.hermes/.env && chmod 600 ~/.hermes/.env
```

The recorder reads it from `~/.hermes/.env` and never prints the value.

**3. Give me the endpoint — the URL, not the token.**
Set these too, or just paste me the API docs section and I'll set them:

```
echo 'ODDSRELAY_BASE=https://<host from docs>' >> ~/.hermes/.env
echo 'ODDSRELAY_PATH=/<path from docs>'  >> ~/.hermes/.env
```

`--mode api` deliberately **refuses** without these. If I guessed a URL, a wrong endpoint returns an
empty board that parses identically to "no events listed" — the exact failure this repo prints HTTP
status and byte size everywhere to avoid.

**4. Read the ToS on three specific points** (the CC BY 4.0 licence covers the *sample*, not the feed):
- may quotes be **stored** long-term;
- may **derived** data (a consensus probability) be used commercially;
- any **rate limit** or attribution wording required.

**5. The one thing that changes the timeline.** The free plan is **14 days**, but REC 2's decision rule
needs **60 days** of paired recording. A trial cannot produce the corpus. So the real choice is:

- **(a) pay after the trial** — cleanest, cost unknown, get the quote at signup; or
- **(b) record only a narrow subset during the trial** — e.g. NFL + NBA + MLB + NHL h2h only, which is
  ~11 % of our book by sport share, and see whether consensus moves the needle before paying.

My recommendation: **(b) then (a)**. Spend the trial proving the pairing works on the highest-volume
families, then pay only if the pairing rate is real. Say which you want and I'll scope it.

**6. Nothing else.** Once the token and endpoint are in, the scheduled job self-activates (it stays
silent while there's no token, so it won't nag you) and the corpus starts growing.

---

## REC 3 — news text stored as-of decision time

### What you have to do

**Nothing.** Your approval covered the carve-out, so the work is mine and none of it is blocking.

Two notes so the decision is on the record rather than buried:

- **The NC split stays out.** `window_a/` (1,141 rows) is **CC BY-NC-SA 4.0 — NonCommercial**. A lane
  that trades real money is commercial use, so those rows are excluded from anything that can feed the
  live lane. They remain usable as *offline research/eval* input only if you ever want that; say so and
  I'll wire it that way, otherwise they're simply not used.
- **Attribution is mechanical:** CC BY 4.0 requires credit. I'll add a `NOTICE` entry naming both
  datasets and their licences alongside any code that consumes them, so the obligation is satisfied in
  the repo rather than remembered.

### What I'll do, in order

1. Train a headline→event-type classifier on the **CC BY 4.0 split only**.
2. Store news text checksum-keyed with its capture timestamp — the structure that makes news features
   leak-free by construction instead of by discipline.
3. Gate it exactly as pre-registered: add features only if era-split AUC beats price-only **0.6704** by
   **≥0.01** out-of-sample, and only if the improvement survives retraining on a later era.
4. Report as a **proposal**, never an apply.

If it fails the gate, it fails, and I'll publish the null rather than tune the window.

---

## Status summary

| item | owner | state |
|---|---|---|
| REC 1 Open-Meteo weather substrate | me | offline measurement first; feature is Lane A |
| REC 2 recorder + de-vig + coverage | done | 402 rows seeded, 100 % sport-family coverage |
| REC 2 account, token, endpoint, ToS, tier | **you** | blocking |
| REC 3 CC BY 4.0 classifier + gate | me | no action needed from you |
| REC 4 recorder audit | dispatched | Lane B, no approval needed |
