import { describe, it, expect } from "vitest";
import {
  gammaSlugEndpointOrder,
  gammaSlugUrl,
  normalizeGammaMarketPayload,
} from "../src/lib/adapters/gamma-market-payload";

/**
 * Gamma slug-endpoint compatibility (audit §P4).
 *
 * Live fact this guards (verified 2026-09-28): the legacy offset endpoint
 * `GET /markets?slug=` answers 200 but returns
 *     deprecation: true
 *     sunset: Fri, 01 May 2026 00:00:00 GMT
 * — already past its sunset — while `GET /markets/slug/{slug}` returns the same
 * fields as a bare OBJECT instead of a one-element ARRAY. Both shapes must
 * parse, the current contract must be tried first, and an error envelope must
 * never be mistaken for a market (that would poison the adapter's negative
 * cache with a live slug).
 */
describe("gammaSlugEndpointOrder", () => {
  it("tries the current contract first by default", () => {
    expect(gammaSlugEndpointOrder({})).toEqual(["slug", "legacy"]);
    expect(gammaSlugEndpointOrder({ GAMMA_SLUG_API: "slug" })).toEqual(["slug", "legacy"]);
    expect(gammaSlugEndpointOrder({ GAMMA_SLUG_API: "SLUG" })).toEqual(["slug", "legacy"]);
  });

  it("pins the legacy order when explicitly requested, so a regression is revertible without code", () => {
    expect(gammaSlugEndpointOrder({ GAMMA_SLUG_API: "legacy" })).toEqual(["legacy", "slug"]);
  });

  it("falls back to the default on an unrecognised value rather than failing open", () => {
    expect(gammaSlugEndpointOrder({ GAMMA_SLUG_API: "whatever" })).toEqual(["slug", "legacy"]);
  });
});

describe("gammaSlugUrl", () => {
  it("builds both endpoint variants and encodes the slug", () => {
    expect(gammaSlugUrl("https://gamma-api.polymarket.com", "abc-123", "slug")).toBe(
      "https://gamma-api.polymarket.com/markets/slug/abc-123"
    );
    expect(gammaSlugUrl("https://gamma-api.polymarket.com", "abc-123", "legacy")).toBe(
      "https://gamma-api.polymarket.com/markets?slug=abc-123"
    );
    expect(gammaSlugUrl("https://gamma-api.polymarket.com/", "a b&c", "slug")).toBe(
      "https://gamma-api.polymarket.com/markets/slug/a%20b%26c"
    );
  });
});

describe("normalizeGammaMarketPayload", () => {
  it("accepts the current contract (bare object)", () => {
    const m = { slug: "xi-jinping-out-before-2027", conditionId: "0xabc", volume24hr: 81670 };
    expect(normalizeGammaMarketPayload(m)).toEqual(m);
  });

  it("accepts the legacy contract (one-element array)", () => {
    const m = { slug: "legacy-market", conditionId: "0xdef" };
    expect(normalizeGammaMarketPayload([m])).toEqual(m);
  });

  it("returns null for empty payloads", () => {
    expect(normalizeGammaMarketPayload([])).toBeNull();
    expect(normalizeGammaMarketPayload({})).toBeNull();
    expect(normalizeGammaMarketPayload(null)).toBeNull();
    expect(normalizeGammaMarketPayload(undefined)).toBeNull();
    expect(normalizeGammaMarketPayload("[]")).toBeNull();
    expect(normalizeGammaMarketPayload(42)).toBeNull();
  });

  it("returns null for error envelopes so a live slug is never negative-cached", () => {
    expect(normalizeGammaMarketPayload({ error: "market not found" })).toBeNull();
    expect(normalizeGammaMarketPayload({ message: "Not Found", status: 404 })).toBeNull();
    expect(normalizeGammaMarketPayload([{ error: "nope" }])).toBeNull();
  });

  it("accepts any object that actually identifies a market", () => {
    expect(normalizeGammaMarketPayload({ id: "123" })).not.toBeNull();
    expect(normalizeGammaMarketPayload([{ conditionId: "0x1" }])).not.toBeNull();
  });
});
