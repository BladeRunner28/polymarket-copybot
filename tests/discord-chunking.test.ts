/**
 * Discord chunking (2026-11-15, found while shipping `research-source-silent-death`).
 *
 * The defect: `sendDiscord` posted `content.slice(0, 1990)` and returned true, so
 * every EOD report longer than one message was half delivered while reporting
 * success. Measured stored summaries: 3,971 / 4,041 / 3,644 chars — chars
 * 1,990→end (rule changes, instrument heartbeat, selection caveat, the new
 * research alarm) never left the host. What is pinned here is the property that
 * would have caught it: EVERY line of the input is delivered exactly once.
 */

import { describe, it, expect } from "vitest";
import { chunkForDiscord, DISCORD_CONTENT_LIMIT } from "../src/lib/discord";

/** Strips the "(i/n) " ordering tag a multi-message send puts in front of each chunk. */
const untag = (c: string) => c.replace(/^\(\d+\/\d+\) /, "");

function reportLike(chars: number): string {
  const lines: string[] = [];
  let n = 0;
  let i = 0;
  while (n < chars) {
    const line = `• line ${i++} ` + "x".repeat(40 + (i % 7) * 10);
    lines.push(line);
    n += line.length + 1;
  }
  return lines.join("\n");
}

describe("chunkForDiscord", () => {
  it("leaves a short report as ONE untagged chunk (no behaviour change)", () => {
    const content = "**Report**\n• a\n• b";
    expect(chunkForDiscord(content)).toEqual([content]);
  });

  it("splits a 4,675-char report into ordered chunks that all fit Discord", () => {
    const content = reportLike(4_675);
    const chunks = chunkForDiscord(content);
    expect(chunks.length).toBeGreaterThan(1);
    for (const c of chunks) expect(c.length).toBeLessThanOrEqual(DISCORD_CONTENT_LIMIT);
    // order tags are sequential
    expect(chunks[0].startsWith(`(1/${chunks.length}) `)).toBe(true);
    expect(chunks[chunks.length - 1].startsWith(`(${chunks.length}/${chunks.length}) `)).toBe(true);
  });

  it("delivers EVERY line exactly once — the property the old slice violated", () => {
    const content = reportLike(4_675);
    const joined = chunkForDiscord(content).map(untag).join("\n");
    expect(joined).toBe(content);
  });

  it("never starts a chunk in the middle of a line when it can avoid it", () => {
    const content = reportLike(3_000);
    const chunks = chunkForDiscord(content).map(untag);
    const firstLines = chunks.map((c) => c.split("\n")[0]);
    // each chunk boundary is a real line of the input
    for (const l of firstLines) expect(content.split("\n")).toContain(l);
  });

  it("hard-splits a single line longer than one message rather than dropping it", () => {
    const content = "x".repeat(5_000);
    const chunks = chunkForDiscord(content);
    expect(chunks.length).toBeGreaterThan(1);
    for (const c of chunks) expect(c.length).toBeLessThanOrEqual(DISCORD_CONTENT_LIMIT);
    expect(chunks.map(untag).join("")).toBe(content);
  });

  it("returns no chunks for empty content, so the caller cannot post a blank message", () => {
    expect(chunkForDiscord("")).toEqual([]);
  });

  it("keeps the research-source alarm line intact inside a chunk", () => {
    const alarm =
      "• ⚠️ Research sources — 3/4 NOT SUPPLYING (RegulatorySignal, clock=processedAt UTC, level=source): " +
      "quiver_congress_trade: SILENT 1683.3h (70.1d) since 2026-09-06T22:46:13.968Z — policy 24h (4× its 6h cadence)";
    const content = `${reportLike(2_000)}\n${alarm}\n${reportLike(1_500)}`;
    const joined = chunkForDiscord(content).map(untag).join("\n");
    expect(joined).toContain(alarm);
  });
});
