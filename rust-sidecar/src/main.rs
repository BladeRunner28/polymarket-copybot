use futures_util::{StreamExt, SinkExt};
use serde_json::json;
use std::env;
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};

const POLYMARKET_CTF: &str = "0x4bFB41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E";

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("🐉 PolyHydra Whale Signal Sidecar (Phase 2)");
    
    // Polygon RPC WebSocket (Public standard, or Alchemy/Infura in prod)
    let ws_url = env::var("POLYGON_WS_URL").unwrap_or_else(|_| "wss://polygon-bor-rpc.publicnode.com".to_string());
    println!("Connecting to Polygon WebSockets at {}...", ws_url);
    
    let (mut ws_stream, _) = connect_async(&ws_url).await?;
    println!("✅ Connected to Polygon WebSocket.");

    // Subscribe to raw logs for the Polymarket CTF Exchange contract
    let subscribe_msg = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_subscribe",
        "params": [
            "logs",
            {
                "address": POLYMARKET_CTF
            }
        ]
    });

    ws_stream.send(Message::Text(subscribe_msg.to_string())).await?;

    println!("📡 Subscribed to Polymarket CTF Exchange events. Listening for whale trades...");

    let client = reqwest::Client::new();

    while let Some(msg) = ws_stream.next().await {
        let msg = msg?;
        if let Message::Text(text) = msg {
            let parsed: serde_json::Value = serde_json::from_str(&text)?;
            
            // Filter and process JSON-RPC subscription log events
            if parsed["method"] == "eth_subscription" {
                let log = &parsed["params"]["result"];
                let tx_hash = log["transactionHash"].as_str().unwrap_or("unknown");
                
                println!("🐋 Zero-Latency Whale Trade Detected! Tx: {}", tx_hash);
                
                // Dispatch directly to our Node.js PolyHydra backend
                let client_clone = client.clone();
                let payload = log.clone();
                
                tokio::spawn(async move {
                    let _ = client_clone.post("http://127.0.0.1:3013/api/webhooks/whale-signal")
                        .json(&payload)
                        .send()
                        .await;
                });
            }
        }
    }

    Ok(())
}
