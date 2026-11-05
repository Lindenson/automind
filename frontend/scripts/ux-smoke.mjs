#!/usr/bin/env node
/**
 * UX smoke test (spec 010 T097, audit F15): drives the mock UI through the intake card, the research grid and the
 * verdict report at 1280 and 390 px, in the light and dark themes; takes screenshots and runs an axe scan. Exits 1
 * when axe reports a critical or serious issue, or a screen does not appear.
 *
 * Playwright and axe-core are NOT dependencies of this repo. Install them in a temporary directory and point the
 * script at it:
 *
 *   mkdir -p /tmp/ux-smoke && (cd /tmp/ux-smoke && npm init -y >/dev/null && \
 *     npm i --no-save --no-package-lock playwright@1.48.2 axe-core@4.10.2 && npx playwright install chromium)
 *   (cd frontend && npx vite --port 5179 --strictPort) &        # the mock UI: no backend needed
 *   UX_SMOKE_DEPS=/tmp/ux-smoke node frontend/scripts/ux-smoke.mjs http://localhost:5179 /tmp/ux-shots
 *
 * UX_SMOKE_VERBOSE=1 prints where each critical or serious issue is.
 * Arguments: base URL (default http://localhost:5179), screenshot directory (default ./ux-shots).
 */
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";

const deps = resolve(process.env.UX_SMOKE_DEPS ?? process.cwd());
const req = createRequire(join(deps, "package.json"));
let chromium, axePath;
try {
  ({ chromium } = req("playwright"));
  axePath = req.resolve("axe-core/axe.min.js");
} catch {
  console.error(`playwright and axe-core not found under ${deps}: see the header of this script.`);
  process.exit(2);
}

const base = (process.argv[2] ?? "http://localhost:5179").replace(/\/$/, "");
const out = resolve(process.argv[3] ?? "ux-shots");
mkdirSync(out, { recursive: true });

const WIDTHS = [1280, 390];
const SCHEMES = ["light", "dark"];
const BAD = new Set(["critical", "serious"]);
const failures = [];
const COMPOSER = "Message AutoMind";

async function axe(page, label) {
  // a fading-in block would be measured half transparent: the scan sees the settled page
  await page.addStyleTag({ content: "*,*::before,*::after{animation:none!important;transition:none!important}" });
  await page.addScriptTag({ path: axePath });
  const res = await page.evaluate(async () => {
    // eslint-disable-next-line no-undef
    const r = await window.axe.run(document, { resultTypes: ["violations"] });
    return r.violations.map((v) => ({
      id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help,
      where: v.nodes.slice(0, 6).map((n) => `${n.target.join(" ")} :: ${(n.any[0]?.message ?? "").slice(0, 120)}`),
    }));
  });
  const bad = res.filter((v) => BAD.has(v.impact));
  for (const v of res) {
    console.log(`  axe ${label}: ${v.impact} ${v.id} (${v.nodes}) — ${v.help}`);
    if (process.env.UX_SMOKE_VERBOSE && BAD.has(v.impact)) for (const w of v.where) console.log(`      ${w}`);
  }
  if (bad.length) failures.push(`${label}: ${bad.map((v) => `${v.impact} ${v.id}`).join(", ")}`);
}

async function shot(page, name) {
  await page.screenshot({ path: join(out, `${name}.png`), fullPage: true });
}

async function run(width, scheme) {
  const label = `${width}-${scheme}`;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width, height: width > 600 ? 900 : 844 }, colorScheme: scheme });
  page.on("pageerror", (e) => failures.push(`${label}: page error ${e.message}`));
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, body: "{}" }));
  try {
    await page.goto(`${base}/?mock=1&q=${encodeURIComponent("Compare Golf GTI and i30 N for mountain roads")}`);
    const card = page.getByRole("group", { name: "Confirm the cars and the research" });
    await card.waitFor({ timeout: 15000 });
    await shot(page, `${label}-1-intake`);
    await axe(page, `${label} intake`);
    await page.getByRole("button", { name: "Yes, research these" }).click();
    await page.getByTestId("progress-legend").waitFor({ timeout: 10000 });
    await shot(page, `${label}-2-progress`);
    const verdict = page.getByRole("region", { name: "Verdict" });
    await verdict.waitFor({ timeout: 20000 });
    await page.getByTestId("based-on").waitFor();
    await page.getByTestId("agreed").waitFor();
    await shot(page, `${label}-3-report`);
    await axe(page, `${label} report`);
    // "Change" on the first car: a structured edit, the report comes back
    const change = page.getByRole("button", { name: /^Change VW Golf GTI/ }).first();
    if (await change.count()) {
      await change.click();
      await page.getByRole("button", { name: "1.5 TSI 150 CV" }).first().click();
      await page.getByTestId("note").last().waitFor({ timeout: 10000 });
      await page.waitForFunction(() => document.querySelectorAll("section[aria-label=Verdict]").length >= 2, null, {
        timeout: 20000,
      });
      await shot(page, `${label}-4-changed`);
    }
    // the error and limit states
    await page.getByRole("textbox", { name: COMPOSER }).fill("show me the limit");
    await page.keyboard.press("Enter");
    await page.getByRole("alert").last().waitFor({ timeout: 10000 });
    await shot(page, `${label}-5-limit`);
    await axe(page, `${label} limit`);
  } catch (e) {
    failures.push(`${label}: ${e.message.split("\n")[0]}`);
    await shot(page, `${label}-x-failed`).catch(() => undefined);
  } finally {
    await browser.close();
  }
}

for (const w of WIDTHS) for (const s of SCHEMES) await run(w, s);
console.log(`screenshots: ${out}`);
if (failures.length) {
  console.error("UX smoke FAILED:\n- " + failures.join("\n- "));
  process.exit(1);
}
console.log("UX smoke passed: no critical or serious axe issues.");
