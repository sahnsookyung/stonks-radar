import { expect, test } from "@playwright/test";

declare global {
  interface Window {
    __stonksRadarMap?: {
      project(lngLat: [number, number]): { x: number; y: number };
      queryRenderedFeatures(
        geometry?: unknown,
        options?: { layers?: string[] },
      ): Array<{
        properties?: Record<string, unknown>;
        geometry?: { type?: string; coordinates?: unknown };
      }>;
    };
    __stonksRadarHoverCountry?: (countryName: string) => void;
  }
}

test("public routes render from snapshots", async ({ page }) => {
  await page.goto("/en");
  await expect(
    page.getByText("Global market intelligence dashboard"),
  ).toBeVisible();
  await expect(page.getByText("Priority Event")).toHaveCount(0);
  await expect(page.getByText("Approved Events")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Scenario Evidence" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Open evidence/ }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Open external tracker/ })).toBeVisible();
  await page.goto("/en/calendar");
  await expect(page.getByRole("heading", { name: "Economic Calendar" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Federal Reserve|NVIDIA IR|FMP|BLS|TSMC IR/ }).first(),
  ).toBeVisible();
  await page.goto("/en/scenario-baskets/ai-infra-capex");
  await expect(page.getByText("Scenario evidence")).toBeVisible();
  await expect(page.getByText("Illustrative methodology")).toHaveCount(0);
  await expect(page.getByText("equal-weight seed")).toHaveCount(0);
  await expect(page.getByRole("link", { name: /External tracker/ })).toBeVisible();
  await page.goto("/en/news");
  await expect(page.getByText("Source-Linked Event News")).toBeVisible();
  await page.goto("/en/portfolio");
  await expect(page.getByText("Portfolio Builder")).toBeVisible();
  await expect(page.getByText("Goal runway")).toBeVisible();
  await page.goto("/en/dashboard");
  await expect(page.getByText("Cockpit").first()).toBeVisible();
  await page.goto("/en/onboarding");
  await expect(page.getByText("CSV import", { exact: true })).toBeVisible();
  await page.goto("/en/portfolios");
  await expect(
    page.getByRole("heading", { name: "Growth + shock absorber portfolio" }),
  ).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/xray");
  await expect(page.getByText("Geographic exposure").first()).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/atlas");
  await expect(page.getByText("Asset-class allocation")).toBeVisible();
  await expect(page.getByText("Edit holdings")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/builder");
  await expect(page.getByText("Target allocation").first()).toBeVisible();
  await expect(page.getByText("Edit holdings")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/backtest");
  await expect(page.getByText("Backtest equity curve")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/monte-carlo");
  await expect(page.getByText("Monte Carlo fan chart")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/rebalance");
  await expect(page.getByText("Contribution-first plan")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/fees");
  await expect(page.getByText("Fee leak chart")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/tax-lots");
  await expect(page.getByRole("heading", { name: "Tax lots" })).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/holdings");
  await expect(page.getByText("Holdings table")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/transactions");
  await expect(page.getByText("Transactions table")).toBeVisible();
  await page.goto("/en/settings/profile");
  await expect(page.getByText("Security boundary")).toHaveCount(0);
  await expect(page.getByText("USD").first()).toBeVisible();
  await page.goto("/en/settings/security");
  await expect(page.getByText("Security boundary")).toBeVisible();
  await page.goto("/admin/feature-gates");
  await expect(
    page.getByRole("heading", { name: "Admin session required" }),
  ).toBeVisible();
  await page.goto("/en/portfolio/glossary");
  await expect(
    page.getByRole("heading", { name: "Maximum drawdown" }),
  ).toBeVisible();
  await page.goto("/en/funds");
  await expect(
    page.getByRole("heading", { name: "Funds Tracker" }),
  ).toBeVisible();
  await expect(
    page.getByText("Disclosure confidence interval", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("not a real-time portfolio")).toBeVisible();
  await page.goto("/en/funds/situational-awareness");
  await expect(
    page.getByText("Leopold Aschenbrenner 13F Portfolio"),
  ).toBeVisible();
  await expect(page.getByText("Public 13F portfolio")).toBeVisible();
  await page.goto("/en/sources");
  await expect(page.getByText("Source registry")).toBeVisible();
  await page.goto("/ko");
  await expect(page.getByText("글로벌 시장 인텔리전스 대시보드")).toBeVisible();
  await page.goto("/ko/news");
  await expect(page.getByText("출처 연결 이벤트 뉴스")).toBeVisible();
});

test("news filters and detail routes render from snapshots", async ({
  page,
}) => {
  await page.goto("/en/news?region=KOR");
  await expect(page.getByText("Source-Linked Event News")).toBeVisible();
  await expect(
    page.getByText("China-origin export-control risk remains elevated").first(),
  ).toBeVisible();

  await page.goto("/en/news");
  const keywordFilter = page.getByPlaceholder("ticker, region, topic");
  if ((page.viewportSize()?.width ?? 0) < 768) {
    const filtersButton = page.getByRole("button", { name: /Filters/ });
    await expect(filtersButton).toBeVisible();
    await filtersButton.click();
  }
  await expect(keywordFilter).toBeVisible();
  await keywordFilter.fill("Rocket Lab");
  await expect(
    page.getByText(
      "Rocket Lab launch-window monitoring is linked to source evidence for RKLB",
    ),
  ).toBeVisible();

  await page.goto("/en/news?topic=energy&breaking=1");
  await expect(
    page.getByText("Energy supply-risk watch links shipping chokepoints"),
  ).toBeVisible();

  await page.goto("/en/news/events/semiconductor_export_controls_seed");
  await expect(
    page.getByText("China-origin export-control risk remains elevated"),
  ).toBeVisible();
  await expect(page.getByText("BIS")).toBeVisible();
});

test("ticker detail news tab renders ticker snapshot", async ({ page }) => {
  await page.goto("/en/tickers/NVDA");
  await page.getByRole("tab", { name: "News" }).click();
  await expect(page.getByText("Ticker-Relevant News")).toBeVisible();
  await expect(page.getByText("NVIDIA Corporation has")).toBeVisible();
  await expect(
    page.getByText("China-origin export-control risk remains elevated"),
  ).toBeVisible();

  await page.goto("/en/tickers/005930_KS");
  await expect(page.getByRole("heading", { name: /005930.KS/ })).toBeVisible();
  await page.goto("/en/tickers/005930.KS");
  await expect(page.getByRole("heading", { name: /005930.KS/ })).toBeVisible();
});

test("portfolio ticker autocomplete resolves identifiers locally and exposes held-state", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/en/portfolios/demo-growth-income/builder");
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/instruments/search")) apiRequests.push(url);
  });

  const search = page.getByRole("combobox", { name: "Add holding" });
  await search.fill("US67066G1040");
  await expect(page.getByRole("button", { name: /NVDA/ })).toBeVisible();
  await page.getByRole("button", { name: /NVDA/ }).click();
  await expect(page.getByText("NVDA").first()).toBeVisible();

  await search.fill("AAPL");
  await expect(page.getByText("Already in this workspace")).toBeVisible();
  expect(apiRequests.length).toBeGreaterThan(0);
  expect(apiRequests.every((url) => url.includes("/api/instruments/search"))).toBeTruthy();
});

test("sector pages use ticker-specific modules and reference entities route", async ({
  page,
}) => {
  await page.goto("/en/sectors/semiconductors");
  await expect(page.getByText("Ticker Catalyst Calendar")).toBeVisible();
  await expect(page.getByText("Sector News")).toBeVisible();
  await expect(page.getByText("FOMC policy decision")).toHaveCount(0);

  await page.goto("/en/entities/QUANTINUUM");
  await expect(
    page.getByText("Reference entity", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("not a quote page")).toBeVisible();
});

test("map countries expose hover feedback", async ({ page }) => {
  await page.goto("/en/map");
  const mapContainer = page.getByTestId("event-map-container");
  await expect(mapContainer).toBeVisible({ timeout: 15000 });
  const containerBox = await mapContainer.boundingBox();
  const minMapHeight = (page.viewportSize()?.height ?? 900) < 800 ? 360 : 500;
  expect(containerBox?.height).toBeGreaterThan(minMapHeight);
  const canvas = page.locator(".maplibregl-canvas").first();
  await expect(canvas).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Loading map")).toBeHidden({ timeout: 15000 });
  const canvasBox = await canvas.boundingBox();
  expect(canvasBox?.height).toBeGreaterThan(minMapHeight);
  await page.waitForFunction(() => Boolean(window.__stonksRadarMap), null, {
    timeout: 15000,
  });
  const box = canvasBox;
  expect(box).not.toBeNull();
  if (!box) return;

  const tooltip = page.getByTestId("country-hover-tooltip");
  const usedDebugHover = await page.evaluate(() => {
    if (!window.__stonksRadarHoverCountry) return false;
    window.__stonksRadarHoverCountry("United States of America");
    return true;
  });
  if (usedDebugHover) {
    await expect(tooltip).toContainText(/[A-Za-z]/);
    return;
  }
  for (const lngLat of [
    [-98, 38],
    [127.5, 36.5],
    [139, 36],
    [10, 51],
    [116, 39],
  ]) {
    const point = await page.evaluate(([lng, lat]) => {
      const map = window.__stonksRadarMap;
      if (!map) return null;
      const projected = map.project([lng, lat]);
      return { x: projected.x, y: projected.y };
    }, lngLat);
    if (point) {
      await page.mouse.move(box.x + point.x, box.y + point.y);
      if (await tooltip.isVisible()) {
        await expect(tooltip).toContainText(/[A-Za-z]/);
        return;
      }
    }
  }
  await expect(tooltip).toBeVisible();
});

test("map renders news nodes at relevant geographies", async ({
  page,
  request,
}) => {
  const manifestResponse = await request.get("/public/latest/manifest.json");
  expect(manifestResponse.ok()).toBeTruthy();
  const manifest = (await manifestResponse.json()) as {
    objects?: {
      map_events?: {
        en?: string;
      };
    };
  };
  const mapEventsPath = manifest.objects?.map_events?.en;
  expect(mapEventsPath).toBeTruthy();
  if (!mapEventsPath) {
    throw new Error("Manifest is missing map_events.en");
  }

  const response = await request.get(
    mapEventsPath.startsWith("/") ? mapEventsPath : `/${mapEventsPath}`,
  );
  expect(response.ok()).toBeTruthy();
  const snapshot = (await response.json()) as {
    data?: {
      events?: Array<{ latitude: number; longitude: number }>;
      breaking_market_map?: {
        map_points?: Array<{
          area_key?: string;
          latitude?: number;
          longitude?: number;
        }>;
      };
    };
  };
  const staticEventCoordinates = new Set(
    (snapshot.data?.events ?? []).map(
      (event) => `${event.latitude.toFixed(1)},${event.longitude.toFixed(1)}`,
    ),
  );
  const newsPoints = snapshot.data?.breaking_market_map?.map_points ?? [];
  const newsAreas = new Set(newsPoints.map((point) => point.area_key));

  expect(staticEventCoordinates.size).toBe(3);
  expect(newsPoints.length).toBeGreaterThan(3);
  expect(newsAreas.size).toBeGreaterThan(3);
  expect([...newsAreas].some((key) => key && key !== "USA")).toBeTruthy();

  await page.goto("/en/map");
  await page.waitForFunction(() => Boolean(window.__stonksRadarMap), null, {
    timeout: 15000,
  });
  await page.waitForFunction(
    () => {
      const map = window.__stonksRadarMap;
      if (!map) return false;
      const features = map.queryRenderedFeatures(undefined, {
        layers: ["breaking-news-clusters", "breaking-news-unclustered"],
      });
      return features.length > 0;
    },
    null,
    { timeout: 15000 },
  );
});

test("map data does not render antimeridian-spanning country rings", async ({
  request,
}) => {
  const response = await request.get(
    "/map/natural-earth/countries-110m.geojson",
  );
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()) as {
    features: Array<{
      properties?: {
        name?: string;
        crossesAntimeridian?: boolean;
        antimeridianSplit?: boolean;
      };
      geometry?: { type?: string; coordinates?: unknown };
    }>;
  };
  const renderedOffenders: string[] = [];
  for (const feature of data.features) {
    if (feature.properties?.crossesAntimeridian) continue;
    if (maxLongitudeDelta(feature.geometry) > 180) {
      renderedOffenders.push(feature.properties?.name ?? "unknown");
    }
  }
  expect(renderedOffenders).toEqual([]);
  for (const name of ["Russia", "Fiji"]) {
    const feature = data.features.find(
      (candidate) => candidate.properties?.name === name,
    );
    expect(feature?.properties?.antimeridianSplit).toBe(true);
    expect(feature?.properties?.crossesAntimeridian).toBeFalsy();
    expect(hasExactAntimeridianVertex(feature?.geometry)).toBe(false);
  }
});

function maxLongitudeDelta(geometry?: {
  type?: string;
  coordinates?: unknown;
}) {
  if (!geometry?.coordinates) return 0;
  const polygons =
    geometry.type === "MultiPolygon"
      ? geometry.coordinates
      : [geometry.coordinates];
  let maxDelta = 0;
  for (const polygon of polygons as number[][][][]) {
    for (const ring of polygon) {
      for (let index = 1; index < ring.length; index += 1) {
        maxDelta = Math.max(
          maxDelta,
          Math.abs(ring[index][0] - ring[index - 1][0]),
        );
      }
    }
  }
  return maxDelta;
}

function hasExactAntimeridianVertex(geometry?: {
  type?: string;
  coordinates?: unknown;
}) {
  if (!geometry?.coordinates) return false;
  const polygons =
    geometry.type === "MultiPolygon"
      ? geometry.coordinates
      : [geometry.coordinates];
  for (const polygon of polygons as number[][][][]) {
    for (const ring of polygon) {
      if (
        ring.some(([longitude]) => Math.abs(Math.abs(longitude) - 180) < 1e-12)
      ) {
        return true;
      }
    }
  }
  return false;
}
