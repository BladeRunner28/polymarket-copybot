/**
 * market-category — what a market IS, as opposed to which slug family it
 * happens to live in.
 *
 * WHY THIS EXISTS (observed-trade-category-field, 2026-09-23): ObservedTrade
 * .marketCategory is the first dash-segment of the EVENT slug, not a category —
 * measured live: 335,443 rows / 863 distinct tokens, and 33.1% of rows carry a
 * question word ('highest' 73,089, 'which' 10,142, 'next' 4,971, 'will' 417…).
 * Token 'highest' alone wraps 14,879 distinct marketIds, so a wallet's
 * 'strongest category' can read 'highest' or 'what' and the category features
 * built on it are slug statistics, not market categories. The v45 blacklist and
 * per-slug cap WANT the token (league granularity is deliberate there —
 * 'lol'/'cs2'/'nfl' are genuinely the leagues; verified by question text), so the
 * token stays exactly where it is and the real category is added BESIDE it.
 *
 * The rule table is a faithful port of scripts/wallet-concentration-test.py
 * (classify()), which was validated against the vendor's own category map at
 * r = +0.548 over 353 wallets — parity with that reference is enforced by
 * scripts/verify-market-category.ts, not assumed.
 *
 * coarse = the bucket a copy book allocates/blacklists against.
 * fine   = the grain a league-level claim lives at.
 */

type Rule = [token: string, coarse: string, fine: string];

// Order matters: first match wins for a slug TOKEN (set-once map), and the
// question rules are evaluated in listed order.
const SLUG_RULES: Rule[] = [
  ["fifwc", "sports", "football-intl"],
  ["uwcl", "sports", "football-intl"],
  ["ucl", "sports", "football-ucl"],
  ["epl", "sports", "football-epl"],
  ["fl1", "sports", "football-epl"],
  ["spl", "sports", "football-epl"],
  ["efl", "sports", "football-epl"],
  ["mls", "sports", "football-mls"],
  ["brco", "sports", "football-intl"],
  ["bra2", "sports", "football-intl"],
  ["lol", "esports", "esports-lol"],
  ["lec", "esports", "esports-lol"],
  ["cs2", "esports", "esports-cs2"],
  ["dota2", "esports", "esports-dota"],
  ["val", "esports", "esports-valorant"],
  ["mlb", "sports", "baseball-mlb"],
  ["wnba", "sports", "basketball-nba"],
  ["nba", "sports", "basketball-nba"],
  ["nfl", "sports", "football-nfl"],
  ["nhl", "sports", "hockey-nhl"],
  ["ufc", "sports", "combat-ufc"],
  ["atp", "sports", "tennis"],
  ["wta", "sports", "tennis"],
  ["itf", "sports", "tennis"],
  ["btc", "crypto", "crypto-btc"],
  ["eth", "crypto", "crypto-eth"],
  ["bitcoin", "crypto", "crypto-btc"],
  ["ethereum", "crypto", "crypto-eth"],
  ["elon", "politics", "politics-elon"],
  ["khamenei", "politics", "politics-geo"],
  ["trump", "politics", "politics-us"],
  ["donald", "politics", "politics-us"],
  ["white", "politics", "politics-us"],
  ["fed", "econ", "econ-macro"],
];

const QUESTION_RULES: Array<[pattern: RegExp, coarse: string, fine: string]> = [
  [/\b(bitcoin|btc|ethereum|eth|solana|sol|xrp|doge|crypto)\b/, "crypto", "crypto-price"],
  [/up or down/, "crypto", "crypto-updown"],
  [
    /\b(league of legends|\blol\b|valorant|dota|counter-?strike|cs2|esports?)\b/,
    "esports",
    "esports-other",
  ],
  [
    /\b(nba|wnba|lakers|celtics|knicks|nuggets|warriors|bucks|nba finals)\b/,
    "sports",
    "basketball-nba",
  ],
  [/\b(mlb|world series|yankees|dodgers|red sox)\b/, "sports", "baseball-mlb"],
  [/\b(nfl|super bowl|touchdown)\b/, "sports", "football-nfl"],
  [/\b(nhl|stanley cup)\b/, "sports", "hockey-nhl"],
  [/\b(ufc|mma)\b/, "sports", "combat-ufc"],
  [/\b(atp|wta|itf|grand slam|wimbledon|us open tennis)\b/, "sports", "tennis"],
  [
    /\b(fifa|world cup|uefa|premier league|la liga|serie a|bundesliga|ligue 1|mls|champions league|copa)\b/,
    "sports",
    "football-intl",
  ],
  [
    /\b(temperature|rain|snow|hurricane|weather|fahrenheit|celsius)\b/,
    "weather",
    "weather-temp",
  ],
  [
    /\b(fed|fomc|interest rate|cpi|inflation|gdp|recession|unemployment|s&p|nasdaq|stock)\b/,
    "econ",
    "econ-macro",
  ],
  [
    /\b(election|senate|house of representatives|president|parliament|prime minister|governor|mayor|nominee|congress|khamenei|putin|zelensky|netanyahu)\b/,
    "politics",
    "politics-elections",
  ],
  [/\b(trump|biden|harris|desantis|newsom|white house|elon musk)\b/, "politics", "politics-us"],
  [
    /\b(oscar|grammy|emmy|movie|box office|album|billboard|song|spotify|netflix|tiktok)\b/,
    "culture",
    "culture-media",
  ],
  [
    /\b(openai|gpt|gemini|claude|llama|anthropic|nvidia|tesla|spacex|starship|apple|google|meta)\b/,
    "tech",
    "tech-corp",
  ],
  [/\b(ai\b|artificial intelligence)\b/, "tech", "tech-ai"],
];

const SLUG_FIRST = new Map<string, { coarse: string; fine: string }>();
for (const [tok, coarse, fine] of SLUG_RULES) {
  if (!SLUG_FIRST.has(tok)) SLUG_FIRST.set(tok, { coarse, fine });
}

export interface MarketCategoryClass {
  coarse: string;
  fine: string;
}

/**
 * Classify a market from its slug + question text. Mirrors the Python reference
 * exactly so both produce the same labels for the same rows.
 */
export function classifyMarketCategory(
  marketId?: string | null,
  question?: string | null
): MarketCategoryClass {
  const slug = (marketId ?? "").toLowerCase();
  const first = slug.split("-")[0];
  const direct = SLUG_FIRST.get(first);
  if (direct) return direct;
  // Series tokens that are not the first segment (e.g. "will-fifwc-...").
  for (const [tok, cls] of SLUG_FIRST) {
    if (new RegExp(`(^|-)${tok.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(-|$)`).test(slug)) {
      return cls;
    }
  }
  const q = (question ?? "").toLowerCase();
  for (const [re, coarse, fine] of QUESTION_RULES) {
    if (re.test(q)) return { coarse, fine };
  }
  return { coarse: "other", fine: "other" };
}
