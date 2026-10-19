import { PolymarketAdapter } from "../src/lib/adapters/polymarket";

const a = new PolymarketAdapter();

async function main() {
  console.log("DATA_API_VERSION env =", JSON.stringify(process.env.DATA_API_VERSION ?? "(unset -> v2)"));
  const lb = await a.fetchLeaderboard(10);
  console.log(`leaderboard: ${lb.length} wallets, top = ${lb[0]?.address.slice(0, 10)}… pnl ${lb[0]?.pnl}`);
  const w = lb[0]!.address;
  const act = await a.fetchWalletActivity(w, 30);
  console.log(`activity(${w.slice(0, 10)}…, 30d): ${act.length} rows`);
  const first = act[0];
  console.log(
    `  sample: ${first?.outcome} ${first?.side} px ${first?.price} size ${first?.size?.toFixed(2)} ` +
      `resolved ${first?.resolved} pnl ${first?.pnl ?? "-"}`
  );
  const depth = await a.fetchWalletDepth(w, { closed: 100, open: 100 });
  console.log(`depth: closed ${depth.closedCount} open ${depth.openCount} censored ${depth.censored} requests ${depth.requests}`);
  if (lb.length === 0 || act.length === 0) {
    console.error("SMOKE FAIL: empty read under the v2 default");
    process.exit(1);
  }
  console.log("SMOKE PASS");
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
