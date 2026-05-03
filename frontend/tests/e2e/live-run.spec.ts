import { test, expect } from "@playwright/test";

test("live run view shows step rail and event stream", async ({ page }) => {
  await page.goto("/campaigns/20260502-153012-a1b2c3");

  await expect(page.getByText("Tampa, FL")).toBeVisible();
  await expect(page.getByText("Bathroom remodelers")).toBeVisible();

  // step rail
  await expect(page.getByText("Source candidates")).toBeVisible();
  await expect(page.getByText("Filter with Claude")).toBeVisible();
  await expect(page.getByText("Identify owners")).toBeVisible();
  await expect(page.getByText("Assemble CSV")).toBeVisible();

  // event stream content
  await expect(page.getByText(/Sourcer started/)).toBeVisible();
  await expect(page.getByText(/Yelp Fusion returned 24 candidates/)).toBeVisible();
  await expect(page.getByText(/Phase 1 in progress/)).toBeVisible();
});
