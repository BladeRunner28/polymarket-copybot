/**
 * Tests for research-source liveness (card `research-source-silent-death`,
 * 2026-11-15, Lane B).
 *
 * What is pinned is the pair of failures the card was written for, because both
 * of them looked healthy on every surface the repo had:
 *   - a feed that STOPPED (quiver_congress_trade: 190 rows, nothing for 70 days)
 *   - a feed that NEVER CONTRIBUTED (govinfo_fr_notice: 1,210 rows, all 0.0)
 * Both must page; a live feed must not. Plus the two ways an alarm can lie: a
 * negative silence from clock skew, and a policy inherited from a default that
 * pretends to be measured.
 */

import { describe, it, expect } from "vitest";
import {
  classifyAll,
  classifySource,
  livenessLine,
  SOURCE_LIVENESS_POLICY,
  DEFAULT_SOURCE_POLICY,
  planPages,
  markPaged,
  type SourceEmission,
} from "../src/lib/source-liveness";

const NOW = new Date("2026-11-16T02:00:00Z");
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3_600_000);

const mk = (over: Partial<SourceEmission> = {}): SourceEmission => ({
  source: "congress_gov_api",
  rows: 1_520,
  opinionatedRows: 1_520,
  windowRows: 20,
  windowOpinionated: 20,
  lastEmitAt: hoursAgo(4.2),
  ...over,
});

describe("classifySource — the live case", () => {
  it("a source emitting on cadence with opinionated rows is OK and does not page", () => {
    const r = classifySource(mk(), NOW);
    expect(r.status).toBe("OK");
    expect(r.pageRequired).toBe(false);
    expect(r.reasons).toEqual([]);
    expect(r.silentHours).toBeCloseTo(4.2, 5);
  });

  it("reports hours since the last emit and echoes the measured policy", () => {
    const r = classifySource(mk({ lastEmitAt: hoursAgo(12) }), NOW);
    expect(r.status).toBe("OK");
    expect(r.policy).toEqual(SOURCE_LIVENESS_POLICY.congress_gov_api);
    expect(r.policyMeasured).toBe(true);
    expect(r.lastEmitAt).toBe("2026-11-15T14:00:00.000Z");
  });
});

describe("classifySource — a source that STOPPED", () => {
  it("flags quiver-shaped silence (70 days) and names the clock it rests on", () => {
    const r = classifySource(
      mk({
        source: "quiver_congress_trade",
        rows: 190,
        opinionatedRows: 190,
        windowRows: 0,
        windowOpinionated: 0,
        lastEmitAt: new Date("2026-09-06T22:46:13Z"),
      }),
      NOW
    );
    expect(r.status).toBe("SILENT");
    expect(r.pageRequired).toBe(true);
    const reason = r.reasons.join();
    expect(reason).toContain("SILENT");
    expect(reason).toContain("70.");
    expect(reason).toContain("2026-09-06T22:46:13.000Z");
    expect(reason).toContain("24h");
  });

  it("treats exactly the policy threshold as OK and one tick past it as SILENT", () => {
    expect(classifySource(mk({ lastEmitAt: hoursAgo(24) }), NOW).status).toBe("OK");
    expect(classifySource(mk({ lastEmitAt: hoursAgo(24.01) }), NOW).status).toBe("SILENT");
  });

  it("a source that never emitted is NEVER_EMITTED, not a quiet zero", () => {
    const r = classifySource(mk({ source: "new_feed", rows: 0, opinionatedRows: 0, windowRows: 0, windowOpinionated: 0, lastEmitAt: null }), NOW);
    expect(r.status).toBe("NEVER_EMITTED");
    expect(r.pageRequired).toBe(true);
    expect(r.reasons[0]).toContain("never emitted");
    expect(r.silentHours).toBeNull();
  });

  it("a null lastEmit with rows present still pages instead of reading as 0h", () => {
    const r = classifySource(mk({ lastEmitAt: null }), NOW);
    expect(r.status).toBe("NEVER_EMITTED");
    expect(r.pageRequired).toBe(true);
    expect(r.silentHours).toBeNull();
  });
});

describe("classifySource — a source that NEVER CONTRIBUTES", () => {
  it("flags govinfo-shaped inertia (1,210 rows, none opinionated) even while emitting", () => {
    const r = classifySource(
      mk({ source: "govinfo_fr_notice", rows: 1_210, opinionatedRows: 0, windowRows: 13, windowOpinionated: 0, lastEmitAt: hoursAgo(4.2) }),
      NOW
    );
    expect(r.status).toBe("INERT");
    expect(r.pageRequired).toBe(true);
    expect(r.reasons.join()).toContain("1,210 rows");
    expect(r.reasons.join()).toContain("0 with |polarity| >= 0.3");
  });

  it("reports SILENT_INERT when a source is both dead and incapable", () => {
    const r = classifySource(
      mk({ source: "reddit_trumpstrades", rows: 1, opinionatedRows: 0, windowRows: 0, windowOpinionated: 0, lastEmitAt: new Date("2026-10-18T21:04:49Z") }),
      NOW
    );
    expect(r.status).toBe("SILENT_INERT");
    expect(r.reasons).toHaveLength(2);
  });

  it("a quiet window on a source that HAS been opinionated is not an alarm", () => {
    const r = classifySource(mk({ windowRows: 3, windowOpinionated: 0 }), NOW);
    expect(r.status).toBe("OK");
    expect(r.pageRequired).toBe(false);
  });
});

describe("policy provenance and clock skew", () => {
  it("labels an unmeasured source as inheriting the default policy", () => {
    const r = classifySource(mk({ source: "brand_new_feed" }), NOW);
    expect(r.policy).toEqual(DEFAULT_SOURCE_POLICY);
    expect(r.policyMeasured).toBe(false);
  });

  it("a last emit in the FUTURE reads 0h, never a negative age that passes silently", () => {
    const r = classifySource(mk({ lastEmitAt: hoursAgo(-6) }), NOW);
    expect(r.silentHours).toBe(0);
    expect(r.status).toBe("OK");
  });
});

describe("classifyAll — alarm ordering", () => {
  it("puts every paging source before the healthy one, worst silence first", () => {
    const out = classifyAll(
      [
        mk(),
        mk({ source: "govinfo_fr_notice", opinionatedRows: 0 }),
        mk({ source: "quiver_congress_trade", lastEmitAt: new Date("2026-09-06T22:46:13Z"), windowRows: 0 }),
      ],
      NOW
    );
    expect(out[0].source).toBe("quiver_congress_trade");
    expect(out[out.length - 1].source).toBe("congress_gov_api");
    expect(out[out.length - 1].pageRequired).toBe(false);
  });
});

describe("livenessLine — the report surface", () => {
  it("names the alarm with its reason instead of printing a healthy total", () => {
    const out = classifyAll(
      [mk(), mk({ source: "quiver_congress_trade", lastEmitAt: new Date("2026-09-06T22:46:13Z"), windowRows: 0 })],
      NOW
    );
    const line = livenessLine(out, NOW);
    expect(line).toContain("NOT SUPPLYING");
    expect(line).toContain("quiver_congress_trade");
    expect(line).toContain("SILENT");
    expect(line).toContain("clock=processedAt UTC");
  });

  it("prints per-source rows/opinionated/age on a clean day, with the basis named", () => {
    const line = livenessLine(classifyAll([mk()], NOW), NOW);
    expect(line).toContain("congress_gov_api ✅");
    expect(line).toContain("20 rows/win");
    expect(line).toContain("level=source");
    expect(line).not.toContain("NOT SUPPLYING");
  });

  it("says NONE readable rather than looking clean when the read returns nothing", () => {
    expect(livenessLine([], NOW)).toContain("NONE readable");
  });
});

describe("planPages — the page is a state machine, not a hope", () => {
  const deadEmission = (over: Partial<SourceEmission> = {}): SourceEmission => ({
    source: "quiver_congress_trade",
    rows: 190,
    opinionatedRows: 190,
    windowRows: 0,
    windowOpinionated: 0,
    lastEmitAt: new Date("2026-09-06T22:46:13Z"),
    ...over,
  });

  it("pages on entry, with no prior state", () => {
    const { pages } = planPages(classifyAll([deadEmission()], NOW), {}, NOW);
    expect(pages).toHaveLength(1);
    expect(pages[0].send).toBe(true);
    expect(pages[0].why).toBe("new alarm");
    expect(pages[0].reason).toContain("SILENT");
  });

  it("suppresses a repeat inside the window and says it was suppressed", () => {
    const readings = classifyAll([deadEmission()], NOW);
    const first = planPages(readings, {}, NOW);
    const paged = markPaged(first.nextState, "quiver_congress_trade", NOW);
    const again = planPages(readings, paged, new Date(NOW.getTime() + 3 * 3_600_000));
    expect(again.pages[0].send).toBe(false);
    expect(again.pages[0].why).toContain("suppressed");
    expect(again.pages[0].why).toContain("3.0h");
  });

  it("re-pages once the window has elapsed", () => {
    const readings = classifyAll([deadEmission()], NOW);
    const paged = markPaged(planPages(readings, {}, NOW).nextState, "quiver_congress_trade", NOW);
    const later = planPages(readings, paged, new Date(NOW.getTime() + 25 * 3_600_000));
    expect(later.pages[0].send).toBe(true);
    expect(later.pages[0].why).toContain("re-page");
  });

  it("pages again immediately when the state CHANGES (SILENT becomes SILENT_INERT)", () => {
    const silent = classifyAll([deadEmission()], NOW);
    const paged = markPaged(planPages(silent, {}, NOW).nextState, "quiver_congress_trade", NOW);
    // Same source, now also incapable of moving a number.
    const both = classifyAll([deadEmission({ opinionatedRows: 0 })], NOW);
    const out = planPages(both, paged, new Date(NOW.getTime() + 60_000));
    expect(out.pages[0].send).toBe(true);
    expect(out.pages[0].why).toContain("state changed");
  });

  it("drops the entry on recovery, so a relapse is a NEW alarm and not a suppressed repeat", () => {
    const paged = markPaged(
      planPages(classifyAll([deadEmission()], NOW), {}, NOW).nextState,
      "quiver_congress_trade",
      NOW
    );
    const ok = { ...deadEmission(), lastEmitAt: hoursAgo(2), windowRows: 3, windowOpinionated: 3 };
    const recovered = planPages(classifyAll([ok], NOW), paged, NOW);
    expect(recovered.pages).toEqual([]);
    expect(recovered.nextState).toEqual({});
    // relapse a minute later
    const relapse = planPages(classifyAll([deadEmission()], NOW), recovered.nextState, new Date(NOW.getTime() + 60_000));
    expect(relapse.pages[0].send).toBe(true);
    expect(relapse.pages[0].why).toBe("new alarm");
  });

  it("never marks a page delivered — only markPaged does", () => {
    const first = planPages(classifyAll([deadEmission()], NOW), {}, NOW);
    expect(first.nextState.quiver_congress_trade.lastPagedAt).toBeNull();
    expect(markPaged(first.nextState, "quiver_congress_trade", NOW).quiver_congress_trade.lastPagedAt).toBe(
      NOW.toISOString()
    );
    // Marking a source that is not in the state is a no-op, not a phantom entry.
    expect(markPaged({}, "ghost", NOW)).toEqual({});
  });
});
