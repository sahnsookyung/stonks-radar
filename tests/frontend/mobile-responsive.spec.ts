import { inflateSync } from "node:zlib";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

const mobileViewports = [
  { width: 360, height: 740 },
  { width: 375, height: 812 },
  { width: 412, height: 915 }
];

const responsiveRoutes = [
  "/en",
  "/en/market-pulse",
  "/en/map",
  "/en/tickers/NVDA",
  "/en/shorts",
  "/en/trump-filings",
  "/en/portfolio",
  "/en/calendar",
  "/en/central-banks",
  "/en/sources",
  "/en/status",
  "/en/methodology",
  "/en/financial-disclaimer",
  "/en/sectors/semiconductors",
  "/en/countries/USA",
  "/en/regions/EUROZONE",
  "/en/scenario-baskets/ai-infra-capex",
  "/ko",
  "/ko/map",
  "/ko/tickers/NVDA",
  "/ko/trump-filings",
  "/ko/calendar"
];

test.describe("mobile responsive public routes", () => {
  test.setTimeout(90_000);

  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "responsive matrix runs once in the mobile project");
  });

  for (const viewport of mobileViewports) {
    test(`fits ${viewport.width}x${viewport.height} without hidden overflow`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      await mockOptionalPublicApis(page);
      const consoleErrors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error" && !isIgnoredConsoleError(message.text())) {
          consoleErrors.push(message.text());
        }
      });
      page.on("pageerror", (error) => consoleErrors.push(error.message));

      for (const route of responsiveRoutes) {
        await page.goto(route, { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(route.includes("/map") ? 1200 : 450);
        await expect(page.locator("main")).toBeVisible();
        await assertHeaderHeight(page, viewport.width);
        await assertAllowedScrollers(page, route);
        await assertNoUnexpectedOverflow(page, route);
        await assertTapTargets(page, route);
        if (route.endsWith("/map")) {
          await assertMapCanvas(page, viewport);
        }
        if (route === "/en/tickers/NVDA") {
          await exerciseTickerTabs(page, route);
        }
      }

      if (consoleErrors.length) {
        await attachMobileScreenshot(page, testInfo, viewport);
      }
      expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
    });
  }
});

async function exerciseTickerTabs(page: Page, route: string) {
  for (const tab of ["Chart", "Technicals", "Options", "News", "Filings", "Fundamentals", "Notes"]) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(150);
    await assertAllowedScrollers(page, `${route}#${tab}`);
    await assertNoUnexpectedOverflow(page, `${route}#${tab}`);
    await assertTapTargets(page, `${route}#${tab}`);
  }
}

async function assertHeaderHeight(page: Page, width: number) {
  const headerHeight = await page.locator("header").evaluate((header) => header.getBoundingClientRect().height);
  expect(headerHeight, `mobile header height at ${width}px`).toBeLessThanOrEqual(145);
}

async function assertAllowedScrollers(page: Page, route: string) {
  const offenders = await page.evaluate(() => {
    const isVisibleElement = (element: Element) => {
      const htmlElement = element as HTMLElement;
      const rect = htmlElement.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      const style = window.getComputedStyle(htmlElement);
      return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0;
    };
    const viewportWidth = document.documentElement.clientWidth;
    return Array.from(document.querySelectorAll<HTMLElement>("[data-allow-horizontal-scroll]"))
      .filter(isVisibleElement)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        const hasAccessibleName = Boolean(element.getAttribute("aria-label") || element.getAttribute("aria-labelledby"));
        return {
          label: element.getAttribute("aria-label") ?? element.getAttribute("aria-labelledby") ?? element.className.toString(),
          hasAccessibleName,
          fitsViewport: rect.left >= -1 && rect.right <= viewportWidth + 1
        };
      })
      .filter((item) => !item.hasAccessibleName || !item.fitsViewport);
  });
  expect(offenders, `${route} has inaccessible or overflowing intentional scrollers`).toEqual([]);
}

async function assertNoUnexpectedOverflow(page: Page, route: string) {
  const offenders = await page.evaluate(() => {
    const isVisibleElement = (element: Element) => {
      const htmlElement = element as HTMLElement;
      const rect = htmlElement.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      const style = window.getComputedStyle(htmlElement);
      return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0;
    };
    const describeElement = (element: Element, rect: DOMRect) => {
      const htmlElement = element as HTMLElement;
      const id = htmlElement.id ? `#${htmlElement.id}` : "";
      const className = htmlElement.className ? `.${String(htmlElement.className).trim().split(/\s+/).slice(0, 3).join(".")}` : "";
      return `${htmlElement.tagName.toLowerCase()}${id}${className} [${Math.round(rect.left)}, ${Math.round(rect.right)}]`;
    };
    const viewportWidth = document.documentElement.clientWidth;
    const seenAllowed = new Set<Element>();
    const items: string[] = [];
    for (const element of Array.from(document.body.querySelectorAll<HTMLElement>("*"))) {
      if (!isVisibleElement(element)) continue;
      if (element.closest("svg")) continue;
      const allowedScroller = element.closest("[data-allow-horizontal-scroll]");
      if (allowedScroller) {
        if (seenAllowed.has(allowedScroller)) continue;
        seenAllowed.add(allowedScroller);
        const scrollerRect = allowedScroller.getBoundingClientRect();
        if (scrollerRect.left < -1 || scrollerRect.right > viewportWidth + 1) {
          items.push(describeElement(allowedScroller, scrollerRect));
        }
        continue;
      }
      const rect = element.getBoundingClientRect();
      if (rect.left < -1 || rect.right > viewportWidth + 1) {
        items.push(describeElement(element, rect));
      }
    }
    return items.slice(0, 10);
  });
  expect(offenders, `${route} has non-allowlisted horizontal overflow`).toEqual([]);
}

async function assertTapTargets(page: Page, route: string) {
  const offenders = await page.evaluate(() => {
    const isVisibleElement = (element: Element) => {
      const htmlElement = element as HTMLElement;
      const rect = htmlElement.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      const style = window.getComputedStyle(htmlElement);
      return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0;
    };
    const describeElement = (element: Element, rect: DOMRect) => {
      const htmlElement = element as HTMLElement;
      const id = htmlElement.id ? `#${htmlElement.id}` : "";
      const className = htmlElement.className ? `.${String(htmlElement.className).trim().split(/\s+/).slice(0, 3).join(".")}` : "";
      return `${htmlElement.tagName.toLowerCase()}${id}${className} [${Math.round(rect.left)}, ${Math.round(rect.right)}]`;
    };
    const selector = [
      "a[href]",
      "button",
      "input:not([type='hidden'])",
      "select",
      "textarea",
      "[role='button']",
      "[role='tab']"
    ].join(",");
    return Array.from(document.body.querySelectorAll<HTMLElement>(selector))
      .filter((element) => {
        if (!isVisibleElement(element)) return false;
        if (element.closest("iframe")) return false;
        if (element.matches(":disabled") || element.getAttribute("aria-disabled") === "true") return false;
        const style = window.getComputedStyle(element);
        return style.pointerEvents !== "none";
      })
      .map((element) => ({ element, rect: element.getBoundingClientRect() }))
      .filter(({ rect }) => rect.width < 43.5 || rect.height < 43.5)
      .map(({ element, rect }) => `${describeElement(element, rect)} ${Math.round(rect.width)}x${Math.round(rect.height)}`)
      .slice(0, 12);
  });
  expect(offenders, `${route} has tap targets below 44px`).toEqual([]);
}

async function assertMapCanvas(page: Page, viewport: { width: number; height: number }) {
  const canvas = page.locator(".maplibregl-canvas").first();
  await expect(canvas).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Loading map")).toBeHidden({ timeout: 15000 });
  const box = await canvas.boundingBox();
  expect(box?.width).toBeGreaterThan(viewport.width - 36);
  expect(box?.height).toBeGreaterThan(320);
  const hasPixels = hasVariedPngPixels(await canvas.screenshot());
  expect(hasPixels, "map canvas should not be blank").toBeTruthy();
}

async function attachMobileScreenshot(page: Page, testInfo: TestInfo, viewport: { width: number; height: number }) {
  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach(`mobile-${viewport.width}x${viewport.height}`, {
    body: screenshot,
    contentType: "image/png"
  });
}

function isIgnoredConsoleError(message: string) {
  return [
    "ResizeObserver loop completed with undelivered notifications",
    "ResizeObserver loop limit exceeded",
    "tradingview-widget.com",
    "widget-sheriff.tradingview-widget.com",
    "www.tradingview.com/support/",
    "s3.tradingview.com/conversions",
    "pine-facade.tradingview.com",
    "Chart.Study.Versioning"
  ].some((pattern) => message.includes(pattern));
}

async function mockOptionalPublicApis(page: Page) {
  const historyPoints = Array.from({ length: 90 }, (_, index) => {
    const date = new Date(Date.UTC(2026, 2, 1 + index));
    return {
      date: date.toISOString().slice(0, 10),
      close: 850 + index * 2 + Math.sin(index / 4) * 18,
      volume: 12_000_000 + index * 42_000
    };
  });
  await page.route("**/api/public/market/history**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        provider: "responsive-fixture",
        source_note: "Responsive fixture for browser layout tests.",
        cache: "hit",
        display_mode: "public",
        display_status: "display_allowed",
        data_freshness: {
          provider: "fixture",
          provider_timestamp: "2026-05-26T10:00:00Z",
          fetched_at: "2026-05-26T10:10:00Z",
          market_session_date: "2026-05-26",
          exchange_timezone: "America/New_York",
          delay_label: "test fixture",
          is_same_day_valid: true,
          is_public_display_allowed: true,
          staleness_reason: "fixture",
          license_mode: "test"
        },
        provider_budget_status: [],
        symbols: ["NVDA"],
        start: "2026-03-01",
        end: "2026-05-26",
        series: [{ symbol: "NVDA", points: historyPoints }],
        warnings: []
      })
    });
  });
  await page.route("**/api/public/filings**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ filings: [], limitations: [] })
    });
  });
  await page.route("**/api/public/transactions**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ transactions: [], limitations: [] })
    });
  });
  await page.route("**/api/public/entities/**/insiders**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ insiders: [], transactions: [], limitations: [] })
    });
  });
  await page.route("**/api/public/trump-disclosures/summary**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        legal_use_warning:
          "OGE public financial disclosure reports may not be obtained or used for unlawful purposes, commercial purposes other than news/media dissemination to the public, credit-rating purposes, or solicitation purposes.",
        limitations: [
          "This is a source-linked public disclosure database, not a copy-trading signal.",
          "OGE data is delayed; Form 278-T may be filed up to 45 days after a transaction."
        ],
        filings: [],
        transactions: [],
        watched_people: [],
        open_review_items: 0
      })
    });
  });
}

function hasVariedPngPixels(buffer: Buffer) {
  const pngSignature = "89504e470d0a1a0a";
  if (buffer.subarray(0, 8).toString("hex") !== pngSignature) return buffer.length > 1000;
  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const idatChunks: Buffer[] = [];
  while (offset + 8 <= buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.subarray(offset + 4, offset + 8).toString("ascii");
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
    }
    if (type === "IDAT") idatChunks.push(data);
    if (type === "IEND") break;
    offset += length + 12;
  }
  const bytesPerPixel = colorType === 6 ? 4 : colorType === 2 ? 3 : colorType === 0 ? 1 : 0;
  if (!width || !height || bitDepth !== 8 || !bytesPerPixel || idatChunks.length === 0) {
    return buffer.length > 1000;
  }
  const inflated = inflateSync(Buffer.concat(idatChunks));
  const rowLength = width * bytesPerPixel;
  const previous = Buffer.alloc(rowLength);
  const current = Buffer.alloc(rowLength);
  let inputOffset = 0;
  let baseline: string | null = null;
  let variedPixels = 0;
  for (let y = 0; y < height; y += 1) {
    const filter = inflated[inputOffset];
    inputOffset += 1;
    inflated.copy(current, 0, inputOffset, inputOffset + rowLength);
    inputOffset += rowLength;
    unfilterRow(current, previous, bytesPerPixel, filter);
    const stride = Math.max(bytesPerPixel, Math.floor(rowLength / 32));
    for (let index = 0; index < rowLength; index += stride) {
      const sample = current.subarray(index, index + Math.min(bytesPerPixel, 3)).toString("hex");
      baseline ??= sample;
      if (sample !== baseline) variedPixels += 1;
      if (variedPixels > 8) return true;
    }
    current.copy(previous);
  }
  return false;
}

function unfilterRow(current: Buffer, previous: Buffer, bytesPerPixel: number, filter: number) {
  for (let index = 0; index < current.length; index += 1) {
    const left = index >= bytesPerPixel ? current[index - bytesPerPixel] : 0;
    const up = previous[index] ?? 0;
    const upLeft = index >= bytesPerPixel ? previous[index - bytesPerPixel] : 0;
    if (filter === 1) current[index] = (current[index] + left) & 0xff;
    else if (filter === 2) current[index] = (current[index] + up) & 0xff;
    else if (filter === 3) current[index] = (current[index] + Math.floor((left + up) / 2)) & 0xff;
    else if (filter === 4) current[index] = (current[index] + paethPredictor(left, up, upLeft)) & 0xff;
  }
}

function paethPredictor(left: number, up: number, upLeft: number) {
  const estimate = left + up - upLeft;
  const distanceLeft = Math.abs(estimate - left);
  const distanceUp = Math.abs(estimate - up);
  const distanceUpLeft = Math.abs(estimate - upLeft);
  if (distanceLeft <= distanceUp && distanceLeft <= distanceUpLeft) return left;
  if (distanceUp <= distanceUpLeft) return up;
  return upLeft;
}
