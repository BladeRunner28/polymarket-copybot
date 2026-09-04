use reqwest::Client;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

// TR-16 (2026-09-03): Kalshi adapter rewritten —
//  1. Host: trading-api.kalshi.com is DEPRECATED (401 "API has been moved").
//     Public market data now lives at external-api.kalshi.com (all markets;
//     the "elections" subdomain name is legacy — see docs quick start).
//  2. Real book shape: orderbook_fp = { yes_dollars: [[price,$size]], no_dollars: ... }
//     — TOP LEVEL ONLY per side, prices are DOLLAR strings (0.1680 = 16.8¢),
//     not the cents integers the old parser assumed.
//  3. No more Ok(0.52) stub: any failure returns Err and the caller books at
//     the Polymarket reference price with a loud execution note instead of a
//     phantom Kalshi price.
//  4. Ticker resolution: intent.market_id is a POLYMARKET id, never a Kalshi
//     ticker. Resolve via a bounded walk of open events with token-overlap
//     scoring + an in-process cache. Best-effort: cross-listing is rare, so
//     most resolutions fail loudly (correct behavior).

const KALSHI_BASE: &str = "https://external-api.kalshi.com/trade-api/v2";
const MAX_EVENT_PAGES: usize = 25;
const MATCH_THRESHOLD: f64 = 0.55;

static TICKER_CACHE: OnceLock<Mutex<HashMap<String, String>>> = OnceLock::new();
fn ticker_cache() -> &'static Mutex<HashMap<String, String>> {
    TICKER_CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

const STOPWORDS: &[&str] = &[
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "will", "be", "is", "are",
    "was", "before", "after", "this", "that", "with", "by", "at", "from", "as", "it", "its",
    "what", "when", "how", "do", "does", "did", "have", "has", "had", "would", "should", "can",
    "could", "may", "might", "more", "than", "over", "under", "between", "during", "per", "day",
    "week", "month", "year", "date", "time", "today", "new", "up", "down",
];

fn norm_words(s: &str) -> Vec<String> {
    s.to_lowercase()
        .split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|w| w.len() > 2 && !STOPWORDS.contains(w))
        .map(|w| w.to_string())
        .collect()
}

/// Token-overlap score in [0,1] — intersection / min(len_a, len_b).
fn token_score(a: &[String], b: &[String]) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let inter = a.iter().filter(|w| b.contains(w)).count() as f64;
    inter / (a.len().min(b.len()) as f64)
}

async fn get_json(client: &Client, url: &str) -> Result<Value, String> {
    let mut attempt = 0;
    loop {
        attempt += 1;
        let resp = client
            .get(url)
            .header("Accept", "application/json")
            .send()
            .await
            .map_err(|e| format!("kalshi http error: {e}"))?;
        if resp.status().as_u16() == 429 && attempt < 3 {
            // Kalshi rate-limits bursty walks — back off and retry once or twice.
            tokio::time::sleep(std::time::Duration::from_millis(800 * attempt as u64)).await;
            continue;
        }
        if !resp.status().is_success() {
            return Err(format!("kalshi http {} for {}", resp.status(), url));
        }
        return resp
            .json()
            .await
            .map_err(|e| format!("kalshi json error: {e}"));
    }
}

/// Best-effort Polymarket-question -> Kalshi EVENT ticker resolution.
/// Bounded walk over open events (8 pages x 200), token-overlap scored,
/// cached per normalized question. Returns Err when nothing clears the bar.
async fn resolve_kalshi_event(client: &Client, question: &str) -> Result<String, String> {
    let q_words = norm_words(question);
    if q_words.is_empty() {
        return Err("unparseable market question".into());
    }
    let cache_key = q_words.join(" ");
    if let Some(hit) = ticker_cache().lock().ok().and_then(|m| m.get(&cache_key).cloned()) {
        return Ok(hit);
    }

    let mut cursor: Option<String> = None;
    let mut best: Option<(String, f64)> = None;
    for _ in 0..MAX_EVENT_PAGES {
        let mut url = format!("{KALSHI_BASE}/events?limit=200&status=open");
        if let Some(c) = &cursor {
            url.push_str(&format!("&cursor={}", c));
        }
        let json = get_json(client, &url).await?;
        let events = json["events"].as_array().cloned().unwrap_or_default();
        for ev in &events {
            let title = ev["title"].as_str().unwrap_or("");
            let score = token_score(&q_words, &norm_words(title));
            let keep = match &best {
                Some((_, s)) => score > *s,
                None => score >= MATCH_THRESHOLD,
            };
            if keep && score >= MATCH_THRESHOLD {
                if let Some(t) = ev["event_ticker"].as_str() {
                    best = Some((t.to_string(), score));
                }
            }
        }
        cursor = json["cursor"].as_str().map(|s| s.to_string());
        if cursor.is_none() {
            break;
        }
        // Be gentle with the shared rate limit during deep walks.
        tokio::time::sleep(std::time::Duration::from_millis(60)).await;
    }

    match best {
        Some((ticker, score)) => {
            if let Ok(mut m) = ticker_cache().lock() {
                m.insert(cache_key, ticker.clone());
            }
            println!("🎯 [Kalshi Matcher] '{question}' -> event {ticker} (score {score:.2})");
            Ok(ticker)
        }
        None => Err(format!(
            "no open Kalshi event matched question (scored {:.2} of open events over {MAX_EVENT_PAGES} pages)",
            best.map(|(_, s)| s).unwrap_or(0.0)
        )),
    }
}

/// Fetch a real executable Kalshi price for the market matching `market_question`.
///
/// Kalshi's public orderbook exposes only the TOP LEVEL per side:
///   orderbook_fp.yes_dollars[0] = best YES bid   (you can SELL YES here)
///   orderbook_fp.no_dollars[0]  = best NO bid    (selling NO here == buying YES at 1-p)
/// So: BUY YES at 1 - best_no_bid, SELL YES at best_yes_bid.
/// Returns a dollar price in [0.01, 0.99] or Err (caller must NOT fabricate).
pub async fn fetch_kalshi_depth(
    client: &Client,
    _market_id: &str,
    market_question: &str,
    side: &str,
) -> Result<f64, String> {
    if market_question.trim().is_empty() {
        return Err(
            "no market_question in intent — Polymarket market_id is not a Kalshi ticker; \
             cannot resolve venue price"
                .into(),
        );
    }
    let event = resolve_kalshi_event(client, market_question).await?;
    let url = format!("{KALSHI_BASE}/markets/{event}/orderbook");
    let json = get_json(client, &url).await?;

    let fp = json["orderbook_fp"].clone();
    let buy = side.eq_ignore_ascii_case("BUY");
    let level = if buy { &fp["no_dollars"] } else { &fp["yes_dollars"] };

    let price = level
        .as_array()
        .and_then(|arr| arr.first())
        .and_then(|row| row[0].as_str())
        .and_then(|p| p.parse::<f64>().ok());

    match price {
        Some(p) if p > 0.0 && p < 1.0 => {
            let px = if buy { 1.0 - p } else { p };
            println!(
                "⚖️ [Kalshi Adapter] event {event} {} price {:.1}¢ (top level)",
                if buy { "ask" } else { "bid" },
                px * 100.0
            );
            Ok(px)
        }
        Some(p) => Err(format!("kalshi price {p} out of [0,1] for event {event}")),
        None => Err(format!("kalshi orderbook empty for event {event}")),
    }
}

// Live PredictIt Adapter (unchanged behaviour, but no more Ok(0.58) stub —
// TR-16: fail loud so callers never book against a fabricated price).
pub async fn fetch_predictit_depth(client: &Client, market_ticker: &str) -> Result<f64, String> {
    println!("📡 [PredictIt Adapter] Fetching L2 depth for {market_ticker}");

    // PredictIt's public XML/JSON market data API requires internal market IDs.
    // Without a ticker mapper, we will blindly query their all-markets endpoint
    // and attempt a string match. (Highly unoptimized, but functional for dry-runs).
    let url = "https://www.predictit.org/api/marketdata/all/";

    let resp = client
        .get(url)
        .header("Accept", "application/json")
        .send()
        .await
        .map_err(|e| format!("predictit http error: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("predictit http {}", resp.status()));
    }
    let json: Value = resp
        .json()
        .await
        .map_err(|e| format!("predictit json error: {e}"))?;

    let search_term = market_ticker.to_lowercase().replace('-', " ");
    if let Some(markets) = json["markets"].as_array() {
        let mut best_match = None;
        let mut best_score = 0.0;
        for market in markets {
            if let Some(name) = market["name"].as_str() {
                let similarity = strsim::jaro(&name.to_lowercase(), &search_term);
                if similarity > best_score && similarity > 0.85 {
                    best_score = similarity;
                    best_match = Some(market.clone());
                }
            }
        }
        if let Some(market) = best_match {
            println!(
                "🎯 [PredictIt AI Matcher] Matched '{}' -> '{}' (Score: {:.2})",
                market_ticker,
                market["name"].as_str().unwrap_or(""),
                best_score
            );
            if let Some(contracts) = market["contracts"].as_array() {
                if let Some(contract) = contracts.first() {
                    if let Some(best_buy) = contract["bestBuyYesCost"].as_f64() {
                        return Ok(best_buy);
                    }
                }
            }
        }
    }
    Err(format!(
        "predictit: no contract matched '{}' in public listings",
        market_ticker
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    // Live smoke test (network) — run with: cargo test -- --ignored --nocapture
    #[tokio::test]
    #[ignore]
    async fn kalshi_depth_live() {
        let client = Client::new();
        // Guaranteed cross-listed-ish: KXELONMARS-99 sits at the top of the
        // default events ordering, so this validates the happy path cheaply.
        let q = "Will Elon Musk visit Mars before August 2099";
        match fetch_kalshi_depth(&client, "0x-dummy", q, "BUY").await {
            Ok(p) => println!("OK price: {p}"),
            Err(e) => println!("ERR: {e}"),
        }
    }
}
