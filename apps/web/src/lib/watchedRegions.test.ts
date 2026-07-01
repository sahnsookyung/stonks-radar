import { describe, expect, it } from "vitest";
import { WATCHED_REGIONS, naturalEarthNamesForCoverage, navVisibleRegions } from "./watchedRegions";

describe("watched region registry helpers", () => {
  it("returns only navigation-visible regions from the shared registry", () => {
    const regions = navVisibleRegions();

    expect(regions.length).toBeGreaterThan(0);
    expect(regions.every((region) => region.nav_visible)).toBe(true);
    expect(regions.map((region) => region.key)).toContain("USA");
  });

  it("resolves map names from coverage payloads with configured fallback and dedupe", () => {
    const usa = WATCHED_REGIONS.find((region) => region.key === "USA");
    const japan = WATCHED_REGIONS.find((region) => region.key === "JPN");

    expect(usa?.natural_earth_names.length).toBeGreaterThan(0);
    expect(japan?.natural_earth_names.length).toBeGreaterThan(0);

    const names = naturalEarthNamesForCoverage([
      {
        key: "USA",
        type: "country",
        label: "United States",
        iso3: "USA",
        groups: ["top_gdp"],
        priority: 100,
        gdp_rank: 1,
        gather_news: true,
        render_on_map: true,
        nav_visible: true,
        coverage_status: "active",
        natural_earth_names: ["United States of America", "United States of America"],
        event_count: 2,
        map_point_count: 2,
        coverage_window_days: 7,
        newest_source_published_at: "2026-07-01T00:00:00Z",
        quiet_reason: null
      },
      {
        key: "JPN",
        type: "country",
        label: "Japan",
        iso3: "JPN",
        groups: ["top_gdp"],
        priority: 90,
        gdp_rank: 4,
        gather_news: true,
        render_on_map: true,
        nav_visible: true,
        coverage_status: "quiet",
        natural_earth_names: [],
        event_count: 0,
        map_point_count: 0,
        coverage_window_days: 7,
        newest_source_published_at: null,
        quiet_reason: "no_recent_events"
      },
      {
        key: "CAN",
        type: "country",
        label: "Canada",
        iso3: "CAN",
        natural_earth_names: ["Canada"],
        groups: ["top_gdp"],
        priority: 80,
        gdp_rank: 10,
        gather_news: true,
        render_on_map: false,
        nav_visible: true,
        coverage_status: "coverage_gap",
        event_count: 0,
        map_point_count: 0,
        coverage_window_days: 7,
        newest_source_published_at: null,
        quiet_reason: "provider_gap"
      }
    ]);

    expect(names).toContain("United States of America");
    expect(names).toEqual(expect.arrayContaining(japan?.natural_earth_names ?? []));
    expect(names.filter((name) => name === "United States of America")).toHaveLength(1);
  });

  it("handles missing coverage data as an empty map-name list", () => {
    expect(naturalEarthNamesForCoverage(undefined)).toEqual([]);
  });
});
