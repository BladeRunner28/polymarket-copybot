-- CreateTable
CREATE TABLE "BotBankroll" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "botId" TEXT NOT NULL,
    "principal" REAL NOT NULL DEFAULT 0,
    "cashBalance" REAL NOT NULL DEFAULT 0,
    "realizedPnl" REAL NOT NULL DEFAULT 0,
    "minPositionSize" REAL NOT NULL DEFAULT 0.25,
    "maxPositionSize" REAL NOT NULL DEFAULT 20.00,
    "updatedAt" DATETIME NOT NULL
);

-- RedefineTables
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_DailyReport" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "date" TEXT NOT NULL,
    "paperPnl" REAL NOT NULL,
    "winRate" REAL NOT NULL,
    "compoundingPnl" REAL NOT NULL DEFAULT 0,
    "compoundingWinRate" REAL NOT NULL DEFAULT 0,
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
INSERT INTO "new_DailyReport" ("bestWalletsJson", "copiedSignals", "createdAt", "date", "id", "newSignals", "openPositions", "paperPnl", "ruleChangesJson", "sentToDiscord", "skippedSignals", "summary", "watchedSignals", "winRate", "worstWalletsJson") SELECT "bestWalletsJson", "copiedSignals", "createdAt", "date", "id", "newSignals", "openPositions", "paperPnl", "ruleChangesJson", "sentToDiscord", "skippedSignals", "summary", "watchedSignals", "winRate", "worstWalletsJson" FROM "DailyReport";
DROP TABLE "DailyReport";
ALTER TABLE "new_DailyReport" RENAME TO "DailyReport";
CREATE UNIQUE INDEX "DailyReport_date_key" ON "DailyReport"("date");
CREATE TABLE "new_PaperTrade" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "botId" TEXT NOT NULL DEFAULT 'STANDARD',
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
INSERT INTO "new_PaperTrade" ("closedAt", "currentPrice", "decisionJournalId", "entryPrice", "id", "isDemo", "marketId", "openedAt", "outcome", "realizedPnl", "resolvedAt", "side", "simulatedPositionSize", "status", "unrealizedPnl", "walletAddress") SELECT "closedAt", "currentPrice", "decisionJournalId", "entryPrice", "id", "isDemo", "marketId", "openedAt", "outcome", "realizedPnl", "resolvedAt", "side", "simulatedPositionSize", "status", "unrealizedPnl", "walletAddress" FROM "PaperTrade";
DROP TABLE "PaperTrade";
ALTER TABLE "new_PaperTrade" RENAME TO "PaperTrade";
CREATE INDEX "PaperTrade_status_idx" ON "PaperTrade"("status");
CREATE INDEX "PaperTrade_walletAddress_idx" ON "PaperTrade"("walletAddress");
CREATE INDEX "PaperTrade_botId_status_idx" ON "PaperTrade"("botId", "status");
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;

-- CreateIndex
CREATE UNIQUE INDEX "BotBankroll_botId_key" ON "BotBankroll"("botId");
