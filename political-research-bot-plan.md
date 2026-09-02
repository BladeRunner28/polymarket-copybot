# Political Research Bot Integration Plan

This document outlines the architecture for a standalone Research Bot designed to ingest political and regulatory data and feed predictive sentiment signals into the C-200 trading engine.

## 1. Core Architecture

The Research Bot will act as a separate microservice (Python-based for NLP/ML libraries) that pushes discrete "Alpha Signals" to your existing Node.js Signal Brain via a webhook.

*   **Research Bot (Python):** Scrapes APIs, parses PDFs/text, runs NLP sentiment analysis, and calculates a `RegulatorySentimentScore` (-1.0 to 1.0).
*   **Signal Brain (Node.js/Prisma):** Receives the score. If `RegulatorySentimentScore > 0.8`, it triggers a cross-market arbitrage scan (Polymarket vs Kalshi) and executes a Maker order via the Rust sidecar.

## 2. Required APIs and Accounts

To monitor the US House, Senate, Executive branch, and political prediction markets, the following data sources are used:

### A. Congressional & Legislative Data
*   **unitedstates/congress GitHub Repo:** The open-source standard for scraping GovInfo, congress.gov, and committee sites into structured JSON. *Replaces the deprecated ProPublica Congress API.*
    *   *Repo:* [unitedstates/congress](https://github.com/unitedstates/congress)
    *   *Usage:* Run the scrapers on a cron schedule to build a local dataset of bill actions and votes.
*   **GovInfo.gov API:** Official API from the GPO. Good for pulling full text of bills, Federal Register notices, and Congressional Record documents for NLP parsing.
    *   *Key:* Installed in `.env`.
*   **Congress.gov API:** Direct access to legislative data.
    *   *Key:* Installed in `.env`.

### B. Congressional Stock Trading
*   **Quiver Quantitative API:** The gold standard for tracking Congressional stock trading, government contracts, and lobbying. If a senator buys defense stocks right before a defense bill vote, this API catches it.
    *   *Key:* Installed in `.env`.

### C. Executive Branch & Regulatory Data
*   **Federal Register API (Free):** Tracks proposed rules and executive orders from agencies (SEC, CFTC, EPA, etc.). Crucial for crypto-regulation markets.

### D. Prediction Market Data (Already Integrated)
*   **Polymarket Gamma API / Polygon WebSockets:** Integrated via the Rust sidecar.
*   **Kalshi API:** Integrated for execution routing.

## 3. Integration with C-200

To make this data actionable for the C-200 bot, we use a unified communication protocol.

### Step 1: Database Expansion
We added a new Prisma model to the schema to store these signals:

```prisma
model RegulatorySignal {
  id               String   @id @default(cuid())
  source           String   // e.g., "quiver_congress_trade", "unitedstates_congress"
  marketCategory   String   // e.g., "Politics", "Crypto"
  sentimentScore   Float    // -1.0 (Bearish) to 1.0 (Bullish)
  confidence       Float    // 0.0 to 1.0
  rawPayload       String   // JSON of the event
  processedAt      DateTime @default(now())
}
```

### Step 2: The Webhook Receiver
A Next.js API route (`/api/webhooks/research-signal`) receives the payload.

1.  The Python Research Bot detects Nancy Pelosi buying NVDA stock via Quiver.
2.  It sends a POST request to `/api/webhooks/research-signal` with a positive sentiment score for the "Tech/AI" category.
3.  The Node.js engine receives the webhook and saves it to the `RegulatorySignal` table.

### Step 3: Modifying the Scoring Engine
We update `src/lib/scoring/trade.ts` to query the `RegulatorySignal` table during trade evaluation.

*   If a Whale buys "YES" on a political market, the engine checks for recent `RegulatorySignals` in that category.
*   If the `RegulatorySentimentScore` strongly agrees with the Whale's direction, the bot adds a massive confidence multiplier (e.g., +30 points to `copyScore`) and increases the position size to the maximum Kalshi Maker limit.
