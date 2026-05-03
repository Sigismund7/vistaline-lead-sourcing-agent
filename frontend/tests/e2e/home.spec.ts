import { test, expect } from "@playwright/test";

test("home redirects to /campaigns", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL("/campaigns");
});
