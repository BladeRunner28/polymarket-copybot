# Data-feed scout — 2026-11-23

Generated 2026-11-23T07:00:44 by `scripts/data-feed-scout.py`.

**This is a candidate list, not a recommendation set.** Per the research-agent rule, a
recommendation needs a decision rule; this script cannot write one. Reading order: the human
report interprets these candidates and carries at most four pre-registered proposals.

## Source health — 16/16 ok, 0 failed

| source | status | entries |
| --- | --- | --- |
| reddit:r/datasets new | ok STALE cache (168.0h old) after HTTP 404 | 25 |
| reddit:r/datasets top/week | ok STALE cache (592.1h old) after HTTP 429 | 21 |
| reddit:r/datasets search: prediction | ok STALE cache (336.0h old) after HTTP 429 | 25 |
| reddit:r/datasets search: sports | ok STALE cache (504.0h old) after HTTP 429 | 16 |
| hf:sports results | ok HTTP 200 2B | 0 |
| hf:football fixtures | ok HTTP 200 1167B | 1 |
| hf:injury | ok HTTP 200 14254B | 12 |
| hf:betting odds | ok HTTP 200 2318B | 2 |
| hf:prediction market | ok HTTP 200 14815B | 12 |
| hf:news headlines | ok HTTP 200 12100B | 12 |
| hf:event dataset | ok HTTP 200 7045B | 12 |
| hf:polling | ok HTTP 200 4012B | 3 |
| hf:weather forecast | ok HTTP 200 10925B | 12 |
| hf:macro economic | ok HTTP 200 12862B | 12 |
| arxiv:arXiv q-fin.TR | ok HTTP 200 904B | 0 |
| arxiv:arXiv stat.ML | ok HTTP 200 108064B | 50 |

## Candidates — 92 (8 eligible, 30 review, 54 ideas-only)

- **[eligible]** `rel=8` `lic=CC BY 4.0` — [[dataset] 1,309 viral events with 19,732 dated timeline events (CC BY 4.0)](https://www.reddit.com/r/datasets/comments/1xfammx/dataset_1309_viral_events_with_19732_dated/) · 2026-10-25 · reddit:r/datasets top/week
  - matched: event, odds, social
  - Reddit post — a LEAD only. Verify at the primary host before believing anything.
- **[eligible]** `rel=7` `lic=CC BY 4.0` — [[OC] Which sportsbooks 45 odds APIs carry: 135 books, Nov 2026 (CSV)](https://www.reddit.com/r/datasets/comments/1xm0d4a/oc_which_sportsbooks_45_odds_apis_carry_135_books/) · 2026-11-02 · reddit:r/datasets search: prediction
  - matched: odds, sports
  - Reddit post — a LEAD only. Verify at the primary host before believing anything.
- **[eligible]** `rel=7` `lic=CC BY 4.0` — [Free sample of UK and Irish bookmaker odds from OddsRelay, with outcomes matched across bookmakers (CSV, JSON)](https://www.reddit.com/r/datasets/comments/1xbu1fz/free_sample_of_uk_and_irish_bookmaker_odds_from/) · 2026-10-21 · reddit:r/datasets search: sports
  - matched: bookmaker, football
  - Reddit post — a LEAD only. Verify at the primary host before believing anything.
- **[eligible]** `rel=6` `lic=cc-by-4.0` — [dnakhla/us-news-headlines-enriched](https://huggingface.co/datasets/dnakhla/us-news-headlines-enriched) · 2026-03-22 · huggingface
  - matched: longitudinal, news, sentiment
  - licence read from the dataset card (never guessed)
- **[eligible]** `rel=5` `lic=cc-by-sa-4.0` — [electricsheepafrica/africa-mauritius-register-polling-stations-constituency-and-local-governmen-55a16058](https://huggingface.co/datasets/electricsheepafrica/africa-mauritius-register-polling-stations-constituency-and-local-governmen-55a16058) · 2026-08-11 · huggingface
  - matched: forecasting, polling
  - licence read from the dataset card (never guessed)
- **[eligible]** `rel=5` `lic=mit` — [openthomas/weather-forecasts](https://huggingface.co/datasets/openthomas/weather-forecasts) · 2026-11-23 · huggingface
  - matched: forecasts, weather
  - licence read from the dataset card (never guessed)
- **[eligible]** `rel=4` `lic=CC BY 4.0` — [Open dataset: 612 NHL skaters ranked under two fantasy scoring systems -- 2025–26](https://www.reddit.com/r/datasets/comments/1wfcpbu/open_dataset_612_nhl_skaters_ranked_under_two/) · 2026-09-13 · reddit:r/datasets search: sports
  - matched: nhl
  - Reddit post — a LEAD only. Verify at the primary host before believing anything.
- **[eligible]** `rel=4` `lic=cc-by-4.0` — [iiiitips/prediction-market-pro-stats](https://huggingface.co/datasets/iiiitips/prediction-market-pro-stats) · 2026-11-23 · huggingface
  - matched: sports
  - licence read from the dataset card (never guessed)
- **[review]** `rel=6` `lic=other` — [paperswithbacktest/PredictionMarkets-Daily-Trades](https://huggingface.co/datasets/paperswithbacktest/PredictionMarkets-Daily-Trades) · 2026-11-23 · huggingface
  - matched: event, forecasting
  - licence read from the dataset card (never guessed)
- **[review]** `rel=6` `lic=other` — [paperswithbacktest/PredictionMarkets-Daily-Markets](https://huggingface.co/datasets/paperswithbacktest/PredictionMarkets-Daily-Markets) · 2026-11-23 · huggingface
  - matched: event, forecasting
  - licence read from the dataset card (never guessed)
- **[review]** `rel=6` `lic=other` — [paperswithbacktest/PredictionMarkets-Hourly-Price](https://huggingface.co/datasets/paperswithbacktest/PredictionMarkets-Hourly-Price) · 2026-11-23 · huggingface
  - matched: event, forecasting
  - licence read from the dataset card (never guessed)
- **[review]** `rel=6` `lic=other` — [paperswithbacktest/PredictionMarkets-Daily-Price](https://huggingface.co/datasets/paperswithbacktest/PredictionMarkets-Daily-Price) · 2026-11-23 · huggingface
  - matched: event, forecasting
  - licence read from the dataset card (never guessed)
