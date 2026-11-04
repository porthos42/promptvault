import { expect, test } from "@playwright/test";
import { API, cleanLibrary, createPrompt, deletePrompt } from "./helpers";

test.beforeEach(async ({ request }) => {
  await cleanLibrary(request);
});

test("trash a prompt from the library and restore it from Trash", async ({ page, request }) => {
  const title = `E2E restore ${Date.now()}`;
  const id = await createPrompt(request, title, "Restore round trip body.");

  // Trash it from the library (detail pane, more-actions menu).
  await page.goto("/");
  await page.getByText(title).first().click();
  await page.getByLabel("More actions").click();
  await page.getByRole("menuitem", { name: "Move to trash" }).click();

  // It is gone from the library and shows in Trash.
  await page.goto("/");
  await expect(page.getByText(title)).toHaveCount(0);
  await page.goto("/trash");
  await expect(page.getByText(title)).toBeVisible();

  // Restore it; it is back in the library.
  await page.getByText(title).first().click();
  await page.getByRole("button", { name: "Restore" }).click();
  await page.goto("/");
  await expect(page.getByText(title).first()).toBeVisible();

  await deletePrompt(request, id);
});
