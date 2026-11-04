import { expect, test } from "@playwright/test";
import { API, cleanLibrary, createPrompt, deletePrompt } from "./helpers";

test.beforeEach(async ({ request }) => {
  await cleanLibrary(request);
});

test("create a prompt through the editor, then find and open it", async ({ page }) => {
  const title = `E2E alpha ${Date.now()}`;
  await page.goto("/new");
  await page.fill("#f-title", title);
  await page.locator(".cm-content").click();
  await page.keyboard.type("Say hello to {{name}} about {{topic}}.");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(/\/p\//);

  // The prompt appears in the library list (searched by title fragment).
  await page.goto("/");
  await page.getByLabel("Search prompts").fill(title.slice(-6));
  await page.getByText(title).first().click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
});

test("fill variables and copy the rendered prompt", async ({ page, request }) => {
  const title = `E2E fill ${Date.now()}`;
  const id = await createPrompt(request, title, "Hello {{name}}, review {{topic}}.");
  try {
    await page.goto("/");
    await page.getByText(title).first().click();

    await page.getByLabel("name").fill("Ada");
    await page.getByLabel("topic").fill("search");
    await expect(page.getByLabel("Preview")).toContainText("Hello Ada, review search.");

    await page.getByRole("button", { name: "Copy" }).click();
    await expect(page.getByText("Copied ✓")).toBeVisible();
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toBe("Hello Ada, review search.");
  } finally {
    await deletePrompt(request, id);
  }
});

test("prompt survives a reload with its URL state", async ({ page, request }) => {
  const title = `E2E reload ${Date.now()}`;
  const id = await createPrompt(request, title, "Persist across reloads.");
  try {
    await page.goto("/");
    await page.getByText(title).first().click();
    const url = page.url();
    await page.reload();
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    expect(page.url()).toBe(url);
  } finally {
    await deletePrompt(request, id);
  }
});
