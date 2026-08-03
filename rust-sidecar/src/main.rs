use axum::{routing::post, Json, Router};
use serde::{Deserialize};
use serde_json::json;
use std::env;
use tokio::net::TcpListener;
use futures_util::{StreamExt, SinkExt};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};

const POLYMARKET_CTF: &str = "0x4bFB41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E";

#[derive(Deserialize, Debug)]
struct ExecutionIntent {
    bot_id: String,
    venue: String,
    market_id: String,
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
    
    // Simulate FAK execution: here we'd query L2 depth. 
    // For now, we simulate a 100% fill and bounce the result back to Node.js.
    let client = reqwest::Client::new();
    let payload = json!({
        "botId": intent.bot_id,
        "decisionJournalId": intent.decision_journal_id,
        "walletAddress": intent.wallet_address,
        "marketId": intent.market_id,
        "outcome": intent.outcome,
        "side": intent.side,
        "entryPrice": intent.price,
        "simulatedPositionSize": intent.size_usd,
        "venue": intent.venue,
        "status": "open",
        "executionNote": "FAK Shadow Execution via Rust"
    });

    tokio::spawn(async move {
        let _ = client.post("http://127.0.0.1:3013/api/webhooks/execution-result")
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
        while let Some(msg) = ws_stream.next().await {
            if let Ok(Message::Text(text)) = msg {
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text) {
                    if parsed["method"] == "eth_subscription" {
                        let log = &parsed["params"]["result"];
                        let tx_hash = log["transactionHash"].as_str().unwrap_or("unknown");
                        println!("🐋 Zero-Latency Whale Trade Detected! Tx: {}", tx_hash);
                        let client_clone = client.clone();
                        let payload = log.clone();
                        tokio::spawn(async move {
                            let _ = client_clone.post("http://127.0.0.1:3013/api/webhooks/whale-signal")
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
