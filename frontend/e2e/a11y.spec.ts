import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { cleanLibrary, createPrompt, deletePrompt } from "./helpers";

const require = createRequire(import.meta.url);
const axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

async function injectAxe(page: Page) {
  await page.addScriptTag({ content: axeSource });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function axeViolations(page: Page): Promise<any[]> {
  await injectAxe(page);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return page.evaluate(() =>
    (window as any).axe.run(document, {
      runOnly: ["wcag2a", "wcag2aa", "wcag21aa"],
      resultTypes: ["violations"],
    }),
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function assertClean(result: any) {
  const violations: any[] = result?.violations ?? [];
  const summary = violations
    .map(
      (v: { id: string; impact: string | null; nodes: { target: string[] }[] }) =>
        `${v.id} [${v.impact ?? "none"}]: ${v.nodes.map((n: { target: string[] }) => n.target.join(" ")).join("; ")}`,
    )
    .join(" | ");
  expect(summary, `axe violations: ${summary || "(none)"}`).toEqual("");
}

async function toggleDark(page: Page) {
  await page.emulateMedia({ colorScheme: "dark" });
}

test.beforeEach(async ({ request }) => {
  await cleanLibrary(request);
});

test("axe sweep: library list, detail pane and the editor (light and dark)", async ({ page, request }) => {
  const title = `E2E a11y ${Date.now()}`;
  const id = await createPrompt(request, title, "Body with {{topic}} placeholder.");
  try {
    for (const dark of [false, true]) {
      if (dark) await toggleDark(page);
      await page.goto("/");
      assertClean(await axeViolations(page));

      // Open the detail pane.
      await page.getByText(title).first().click();
      assertClean(await axeViolations(page));

      // The editor page.
      await page.goto("/new");
      assertClean(await axeViolations(page));
    }
  } finally {
    await deletePrompt(request, id);
  }
});

test("axe sweep: Trash, Data page (export and import wizard) and the palette", async ({ page, request }) => {
  for (const dark of [false, true]) {
    if (dark) await toggleDark(page);

    await page.goto("/trash");
    assertClean(await axeViolations(page));

    await page.goto("/data?tab=export");
    assertClean(await axeViolations(page));

    await page.goto("/data?tab=import");
    assertClean(await axeViolations(page));

    // The Ctrl+K palette.
    await page.keyboard.press("Control+K");
    await expect(page.getByRole("dialog")).toBeVisible();
    assertClean(await axeViolations(page));
    await page.keyboard.press("Escape");
  }
});


