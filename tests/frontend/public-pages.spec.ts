import { expect, test } from "@playwright/test";

declare global {
  interface Window {
    __stonksRadarMap?: {
      project(lngLat: [number, number]): { x: number; y: number };
    };
  }
}

test("public routes render from snapshots", async ({ page }) => {
  await page.goto("/en");
  await expect(page.getByText("Global market intelligence dashboard")).toBeVisible();
  await page.goto("/en/portfolio");
  await expect(page.getByText("Portfolio lab")).toBeVisible();
  await page.goto("/en/sources");
  await expect(page.getByText("Source registry")).toBeVisible();
  await page.goto("/ko");
  await expect(page.getByText("글로벌 시장 인텔리전스 대시보드")).toBeVisible();
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
  await page.waitForFunction(() => Boolean(window.__stonksRadarMap), null, { timeout: 15000 });
  const box = canvasBox;
  expect(box).not.toBeNull();
  if (!box) return;

  const tooltip = page.getByTestId("country-hover-tooltip");
  for (const lngLat of [
    [-98, 38],
    [127.5, 36.5],
    [139, 36],
    [10, 51],
    [116, 39]
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

test("map data does not render antimeridian-spanning country rings", async ({ request }) => {
  const response = await request.get("/map/natural-earth/countries-110m.geojson");
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()) as {
    features: Array<{
      properties?: { name?: string; crossesAntimeridian?: boolean; antimeridianSplit?: boolean };
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
    const feature = data.features.find((candidate) => candidate.properties?.name === name);
    expect(feature?.properties?.antimeridianSplit).toBe(true);
    expect(feature?.properties?.crossesAntimeridian).toBeFalsy();
    expect(hasExactAntimeridianVertex(feature?.geometry)).toBe(false);
  }
});

function maxLongitudeDelta(geometry?: { type?: string; coordinates?: unknown }) {
  if (!geometry?.coordinates) return 0;
  const polygons = geometry.type === "MultiPolygon" ? geometry.coordinates : [geometry.coordinates];
  let maxDelta = 0;
  for (const polygon of polygons as number[][][][]) {
    for (const ring of polygon) {
      for (let index = 1; index < ring.length; index += 1) {
        maxDelta = Math.max(maxDelta, Math.abs(ring[index][0] - ring[index - 1][0]));
      }
    }
  }
  return maxDelta;
}

function hasExactAntimeridianVertex(geometry?: { type?: string; coordinates?: unknown }) {
  if (!geometry?.coordinates) return false;
  const polygons = geometry.type === "MultiPolygon" ? geometry.coordinates : [geometry.coordinates];
  for (const polygon of polygons as number[][][][]) {
    for (const ring of polygon) {
      if (ring.some(([longitude]) => Math.abs(Math.abs(longitude) - 180) < 1e-12)) {
        return true;
      }
    }
  }
  return false;
}
