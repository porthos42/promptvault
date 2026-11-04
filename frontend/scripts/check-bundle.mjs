// Fails the build when the main JS bundle exceeds the gzip budget (default 200 KB).
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import path from "node:path";

const dist = process.argv[2] || path.resolve("../backend/src/promptvault/static");
const html = readFileSync(path.join(dist, "index.html"), "utf8");
const match = html.match(/<script[^>]+src="([^"]+\.js)"/);
if (!match) {
  console.error("No entry <script> found in index.html");
  process.exit(1);
}
const entry = path.join(dist, match[1]);
const bytes = gzipSync(readFileSync(entry)).length;
const budget = Number(process.env.BUNDLE_BUDGET_KB || 200);
const kb = Math.round((bytes / 1024) * 10) / 10;
if (bytes > budget * 1024) {
  console.error(`Bundle budget exceeded: ${kb} KB gzip > ${budget} KB (${path.basename(entry)})`);
  process.exit(1);
}
console.log(`Main JS bundle: ${kb} KB gzip (budget ${budget} KB) — OK`);
