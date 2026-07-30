-- CreateTable
CREATE TABLE "LeaderboardScan" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "source" TEXT NOT NULL,
    "scannedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "walletCount" INTEGER NOT NULL,
    "lookbackDays" INTEGER NOT NULL,
    "rawSummaryJson" TEXT NOT NULL
);

-- CreateTable
CREATE TABLE "WalletProfile" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "address" TEXT NOT NULL,
    "label" TEXT,
    "sourceRank" INTEGER,
    "status" TEXT NOT NULL DEFAULT 'watch',
    "roi30d" REAL NOT NULL DEFAULT 0,
    "consistencyScore" REAL NOT NULL DEFAULT 0,
    "copyabilityScore" REAL NOT NULL DEFAULT 0,
    "oneHitWonderPenalty" REAL NOT NULL DEFAULT 0,
    "globalScore" REAL NOT NULL DEFAULT 0,
    "bestCategory" TEXT,
    "categoryStrengthsJson" TEXT NOT NULL DEFAULT '{}',
    "averageTradeSize" REAL NOT NULL DEFAULT 0,
    "tradeCount30d" INTEGER NOT NULL DEFAULT 0,
    "resolvedTradeCount30d" INTEGER NOT NULL DEFAULT 0,
    "winRate30d" REAL NOT NULL DEFAULT 0,
    "averageLiquidity" REAL NOT NULL DEFAULT 0,
    "averageSpread" REAL NOT NULL DEFAULT 0,
    "averageEntryTiming" REAL NOT NULL DEFAULT 0,
    "copyabilityNotes" TEXT,
    "riskNotes" TEXT,
    "isDemo" BOOLEAN NOT NULL DEFAULT false,
    "lastScannedAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "ObservedTrade" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "walletAddress" TEXT NOT NULL,
    "marketId" TEXT NOT NULL,
    "conditionId" TEXT,
    "marketQuestion" TEXT NOT NULL,
    "marketCategory" TEXT,
    "outcome" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "walletEntryPrice" REAL NOT NULL,
    "detectedPrice" REAL NOT NULL,
    "size" REAL NOT NULL,
    "timestamp" DATETIME NOT NULL,
    "rawTradeJson" TEXT NOT NULL DEFAULT '{}',
    "isDemo" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ObservedTrade_walletAddress_fkey" FOREIGN KEY ("walletAddress") REFERENCES "WalletProfile" ("address") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "MarketSnapshot" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "marketId" TEXT NOT NULL,
    "conditionId" TEXT,
    "question" TEXT NOT NULL,
    "category" TEXT,
    "yesPrice" REAL,
    "noPrice" REAL,
    "bestBid" REAL,
    "bestAsk" REAL,
    "spread" REAL,
    "liquidity" REAL,
    "volume" REAL,
    "timeToResolution" REAL,
    "isDemo" BOOLEAN NOT NULL DEFAULT false,
    "collectedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "rawMarketJson" TEXT NOT NULL DEFAULT '{}'
);

-- CreateTable
CREATE TABLE "DecisionJournal" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "observedTradeId" TEXT NOT NULL,
    "walletAddress" TEXT NOT NULL,
    "marketId" TEXT NOT NULL,
    "decision" TEXT NOT NULL,
    "copyScore" REAL NOT NULL,
    "confidence" REAL NOT NULL,
    "reasonsJson" TEXT NOT NULL DEFAULT '[]',
    "risksJson" TEXT NOT NULL DEFAULT '[]',
    "walletQualityScore" REAL NOT NULL DEFAULT 0,
    "roiScore" REAL NOT NULL DEFAULT 0,
    "consistencyScore" REAL NOT NULL DEFAULT 0,
    "copyabilityScore" REAL NOT NULL DEFAULT 0,
    "categoryFitScore" REAL NOT NULL DEFAULT 0,
    "entryTimingScore" REAL NOT NULL DEFAULT 0,
    "spreadScore" REAL NOT NULL DEFAULT 0,
    "liquidityScore" REAL NOT NULL DEFAULT 0,
    "thesisScore" REAL NOT NULL DEFAULT 0,
    "simulatedPositionSize" REAL,
    "ruleSetVersion" INTEGER,
    "isDemo" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "DecisionJournal_observedTradeId_fkey" FOREIGN KEY ("observedTradeId") REFERENCES "ObservedTrade" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "PaperTrade" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "decisionJournalId" TEXT NOT NULL,
    "walletAddress" TEXT NOT NULL,
    "marketId" TEXT NOT NULL,
    "outcome" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "entryPrice" REAL NOT NULL,
    "currentPrice" REAL NOT NULL,
    "simulatedPositionSize" REAL NOT NULL,
    "unrealizedPnl" REAL NOT NULL DEFAULT 0,
    "realizedPnl" REAL,
    "status" TEXT NOT NULL DEFAULT 'open',
    "isDemo" BOOLEAN NOT NULL DEFAULT false,
    "openedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "closedAt" DATETIME,
    "resolvedAt" DATETIME,
    CONSTRAINT "PaperTrade_decisionJournalId_fkey" FOREIGN KEY ("decisionJournalId") REFERENCES "DecisionJournal" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "PnlSnapshot" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "paperTradeId" TEXT NOT NULL,
    "price" REAL NOT NULL,
    "pnl" REAL NOT NULL,
    "collectedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PnlSnapshot_paperTradeId_fkey" FOREIGN KEY ("paperTradeId") REFERENCES "PaperTrade" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "OutcomeReview" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "decisionJournalId" TEXT NOT NULL,
    "paperTradeId" TEXT,
    "reviewTime" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "priceAfter1h" REAL,
    "priceAfter6h" REAL,
    "priceAfter24h" REAL,
    "finalOutcome" TEXT,
    "simulatedPnl" REAL,
    "wasDecisionGood" BOOLEAN,
    "lessonsJson" TEXT NOT NULL DEFAULT '[]',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "OutcomeReview_decisionJournalId_fkey" FOREIGN KEY ("decisionJournalId") REFERENCES "DecisionJournal" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "OutcomeReview_paperTradeId_fkey" FOREIGN KEY ("paperTradeId") REFERENCES "PaperTrade" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "RuleSet" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "version" INTEGER NOT NULL,
    "active" BOOLEAN NOT NULL DEFAULT false,
    "rulesJson" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "RuleChange" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "oldRuleSetId" TEXT,
    "newRuleSetId" TEXT NOT NULL,
    "changedBy" TEXT NOT NULL DEFAULT 'hermes',
    "reason" TEXT NOT NULL,
    "evidenceSummary" TEXT NOT NULL,
    "beforeJson" TEXT NOT NULL,
    "afterJson" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "RuleChange_oldRuleSetId_fkey" FOREIGN KEY ("oldRuleSetId") REFERENCES "RuleSet" ("id") ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT "RuleChange_newRuleSetId_fkey" FOREIGN KEY ("newRuleSetId") REFERENCES "RuleSet" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "DailyReport" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "date" TEXT NOT NULL,
    "paperPnl" REAL NOT NULL,
    "winRate" REAL NOT NULL,
    "openPositions" INTEGER NOT NULL,
    "newSignals" INTEGER NOT NULL,
    "copiedSignals" INTEGER NOT NULL,
    "watchedSignals" INTEGER NOT NULL,
    "skippedSignals" INTEGER NOT NULL,
    "bestWalletsJson" TEXT NOT NULL DEFAULT '[]',
    "worstWalletsJson" TEXT NOT NULL DEFAULT '[]',
    "ruleChangesJson" TEXT NOT NULL DEFAULT '[]',
    "summary" TEXT NOT NULL,
    "sentToDiscord" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateIndex
CREATE UNIQUE INDEX "WalletProfile_address_key" ON "WalletProfile"("address");

-- CreateIndex
CREATE INDEX "ObservedTrade_walletAddress_idx" ON "ObservedTrade"("walletAddress");

-- CreateIndex
CREATE INDEX "ObservedTrade_marketId_idx" ON "ObservedTrade"("marketId");

-- CreateIndex
CREATE UNIQUE INDEX "ObservedTrade_walletAddress_marketId_outcome_side_timestamp_key" ON "ObservedTrade"("walletAddress", "marketId", "outcome", "side", "timestamp");

-- CreateIndex
CREATE INDEX "MarketSnapshot_marketId_idx" ON "MarketSnapshot"("marketId");

-- CreateIndex
CREATE INDEX "DecisionJournal_walletAddress_idx" ON "DecisionJournal"("walletAddress");

-- CreateIndex
CREATE INDEX "DecisionJournal_decision_idx" ON "DecisionJournal"("decision");

-- CreateIndex
CREATE INDEX "PaperTrade_status_idx" ON "PaperTrade"("status");

-- CreateIndex
CREATE INDEX "PaperTrade_walletAddress_idx" ON "PaperTrade"("walletAddress");

-- CreateIndex
CREATE INDEX "PnlSnapshot_paperTradeId_idx" ON "PnlSnapshot"("paperTradeId");

-- CreateIndex
CREATE UNIQUE INDEX "RuleSet_version_key" ON "RuleSet"("version");

-- CreateIndex
CREATE UNIQUE INDEX "DailyReport_date_key" ON "DailyReport"("date");
