/**
 * sell-log — the discarded SELL prints.
 *
 * Pins the two properties the forward measurement depends on: the print is recorded verbatim
 * (so it can be joined to the wallet's BUY by market/outcome), and the append can never throw
 * (an observability ledger must not be able to fail the monitor loop).
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { appendSellPrint, sellLogPath, type SellPrintRecord } from "../src/lib/sell-log";

const rec = (o: Partial<SellPrintRecord> = {}): SellPrintRecord => ({
  walletAddress: "0xabc",
  marketId: "will-x-win",
  outcome: "YES",
  side: "SELL",
  price: 0.62,
  size: 4210.5,
  printTs: 1792794420000,
  observationOnly: false,
  ...o,
});

describe("sell-print sidecar", () => {
  it("appends one JSONL line carrying wallet, market, price and the venue print time", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sell-log-"));
    expect(appendSellPrint(rec(), dir)).toContain("SELL");
    const rows = fs
      .readFileSync(sellLogPath(dir), "utf8")
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l));
    expect(rows).toHaveLength(1);
    expect(rows[0].walletAddress).toBe("0xabc");
    expect(rows[0].price).toBe(0.62);
    expect(rows[0].printTs).toBe(1792794420000);
    expect(typeof rows[0].loggedAt).toBe("string");
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("is append-only: two prints leave two lines, in order", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sell-log-"));
    appendSellPrint(rec({ marketId: "a" }), dir);
    appendSellPrint(rec({ marketId: "b" }), dir);
    const ids = fs
      .readFileSync(sellLogPath(dir), "utf8")
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l).marketId);
    expect(ids).toEqual(["a", "b"]);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("never throws when the directory cannot be written", () => {
    expect(appendSellPrint(rec(), "/dev/null/nope")).toBeNull();
  });
});
