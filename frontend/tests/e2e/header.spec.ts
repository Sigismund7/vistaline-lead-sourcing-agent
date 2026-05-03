import { test, expect } from "@playwright/test";

test("global header renders the VistalineDigital wordmark and active nav", async ({ page }) => {
  await page.goto("/campaigns");
  await expect(page.getByTestId("app-header")).toBeVisible();
  const wordmark = page.getByTestId("wordmark");
  await expect(wordmark).toContainText("Vistaline");
  await expect(wordmark).toContainText("Digital");
  await expect(page.getByRole("link", { name: "Campaigns" })).toBeVisible();
  await expect(page.getByText("Lead Sourcer")).toBeVisible();
});
