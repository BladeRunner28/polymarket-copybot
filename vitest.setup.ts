/**
 * Vitest setup: point Prisma at an isolated test database BEFORE any test
 * module imports the client. (ES imports are hoisted, so setting env inside
 * a test file is too late — it must happen here.)
 */
import path from "node:path";

process.env.DATABASE_URL = `file:${path.resolve(__dirname, "tests", "test.db")}`;
process.env.DATA_MODE = "demo";
