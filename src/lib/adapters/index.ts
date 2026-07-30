import { DataAdapter } from "../types";
import { PolymarketAdapter } from "./polymarket";
import { DemoAdapter } from "./demo";

export function getAdapter(): DataAdapter {
  const mode = (process.env.DATA_MODE ?? "live").toLowerCase();
  if (mode === "demo") return new DemoAdapter();
  return new PolymarketAdapter();
}

export { PolymarketAdapter, DemoAdapter };
