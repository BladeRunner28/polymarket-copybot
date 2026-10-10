use axum::{routing::post, Json, Router};
use serde::{Deserialize};
use serde_json::json;
use std::env;
use tokio::net::TcpListener;
use futures_util::{StreamExt, SinkExt};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};

mod adapters;

const POLYMARKET_CTF: &str = "0x4bFB41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E";

#[derive(Deserialize, Debug)]
struct ExecutionIntent {
    bot_id: String,
    venue: String,
    market_id: String,
    /// Polymarket question text — needed to resolve a real Kalshi ticker
    /// (market_id is a Polymarket id, never a Kalshi ticker). TR-16.
    #[serde(default)]
    market_question: String,
    outcome: String,
    side: String,
    price: f64,
    size_usd: f64,
    decision_journal_id: String,
    wallet_address: String,
}

#[derive(Deserialize, Debug)]
struct QuoteRequest {
    market_id: String,
    #[serde(default)]
    market_question: String,
    side: String,
}

/// READ-ONLY Kalshi quote probe (venue-shadow book, 2026-09-13).
///
/// `POST /execute` cannot be used for price discovery: it books a paper trade via
/// the execution-result webhook. This route runs the SAME adapter path as
/// /execute (ticker resolution + top-of-book) and returns the price without any
/// side effect — the single source of truth for the fuzzy matcher stays here.
///
/// Kalshi's public orderbook exposes only the top level per side, so this is a
/// best-price probe, not a depth model.
async fn handle_quote(Json(req): Json<QuoteRequest>) -> Json<serde_json::Value> {
    let client = reqwest::Client::new();
    let market_id = if req.market_id.is_empty() { "0x-venue-shadow".to_string() } else { req.market_id.clone() };
    match adapters::fetch_kalshi_quote(&client, &market_id, &req.market_question, &req.side).await {
        Ok(q) => Json(json!({
            "ok": true,
            "venue": "Kalshi",
            "price": q.price,
            // Match provenance: the caller MUST audit this (token_score clears its
            // bar on generic tokens — see adapters.rs resolve_kalshi_match).
            "ticker": q.ticker,
            "matched_title": q.title,
            "match_score": q.score,
            "source": "kalshi-top-of-book",
        })),
        Err(e) => Json(json!({
            "ok": false,
            "venue": "Kalshi",
            "error": e,
        })),
    }
}

/// BANKROLL_200's maker-fill credit: the inside-spread improvement the sidecar
/// books on every C-200 BUY (`entry = intent − credit`).
///
/// Measured for the first time on 2026-10-10 (freeze thaw): across 354 dispatched
/// intents / 353 book-analysable legs the level was reachable — a print, or a best
/// ask, at or below it within an hour of the dispatch — on only ~18% of legs, not
/// the archive's PRINT-anchored 74.3% @5m / 81.1% @1h the assumption had been
/// riding on. The rate is BAND-DEPENDENT, and the credit is biggest exactly where
/// the rate is smallest (2¢ is 34.9% of a $0.05 entry, 2.9% of a $0.70 one), so
/// the band weights below, not one average, are what the lane should book.
///   band        own 5s L2 (1h)   public tape (1h)   weight booked
///   0.00–0.10        0.0%             5.6%            0.028
///   0.10–0.20        6.7%            10.0%            0.084
///   0.20–0.40       27.2%            18.5%            0.229
///   0.40–0.60       17.6%            19.9%            0.188
///   0.60–0.80       19.6%            17.4%            0.185
///   ≥0.80           50.0%           100.0%            0.185  (n=2 — unmeasured, extrapolated)
/// Detail: drafts/thaw-reads-2026-10-10.md §7/§9, cards c200-maker-fill-assumption
/// and c200-intent-printthrough-check. The same table lives in
/// src/lib/copy-cost.ts (MEASURED_FILL_WEIGHTS) so the EOD report can print the
/// as-booked and measured-rate counterfactuals side by side.
///
/// MODE (`MAKER_CREDIT_MODE`, read per request, so reverting is an .env edit plus
/// a `launchctl kickstart` — never a rebuild):
///   "measured" (default) — 2¢ × the measured share for the leg's price band
///   "modelled"           — the pre-2026-10-10 behaviour: the full 2¢ on every leg
fn maker_credit(price: f64, mode: &str) -> f64 {
    const MODELLED_CREDIT: f64 = 0.02;
    if mode == "modelled" {
        return MODELLED_CREDIT;
    }
    const BANDS: [(f64, f64, f64); 6] = [
        (0.00, 0.10, 0.028),
        (0.10, 0.20, 0.084),
        (0.20, 0.40, 0.229),
        (0.40, 0.60, 0.188),
        (0.60, 0.80, 0.185),
        (0.80, 999.0, 0.185),
    ];
    for (lo, hi, share) in BANDS {
        if price >= lo && price < hi {
            return MODELLED_CREDIT * share;
        }
    }
    MODELLED_CREDIT * 0.185
}

async fn handle_execution(Json(intent): Json<ExecutionIntent>) -> Json<serde_json::Value> {
    println!("🚀 [Shadow FAK] Received Execution Intent for {}: ${:.2} on {} at {:.1}¢", 
        intent.bot_id, intent.size_usd, intent.outcome, intent.price * 100.0);
    
    let client = reqwest::Client::new();
    let token = env::var("INTERNAL_API_SECRET").unwrap_or_default();

    // Feature: Phase 5 Cross-Market Routing (Dry-Run)
    // If the venue is Kalshi or PredictIt, query the specific adapter's L2 depth first.
    // TR-16: adapters NEVER fabricate a price now — on any failure we book at
    // the Polymarket reference price and say so in the execution note.
    let mut executed_price = intent.price;
    let mut depth_warning: Option<String> = None;

    if intent.venue == "Kalshi" {
        match adapters::fetch_kalshi_depth(&client, &intent.market_id, &intent.market_question, &intent.side).await {
            Ok(kalshi_price) => {
                println!("⚖️ [Depth Guard] Kalshi L2 depth confirmed at {:.1}¢", kalshi_price * 100.0);
                executed_price = kalshi_price;
            }
            Err(e) => {
                println!("⚠️ [Depth Guard] Kalshi depth unavailable ({e}) — booking at Polymarket reference {:.1}¢", intent.price * 100.0);
                depth_warning = Some(format!("Kalshi depth unavailable ({e}) — booked at PM reference price"));
            }
        }
    } else if intent.venue == "PredictIt" {
        match adapters::fetch_predictit_depth(&client, &intent.market_id).await {
            Ok(pi_price) => {
                println!("⚖️ [Depth Guard] PredictIt L2 depth confirmed at {:.1}¢", pi_price * 100.0);
                executed_price = pi_price;
            }
            Err(e) => {
                println!("⚠️ [Depth Guard] PredictIt depth unavailable ({e}) — booking at Polymarket reference {:.1}¢", intent.price * 100.0);
                depth_warning = Some(format!("PredictIt depth unavailable ({e}) — booked at PM reference price"));
            }
        }
    }
    
    // Feature: Phase 6 ImMike's Maker Copying
    // If this is the compounding bot, place the order slightly above the best bid instead of crossing the spread.
    let mut execution_note = "FAK Shadow Execution via Rust".to_string();
    
    if intent.bot_id == "BANKROLL_200" {
        // Assuming the passed `intent.price` is the Ask (since we're a Taker by default),
        // simulate placing a Maker limit order near the Bid to capture the spread.
        // The credit is the MEASURED fill share for the leg's band (2026-10-10 read),
        // not a flat 2¢ — see maker_credit() above. MAKER_CREDIT_MODE=modelled
        // restores the old behaviour without a rebuild.
        let credit_mode = env::var("MAKER_CREDIT_MODE").unwrap_or_else(|_| "measured".to_string());
        let maker_improvement = maker_credit(executed_price, &credit_mode);

        if intent.side.to_uppercase() == "BUY" {
            executed_price = f64::max(0.01, executed_price - maker_improvement);
            println!("📈 [Maker Credit] mode={} BUY booked {:.2}¢ inside the spread at {:.2}¢ (modelled 2.00¢)", credit_mode, maker_improvement * 100.0, executed_price * 100.0);
        } else {
            executed_price = f64::min(0.99, executed_price + maker_improvement);
            println!("📉 [Maker Credit] mode={} SELL booked {:.2}¢ inside the spread at {:.2}¢ (modelled 2.00¢)", credit_mode, maker_improvement * 100.0, executed_price * 100.0);
        }

        let note = match credit_mode.as_str() {
            "modelled" => "MAKER Shadow Execution (Spread Captured)".to_string(),
            _ => format!("MAKER Shadow Execution (measured credit {:.2}¢)", maker_improvement * 100.0),
        };
        execution_note = match depth_warning {
            Some(w) => format!("{note} — {w}"),
            None => note,
        };
    }

    let payload = json!({
        "botId": intent.bot_id,
        "decisionJournalId": intent.decision_journal_id,
        "walletAddress": intent.wallet_address,
        "marketId": intent.market_id,
        "outcome": intent.outcome,
        "side": intent.side,
        "entryPrice": executed_price,
        "simulatedPositionSize": intent.size_usd,
        "venue": intent.venue,
        "status": "open",
        "executionNote": execution_note
    });

    tokio::spawn(async move {
        let _ = client.post("http://127.0.0.1:3013/api/webhooks/execution-result")
            .bearer_auth(&token)
            .json(&payload)
            .send()
            .await;
    });

    Json(json!({"status": "received", "message": "Executing FAK via Depth Guard..."}))
}

async fn start_whale_subscriber() {
    let ws_url = env::var("POLYGON_WS_URL").unwrap_or_else(|_| "wss://polygon-bor-rpc.publicnode.com".to_string());
    if let Ok((mut ws_stream, _)) = connect_async(&ws_url).await {
        let subscribe_msg = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["logs", { "address": POLYMARKET_CTF }]
        });
        let _ = ws_stream.send(Message::Text(subscribe_msg.to_string())).await;
        
        let client = reqwest::Client::new();
        let token = env::var("INTERNAL_API_SECRET").unwrap_or_default();
        while let Some(msg) = ws_stream.next().await {
            if let Ok(Message::Text(text)) = msg {
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text) {
                    if parsed["method"] == "eth_subscription" {
                        let log = &parsed["params"]["result"];
                        let tx_hash = log["transactionHash"].as_str().unwrap_or("unknown");
                        println!("🐋 Zero-Latency Whale Trade Detected! Tx: {}", tx_hash);
                        let client_clone = client.clone();
                        let payload = log.clone();
                        let token_for_post = token.clone();
                        tokio::spawn(async move {
                            let _ = client_clone.post("http://127.0.0.1:3013/api/webhooks/whale-signal")
                                .bearer_auth(token_for_post)
                                .json(&payload).send().await;
                        });
                    }
                }
            }
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("🐉 PolyHydra Rust Core (Phase 4 Shadow Production)");
    
    // Spawn WebSocket Whale Subscriber in background
    tokio::spawn(start_whale_subscriber());
    
    // Start Axum Execution Server. Port is overridable so a rebuilt binary can be
    // smoke-tested on a spare port while the live daemon keeps serving SIDECAR_PORT
    // (default 3014) — see scripts/kalshi-venue-shadow.ts.
    let app = Router::new()
        .route("/execute", post(handle_execution))
        .route("/quote", post(handle_quote));
    let port = env::var("SIDECAR_PORT").unwrap_or_else(|_| "3014".to_string());
    let addr = format!("127.0.0.1:{port}");
    let listener = TcpListener::bind(&addr).await?;
    println!("🔥 Rust Execution API running on http://{addr}");
    axum::serve(listener, app).await?;
    
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The measured per-band credit (2026-10-10 read) — the whole point of the
    /// change is that the cheap bands, where 2¢ is worth the most, now book the
    /// least. A regression to a flat 2¢ fails here.
    #[test]
    fn measured_mode_books_the_band_share() {
        assert!((maker_credit(0.05, "measured") - 0.02 * 0.028).abs() < 1e-12);
        assert!((maker_credit(0.15, "measured") - 0.02 * 0.084).abs() < 1e-12);
        assert!((maker_credit(0.30, "measured") - 0.02 * 0.229).abs() < 1e-12);
        assert!((maker_credit(0.50, "measured") - 0.02 * 0.188).abs() < 1e-12);
        assert!((maker_credit(0.70, "measured") - 0.02 * 0.185).abs() < 1e-12);
        assert!((maker_credit(0.95, "measured") - 0.02 * 0.185).abs() < 1e-12);
        // band edges land on their own band, never on the neighbour's
        assert!((maker_credit(0.10, "measured") - 0.02 * 0.084).abs() < 1e-12);
        assert!((maker_credit(0.20, "measured") - 0.02 * 0.229).abs() < 1e-12);
    }

    /// The cheap bands are where the credit was worth 30-40% of the entry: they
    /// must never book MORE than the modelled 2¢, and the whole table must stay
    /// inside [0, 0.02].
    #[test]
    fn credit_never_exceeds_the_modelled_two_cents() {
        for cents in 1..100 {
            let p = cents as f64 / 100.0;
            let c = maker_credit(p, "measured");
            assert!(c >= 0.0 && c <= 0.02, "band {p} booked {c}");
        }
    }

    /// Reverting is an env edit, not a rebuild: "modelled" restores the exact
    /// pre-2026-10-10 behaviour on every price.
    #[test]
    fn modelled_mode_is_the_old_behaviour() {
        for cents in 1..100 {
            let p = cents as f64 / 100.0;
            assert_eq!(maker_credit(p, "modelled"), 0.02);
        }
        assert_eq!(maker_credit(0.5, ""), 0.02 * 0.188); // unknown mode falls back to measured
    }

    /// The booked entry must move by exactly the credit, with the floor intact.
    #[test]
    fn buy_entry_is_intent_minus_credit_and_never_below_one_cent() {
        let intent = 0.535_f64;
        let credit = maker_credit(intent, "measured");
        let booked = f64::max(0.01, intent - credit);
        assert!((intent - booked - credit).abs() < 1e-12);
        // intent − credit below the 1¢ floor clamps to 1¢ (cheap tokens)
        assert_eq!(f64::max(0.01, 0.0102 - maker_credit(0.0102, "measured")), 0.01);
    }
}
