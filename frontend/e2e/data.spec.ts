import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { cleanLibrary, createPrompt } from "./helpers";

const CSV = "e2e/fixtures/sample-prompts.csv";

test.beforeEach(async ({ request }) => {
  await cleanLibrary(request);
});

test("import two prompts through the wizard with a real CSV", async ({ page }) => {
  await page.goto("/data?tab=import");

  // The wizard starts with no importer picked; choose CSV to reveal the file input.
  // "csv" would also substring-match the github and url importer labels, so anchor it.
  await page.getByRole("radio", { name: /^csv CSV with a header row/ }).click();
  // A default license keeps rows from needing per-row license confirmation, so
  // the Import button stays enabled.
  await page.getByLabel(/^License/).fill("MIT");
  await page.setInputFiles("input[type=file]", CSV);
  await page.getByRole("button", { name: /Next: check the data/ }).click();

  // Mapping step: the CSV headers auto-map; re-run the preview to reach Step 3.
  // A direct click auto-waits for the mapping step to render — an isVisible()
  // probe here races the render and silently skips the step.
  await page.getByRole("button", { name: "Re-run preview" }).click();

  await expect(page.getByRole("region", { name: /preview/i })).toBeVisible();
  await page.locator(".wizard-nav button.primary").click(); // the Import button

  await expect(page.getByText(/2 new/)).toBeVisible();

  // The imported prompts are in the library.
  await page.goto("/");
  await expect(page.getByText("Wizard title one")).toBeVisible();
  await expect(page.getByText("Wizard title two")).toBeVisible();
});

test("export the library as JSON and download it", async ({ page, request }) => {
  // The suite cleans the library before each test, so seed the content this
  // export is supposed to contain (it used to lean on leftover state).
  await createPrompt(request, "Export alpha", "Body {{a}} {{b}} {{c}}");
  await createPrompt(request, "Export beta", "Body two");

  await page.goto("/data?tab=export");

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download" }).click();
  const dl = await download;

  expect(dl.suggestedFilename()).toMatch(/promptvault-export-\d{8}\.json$/);
  const file = "e2e-results/last-export.json";
  await dl.saveAs(file);
  const content = JSON.parse(readFileSync(file, "utf8"));
  // The JSON export is an object whose "prompts" key holds the prompt records.
  expect(Array.isArray(content.prompts)).toBe(true);
  expect(content.prompts.length).toBeGreaterThanOrEqual(2);
  expect(content.prompts[0]).toHaveProperty("title");
});
