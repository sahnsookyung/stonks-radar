import { performance } from "node:perf_hooks";

const target = new URL(process.env.STONKS_AUDIT_BASE_URL ?? "https://stonks.sookyungahn.com");
const skipApi = process.env.STONKS_AUDIT_SKIP_API === "true";
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
    expect(response) {
      assert(response.status === 200, "Latest manifest must return 200");
      assert(
        (response.headers.get("cache-control") ?? "").includes("no-cache"),
        "Latest manifest must be no-cache"
      );
    }
  },
  {
    name: "versioned snapshot",
    path: "/public/v1/en/home.json",
    expect(response) {
      assert(response.status === 200, "Versioned snapshot must return 200");
      assert(
        (response.headers.get("cache-control") ?? "").includes("max-age=60"),
        "Versioned snapshots must have a bounded cache TTL"
      );
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
  const url = new URL(check.path, target);
  const started = performance.now();
  const response = await fetch(url, { redirect: "manual" });
  const elapsedMs = Math.round(performance.now() - started);
  results.push({
    name: check.name,
    path: check.path,
    status: response.status,
    elapsedMs,
    cacheControl: response.headers.get("cache-control"),
    contentType: response.headers.get("content-type")
  });
  try {
    check.expect(response);
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
