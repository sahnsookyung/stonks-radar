import { afterEach, describe, expect, it, vi } from "vitest";
import { buildFreshnessMeta, computeIndicatorSet, normalizePoints, tickerDateRange } from "./tickerDetailModel";
import type { MarketHistoryResponse, MarketPoint } from "./tickerDetailModel";

describe("ticker detail model", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("normalizes market points and computes indicator summary values", () => {
    const points = Array.from({ length: 60 }, (_, index): MarketPoint => ({
      date: isoDateFromOffset(index),
      close: 100 + index,
      volume: 1_000_000 + index * 1_000
    })).reverse();

    const normalized = normalizePoints([...points, { date: "2026-01-31", close: Number.NaN }]);
    expect(normalized[0].date).toBe("2026-01-01");
    expect(normalized).toHaveLength(60);

    const indicators = computeIndicatorSet(points);
    expect(indicators.latestClose).toBe(159);
    expect(indicators.previousClose).toBe(158);
    expect(indicators.change).toBe(1);
    expect(indicators.changePct).toBeCloseTo(0.6329, 3);
    expect(indicators.score.total).toBeGreaterThan(0);
    expect(indicators.score.total).toBeLessThanOrEqual(100);
    expect(indicators.macd.histogram).toEqual(expect.any(Number));
  });

  it("builds freshness metadata from explicit backend data freshness", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-05T12:00:00Z"));
    const payload: MarketHistoryResponse = {
      status: "ok",
      provider: "fmp",
      source_note: "stored",
      cache: "persistent_hit",
      symbols: ["AAPL"],
      start: "2026-07-01",
      end: "2026-07-05",
      series: [],
      warnings: [],
      data_freshness: {
        provider: "fmp",
        provider_timestamp: "2026-07-05T10:00:00Z",
        fetched_at: "2026-07-05T10:10:00Z",
        source_observed_at: "2026-07-05T10:00:00Z",
        market_session_date: "2026-07-05",
        exchange_timezone: "America/New_York",
        delay_label: "delayed",
        is_same_day_valid: true,
        is_public_display_allowed: true,
        staleness_reason: "within cache window",
        license_mode: "public"
      }
    };

    expect(buildFreshnessMeta(payload, Date.now())).toMatchObject({
      providerLabel: "provider: fmp",
      delayLabel: "delayed",
      ageLabel: "2h ago",
      sameDayValid: true,
      isPublicDisplayAllowed: true
    });
  });

  it("uses legacy fallback freshness and one-year ticker date ranges", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-05T12:00:00Z"));

    expect(buildFreshnessMeta(undefined, 0, { date: "2026-07-04", close: 10 })).toMatchObject({
      providerLabel: "provider: provider unavailable",
      delayLabel: "daily / previous-session snapshot",
      providerTimestamp: "2026-07-04",
      licenseMode: "legacy"
    });
    expect(tickerDateRange()).toEqual({ start: "2025-07-05", end: "2026-07-05" });
  });
});

function isoDateFromOffset(offsetDays: number) {
  const date = new Date(Date.UTC(2026, 0, 1 + offsetDays));
  return date.toISOString().slice(0, 10);
}
