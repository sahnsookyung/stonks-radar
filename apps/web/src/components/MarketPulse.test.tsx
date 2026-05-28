import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { MetricTile } from "@frw/shared-types";
import { MarketPulseBoard } from "./MarketPulse";
import "../i18n/config";

vi.mock("../lib/locale", () => ({
  useLocale: () => "en"
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
          { date: "2026-05-27", value: 110 }
        ]
      }
    ];

    render(<MarketPulseBoard tiles={tiles} />);

    const card = screen.getByRole("link", { name: "Nasdaq Composite source" });
    expect(within(card).getByText("2h ago")).toBeInTheDocument();
    expect(within(card).getByText("every 15m")).toBeInTheDocument();
    expect(within(card).getByText("target missed")).toBeInTheDocument();
    expect(within(card).getByText("10")).toBeInTheDocument();
  });
});
