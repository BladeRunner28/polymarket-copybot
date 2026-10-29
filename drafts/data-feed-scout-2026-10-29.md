# Data-feed scout — 2026-10-29

Generated 2026-10-29T15:55:11 by `scripts/data-feed-scout.py`.

**This is a candidate list, not a recommendation set.** Per the research-agent rule, a
recommendation needs a decision rule; this script cannot write one. Reading order: the human
report interprets these candidates and carries at most four pre-registered proposals.

## Source health — 15/16 ok, 1 failed

| source | status | entries |
| --- | --- | --- |
| reddit:r/datasets new | ok cache (0.1h old) | 25 |
| reddit:r/datasets top/week | ok cache (0.0h old) | 21 |
| reddit:r/datasets search: prediction | ok HTTP 200 78690B | 25 |
| reddit:r/datasets search: sports | **FAILED** HTTP 429 | 0 |
| hf:sports results | ok cache (0.1h old) | 0 |
| hf:football fixtures | ok cache (0.1h old) | 1 |
| hf:injury | ok cache (0.1h old) | 12 |
| hf:betting odds | ok cache (0.1h old) | 1 |
| hf:prediction market | ok cache (0.1h old) | 12 |
| hf:news headlines | ok cache (0.1h old) | 12 |
| hf:event dataset | ok cache (0.1h old) | 12 |
| hf:polling | ok cache (0.1h old) | 2 |
| hf:weather forecast | ok cache (0.1h old) | 12 |
| hf:macro economic | ok cache (0.1h old) | 12 |
| arxiv:arXiv q-fin.TR | ok cache (0.1h old) | 0 |
| arxiv:arXiv stat.ML | ok cache (0.1h old) | 0 |

## Candidates — 62 (8 eligible, 21 review, 33 ideas-only)

- **[eligible]** `rel=8` `lic=CC BY 4.0` — [[dataset] 1,309 viral events with 19,732 dated timeline events (CC BY 4.0)](https://www.reddit.com/r/datasets/comments/1xfammx/dataset_1309_viral_events_with_19732_dated/) · 2026-10-25 · reddit:r/datasets new
  - matched: event, odds, social
  - Reddit post — a LEAD only. Verify at the primary host before believing anything.
- **[eligible]** `rel=7` `lic=CC BY 4.0` — [Free sample of UK and Irish bookmaker odds from OddsRelay, with outcomes matched across bookmakers (CSV, JSON)](https://www.reddit.com/r/datasets/comments/1xbu1fz/free_sample_of_uk_and_irish_bookmaker_odds_from/) · 2026-10-21 · reddit:r/datasets new
  - matched: bookmaker, football
  - Reddit post — a LEAD only. Verify at the primary host before believing anything.
- **[eligible]** `rel=6` `lic=cc-by-4.0` — [SuperAGI/llm-vs-prediction-markets-news](https://huggingface.co/datasets/SuperAGI/llm-vs-prediction-markets-news) · 2026-10-01 · huggingface
  - matched: forecasting, news
  - licence read from the dataset card (never guessed)
- **[eligible]** `rel=6` `lic=cc-by-4.0` — [dnakhla/us-news-headlines-enriched](https://huggingface.co/datasets/dnakhla/us-news-headlines-enriched) · 2026-03-22 · huggingface
  - matched: longitudinal, news, sentiment
  - licence read from the dataset card (never guessed)
- **[eligible]** `rel=5` `lic=cc-by-sa-4.0` — [electricsheepafrica/africa-mauritius-register-polling-stations-constituency-and-local-governmen-55a16058](https://huggingface.co/datasets/electricsheepafrica/africa-mauritius-register-polling-stations-constituency-and-local-governmen-55a16058) · 2026-08-11 · huggingface
  - matched: forecasting, polling
  - licence read from the dataset card (never guessed)
- **[eligible]** `rel=5` `lic=mit` — [openthomas/weather-forecasts](https://huggingface.co/datasets/openthomas/weather-forecasts) · 2026-10-29 · huggingface
  - matched: forecasts, weather
  - licence read from the dataset card (never guessed)
- **[eligible]** `rel=4` `lic=cc-by-4.0` — [iiiitips/prediction-market-pro-stats](https://huggingface.co/datasets/iiiitips/prediction-market-pro-stats) · 2026-10-26 · huggingface
  - matched: sports
  - licence read from the dataset card (never guessed)
- **[eligible]** `rel=4` `lic=cc-by-4.0` — [manja316/crypto-prediction-market-signals](https://huggingface.co/datasets/manja316/crypto-prediction-market-signals) · 2026-04-23 · huggingface
  - matched: crypto, forecasting
  - licence read from the dataset card (never guessed)
- **[review]** `rel=6` `lic=other` — [OliverLee520/WeatherForecast](https://huggingface.co/datasets/OliverLee520/WeatherForecast) · 2026-10-29 · huggingface
  - matched: forecasting, timeseries, weather
  - licence read from the dataset card (never guessed)
- **[review]** `rel=5` `lic=other` — [kpubdata/weather-village-forecast](https://huggingface.co/datasets/kpubdata/weather-village-forecast) · 2026-10-13 · huggingface
  - matched: forecast, weather
  - licence read from the dataset card (never guessed)
- **[review]** `rel=3` `lic=cc-by-4.0` — [SuperAGI/llm-vs-prediction-markets](https://huggingface.co/datasets/SuperAGI/llm-vs-prediction-markets) · 2026-10-01 · huggingface
  - matched: forecasting
  - licence read from the dataset card (never guessed)
- **[review]** `rel=3` `lic=mit` — [rhinot/prediction-market-analysis](https://huggingface.co/datasets/rhinot/prediction-market-analysis) · 2026-09-12 · huggingface
  - matched: forecasting
  - licence read from the dataset card (never guessed)
