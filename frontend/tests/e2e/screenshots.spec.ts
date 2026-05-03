import { test } from "@playwright/test";
import path from "node:path";

const OUT = path.resolve(__dirname, "../../../docs/brand/mockups");

const ROUTES: Array<[string, string]> = [
  ["/campaigns", "01-campaigns-list.png"],
  ["/campaigns/new", "02-new-campaign.png"],
  ["/campaigns/20260502-153012-a1b2c3", "03-live-run.png"],
  ["/campaigns/20260502-103940-d4e5f6/results", "04-results.png"],
];

for (const [route, file] of ROUTES) {
  test(`screenshot ${route}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: path.join(OUT, file), fullPage: true });
  });
}
