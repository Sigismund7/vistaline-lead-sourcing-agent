import { test, expect } from "@playwright/test";

test("results page shows leads, exclude checkboxes, cost panel, and CSV export", async ({ page }) => {
  await page.goto("/campaigns/20260502-103940-d4e5f6/results");

  await expect(page.getByRole("heading", { name: /results/i })).toBeVisible();
  await expect(page.getByText("Lloyd & Sons Bath Remodel")).toBeVisible();
  await expect(page.getByText("Sunrise Tile & Bath")).toBeVisible();

  // cost panel
  await expect(page.getByText(/total spend/i)).toBeVisible();

  // exclude checkboxes
  const checkboxes = page.getByRole("checkbox");
  await expect(checkboxes.first()).toBeVisible();

  // download button
  await expect(page.getByRole("button", { name: /download findymail csv/i })).toBeVisible();
});
