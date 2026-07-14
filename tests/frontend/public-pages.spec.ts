import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

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

type ManifestObject = string | Record<string, string>;

type SnapshotManifest = {
  objects?: Record<string, ManifestObject>;
};

type NewsEvent = {
  id?: string;
  title?: string;
  summary?: string;
  topics?: Array<{ key?: string; label?: string }>;
  source_links?: Array<{ label?: string }>;
};

type NewsListSnapshot = {
  events?: NewsEvent[];
};

test.beforeEach(async ({ page }) => {
  if (!process.env.STONKS_E2E_BASE_URL) {
    await page.clock.setFixedTime(new Date("2026-07-06T12:00:00Z"));
    await page.route("**/api/public/readiness", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ready",
          reason: "fixture_fresh",
          version: 3546,
          generated_at: "2026-07-04T11:17:41Z",
          stale_after: "2026-07-05T11:17:41Z",
          hard_expires_at: "2026-07-11T11:17:41Z",
          age_seconds: 176_539
        })
      });
    });
  }
});

async function getSnapshotData<T>(
  request: APIRequestContext,
  objectKey: string,
  locale = "en",
): Promise<T> {
  const manifestResponse = await request.get("/public/latest/manifest.json");
  expect(manifestResponse.ok()).toBeTruthy();
  const manifest = (await manifestResponse.json()) as SnapshotManifest;
  const object = manifest.objects?.[objectKey];
  const path =
    typeof object === "string"
      ? object
      : (object?.[locale] ?? object?.en ?? Object.values(object ?? {})[0]);
  expect(path).toBeTruthy();
  if (!path) {
    throw new Error(`Manifest is missing ${objectKey}.${locale}`);
  }

  const response = await request.get(path.startsWith("/") ? path : `/${path}`);
  expect(response.ok()).toBeTruthy();
  const snapshot = (await response.json()) as { data?: T };
  expect(snapshot.data).toBeTruthy();
  return snapshot.data as T;
}

function firstEvent(snapshot: NewsListSnapshot, label: string): NewsEvent {
  const event = snapshot.events?.find((candidate) => candidate.title);
  expect(event?.title, `${label} snapshot has a titled event`).toBeTruthy();
  if (!event?.title) {
    throw new Error(`${label} snapshot has no titled events`);
  }
  return event;
}

function searchTermFor(event: NewsEvent): string {
  const text = `${event.title ?? ""} ${event.summary ?? ""}`;
  if (/Rocket Lab|RKLB/i.test(text)) return "Rocket Lab";
  const token = text.match(/[A-Za-z][A-Za-z0-9-]{4,}/)?.[0];
  return token ?? text.slice(0, 12);
}

test("public routes render from snapshots", async ({ page }) => {
  await page.goto("/en");
  await expect(
    page.getByText("Global market intelligence dashboard"),
  ).toBeVisible();
  await expect(page.getByText("Priority Event")).toHaveCount(0);
  await expect(page.getByText("Approved Events")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Scenario Evidence" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Open evidence/ }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Open external tracker/ }),
  ).toBeVisible();
  await page.goto("/en/calendar");
  await expect(
    page.getByRole("heading", { name: "Economic Calendar" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("link", { name: /Federal Reserve|NVIDIA IR|FMP|BLS|TSMC IR/ })
      .first(),
  ).toBeVisible();
  await page.goto("/en/scenario-baskets/ai-infra-capex");
  await expect(page.getByText("Scenario evidence")).toBeVisible();
  await expect(page.getByText("Illustrative methodology")).toHaveCount(0);
  await expect(page.getByText("equal-weight seed")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: /External tracker/ }),
  ).toBeVisible();
  await page.goto("/en/news");
  await expect(page.getByText("Source-Linked News Radar")).toBeVisible();
  await page.goto("/en/portfolio");
  await expect(page.getByText("Portfolio Workspace")).toBeVisible();
  await expect(page.getByText("Investment checkup")).toBeVisible();
  await expect(page.getByText("Goal runway")).toBeVisible();
  await page.goto("/en/dashboard");
  await expect(page.getByText("Cockpit").first()).toBeVisible();
  await page.goto("/en/onboarding");
  await expect(page.getByText("CSV import", { exact: true })).toBeVisible();
  await page.goto("/en/portfolios");
  await expect(
    page
      .getByRole("heading", { name: "Growth + shock absorber portfolio" })
      .first(),
  ).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/xray");
  await expect(page.getByText("Geographic exposure").first()).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/atlas");
  await expect(page.getByText("Asset-class allocation")).toBeVisible();
  await expectPortfolioEditorAccess(page);
  await page.goto("/en/portfolios/demo-growth-income/builder");
  await expect(page.getByText("Target allocation").first()).toBeVisible();
  await expectPortfolioEditorAccess(page);
  await page.goto("/en/portfolios/demo-growth-income/backtest");
  await expect(page.getByText("Backtest equity curve")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/monte-carlo");
  await expect(page.getByText("Monte Carlo fan chart")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/rebalance");
  await expect(page.getByText("Contribution-first plan")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/fees");
  await expect(page.getByText("Fee leak chart")).toBeVisible();
  await page.goto("/en/portfolios/demo-growth-income/tax-lots");
  await expect(
    page.getByText("Tax lots", { exact: true }).first(),
  ).toBeVisible();
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
    page.getByText("Leopold Aschenbrenner").filter({ visible: true }),
  ).toHaveCount(1);
  await expect(
    page.getByText("Situational Awareness").filter({ visible: true }),
  ).toHaveCount(1);
  await expect(
    page
      .getByRole("link", { name: /HedgeFollow/ })
      .filter({ visible: true })
      .first(),
  ).toHaveAttribute("href", /hedgefollow\.com\/funds/);
  await expect(
    page.getByText("Donald Trump", { exact: true }).filter({ visible: true }),
  ).toHaveCount(1);
  await expect(
    page.getByText("Donald Trump Stock Trades").filter({ visible: true }),
  ).toHaveCount(1);
  await expect(
    page
      .getByRole("link", { name: /QuiverQuant/ })
      .filter({ visible: true })
      .first(),
  ).toHaveAttribute("href", /quiverquant\.com\/Donald-Trump-Stock-Trades/);
  await expect(
    page.getByText("not a live portfolio feed").first(),
  ).toBeVisible();
  await expect(page.getByText("Top public-equity allocation")).toHaveCount(0);
  await page.goto("/en/funds/situational-awareness");
  await expect(
    page.getByText("The previous internal 13F portfolio view"),
  ).toBeVisible();
  await expect(page.getByText("Leopold Aschenbrenner")).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Open HedgeFollow/ }),
  ).toHaveAttribute("href", /Situational%2BAwareness/);
  await expect(
    page.getByText("Leopold Aschenbrenner 13F Portfolio"),
  ).toHaveCount(0);
  await expect(page.getByText("Public portfolio filings")).toHaveCount(0);
  await page.goto("/en");
  await expect(
    page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Sources" }),
  ).toHaveCount(0);
  await expect(
    page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Status" }),
  ).toHaveCount(0);
  await page.goto("/en/sources");
  await expect(
    page.getByRole("heading", { name: "Admin session required" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/data-sources$/);
  await page.goto("/en/status");
  await expect(
    page.getByRole("heading", { name: "Admin session required" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/system-config$/);
  await page.goto("/ko/sources");
  await expect(
    page.getByRole("heading", { name: "Admin session required" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/data-sources$/);
  await page.goto("/ko/status");
  await expect(
    page.getByRole("heading", { name: "Admin session required" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/system-config$/);
  await page.goto("/ko");
  await expect(page.getByText("글로벌 시장 인텔리전스 대시보드")).toBeVisible();
  await page.goto("/ko/news");
  await expect(page.getByText("출처 연결 뉴스 레이더")).toBeVisible();
});

test("news filters and detail routes render from snapshots", async ({
  page,
  request,
}) => {
  const regionalEvent = firstEvent(
    await getSnapshotData<NewsListSnapshot>(request, "news_region_KOR"),
    "Korea news",
  );
  const newsIndex = await getSnapshotData<NewsListSnapshot>(
    request,
    "news_index",
  );
  const keywordEvent =
    newsIndex.events?.find((event) =>
      /Rocket Lab|RKLB/i.test(`${event.title ?? ""} ${event.summary ?? ""}`),
    ) ?? firstEvent(newsIndex, "news index");
  const topicEvent =
    newsIndex.events?.find((event) =>
      event.topics?.some((topic) => topic.key),
    ) ?? firstEvent(newsIndex, "news index");
  const topicKey = topicEvent.topics?.find((topic) => topic.key)?.key;
  expect(topicKey, "news index has a filterable topic").toBeTruthy();
  const detailEvent =
    newsIndex.events?.find((event) => event.id && event.title) ??
    firstEvent(newsIndex, "news index");

  await page.goto("/en/news?region=KOR");
  await expect(page.getByText("Source-Linked News Radar")).toBeVisible();
  await expect(page.getByText(regionalEvent.title!).first()).toBeVisible();

  await page.goto("/en/news");
  const keywordFilter = page.getByPlaceholder("ticker, region, topic");
  if ((page.viewportSize()?.width ?? 0) < 768) {
    const filtersButton = page.getByRole("button", { name: /Filters/ });
    await expect(filtersButton).toBeVisible();
    await filtersButton.click();
  }
  await expect(keywordFilter).toBeVisible();
  const tickerOptions = await page.getByLabel("Ticker").locator("option").allTextContents();
  expect(tickerOptions.some((option) => option.includes("Rocket Lab"))).toBe(true);
  expect(tickerOptions.some((option) => option.includes("Advanced Micro Devices") && option.includes("(0)"))).toBe(true);
  await keywordFilter.fill(searchTermFor(keywordEvent));
  await expect(page.getByText(keywordEvent.title!).first()).toBeVisible();

  await page.goto(`/en/news?topic=${topicKey}`);
  await expect(page.getByText(topicEvent.title!).first()).toBeVisible();

  await page.goto(`/en/news/events/${detailEvent.id}`);
  await expect(page.getByText(detailEvent.title!).first()).toBeVisible();
  const sourceLabel = detailEvent.source_links?.find(
    (link) => link.label,
  )?.label;
  if (sourceLabel) {
    await expect(page.getByText(sourceLabel).first()).toBeVisible();
  }
});

test("ticker detail news tab renders ticker snapshot", async ({
  page,
  request,
}) => {
  const nvdaEvent = firstEvent(
    await getSnapshotData<NewsListSnapshot>(request, "news_ticker_NVDA"),
    "NVDA news",
  );

  await page.goto("/en/tickers/NVDA");
  await page.getByLabel("Search tickers").fill("rocket");
  await expect(page.getByRole("link", { name: /RKLB Rocket Lab/ })).toBeVisible();
  await page.getByRole("tab", { name: "News" }).click();
  await expect(page.getByText("Ticker-Relevant News")).toBeVisible();
  await expect(page.getByText(nvdaEvent.title!).first()).toBeVisible();

  await page.goto("/en/tickers/005930_KS");
  await expect(page.getByRole("heading", { name: /005930.KS/ })).toBeVisible();
  await page.goto("/en/tickers/005930.KS");
  await expect(page.getByRole("heading", { name: /005930.KS/ })).toBeVisible();
});

test("portfolio ticker autocomplete resolves identifiers locally and exposes held-state", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.route("**/api/instruments/search**", async (route) => {
    const query = new URL(route.request().url()).searchParams.get("q")?.toUpperCase();
    const symbol = query === "US67066G1040" ? "NVDA" : "AAPL";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        results: [instrumentSearchFixture(symbol)],
        warnings: [],
        cache: "fixture"
      })
    });
  });
  await page.goto("/en/portfolios/demo-growth-income/builder");
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/instruments/")) apiRequests.push(url);
  });

  if ((page.viewportSize()?.width ?? 1280) < 1280) {
    await page.getByText("Add / edit holdings").first().click();
  }
  const search = page.getByRole("combobox", { name: "Add holding" });
  await search.fill("US67066G1040");
  await expect(page.getByRole("option", { name: /NVDA/ })).toBeVisible();
  await page.getByRole("option", { name: /NVDA/ }).click();
  await expect(page.getByRole("button", { name: "Remove NVDA" })).toBeVisible();

  await search.fill("AAPL");
  await expect(page.getByText("Already in this workspace")).toBeVisible();
  expect(apiRequests.length).toBeGreaterThan(0);
  expect(
    apiRequests.every((url) => url.includes("/api/instruments/search")),
  ).toBeTruthy();
});

function instrumentSearchFixture(symbol: "AAPL" | "NVDA") {
  const isNvda = symbol === "NVDA";
  return {
    instrumentId: symbol,
    listingId: `NASDAQ:${symbol}`,
    displaySymbol: symbol,
    name: isNvda ? "NVIDIA Corporation" : "Apple Inc.",
    exchange: "NASDAQ",
    country: "US",
    currency: "USD",
    assetClass: "Equity",
    instrumentType: "stock",
    sector: "Technology",
    isPrimaryListing: true,
    isAdvancedInstrument: false,
    isActive: true,
    isStale: false,
    qualityLevel: "COMPLETE",
    qualityMessage: "Complete fixture record.",
    metadataCoverage: "full",
    priceCoverage: "available",
    calculationEligible: true,
    requiresUserPrice: false,
    sourceProviders: ["playwright_fixture"],
    score: 100,
    matchedOn: [isNvda ? "ISIN_EXACT" : "SYMBOL_EXACT"],
    tooltipKeys: []
  };
}

async function expectPortfolioEditorAccess(page: Page) {
  const viewportWidth = page.viewportSize()?.width ?? 1280;
  if (viewportWidth < 1280) {
    await expect(page.getByText("Add / edit holdings")).toBeVisible();
    return;
  }
  await expect(
    page.locator("aside").filter({ hasText: "Edit holdings" }).last(),
  ).toBeVisible();
}

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

  expect(staticEventCoordinates.size).toBe(0);
  if (newsPoints.length > 0) {
    expect(newsAreas.size).toBeGreaterThan(3);
    expect([...newsAreas].some((key) => key && key !== "USA")).toBeTruthy();
  }

  await page.goto("/en/map");
  await page.waitForFunction(() => Boolean(window.__stonksRadarMap), null, {
    timeout: 15000,
  });
  if (newsPoints.length > 0) {
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
  }
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
