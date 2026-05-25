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
  const canvas = page.locator(".maplibregl-canvas").first();
  await expect(canvas).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Loading map")).toBeHidden({ timeout: 15000 });
  await page.waitForFunction(() => Boolean(window.__stonksRadarMap), null, { timeout: 15000 });
  const box = await canvas.boundingBox();
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
