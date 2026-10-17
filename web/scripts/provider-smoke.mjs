// Explicitly synthetic status transport through the real authenticated API and bundle.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const directory = await mkdtemp(join(tmpdir(), "researchos-provider-"));
const python = process.env.RESEARCHOS_PYTHON ?? join(root, ".venv/bin/python");
let browser, server;
const errors = [];
try {
  server = spawn(python, ["tests/workbench_smoke_server.py", directory, "--fresh", "--provider-fixture"], {
    cwd: root, env: { ...process.env, PYTHONPATH: `${root}/src:${root}/tests` }, stdio: ["ignore", "pipe", "pipe"],
  });
  const fixture = await new Promise((ok, fail) => {
    const timer = setTimeout(() => fail(new Error("Fixture startup timeout")), 15000);
    const lines = createInterface({ input: server.stdout });
    lines.once("line", line => { clearTimeout(timer); lines.close(); ok(JSON.parse(line)); });
    server.once("error", fail);
    server.stderr.on("data", chunk => errors.push(chunk.toString()));
  });
  const custom = process.env.RESEARCHOS_CHROMIUM_EXECUTABLE;
  browser = await chromium.launch({ headless: true, ...(custom ? {
    executablePath: custom, args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("pageerror", error => errors.push(String(error)));
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page.getByRole("button", { name: "Add component", exact: true }).click();
  await page.getByRole("button", { name: /OpenAI official status/ }).click();
  await page.getByRole("button", { name: "Refresh OpenAI status", exact: true }).click();
  await page.getByText("Official report refreshed. No model API was called.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Browse", exact: true }).click();
  await page.getByText("synthetic · browser fixture", { exact: true }).waitFor();
  const read = async () => (await page.request.get(`${fixture.url}/api/v0alpha1/dashboard/observations`)).json();
  const before = await read();
  assert.equal(before.observations[0].origin, "synthetic");
  assert.equal(before.observations[0].status, "degraded");
  await page.getByRole("button", { name: "Refresh OpenAI status", exact: true }).click();
  await page.getByText("Official status refresh failed. The previous report has not been replaced.", { exact: true }).waitFor();
  assert.deepEqual(await read(), before);
  await page.getByRole("button", { name: "Add component", exact: true }).click();
  await page.getByRole("button", { name: /Claude official status/ }).click();
  await page.getByRole("button", { name: "Refresh Claude status", exact: true }).click();
  await page.getByText("Official report refreshed. No model API was called.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Browse", exact: true }).click();
  await page.getByText("Synthetic · Stale", { exact: true }).last().waitFor();
  await page.getByRole("button", { name: "Save map", exact: true }).click();
  await page.getByText("Saved revision 1", { exact: true }).waitFor();
  await page.reload();
  await page.getByLabel("Find a component").fill("Claude official status");
  await page.locator(".map-search-results button").click();
  await page.getByRole("button", { name: "Refresh Claude status", exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await assert.rejects(access(join(directory, "project/control/events.sqlite")));
  await assert.rejects(access(join(directory, "project/operation-receipts.sqlite")));
  assert.deepEqual(errors, []);
  console.log("Provider components: synthetic collector, failure retention, expiry, source binding, reload and mobile passed.");
} finally {
  await browser?.close(); server?.kill("SIGTERM");
  await rm(directory, { recursive: true, force: true });
}
