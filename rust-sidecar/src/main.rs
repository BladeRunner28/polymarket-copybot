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
        // We simulate a 2-cent spread improvement.
        let maker_improvement = 0.02;
        
        if intent.side.to_uppercase() == "BUY" {
            executed_price = f64::max(0.01, executed_price - maker_improvement);
            println!("📈 [Maker Execution] Parked BUY limit order inside spread at {:.1}¢ (avoided {:.1}¢ taker fee)", executed_price * 100.0, maker_improvement * 100.0);
        } else {
            executed_price = f64::min(0.99, executed_price + maker_improvement);
            println!("📉 [Maker Execution] Parked SELL limit order inside spread at {:.1}¢ (avoided {:.1}¢ taker fee)", executed_price * 100.0, maker_improvement * 100.0);
        }
        
        execution_note = match depth_warning {
            Some(w) => format!("MAKER Shadow Execution (Spread Captured) — {w}"),
            None => "MAKER Shadow Execution (Spread Captured)".to_string(),
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
    
    // Start Axum Execution Server
    let app = Router::new().route("/execute", post(handle_execution));
    let listener = TcpListener::bind("127.0.0.1:3014").await?;
    println!("🔥 Rust Execution API running on http://127.0.0.1:3014");
    axum::serve(listener, app).await?;
    
    Ok(())
}
