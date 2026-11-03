# Data-feed scout — 2026-11-02

Generated 2026-11-02T07:01:38 by `scripts/data-feed-scout.py`.

**This is a candidate list, not a recommendation set.** Per the research-agent rule, a
recommendation needs a decision rule; this script cannot write one. Reading order: the human
report interprets these candidates and carries at most four pre-registered proposals.

## Source health — 16/16 ok, 0 failed

| source | status | entries |
| --- | --- | --- |
| reddit:r/datasets new | ok HTTP 200 61225B | 25 |
| reddit:r/datasets top/week | ok STALE cache (88.1h old) after HTTP 429 | 21 |
| reddit:r/datasets search: prediction | ok STALE cache (88.1h old) after HTTP 429 | 25 |
| reddit:r/datasets search: sports | ok HTTP 200 37248B | 16 |
| hf:sports results | ok HTTP 200 2B | 0 |
| hf:football fixtures | ok HTTP 200 1167B | 1 |
| hf:injury | ok HTTP 200 15058B | 12 |
| hf:betting odds | ok HTTP 200 1104B | 1 |
| hf:prediction market | ok HTTP 200 14719B | 12 |
| hf:news headlines | ok HTTP 200 12005B | 12 |
| hf:event dataset | ok HTTP 200 8242B | 12 |
| hf:polling | ok HTTP 200 2723B | 2 |
| hf:weather forecast | ok HTTP 200 11487B | 12 |
| hf:macro economic | ok HTTP 200 12067B | 12 |
| arxiv:arXiv q-fin.TR | ok HTTP 200 2904B | 1 |
| arxiv:arXiv stat.ML | ok HTTP 200 100381B | 47 |

## Candidates — 95 (10 eligible, 26 review, 59 ideas-only)

- **[eligible]** `rel=8` `lic=CC BY 4.0` — [[dataset] 1,309 viral events with 19,732 dated timeline events (CC BY 4.0)](https://www.reddit.com/r/datasets/comments/1xfammx/dataset_1309_viral_events_with_19732_dated/) · 2026-10-25 · reddit:r/datasets top/week
  - matched: event, odds, social
  - Reddit post — a LEAD only. Verify at the primary host before believing anything.
- **[eligible]** `rel=7` `lic=MIT` — [[self-promotion] Fantasy football league outcomes: 26,500 public league IDs + per-league and per-team results from 8 pre-registered studies (code MIT, data CC BY-NC)](https://www.reddit.com/r/datasets/comments/1xjn1vh/selfpromotion_fantasy_football_league_outcomes/) · 2026-10-30 · reddit:r/datasets new
  - matched: football, headline
  - Reddit post — a LEAD only. Verify at the primary host before believing anything.
- **[eligible]** `rel=7` `lic=CC BY 4.0` — [Free sample of UK and Irish bookmaker odds from OddsRelay, with outcomes matched across bookmakers (CSV, JSON)](https://www.reddit.com/r/datasets/comments/1xbu1fz/free_sample_of_uk_and_irish_bookmaker_odds_from/) · 2026-10-21 · reddit:r/datasets search: sports
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
- **[eligible]** `rel=5` `lic=mit` — [openthomas/weather-forecasts](https://huggingface.co/datasets/openthomas/weather-forecasts) · 2026-11-02 · huggingface
  - matched: forecasts, weather
  - licence read from the dataset card (never guessed)
- **[eligible]** `rel=4` `lic=CC BY 4.0` — [Open dataset: 612 NHL skaters ranked under two fantasy scoring systems -- 2025–26](https://www.reddit.com/r/datasets/comments/1wfcpbu/open_dataset_612_nhl_skaters_ranked_under_two/) · 2026-09-13 · reddit:r/datasets search: sports
  - matched: nhl
  - Reddit post — a LEAD only. Verify at the primary host before believing anything.
- **[eligible]** `rel=4` `lic=cc-by-4.0` — [iiiitips/prediction-market-pro-stats](https://huggingface.co/datasets/iiiitips/prediction-market-pro-stats) · 2026-11-02 · huggingface
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
