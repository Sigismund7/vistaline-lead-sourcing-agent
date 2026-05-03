import { test, expect } from "@playwright/test";

test("new-campaign form shows city, niche selector, count, and start button", async ({ page }) => {
  await page.goto("/campaigns/new");
  await expect(page.getByRole("heading", { name: /new campaign/i })).toBeVisible();
  await expect(page.getByLabel("City")).toBeVisible();
  await expect(page.getByLabel(/state/i)).toBeVisible();
  await expect(page.getByLabel(/lead count/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /select niche/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /start campaign/i })).toBeVisible();
});

test("niche combobox opens and lists presets + custom option", async ({ page }) => {
  await page.goto("/campaigns/new");
  await page.getByRole("button", { name: /select niche/i }).click();
  await expect(page.getByText("Kitchen remodelers")).toBeVisible();
  await expect(page.getByText("Bathroom remodelers")).toBeVisible();
  await expect(page.getByText("Roofing")).toBeVisible();
  await expect(page.getByText(/custom\.\.\./i)).toBeVisible();
});
