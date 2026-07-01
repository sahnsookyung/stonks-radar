import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SnapshotHardExpiredError,
  getManifest,
  getSnapshot,
  isHardExpired,
  isStale,
  snapshotFreshness,
  snapshotQueries
} from "./snapshots";

const activeEnvelope = {
  schema_version: "1.0.0",
  snapshot_version: 1,
  locale: "en",
  generated_at: "2026-06-04T00:00:00Z",
  stale_after: "2026-06-04T01:00:00Z",
  hard_expires_at: "2026-06-05T00:00:00Z",
  object_type: "home",
  object_key: "home",
  content_hash: "sha256:test",
  source_policy_versions: [{ source_key: "seed", policy_version: 1 }],
  data: {},
  warnings: [],
  corrections: []
};

describe("snapshot freshness helpers", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("classifies active, stale, and hard-expired snapshots", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-04T00:30:00Z"));

    expect(snapshotFreshness(activeEnvelope)).toBe("active");
    expect(snapshotFreshness({ ...activeEnvelope, stale_after: "2026-06-04T00:10:00Z" })).toBe("stale");
    expect(snapshotFreshness({ ...activeEnvelope, hard_expires_at: "2026-06-04T00:10:00Z" })).toBe("expired");
    expect(isStale("2026-06-04T01:00:00Z")).toBe(false);
    expect(isHardExpired("2026-06-04T00:10:00Z")).toBe(true);
  });

  it("rejects hard-expired snapshot payloads before pages render them", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-06T00:00:00Z"));

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/public/latest/manifest.json") {
          return new Response(
            JSON.stringify({
              current_version: 1,
              generated_at: "2026-06-04T00:00:00Z",
              locales: ["en"],
              objects: { home: { en: "public/v1/en/home.json" } }
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        return new Response(JSON.stringify(activeEnvelope), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      })
    );

    await expect(getSnapshot("home", "en")).rejects.toBeInstanceOf(SnapshotHardExpiredError);
  });

  it("loads manifests and active snapshots from manifest object paths", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-04T00:30:00Z"));
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/public/latest/manifest.json") {
        return new Response(
          JSON.stringify({
            current_version: 1,
            generated_at: "2026-06-04T00:00:00Z",
            locales: ["en"],
            objects: { home: { en: "public/v1/en/home.json" } }
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      expect(url).toBe("/public/v1/en/home.json");
      return new Response(JSON.stringify(activeEnvelope), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getManifest()).resolves.toMatchObject({ current_version: 1 });
    await expect(getSnapshot("home", "en")).resolves.toMatchObject({ object_key: "home" });
    expect(fetchMock).toHaveBeenCalledWith("/public/latest/manifest.json", {
      headers: { Accept: "application/json" }
    });
  });

  it("reports missing manifest entries and failed snapshot loads", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-04T00:30:00Z"));
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/public/latest/manifest.json") {
          return new Response(
            JSON.stringify({
              current_version: 1,
              generated_at: "2026-06-04T00:00:00Z",
              locales: ["en"],
              objects: { status: { en: "public/v1/en/status.json" } }
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        return new Response("missing", { status: 404 });
      })
    );

    await expect(getSnapshot("home", "en")).rejects.toThrow("not in the manifest");

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/public/latest/manifest.json") {
          return new Response(
            JSON.stringify({
              current_version: 1,
              generated_at: "2026-06-04T00:00:00Z",
              locales: ["en"],
              objects: { home: { en: "public/v1/en/home.json" } }
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        return new Response("missing", { status: 503 });
      })
    );

    await expect(getSnapshot("home", "en")).rejects.toThrow("Failed to load /public/v1/en/home.json: 503");
  });

  it("routes every snapshot query helper through the expected manifest object key", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-04T00:30:00Z"));
    const objectKeys = [
      "home",
      "map_events",
      "calendar_upcoming",
      "country_USA",
      "region_TOP30",
      "sector_space",
      "scenario_basket_ai_capex",
      "source_status",
      "correction_log",
      "news_index",
      "news_event_abc",
      "news_ticker_NVDA",
      "entity_nvidia",
      "news_region_USA",
      "news_topic_semiconductors",
      "fund_portfolio_space"
    ];
    const objects = Object.fromEntries(
      objectKeys.map((objectKey) => [objectKey, { en: `public/v1/en/${objectKey}.json` }])
    );

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/public/latest/manifest.json") {
          return new Response(
            JSON.stringify({
              current_version: 1,
              generated_at: "2026-06-04T00:00:00Z",
              locales: ["en"],
              objects
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        const objectKey = String(url).split("/").at(-1)?.replace(".json", "") ?? "unknown";
        return new Response(JSON.stringify({ ...activeEnvelope, object_key: objectKey }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      })
    );

    await expect(snapshotQueries.home("en")).resolves.toMatchObject({ object_key: "home" });
    await expect(snapshotQueries.map("en")).resolves.toMatchObject({ object_key: "map_events" });
    await expect(snapshotQueries.calendar("en")).resolves.toMatchObject({ object_key: "calendar_upcoming" });
    await expect(snapshotQueries.country("USA", "en")).resolves.toMatchObject({ object_key: "country_USA" });
    await expect(snapshotQueries.region("TOP30", "en")).resolves.toMatchObject({ object_key: "region_TOP30" });
    await expect(snapshotQueries.sector("space", "en")).resolves.toMatchObject({ object_key: "sector_space" });
    await expect(snapshotQueries.scenarioBasket("ai_capex", "en")).resolves.toMatchObject({
      object_key: "scenario_basket_ai_capex"
    });
    await expect(snapshotQueries.status("en")).resolves.toMatchObject({ object_key: "source_status" });
    await expect(snapshotQueries.corrections("en")).resolves.toMatchObject({ object_key: "correction_log" });
    await expect(snapshotQueries.newsIndex("en")).resolves.toMatchObject({ object_key: "news_index" });
    await expect(snapshotQueries.newsEvent("abc", "en")).resolves.toMatchObject({ object_key: "news_event_abc" });
    await expect(snapshotQueries.newsTicker("NVDA", "en")).resolves.toMatchObject({ object_key: "news_ticker_NVDA" });
    await expect(snapshotQueries.referenceEntity("nvidia", "en")).resolves.toMatchObject({
      object_key: "entity_nvidia"
    });
    await expect(snapshotQueries.newsRegion("USA", "en")).resolves.toMatchObject({ object_key: "news_region_USA" });
    await expect(snapshotQueries.newsTopic("semiconductors", "en")).resolves.toMatchObject({
      object_key: "news_topic_semiconductors"
    });
    await expect(snapshotQueries.fundPortfolio("space", "en")).resolves.toMatchObject({
      object_key: "fund_portfolio_space"
    });
  });
});
