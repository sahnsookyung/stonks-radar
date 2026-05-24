import { expect, test } from "@playwright/test";

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
