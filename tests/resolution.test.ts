import { describe, expect, it } from "vitest";
import { didOutcomeWin, normalizeOutcomeLabel } from "../src/lib/resolution";

/**
 * Regression cover for the 2026-09-13 phantom-loss audit: resolution used to
 * guess `YES`/`NO` from the first token's price, which can never equal a real
 * token label ("Dynasty", "Under", "9z") — every such market was booked as a
 * full-stake loss (70 confirmed, −$828 booked where +$942 was owed).
 */
describe("normalizeOutcomeLabel", () => {
  it("ignores case, spaces and punctuation", () => {
    expect(normalizeOutcomeLabel("Team Liquid")).toBe("TEAMLIQUID");
    expect(normalizeOutcomeLabel("TEAM LIQUID")).toBe("TEAMLIQUID");
    expect(normalizeOutcomeLabel("team-liquid")).toBe("TEAMLIQUID");
    expect(normalizeOutcomeLabel("Yes")).toBe("YES");
    expect(normalizeOutcomeLabel("9z")).toBe("9Z");
  });

  it("maps empty/absent values to an empty string", () => {
    expect(normalizeOutcomeLabel("")).toBe("");
    expect(normalizeOutcomeLabel(null)).toBe("");
    expect(normalizeOutcomeLabel(undefined)).toBe("");
  });
});

describe("didOutcomeWin — labelled (non-Yes/No) markets", () => {
  it("matches a real token label case-insensitively", () => {
    // The exact rows the audit found booked as losses while actually winning.
    expect(didOutcomeWin("DYNASTY", { winningLabel: "DYNASTY" })).toBe(true);
    expect(didOutcomeWin("TEAM LIQUID", { winningLabel: "Team Liquid" })).toBe(true);
    expect(didOutcomeWin("VITALITY", { winningLabel: "Vitality" })).toBe(true);
    expect(didOutcomeWin("UNDER", { winningLabel: "Under" })).toBe(true);
  });

  it("returns false for the token that lost", () => {
    expect(didOutcomeWin("9Z", { winningLabel: "Vitality" })).toBe(false);
    expect(didOutcomeWin("OVER", { winningLabel: "Under" })).toBe(false);
    expect(didOutcomeWin("CUPID ESPORTS", { winningLabel: "Maryville University" })).toBe(false);
  });

  it("never confuses a binary winner with a label-named trade (fail loud)", () => {
    // Different naming schemes ⇒ we cannot know. Must NOT be booked as a loss.
    expect(didOutcomeWin("VITALITY", { winningLabel: "Yes", yesPrice: 1 })).toBeNull();
    expect(didOutcomeWin("YES", { winningLabel: "Vitality", yesPrice: 1 })).toBeNull();
  });

  it("returns null when there is nothing to compare", () => {
    expect(didOutcomeWin("", { winningLabel: "DYNASTY" })).toBeNull();
    expect(didOutcomeWin(null, { winningLabel: "DYNASTY" })).toBeNull();
  });
});

describe("didOutcomeWin — binary markets", () => {
  it("still compares Yes/No labels", () => {
    expect(didOutcomeWin("YES", { winningLabel: "Yes" })).toBe(true);
    expect(didOutcomeWin("NO", { winningLabel: "Yes" })).toBe(false);
    expect(didOutcomeWin("NO", { winningLabel: "No" })).toBe(true);
  });

  it("preserves the legacy yesPrice fallback when the venue gives no labels", () => {
    expect(didOutcomeWin("YES", { yesPrice: 0.99 })).toBe(true);
    expect(didOutcomeWin("NO", { yesPrice: 0.99 })).toBe(false);
    expect(didOutcomeWin("YES", { yesPrice: 0.01 })).toBe(false);
    expect(didOutcomeWin("NO", { yesPrice: 0.01 })).toBe(true);
  });

  it("returns null rather than guessing when neither labels nor a price exist", () => {
    expect(didOutcomeWin("YES", {})).toBeNull();
    expect(didOutcomeWin("YES", { yesPrice: null })).toBeNull();
    // A non-binary trade with no label is undeterminable, price or not.
    expect(didOutcomeWin("DYNASTY", { yesPrice: 0.99 })).toBeNull();
  });
});
