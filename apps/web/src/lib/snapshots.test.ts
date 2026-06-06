import { afterEach, describe, expect, it, vi } from "vitest";
import { SnapshotHardExpiredError, getSnapshot, isHardExpired, snapshotFreshness } from "./snapshots";

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
});
