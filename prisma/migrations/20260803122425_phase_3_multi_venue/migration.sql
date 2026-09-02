-- RedefineTables
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_DecisionJournal" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "venue" TEXT NOT NULL DEFAULT 'Polymarket',
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
INSERT INTO "new_DecisionJournal" ("categoryFitScore", "confidence", "consistencyScore", "copyScore", "copyabilityScore", "createdAt", "decision", "entryTimingScore", "id", "isDemo", "liquidityScore", "marketId", "observedTradeId", "reasonsJson", "risksJson", "roiScore", "ruleSetVersion", "simulatedPositionSize", "spreadScore", "thesisScore", "walletAddress", "walletQualityScore") SELECT "categoryFitScore", "confidence", "consistencyScore", "copyScore", "copyabilityScore", "createdAt", "decision", "entryTimingScore", "id", "isDemo", "liquidityScore", "marketId", "observedTradeId", "reasonsJson", "risksJson", "roiScore", "ruleSetVersion", "simulatedPositionSize", "spreadScore", "thesisScore", "walletAddress", "walletQualityScore" FROM "DecisionJournal";
DROP TABLE "DecisionJournal";
ALTER TABLE "new_DecisionJournal" RENAME TO "DecisionJournal";
CREATE INDEX "DecisionJournal_walletAddress_idx" ON "DecisionJournal"("walletAddress");
CREATE INDEX "DecisionJournal_decision_idx" ON "DecisionJournal"("decision");
CREATE TABLE "new_PaperTrade" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "botId" TEXT NOT NULL DEFAULT 'STANDARD',
    "venue" TEXT NOT NULL DEFAULT 'Polymarket',
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
INSERT INTO "new_PaperTrade" ("botId", "closedAt", "currentPrice", "decisionJournalId", "entryPrice", "id", "isDemo", "marketId", "openedAt", "outcome", "realizedPnl", "resolvedAt", "side", "simulatedPositionSize", "status", "unrealizedPnl", "walletAddress") SELECT "botId", "closedAt", "currentPrice", "decisionJournalId", "entryPrice", "id", "isDemo", "marketId", "openedAt", "outcome", "realizedPnl", "resolvedAt", "side", "simulatedPositionSize", "status", "unrealizedPnl", "walletAddress" FROM "PaperTrade";
DROP TABLE "PaperTrade";
ALTER TABLE "new_PaperTrade" RENAME TO "PaperTrade";
CREATE INDEX "PaperTrade_status_idx" ON "PaperTrade"("status");
CREATE INDEX "PaperTrade_walletAddress_idx" ON "PaperTrade"("walletAddress");
CREATE INDEX "PaperTrade_botId_status_idx" ON "PaperTrade"("botId", "status");
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;
