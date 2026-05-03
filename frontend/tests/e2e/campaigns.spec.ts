import { test, expect } from "@playwright/test";

test("campaigns list shows recent runs and a new-campaign button", async ({ page }) => {
  await page.goto("/campaigns");
  await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
  await expect(page.getByRole("link", { name: /new campaign/i })).toHaveAttribute(
    "href",
    "/campaigns/new",
  );

  // Active running campaign
  await expect(page.getByText("Tampa, FL").first()).toBeVisible();
  await expect(page.getByText("Bathroom remodelers").first()).toBeVisible();
  await expect(page.getByText("running", { exact: false }).first()).toBeVisible();

  // Completed campaign with stats
  await expect(page.getByText("Orlando, FL").first()).toBeVisible();
  await expect(page.getByText("38 / 47").first()).toBeVisible();
});
