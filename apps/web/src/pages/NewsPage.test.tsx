import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  NewsIndexSnapshotData,
  SnapshotEnvelope,
} from "@frw/shared-types";
import { NewsPage } from "./NewsPage";
import "../i18n/config";

vi.mock("../lib/locale", () => ({
  useLocale: () => "en",
}));

const unavailableSnapshot: SnapshotEnvelope<NewsIndexSnapshotData> = {
  schema_version: "1",
  snapshot_version: 8,
  object_key: "news_index",
  object_type: "news_index",
  content_hash: "test-news-unavailable",
  locale: "en",
  generated_at: "2026-07-15T02:36:00Z",
  stale_after: "2099-01-01T00:00:00Z",
  hard_expires_at: "2099-01-02T00:00:00Z",
  source_policy_versions: [],
  warnings: [
    {
      code: "live_data_unavailable",
      message: "No current source-backed data is available for this view.",
      severity: "warning",
    },
  ],
  corrections: [],
  data: {
    generated_label: "2026-07-15T02:36:00Z",
    filters: { regions: [], topics: [], tickers: [], trust_tiers: [] },
    events: [],
  },
};

vi.mock("../lib/snapshots", () => ({
  snapshotQueries: {
    newsIndex: () => Promise.resolve(unavailableSnapshot),
  },
  snapshotFreshness: () => "active",
}));

describe("NewsPage", () => {
  it("distinguishes a live-data outage from an empty filter result", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <NewsPage />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText(
        "Current source-backed news is unavailable. Static example news is not displayed.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No source-linked items match the selected filters."),
    ).not.toBeInTheDocument();
  });
});
