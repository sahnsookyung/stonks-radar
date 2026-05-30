import { performance } from "node:perf_hooks";

const target = new URL(process.env.STONKS_AUDIT_BASE_URL ?? "https://stonks.sookyungahn.com");
const skipApi = process.env.STONKS_AUDIT_SKIP_API === "true";
let latestManifest = null;
const checks = [
  {
    name: "html",
    path: "/en",
    expect(response) {
      const csp = response.headers.get("content-security-policy") ?? "";
      assert(response.status === 200, "HTML route must return 200");
      assert(csp.includes("connect-src 'self'"), "HTML CSP must restrict connect-src to self");
      assert(!csp.includes("localhost"), "HTML CSP must not contain localhost");
      assert(
        (response.headers.get("cache-control") ?? "").includes("no-cache"),
        "HTML route must be no-cache"
      );
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
      latestManifest = await response.json();
      assert(latestManifest?.objects?.home?.en, "Latest manifest must expose current home snapshot path");
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

console.log(JSON.stringify({ target: target.origin, results, failures }, null, 2));
if (failures.length > 0) {
  process.exitCode = 1;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
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
