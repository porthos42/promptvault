import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import type { APIRequestContext, Page } from "@playwright/test";

export const API = "/api/v1";

export async function createPrompt(
  request: APIRequestContext,
  title: string,
  body: string,
): Promise<string> {
  const res = await request.post(`${API}/prompts`, { data: { title, body } });
  if (res.status() !== 201) throw new Error(`create failed: ${res.status()} ${await res.text()}`);
  return (await res.json()).id as string;
}

export async function deletePrompt(request: APIRequestContext, id: string) {
  await request.delete(`${API}/prompts/${id}`); // to trash
  await request.delete(`${API}/prompts/${id}?permanent=true`); // purge
}

/** Wipe every prompt (library + trash) so tests start from a clean state. */
export async function cleanLibrary(request: APIRequestContext) {
  const list = await (await request.get(`${API}/prompts?limit=1000`)).json();
  for (const p of list.items ?? []) await deletePrompt(request, p.id);
  // One bulk purge instead of per-item permanent deletes: atomic and fast,
  // so no trash item survives into the next test and trips dedupe.
  await request.delete(`${API}/trash`);
}

const require = createRequire(import.meta.url);
let axeSource: string | null = null;

function loadAxe(): string {
  if (!axeSource) axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
  return axeSource;
}

export interface AxeResult {
  violations: { id: string; impact: string | null; nodes: { target: string[]; failureSummary: string }[] }[];
}

export async function runAxe(page: Page): Promise<AxeResult> {
  await page.addScriptTag({ content: loadAxe() });
  return page.evaluate(() =>
    (window as unknown as { axe: { run(d: Document, o: object): Promise<AxeResult> } }).axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
      resultTypes: ["violations"],
    }),
  );
}

export function summarizeViolations(result: AxeResult): string {
  return result.violations
    .map(
      (v) =>
        `${v.id} (${v.impact ?? "minor"}): ` +
        v.nodes.map((n) => n.target.join(" ")).join(", "),
    )
    .join("; ");
}
