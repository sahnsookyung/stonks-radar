import { performance } from "node:perf_hooks";
import { createHash } from "node:crypto";

const target = new URL(process.env.STONKS_AUDIT_BASE_URL ?? "https://stonks.sookyungahn.com");
const originTarget = optionalUrl(process.env.STONKS_AUDIT_ORIGIN_BASE_URL);
const cdnTarget = optionalUrl(process.env.STONKS_AUDIT_CDN_BASE_URL);
const skipApi = process.env.STONKS_AUDIT_SKIP_API === "true";
const expectedCommit = optionalText(process.env.STONKS_AUDIT_EXPECTED_COMMIT);
const expectedWebArtifact =
  optionalText(process.env.STONKS_AUDIT_EXPECTED_WEB_ARTIFACT) ?? expectedCommit;
const expectedManifestVersion = optionalText(process.env.STONKS_AUDIT_EXPECTED_MANIFEST_VERSION);
const expectedManifestHash = optionalText(process.env.STONKS_AUDIT_EXPECTED_MANIFEST_HASH);
const manifestMaxAgeMs = Number(process.env.STONKS_AUDIT_MANIFEST_MAX_AGE_MS ?? 2 * 60 * 60 * 1000);
let latestManifest = null;
let latestManifestHash = null;
let observedWebArtifact = null;
let latestNewsIds = new Set();
let latestNewsDetailId = null;
let latestHomeIds = new Set();
const checks = [
  {
    name: "html",
    path: "/en",
    async expect(response) {
      const csp = response.headers.get("content-security-policy") ?? "";
      assert(response.status === 200, "HTML route must return 200");
      assert(csp.includes("connect-src 'self'"), "HTML CSP must restrict connect-src to self");
      assert(!csp.includes("localhost"), "HTML CSP must not contain localhost");
      assert(
        (response.headers.get("cache-control") ?? "").includes("no-cache"),
        "HTML route must be no-cache"
      );
      const html = await response.text();
      observedWebArtifact = htmlMetaContent(html, "stonks-web-artifact-version");
      if (expectedWebArtifact) {
        assert(
          observedWebArtifact === expectedWebArtifact,
          `HTML web artifact must match expected ${expectedWebArtifact}, got ${observedWebArtifact ?? "missing"}`
        );
      }
    }
  },
  {
    name: "missing asset",
    path: "/assets/definitely-missing.js",
    expect(response) {
      assert(response.status === 404, "Missing assets must return 404");
      assert(
        !(response.headers.get("content-type") ?? "").includes("text/html"),
        "Missing assets must not return SPA HTML"
      );
    }
  },
  {
    name: "latest manifest",
    path: "/public/latest/manifest.json",
    async expect(response) {
      assert(response.status === 200, "Latest manifest must return 200");
      assert(
        (response.headers.get("cache-control") ?? "").includes("no-cache"),
        "Latest manifest must be no-cache"
      );
      const manifestText = await response.text();
      latestManifestHash = sha256(manifestText);
      latestManifest = JSON.parse(manifestText);
      assert(latestManifest?.objects?.home?.en, "Latest manifest must expose current home snapshot path");
      assertFreshManifest(latestManifest);
      if (expectedManifestVersion) {
        assert(
          String(latestManifest.current_version) === expectedManifestVersion,
          `Latest manifest version must match expected ${expectedManifestVersion}, got ${latestManifest.current_version}`
        );
      }
      if (expectedManifestHash) {
        assert(
          latestManifestHash === expectedManifestHash,
          `Latest manifest hash must match expected ${expectedManifestHash}, got ${latestManifestHash}`
        );
      }
    }
  },
  {
    name: "versioned snapshot",
    path() {
      return latestManifest?.objects?.home?.en ?? "/public/v1/en/home.json";
    },
    async expect(response) {
      assert(response.status === 200, "Versioned snapshot must return 200");
      assert(
        (response.headers.get("cache-control") ?? "").includes("max-age=60"),
        "Versioned snapshots must have a bounded cache TTL"
      );
      const snapshot = await response.json();
      assert(snapshot?.snapshot_version === latestManifest?.current_version, "Versioned snapshot must match latest manifest version");
      assertUsableSnapshot(snapshot);
      if (expectedManifestVersion) {
        assert(
          String(snapshot?.snapshot_version) === expectedManifestVersion,
          `Versioned snapshot must match expected version ${expectedManifestVersion}`
        );
      }
      assertNoBlockedMarketPulseSources(snapshot);
      assertRecentBreakingNews(snapshot);
      assertNoStaticSeedData(snapshot, "home");
      latestHomeIds = eventIds(snapshot?.data?.top_events);
    }
  },
  {
    name: "news snapshot",
    path() {
      return latestManifest?.objects?.news_index?.en ?? "/public/v1/en/news/index.json";
    },
    async expect(response) {
      const snapshot = await assertCurrentSnapshotResponse(response, "News");
      assertNoStaticSeedData(snapshot, "news");
      latestNewsIds = eventIds(snapshot?.data?.events);
      latestNewsDetailId = latestNewsIds.values().next().value ?? null;
      assertSubset(latestHomeIds, latestNewsIds, "Dashboard headlines must come from the News snapshot");
    }
  },
  {
    name: "news detail snapshot",
    path() {
      return latestNewsDetailId
        ? latestManifest?.objects?.[`news_event_${latestNewsDetailId}`]?.en
        : latestManifest?.objects?.news_index?.en;
    },
    async expect(response) {
      if (!latestNewsDetailId) return;
      const snapshot = await assertCurrentSnapshotResponse(response, "News detail");
      assert(
        snapshot?.object_key === `news_event_${latestNewsDetailId}`,
        "News detail snapshot must match the selected News index event"
      );
      assertNoStaticSeedData(snapshot, "news detail");
    }
  },
  {
    name: "map snapshot",
    path() {
      return latestManifest?.objects?.map_events?.en ?? "/public/v1/en/map/events.json";
    },
    async expect(response) {
      const snapshot = await assertCurrentSnapshotResponse(response, "Map");
      assertNoStaticSeedData(snapshot, "map");
      assertSubset(
        eventIds(snapshot?.data?.events),
        latestNewsIds,
        "Map events must come from the News snapshot"
      );
    }
  },
  !skipApi && {
    name: "api health",
    path: "/api/public/health",
    expect(response) {
      assert(response.status === 200, "Public health endpoint must return 200");
    }
  },
  !skipApi && {
    name: "api readiness",
    path: "/api/public/readiness",
    async expect(response) {
      assert(response.status === 200, "Public readiness endpoint must return 200");
      const readiness = await response.json();
      assert(readiness.status === "ready", `Public readiness must be ready, got ${readiness.status}`);
    }
  }
].filter(Boolean);

const results = [];
const failures = [];

for (const check of checks) {
  const path = typeof check.path === "function" ? check.path() : check.path;
  const url = new URL(path, target);
  const started = performance.now();
  const response = await fetch(url, { redirect: "manual" });
  const elapsedMs = Math.round(performance.now() - started);
  results.push({
    name: check.name,
    path,
    status: response.status,
    elapsedMs,
    cacheControl: response.headers.get("cache-control"),
    contentType: response.headers.get("content-type")
  });
  try {
    await check.expect(response);
  } catch (error) {
    failures.push(`${check.name}: ${error.message}`);
  }
}

const edgeComparison = await compareOriginAndCdnManifests();

console.log(
  JSON.stringify(
    {
      target: target.origin,
      expected: {
        commit: expectedCommit,
        webArtifact: expectedWebArtifact,
        manifestVersion: expectedManifestVersion,
        manifestHash: expectedManifestHash
      },
      observed: {
        webArtifact: observedWebArtifact,
        manifestVersion: latestManifest?.current_version,
        manifestHash: latestManifestHash,
        manifestGeneratedAt: latestManifest?.generated_at
      },
      results,
      edgeComparison,
      failures
    },
    null,
    2
  )
);
if (failures.length > 0) {
  process.exitCode = 1;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertFreshManifest(manifest) {
  assert(Number.isFinite(manifestMaxAgeMs) && manifestMaxAgeMs > 0, "Manifest max age must be positive");
  const generatedAt = Date.parse(manifest?.generated_at);
  assert(Number.isFinite(generatedAt), "Latest manifest generated_at must be parseable");
  const ageMs = Date.now() - generatedAt;
  assert(ageMs >= 0, "Latest manifest generated_at must not be in the future");
  assert(ageMs <= manifestMaxAgeMs, `Latest manifest is ${Math.round(ageMs / 60_000)} minutes old; maximum is ${Math.round(manifestMaxAgeMs / 60_000)} minutes`);
}

function assertUsableSnapshot(snapshot) {
  const hardExpiresAt = Date.parse(snapshot?.hard_expires_at);
  assert(Number.isFinite(hardExpiresAt), "Versioned snapshot hard_expires_at must be parseable");
  assert(hardExpiresAt > Date.now(), `Versioned snapshot hard-expired at ${snapshot?.hard_expires_at}`);
}

async function assertCurrentSnapshotResponse(response, label) {
  assert(response.status === 200, `${label} snapshot must return 200`);
  assert(
    (response.headers.get("cache-control") ?? "").includes("max-age=60"),
    `${label} snapshot must have a bounded cache TTL`
  );
  const snapshot = await response.json();
  assert(
    snapshot?.snapshot_version === latestManifest?.current_version,
    `${label} snapshot must match latest manifest version`
  );
  assertUsableSnapshot(snapshot);
  return snapshot;
}

function assertNoStaticSeedData(snapshot, label) {
  assert(
    !JSON.stringify(snapshot).includes("_seed"),
    `${label} snapshot must not contain checked-in seed data`
  );
}

function eventIds(events) {
  return new Set(
    (Array.isArray(events) ? events : [])
      .map((event) => event?.id ?? event?.event_id)
      .filter((id) => typeof id === "string" && id.length > 0)
  );
}

function assertSubset(subset, superset, message) {
  const missing = [...subset].filter((id) => !superset.has(id));
  assert(missing.length === 0, `${message}; missing IDs: ${missing.slice(0, 5).join(", ")}`);
}

function optionalUrl(value) {
  if (!value || !value.trim()) return null;
  return new URL(value);
}

function optionalText(value) {
  if (!value?.trim()) return null;
  return value.trim();
}

function sha256(text) {
  return `sha256:${createHash("sha256").update(text).digest("hex")}`;
}

function htmlMetaContent(html, name) {
  const pattern = new RegExp(String.raw`<meta\s+[^>]*name=["']${escapeRegExp(name)}["'][^>]*>`, "i");
  const tag = html.match(pattern)?.[0];
  if (!tag) return null;
  return tag.match(/\scontent=["']([^"']*)["']/i)?.[1] ?? null;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);
}

async function compareOriginAndCdnManifests() {
  const origin = originTarget;
  const cdn = cdnTarget ?? (originTarget ? target : null);
  if (!origin || !cdn) {
    return {
      status: "skipped",
      reason: "set STONKS_AUDIT_ORIGIN_BASE_URL and optionally STONKS_AUDIT_CDN_BASE_URL to compare edge manifests"
    };
  }

  let originManifest;
  let cdnManifest;

  try {
    [originManifest, cdnManifest] = await Promise.all([
      fetchManifestSummary(origin),
      fetchManifestSummary(cdn)
    ]);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    failures.push(`edge manifest comparison failed: ${message}`);
    return { status: "fail", error: message };
  }

  const status =
    originManifest.currentVersion === cdnManifest.currentVersion &&
    originManifest.manifestHash === cdnManifest.manifestHash
      ? "pass"
      : "fail";

  if (status === "fail") {
    failures.push(
      `edge manifest mismatch: origin v${originManifest.currentVersion} ${originManifest.manifestHash} vs cdn v${cdnManifest.currentVersion} ${cdnManifest.manifestHash}`
    );
  }

  return { status, origin: originManifest, cdn: cdnManifest };
}

async function fetchManifestSummary(baseUrl) {
  const url = new URL("/public/latest/manifest.json", baseUrl);
  const response = await fetch(url, { redirect: "manual" });
  assert(response.status === 200, `${url.origin} latest manifest must return 200`);
  const manifestText = await response.text();
  const manifest = JSON.parse(manifestText);

  return {
    target: url.origin,
    currentVersion: manifest.current_version,
    generatedAt: manifest.generated_at,
    manifestHash: sha256(manifestText)
  };
}

function assertNoBlockedMarketPulseSources(snapshot) {
  const blockedKeys = new Set([
    "nasdaq_composite",
    "nasdaq_100",
    "kospi",
    "kodex_200",
    "wti_crude",
    "gold_futures",
    "silver_futures",
    "copper_futures",
    "vix",
    "usd_krw",
    "usd_jpy",
    "japan_policy_rate"
  ]);
  const blockedSources = [
    /FRED \/ Nasdaq/i,
    /FRED \/ OECD Korea/i,
    /FRED \/ EIA/i,
    /FRED \/ Cboe/i,
    /FRED \/ Federal Reserve H\.10/i,
    /FRED \/ OECD Japan/i
  ];
  for (const tile of snapshot?.data?.macro_tiles ?? []) {
    if (!blockedKeys.has(tile.key)) continue;
    assert(!blockedSources.some((pattern) => pattern.test(tile.source ?? "")), `${tile.key} must not use a stale FRED market-pulse source`);
  }
}

function assertRecentBreakingNews(snapshot) {
  const lane = (snapshot?.data?.alternative_signals ?? []).find((item) => item.key === "breaking_market_news");
  if (!lane) return;
  const generatedAt = Date.parse(snapshot.generated_at);
  const maxAgeMs = 24 * 60 * 60 * 1000;
  for (const item of lane.items ?? []) {
    const updatedAt = Date.parse(item.updated_at);
    assert(Number.isFinite(updatedAt), `Breaking news item ${item.key} must have parseable updated_at`);
    assert(generatedAt - updatedAt <= maxAgeMs, `Breaking news item ${item.key} is older than 24h`);
  }
}
