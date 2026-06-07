import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { HomeSnapshotData, SnapshotEnvelope } from "@frw/shared-types";
import { YieldCurvesPage } from "./YieldCurvesPage";
import "../i18n/config";

vi.mock("../lib/locale", () => ({
  useLocale: () => "en"
}));

const homeSnapshot: SnapshotEnvelope<HomeSnapshotData> = {
  schema_version: "1",
  snapshot_version: 1,
  object_key: "home",
  object_type: "home",
  content_hash: "test-home",
  locale: "en",
  generated_at: "2026-06-07T00:00:00Z",
  stale_after: "2099-01-01T00:00:00Z",
  hard_expires_at: "2099-01-02T00:00:00Z",
  source_policy_versions: [],
  warnings: [],
  corrections: [],
  data: {
    headline: "Snapshot",
    summary: "Snapshot",
    generated_label: "2026-06-07T00:00:00Z",
    snapshot_health: {
      status: "fresh",
      age_minutes: 1,
      stale_after: "2099-01-01T00:00:00Z",
      backend_dependency: "none_for_public_pages"
    },
    top_events: [],
    macro_tiles: [
      yieldTile("us_2y", "US Treasury 2Y", "4.10", "2026-06-05"),
      yieldTile("us_3y", "US Treasury 3Y", "4.16", "2026-06-05"),
      yieldTile("us_5y", "US Treasury 5Y", "4.25", "2026-06-05"),
      yieldTile("us_10y", "US Treasury 10Y", "4.60", "2026-06-05"),
      yieldTile("japan_2y", "Japan govt 2Y", "0.70", "2026-06-05"),
      yieldTile("japan_5y", "Japan govt 5Y", "1.18", "2026-06-05"),
      yieldTile("japan_10y", "Japan govt 10Y", "1.56", "2026-06-05")
    ],
    alternative_signals: [],
    sector_tiles: [],
    calendar_preview: [],
    scenario_baskets: []
  }
};

vi.mock("../lib/snapshots", () => ({
  snapshotQueries: {
    home: () => Promise.resolve(homeSnapshot)
  },
  snapshotFreshness: () => "active"
}));

describe("YieldCurvesPage", () => {
  it("renders source-backed US and Japan yield curves with spreads", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <YieldCurvesPage />
      </QueryClientProvider>
    );

    expect(await screen.findByText("Government Yield Curves")).toBeInTheDocument();
    expect(screen.getByText("US Treasury")).toBeInTheDocument();
    expect(screen.getByText("Japan Government Bonds")).toBeInTheDocument();
    expect(screen.getByText("US 10Y-2Y")).toBeInTheDocument();
    expect(screen.getByText("50 bp")).toBeInTheDocument();
    expect(screen.getByText("Japan 10Y-2Y")).toBeInTheDocument();
    expect(screen.getByText("86 bp")).toBeInTheDocument();
  });
});

function yieldTile(key: string, label: string, value: string, updatedAt: string) {
  return {
    key,
    label,
    value,
    unit: "%",
    source: "Official public rate source",
    source_url: "https://home.treasury.gov/",
    freshness: "fresh" as const,
    delay_label: `actual through ${updatedAt}`,
    updated_at: `${updatedAt}T20:00:00Z`,
    points: [
      { date: "2026-06-04", value: Number(value) - 0.05 },
      { date: updatedAt, value: Number(value) }
    ]
  };
}
