import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { MetricTile } from "@frw/shared-types";
import { MarketPulseBoard } from "./MarketPulse";
import "../i18n/config";

vi.mock("../lib/locale", () => ({
  useLocale: () => "en",
}));

describe("MarketPulseBoard", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows missed refresh targets and refresh deltas", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-27T12:00:00Z"));
    const tiles: MetricTile[] = [
      {
        key: "nasdaq_composite",
        label: "Nasdaq Composite",
        value: "110",
        source: "FRED / Nasdaq",
        source_url: "https://fred.stlouisfed.org/series/NASDAQCOM",
        freshness: "watch",
        delay_label: "Using last published value; current refresh unavailable",
        updated_at: "2026-05-27T10:00:00Z",
        coverage_status: "active",
        refresh_seconds: 900,
        refresh_delta: 10,
        points: [
          { date: "2026-05-26", value: 100 },
          { date: "2026-05-27", value: 110 },
        ],
      },
    ];

    render(<MarketPulseBoard tiles={tiles} />);

    const card = screen.getByRole("link", { name: "Nasdaq Composite source" });
    expect(within(card).getByText("2h ago")).toBeInTheDocument();
    expect(within(card).getByText("every 15m")).toBeInTheDocument();
    expect(within(card).getByText("target missed")).toBeInTheDocument();
    expect(within(card).getByText("10")).toBeInTheDocument();
  });

  it("labels delayed quote observations as last market close instead of a failed refresh", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-31T08:30:00Z"));
    const tiles: MetricTile[] = [
      {
        key: "vix",
        label: "VIX",
        value: "15.32",
        source: "Yahoo Finance delayed quote",
        source_url:
          "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=1d&interval=1m",
        freshness: "stale",
        delay_label:
          "Latest available Yahoo Finance delayed quote observed at 2026-05-29T20:15:01Z; market may be closed.",
        updated_at: "2026-05-29T20:15:01Z",
        coverage_status: "active",
        refresh_seconds: 43200,
        refresh_delta: -0.42,
        points: [
          { date: "2026-05-29T20:14:00Z", value: 15.74 },
          { date: "2026-05-29T20:15:01Z", value: 15.32 },
        ],
      },
    ];

    render(<MarketPulseBoard tiles={tiles} />);

    const card = screen.getByRole("link", { name: "VIX source" });
    expect(within(card).getByText("last close 36h ago")).toBeInTheDocument();
    expect(
      within(card).getByText("public delayed / market close"),
    ).toBeInTheDocument();
    expect(within(card).queryByText("target missed")).not.toBeInTheDocument();
  });
});
