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
let latestManifest = null;
let latestManifestHash = null;
let observedWebArtifact = null;
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
      if (expectedManifestVersion) {
        assert(
          String(snapshot?.snapshot_version) === expectedManifestVersion,
          `Versioned snapshot must match expected version ${expectedManifestVersion}`
        );
      }
      assertNoBlockedMarketPulseSources(snapshot);
      assertRecentBreakingNews(snapshot);
    }
  },
  !skipApi && {
    name: "api health",
    path: "/api/public/health",
    expect(response) {
      assert(response.status === 200, "Public health endpoint must return 200");
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

function optionalUrl(value) {
  if (!value || !value.trim()) return null;
  return new URL(value);
}

function optionalText(value) {
  if (!value || !value.trim()) return null;
  return value.trim();
}

function sha256(text) {
  return `sha256:${createHash("sha256").update(text).digest("hex")}`;
}

function htmlMetaContent(html, name) {
  const pattern = new RegExp(`<meta\\s+[^>]*name=["']${escapeRegExp(name)}["'][^>]*>`, "i");
  const tag = html.match(pattern)?.[0];
  if (!tag) return null;
  return tag.match(/\scontent=["']([^"']*)["']/i)?.[1] ?? null;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
