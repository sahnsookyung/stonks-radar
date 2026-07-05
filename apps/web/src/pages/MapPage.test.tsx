import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  BreakingMarketEvent,
  MapEventsData,
  NewsMapPoint,
  PublicEvent,
  Severity,
  SnapshotEnvelope,
  WatchedRegionCoverage
} from "@frw/shared-types";
import { MapPage } from "./MapPage";
import "../i18n/config";

vi.mock("../lib/locale", () => ({
  useLocale: () => "en"
}));

vi.mock("../components/EventMap", () => ({
  EventMap: ({
    events,
    mapPoints,
    selectedMapPointId,
    onMapPointSelect
  }: {
    events: PublicEvent[];
    mapPoints: NewsMapPoint[];
    selectedMapPointId?: string | null;
    onMapPointSelect?: (id: string) => void;
  }) => (
    <div
      data-testid="event-map"
      data-events={events.length}
      data-map-points={mapPoints.length}
      data-selected={selectedMapPointId ?? ""}
      data-first-trust={(mapPoints[0] as NewsMapPoint & { trust_tier?: string } | undefined)?.trust_tier ?? ""}
    >
      mapPoints:{mapPoints.length} events:{events.length}
      {mapPoints[0] ? <button onClick={() => onMapPointSelect?.(mapPoints[0].event_id)}>select map point</button> : null}
    </div>
  )
}));

vi.mock("../components/EventList", () => ({
  EventList: ({
    events,
    selectedEventId,
    onEventSelect
  }: {
    events: PublicEvent[];
    selectedEventId?: string | null;
    onEventSelect?: (id: string) => void;
  }) => (
    <div data-testid="event-list" data-events={events.length} data-selected={selectedEventId ?? ""}>
      events:{events.length}
      {events.map((event) => (
        <button key={event.id} onClick={() => onEventSelect?.(event.id)}>
          focus {event.id}
        </button>
      ))}
    </div>
  )
}));

const mapSnapshot: SnapshotEnvelope<MapEventsData> = {
  schema_version: "1",
  snapshot_version: 1,
  object_key: "map_events",
  object_type: "map_events",
  content_hash: "test-map",
  locale: "en",
  generated_at: "2026-07-04T12:00:00Z",
  stale_after: "2099-01-01T00:00:00Z",
  hard_expires_at: "2099-01-02T00:00:00Z",
  source_policy_versions: [],
  warnings: [],
  corrections: [],
  data: {
    events: [
      publicEvent("news-recent-verified", "Recent public event", "high", ["technology"], "2026-07-04T10:00:00Z"),
      publicEvent("public-previous-window", "Previous public event", "high", ["technology"], "2026-07-03T10:00:00Z"),
      publicEvent("public-old", "Older public event", "medium", ["space"], "2026-07-01T10:00:00Z")
    ],
    breaking_market_events: [
      breakingEvent("news-recent-verified", "high", "2026-07-04T11:00:00Z", "T2_REPUTABLE_MEDIA"),
      breakingEvent("news-recent-single", "medium", "2026-07-04T09:00:00Z", "T4_WEAK_SIGNAL"),
      breakingEvent("news-previous-window", "high", "2026-07-03T10:00:00Z", "T2_REPUTABLE_MEDIA"),
      breakingEvent("news-old-verified", "high", "2026-07-01T10:00:00Z", "T1_REGULATED_FILING")
    ],
    breaking_market_map: {
      events: [
        breakingEvent("news-recent-verified", "high", "2026-07-04T11:00:00Z", "T2_REPUTABLE_MEDIA"),
        breakingEvent("news-recent-single", "medium", "2026-07-04T09:00:00Z", "T4_WEAK_SIGNAL"),
        breakingEvent("news-previous-window", "high", "2026-07-03T10:00:00Z", "T2_REPUTABLE_MEDIA"),
        breakingEvent("news-old-verified", "high", "2026-07-01T10:00:00Z", "T1_REGULATED_FILING")
      ],
      map_points: [
        mapPoint("point-recent-verified", "news-recent-verified", "high", "usa", "2026-07-04T11:00:00Z", 2, [
          "source_velocity"
        ]),
        mapPoint("point-recent-single", "news-recent-single", "medium", "usa", "2026-07-04T09:00:00Z", 1),
        mapPoint("point-previous-window", "news-previous-window", "high", "usa", "2026-07-03T10:00:00Z", 2),
        mapPoint("point-old-verified", "news-old-verified", "high", "shipping", "2026-07-01T10:00:00Z", 3)
      ],
      watched_regions: [
        watchedRegion("usa", "United States", true),
        watchedRegion("shipping", "Shipping lanes", false)
      ],
      coverage_gaps: [
        {
          region_key: "shipping",
          label: "Shipping lanes",
          reason: "no_recent_evidence",
          coverage_window_days: 7,
          newest_source_published_at: null
        }
      ],
      regional_briefs: [],
      shown_count: 4,
      total_count: 4,
      ranking_cutoff: null,
      registry_version: 1,
      scoring_version: "test",
      thinning_version: "test",
      generated_at: "2026-07-04T12:00:00Z"
    },
    filters: {
      countries_regions: ["usa", "shipping"],
      sectors: ["technology", "space"],
      severities: ["low", "medium", "high", "critical"],
      event_types: []
    }
  }
};

vi.mock("../lib/snapshots", () => ({
  snapshotQueries: {
    map: () => Promise.resolve(mapSnapshot)
  },
  snapshotFreshness: () => "active"
}));

describe("MapPage", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    Object.defineProperty(globalThis.window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => store.get(key) ?? null),
        setItem: vi.fn((key: string, value: string) => store.set(key, value)),
        clear: vi.fn(() => store.clear())
      }
    });
  });

  afterEach(() => {
    cleanup();
    globalThis.window.localStorage.clear();
    globalThis.window.history.replaceState(null, "", "/en/map");
    vi.restoreAllMocks();
  });

  it("filters map news with UTC range, source count, watched-region controls, and reset", async () => {
    globalThis.window.history.replaceState(null, "", "/en/map");
    renderMapPage();

    expect(await screen.findByText("Global Intelligence Map")).toBeInTheDocument();
    expect(screen.getByTestId("event-map")).toHaveAttribute("data-map-points", "4");
    expect(screen.getByTestId("event-map")).toHaveAttribute("data-events", "0");
    expect(screen.getByTestId("event-map")).toHaveAttribute("data-first-trust", "T2_REPUTABLE_MEDIA");
    expect(screen.getByTestId("event-list")).toHaveAttribute("data-events", "3");
    expect(screen.getByText("1 coverage gaps")).toBeInTheDocument();
    expect(screen.getByText("Source drilldown")).toBeInTheDocument();
    expect(screen.getByText("Trust T2_REPUTABLE_MEDIA")).toBeInTheDocument();
    expect(screen.getByText("source velocity")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Time"), { target: { value: "24h" } });
    await waitFor(() => expect(screen.getByTestId("event-map")).toHaveAttribute("data-map-points", "2"));
    expect(screen.getByTestId("event-list")).toHaveAttribute("data-events", "1");
    expect(screen.getByText("Current 2 pts / 1 events")).toBeInTheDocument();
    expect(screen.getByText("Previous 1 pts / 1 events")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Sources"), { target: { value: "2" } });
    await waitFor(() => expect(screen.getByTestId("event-map")).toHaveAttribute("data-map-points", "1"));
    fireEvent.click(screen.getByRole("button", { name: "Save map view" }));
    expect(screen.getByText(/Last 24h UTC \/ 2\+ sources/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Watched regions"));
    await waitFor(() => expect(screen.getByTestId("event-map")).toHaveAttribute("data-map-points", "1"));

    fireEvent.click(screen.getByRole("button", { name: "select map point" }));
    await waitFor(() => expect(screen.getByTestId("event-map")).toHaveAttribute("data-selected", "news-recent-verified"));
    expect(screen.getByTestId("event-list")).toHaveAttribute("data-selected", "news-recent-verified");

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(screen.getByTestId("event-map")).toHaveAttribute("data-map-points", "4"));
    expect(screen.getByTestId("event-list")).toHaveAttribute("data-events", "3");
    expect(globalThis.window.location.search).toBe("");
    fireEvent.click(screen.getByText(/Last 24h UTC \/ 2\+ sources/));
    await waitFor(() => expect(screen.getByTestId("event-map")).toHaveAttribute("data-map-points", "1"));
    fireEvent.click(screen.getByRole("button", { name: /Remove Last 24h UTC \/ 2\+ sources/ }));
    expect(screen.queryByText(/Last 24h UTC \/ 2\+ sources/)).not.toBeInTheDocument();
  });

  it("hydrates controls from shareable URL params and removes invalid values", async () => {
    globalThis.window.history.replaceState(
      null,
      "",
      "/en/map?severity=high&time=24h&sources=2&watched=1"
    );
    renderMapPage();

    expect(await screen.findByText("Global Intelligence Map")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("event-map")).toHaveAttribute("data-map-points", "1"));
    expect(screen.getByTestId("event-list")).toHaveAttribute("data-events", "1");
    expect(globalThis.window.location.search).toContain("severity=high");
    expect(globalThis.window.location.search).toContain("time=24h");
    expect(globalThis.window.location.search).toContain("sources=2");
    expect(globalThis.window.location.search).toContain("watched=1");

    fireEvent.change(screen.getByLabelText("Time"), { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText("Start UTC"), { target: { value: "2026-07-05T00:00" } });
    await waitFor(() => expect(screen.getByText("No matches in this custom UTC range")).toBeInTheDocument());
    expect(globalThis.window.location.search).toContain("time=custom");
    expect(globalThis.window.location.search).toContain("from=2026-07-05T00%3A00");
  });

  it("falls back to all controls when URL params are invalid", async () => {
    globalThis.window.history.replaceState(
      null,
      "",
      "/en/map?severity=bad&sector=bad%20sector&time=forever&from=nope&sources=4&watched=no"
    );
    renderMapPage();

    expect(await screen.findByText("Global Intelligence Map")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("event-map")).toHaveAttribute("data-map-points", "4"));
    expect(screen.getByTestId("event-list")).toHaveAttribute("data-events", "3");
    await waitFor(() => expect(globalThis.window.location.search).toBe(""));
  });
});

function renderMapPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false
      }
    }
  });
  render(
    <QueryClientProvider client={client}>
      <MapPage />
    </QueryClientProvider>
  );
}

function publicEvent(
  id: string,
  title: string,
  severity: Severity,
  sectorKeys: string[],
  publishedAt: string
): PublicEvent {
  return {
    id,
    title,
    summary: `${title} summary`,
    why_it_matters: `${title} matters`,
    occurred_at: publishedAt,
    published_at: publishedAt,
    country_region_keys: [],
    sector_keys: sectorKeys,
    event_type: "market_news",
    severity,
    confidence: 0.9,
    source_strength: "source-linked",
    freshness: "fresh",
    evidence_count: 1,
    latitude: 37.77,
    longitude: -122.42,
    affected_objects: [],
    source_links: [],
    correction_status: "none"
  };
}

function mapPoint(
  pointId: string,
  eventId: string,
  severity: Severity,
  areaKey: string,
  sourcePublishedAt: string,
  sourceCount: number,
  reasonCodes: string[] = []
): NewsMapPoint {
  return {
    point_id: pointId,
    event_id: eventId,
    event_ids: [eventId],
    title: `${eventId} title`,
    summary: `${eventId} summary`,
    area_id: areaKey,
    area_key: areaKey,
    area_label: areaKey,
    relation: "event_location",
    latitude: 37.77,
    longitude: -122.42,
    severity,
    urgency_score: 80,
    source_published_at: sourcePublishedAt,
    observed_at: sourcePublishedAt,
    source_url: "https://example.com/news",
    source_count: sourceCount,
    geo_confidence: 0.9,
    area_priority: 1,
    score_reason_codes: reasonCodes
  };
}

function breakingEvent(
  eventId: string,
  severity: Severity,
  sourcePublishedAt: string,
  trustTier: BreakingMarketEvent["trust_tier"]
): BreakingMarketEvent {
  return {
    event_id: eventId,
    title: `${eventId} title`,
    summary: `${eventId} summary`,
    source_url: "https://example.com/news",
    source_published_at: sourcePublishedAt,
    observed_at: sourcePublishedAt,
    verified_at: sourcePublishedAt,
    freshness_confidence: 0.9,
    urgency_score: 80,
    severity,
    trust_tier: trustTier,
    discovery_only: false,
    review_state: "published",
    citation_ids: [],
    retention_class: "metadata_only",
    geo_points: [],
    geo_confidence: 0.95,
    score_reason_codes: ["event_score"],
    dedupe_key: eventId,
    label: "breaking",
    tickers: [],
    regions: [],
    topics: [],
    source_count: 2
  };
}

function watchedRegion(key: string, label: string, renderOnMap: boolean): WatchedRegionCoverage {
  return {
    key,
    type: "country",
    label,
    iso3: key.toUpperCase().slice(0, 3),
    natural_earth_names: [label],
    groups: [],
    priority: 1,
    gdp_rank: null,
    gather_news: true,
    render_on_map: renderOnMap,
    nav_visible: true,
    coverage_status: "active",
    coverage_window_days: 7,
    event_count: 1,
    map_point_count: 1,
    newest_source_published_at: "2026-07-04T11:00:00Z",
    quiet_reason: null
  };
}
