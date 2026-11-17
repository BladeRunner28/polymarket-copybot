/**
 * profit-clip-frame-probe -- what Kelly says about the legs the book BOUGHT at a
 * favourite price while the journal sized them on a cheap-band lambda.
 *
 * READ-ONLY instrument for the Lane A proposal t_4eb720b1
 * (drafts/profit-c200-clip-cap-25-20261116.md). It writes nothing: no DB handle,
 * no RuleSet, no row. It calls the SAME functions the scorer calls.
 *
 * WHY THIS EXISTS
 * ---------------
 * 13 of the regime's 41 $100 clips were booked at 0.805-0.94, and every one of
 * their DecisionJournal rows carries `premium λ̂ = -0.68 / -0.74` -- the 0.0-0.2
 * band's lambda. The FillIntent rows for that set record `intentPrice` 0.06-0.195,
 * i.e. `booked entry = 1 - intent`: the scorer priced and sized the SIBLING token,
 * while the sidecar booked the token actually named by the outcome label (and
 * ObservedTrade.walletEntryPrice agrees with the booked side, not the intent).
 *
 * So the question "is a $100 clip too big here" has a different answer per frame:
 *   - at the price the scorer used (cheap), the leg is an 'underpriced longshot',
 *     Kelly funds it to the hard cap, and $100 is the MODEL'S OWN size;
 *   - at the price the book paid (favourite), the 0.8-1.01 band's lambda puts q
 *     below p, so Kelly returns skip("no edge") and the correct clip is ZERO.
 *
 * USAGE
 *   npx tsx scripts/profit-clip-frame-probe.ts
 *   npx tsx scripts/profit-clip-frame-probe.ts --cash 7400
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { kellySizeForCopy } from "../src/lib/kelly";
import { getBandLambda } from "../src/lib/premium";
import type { PremiumBand, PremiumCalibration } from "../src/lib/premium";

const args = process.argv.slice(2);
const arg = (n: string, d: number) => {
  const i = args.indexOf(`--${n}`);
  return i >= 0 && args[i + 1] ? Number(args[i + 1]) : d;
};

const cal = JSON.parse(
  readFileSync(join(__dirname, "..", "data", "premium-calibration.json"), "utf8")
);
const bands: PremiumBand[] = cal.bands;
const AVAIL = arg("cash", 7400);
const RULES = { fraction: 0.5, maxBankrollPct: 0.1, maxSizeUsd: 100, minBetUsd: 1, minEdgePct: 0.02 };

console.log(
  `premium calibration ${cal.calibratedAt}   availableBankroll $${AVAIL}   ` +
    `fraction ${RULES.fraction}  maxBankrollPct ${RULES.maxBankrollPct}  maxSizeUsd $${RULES.maxSizeUsd}`
);
console.log(
  "bands: " +
    bands.map((b) => `[${b.lo},${b.hi}) λ̂=${b.lambda.toFixed(3)}`).join("  ")
);

function run(price: number, label: string) {
  const lam = getBandLambda(price, bands);
  const r = kellySizeForCopy({
    price,
    outcome: "YES",
    lambda: lam,
    side: "BUY",
    availableBankroll: AVAIL,
    ...RULES,
  });
  console.log(
    `${label.padEnd(30)} p=${price.toFixed(3)}  λ̂=${lam.toFixed(3).padStart(7)}  ` +
      `q=${r.q.toFixed(3)}  f*=${r.fStarFull.toFixed(4)}  size=$${r.sizeUsd.toFixed(2)}` +
      `${r.skip ? "   SKIP: " + r.reason : ""}`
  );
  return r;
}

// the regime's complement-framed $100 legs: (price the scorer used, price the book paid)
const PAIRS: [number, number][] = [
  [0.135, 0.865],
  [0.195, 0.805],
  [0.06, 0.94],
  [0.125, 0.875],
  [0.105, 0.895],
  [0.085, 0.915],
  [0.175, 0.825],
];

console.log("\n== per leg: the two frames ==");
let scorerFunded = 0;
let bookSkipped = 0;
for (const [cheap, paid] of PAIRS) {
  const a = run(cheap, "scorer frame (sibling px)");
  const b = run(paid, "book frame (paid px)");
  if (!a.skip) scorerFunded++;
  if (b.skip) bookSkipped++;
  console.log("");
}
console.log(
  `of ${PAIRS.length} complement-framed legs: Kelly funds ${scorerFunded} at the scorer's price; ` +
    `at the price actually paid ${bookSkipped} are SKIP(no edge) -> correct clip $0`
);

// what a price-frame fix would have admitted at all, on a clean frame
console.log("\n== sensitivity: size at the paid price across the favourite band ==");
for (const p of [0.75, 0.8, 0.85, 0.9, 0.94]) run(p, "paid-price frame");
