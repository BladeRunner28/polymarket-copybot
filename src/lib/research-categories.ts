/**
 * Maps a Polymarket market (question text + event slug) to the research-bot
 * RegulatorySignal category used by the C-200 sentiment agreement boost.
 * Returns undefined when no regulatory category applies (e.g. sports/esports).
 *
 * Category names must match RegulatorySignal.marketCategory exactly:
 * Crypto | Tech/AI | Defense/Geopolitics | Healthcare | Energy/Climate |
 * Finance | Macro/Politics
 */

const KEYWORDS: Array<[string, RegExp]> = [
  [
    "Crypto",
    /\b(crypto|bitcoin|ethereum|solana|xrp|stablecoin|digital assets?|sec|cftc|coinbase|binance|dogecoin)\b/i,
  ],
  [
    "Tech/AI",
    /\b(ai|artificial intelligence|openai|anthropic|chatgpt|nvidia|semiconductor|chips act|tech giants?)\b/i,
  ],
  [
    "Defense/Geopolitics",
    /\b(ukraine|russia|israel|iran|defense|defence|military|nato|taiwan|ceasefire|invasion|missile)\b/i,
  ],
  [
    "Healthcare",
    /\b(fda|medicare|medicaid|vaccine|health|obamacare|abortion|drug prices?|pharma|pandemic)\b/i,
  ],
  ["Energy/Climate", /\b(climate|epa|oil|energy|renewable|fossil fuel|emissions|carbon|paris agreement)\b/i],
  [
    "Finance",
    /\b(fed|federal reserve|rate cut|rate hike|interest rate|inflation|cpi|recession|gdp|treasury|stock market|dow jones|nasdaq|tariff|tax|economy)\b/i,
  ],
  [
    "Macro/Politics",
    /\b(election|president|congress|senate|house|governor|senator|party|democrat|republican|primary|voter|vote|ballot|midterm|minister|parliament|cabinet|presidential|politician|impeach)\b/i,
  ],
];

export function researchCategoryFor(question?: string | null, slug?: string | null): string | undefined {
  const text = `${question ?? ""} ${slug ?? ""}`.toLowerCase();
  if (!text.trim()) return undefined;
  for (const [category, re] of KEYWORDS) {
    if (re.test(text)) return category;
  }
  return undefined;
}
