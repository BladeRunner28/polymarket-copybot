import { describe, expect, it } from "vitest";
import {
  buildCapitalSeries,
  bookedAtMs,
  dayKeyToMs,
  dayWindowKeys,
  depositScale,
  localDayKey,
  positiveStreak,
  topDays,
  type CapitalLedgerEntry,
  type FinishedTradeRow,
} from "../src/lib/capital";

/** Local-midnight epoch ms for a local day (keeps the test TZ-independent). */
function localMs(day: string, hour = 12): number {
  return dayKeyToMs(day) + hour * 3_600_000;
}
function row(day: string, pnl: number, kind: "closed" | "resolved" = "resolved", hour = 12): FinishedTradeRow {
  const ms = localMs(day, hour);
  return kind === "closed"
    ? { closedAt: ms, resolvedAt: null, realizedPnl: pnl }
    : { closedAt: null, resolvedAt: ms, realizedPnl: pnl };
}

const OPENING: CapitalLedgerEntry = { date: "2026-07-22", amountUsd: 1900, kind: "opening" };

describe("capital day helpers", () => {
  it("keys days on the LOCAL calendar, across a month boundary", () => {
    expect(localDayKey(localMs("2026-08-31"))).toBe("2026-08-31");
    expect(localDayKey(localMs("2026-09-01"))).toBe("2026-09-01");
    const keys = dayWindowKeys(dayKeyToMs("2026-09-02") + 3_600_000, 4);
    expect(keys).toEqual(["2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02"]);
  });

  it("books an early exit at closedAt and a settlement at resolvedAt", () => {
    expect(bookedAtMs(row("2026-09-10", 5, "closed"))).toBe(localMs("2026-09-10"));
    expect(bookedAtMs(row("2026-09-10", 5, "resolved"))).toBe(localMs("2026-09-10"));
    expect(bookedAtMs({ closedAt: null, resolvedAt: null, realizedPnl: 0 })).toBeNull();
  });

  it("rejects a malformed day key instead of silently rolling over", () => {
    expect(() => dayKeyToMs("2026-9-1")).toThrow();
    expect(() => dayWindowKeys(Date.now(), 0)).toThrow();
  });
});

describe("buildCapitalSeries", () => {
  const rows: FinishedTradeRow[] = [
    row("2026-09-10", 100),
    row("2026-09-10", -30, "closed"),
    row("2026-09-11", -50),
    row("2026-09-12", 25),
    row("2026-09-01", 999), // before the emitted window
  ];

  it("adds booked PnL per local day and carries the closing capital forward", () => {
    const s = buildCapitalSeries({ principal: 1900, rows, ledger: [OPENING], days: 3, todayMs: localMs("2026-09-12") });
    expect(s.points.map((p) => p.day)).toEqual(["2026-09-10", "2026-09-11", "2026-09-12"]);
    expect(s.points.map((p) => p.booked)).toEqual([70, -50, 25]);
    expect(s.points.map((p) => p.trades)).toEqual([2, 1, 1]);
    // opening = seed + everything booked before the window (the +999 on 09-01)
    expect(s.openingUsd).toBe(2899);
    expect(s.points.map((p) => p.closing)).toEqual([2969, 2919, 2944]);
    expect(s.closingUsd).toBe(2944);
    expect(s.bookedTotal).toBe(45);
    expect(s.seededOn).toBe("2026-07-22");
  });

  it("treats a ledger deposit as a daily deposit bar and moves the closing level", () => {
    const ledger: CapitalLedgerEntry[] = [OPENING, { date: "2026-09-11", amountUsd: 500, kind: "deposit" }];
    const s = buildCapitalSeries({ principal: 2400, rows, ledger, days: 3, todayMs: localMs("2026-09-12") });
    expect(s.points[1].injected).toBe(500);
    expect(s.points[1].deposit).toBe(450); // −50 booked + 500 injected
    expect(s.injectedTotal).toBe(500);
    expect(s.ledgerGapUsd).toBe(0); // principal 2400 = seed 1900 + 500
  });

  it("flags a principal the ledger does not explain", () => {
    const s = buildCapitalSeries({ principal: 2400, rows, ledger: [OPENING], days: 2, todayMs: localMs("2026-09-11") });
    expect(s.ledgerGapUsd).toBe(500);
    expect(s.warnings.join(" ")).toContain("not explained by the ledger");
  });

  it("warns when there is no opening entry and seeds from the principal", () => {
    const s = buildCapitalSeries({ principal: 1900, rows: [], ledger: [], days: 2, todayMs: localMs("2026-09-11") });
    expect(s.seedUsd).toBe(1900);
    expect(s.warnings.join(" ")).toContain("no `opening` entry");
  });

  it("never emits a day twice and keeps days contiguous and ordered", () => {
    const s = buildCapitalSeries({ principal: 1900, rows, ledger: [OPENING], days: 40, todayMs: localMs("2026-09-12") });
    const days = s.points.map((p) => p.day);
    expect(new Set(days).size).toBe(days.length);
    for (let i = 1; i < days.length; i++) {
      expect(dayKeyToMs(days[i]) - dayKeyToMs(days[i - 1])).toBe(86_400_000);
    }
    expect(days[days.length - 1]).toBe("2026-09-12");
  });
});

describe("depositScale", () => {
  const mk = (deposits: number[], injected: number[] = []) =>
    deposits.map((d, i) => ({
      day: `2026-09-${String(i + 1).padStart(2, "0")}`,
      booked: d - (injected[i] ?? 0),
      injected: injected[i] ?? 0,
      deposit: d,
      closing: 0,
      trades: 1,
    }));

  it("uses the real maximum when no day is an outlier", () => {
    const s = depositScale(mk([10, -5, 20, 15, -12]));
    expect(s.isClipped).toBe(false);
    expect(s.axisMax).toBe(20);
    expect(s.clipped).toEqual([]);
  });

  it("clips a single dominating day instead of flattening the rest", () => {
    const pts = mk([5, -8, 12, 20, 993.7]);
    const s = depositScale(pts);
    expect(s.isClipped).toBe(true);
    // Tukey fence Q3 + 1.5*IQR on [5,8,12,20,993.7] = 20 + 1.5*(20-8) = 38
    expect(s.axisMax).toBe(38);
    expect(s.clipped.map((c) => c.day)).toEqual(["2026-09-05"]);
    expect(s.clipped[0].deposit).toBe(993.7);
  });

  it("keeps the axis equal to the max when the outlier is not material", () => {
    // fence = 50 + 1.5*30 = 95; max 100 is inside 1.5x the fence -> no clip
    const s = depositScale(mk([10, 20, 30, 50, 100]));
    expect(s.isClipped).toBe(false);
    expect(s.axisMax).toBe(100);
    expect(s.clipped).toEqual([]);
  });

  it("clips only the two real outliers of the September window", () => {
    // the measured Sep 2026 window magnitudes: a $993.7 and $743.4 day on a base of $5-277
    const m = [993.7, 743.4, 276.9, 272.8, 229.5, 206.8, 136.6, 119.5, 116.4, 107.5, 99.7, 70.4, 58.9, 38, 29.9, 28.8, 27.8, 22.5, 20.4, 18.9, 18, 15.2, 12.4, 10.1, 7.4, 6.1, 5.5];
    const s = depositScale(mk(m));
    expect(s.isClipped).toBe(true);
    expect(s.axisMax).toBeGreaterThan(250);
    expect(s.axisMax).toBeLessThan(300);
    expect(s.clipped.map((c) => c.deposit).sort((a, b) => b - a)).toEqual([993.7, 743.4]);
    // an ordinary $20 day is now ~11px tall in the 164px panel instead of 2px
    const px = (20 / s.axisMax) * 164;
    expect(px).toBeGreaterThan(9);
  });

  it("degrades safely on an all-zero window", () => {
    const s = depositScale(mk([0, 0, 0]));
    expect(s.axisMax).toBe(1);
    expect(s.isClipped).toBe(false);
  });
});

describe("report helpers", () => {
  const pts = [3, -1, 5, 2, -4].map((d, i) => ({
    day: `2026-09-0${i + 1}`,
    booked: d,
    injected: 0,
    deposit: d,
    closing: 0,
    trades: 1,
  }));

  it("ranks days by absolute deposit", () => {
    expect(topDays(pts, 2).map((p) => p.deposit)).toEqual([5, -4]);
  });

  it("measures the positive-deposit streak from the end", () => {
    expect(positiveStreak(pts)).toEqual({ current: 0, best: 2 });
    expect(positiveStreak(pts.slice(0, 4))).toEqual({ current: 2, best: 2 });
  });
});
