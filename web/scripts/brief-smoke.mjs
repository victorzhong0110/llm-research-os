// First-use preparation against a real fresh workspace, without execution facts.
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { mkdtemp, rm, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const directory = await mkdtemp(join(tmpdir(), "researchos-brief-"));
const python = process.env.RESEARCHOS_PYTHON ?? join(root, ".venv/bin/python");
const workspace = join(directory, "project");
const failures = [];
let server, browser;
function saved() {
  return JSON.parse(execFileSync(python, ["-m", "llm_research_os", "dashboard", "show", "--root", workspace], {
    cwd: root, env: { ...process.env, PYTHONPATH: `${root}/src` }, encoding: "utf8",
  }));
}
try {
  server = spawn(python, ["tests/workbench_smoke_server.py", directory, "--fresh"], {
    cwd: root, env: { ...process.env, PYTHONPATH: `${root}/src:${root}/tests` },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const fixture = await new Promise((ok, fail) => {
    const timer = setTimeout(() => fail(new Error("Fixture startup timeout")), 15000);
    const lines = createInterface({ input: server.stdout });
    lines.once("line", line => { clearTimeout(timer); lines.close(); ok(JSON.parse(line)); });
    server.once("error", fail);
    server.stderr.on("data", chunk => failures.push(chunk.toString()));
  });
  const custom = process.env.RESEARCHOS_CHROMIUM_EXECUTABLE;
  browser = await chromium.launch({ headless: true, ...(custom ? {
    executablePath: custom,
    args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("pageerror", error => failures.push(String(error)));
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page.getByRole("button", { name: "Create my first brief", exact: true }).click();
  await page.getByLabel("Brief title", { exact: true }).fill("Compare small models");
  await page.getByLabel("Research goal", { exact: true }).fill("Can a smaller model answer our document questions accurately enough?");
  // Closing the side panel must not silently discard the user's draft.
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await page.getByRole("button", { name: "Research brief", exact: true }).click();
  assert.equal(await page.getByLabel("Brief title", { exact: true }).inputValue(), "Compare small models");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Continue", exact: true }).isDisabled(), true);
  await page.getByLabel("What would count as progress?", { exact: true }).fill("Compare factual accuracy on 30 reviewed questions, including failures.");
  await page.getByLabel("Materials you already have (optional)", { exact: true }).fill("A document collection; permitted use still needs checking.");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  if (process.env.RESEARCHOS_BRIEF_SCREENSHOT) await page.screenshot({ path: process.env.RESEARCHOS_BRIEF_SCREENSHOT });
  let lost = false;
  await page.route("**/api/v0alpha1/dashboard", async route => {
    if (route.request().method() === "POST" && !lost) {
      lost = true; await route.fetch(); await route.abort();
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Save brief to map", exact: true }).click();
  await page.getByRole("button", { name: "Retry saving this brief", exact: true }).waitFor();
  // The committed response was lost; reopening still exposes the same retry.
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await page.getByRole("button", { name: "Research brief", exact: true }).click();
  await page.getByRole("button", { name: "Retry saving this brief", exact: true }).click();
  await page.getByRole("heading", { name: "Your research has a starting point.", exact: true }).waitFor();
  await page.unroute("**/api/v0alpha1/dashboard");
  const doc = saved();
  assert.equal(doc.revision, 1);
  assert.equal(doc.state.components.length, 25);
  const brief = doc.state.components.find(n => n.title === "Compare small models");
  assert.ok(brief);
  assert.equal(doc.state.components.filter(n => n.parentId === brief.id).length, 4);
  assert.match(doc.state.components.find(n => n.id === `${brief.id}.resources`).body, /Not identified yet/);
  await assert.rejects(access(join(workspace, "control/events.sqlite")));
  await assert.rejects(access(join(workspace, "operation-receipts.sqlite")));
  await page.getByRole("button", { name: "Discuss this brief with my Agent", exact: true }).click();
  await page.getByText("Next message:", { exact: false }).waitFor();
  assert.match(await page.locator(".map-context").first().innerText(), /Compare small models/);
  // Opening discussion never sends a message automatically.
  assert.equal(await page.getByRole("button", { name: "Send to Agent inbox", exact: true }).isDisabled(), true);
  await page.reload();
  await page.getByRole("button", { name: "Open Compare small models", exact: true }).waitFor();
  const search = page.getByLabel("Find a component");
  await search.fill("Research goal");
  await page.locator(".map-search-results button").click();
  await page.getByText("Can a smaller model answer our document questions accurately enough?", { exact: true }).last().waitFor();
  await page.getByRole("button", { name: "Close details", exact: true }).click();
  await page.getByRole("button", { name: "Appearance", exact: false }).click();
  await page.getByRole("button", { name: "Warm paper", exact: true }).click();
  await page.getByRole("button", { name: "Research brief", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("Brief title", { exact: true }).fill("Mobile preparation");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(failures, []);
  console.log("Fresh-workspace brief: draft retention, validation, exact retry, persistence, Agent scope, mobile and no execution facts passed.");
} finally {
  await browser?.close();
  server?.kill("SIGTERM");
  await rm(directory, { recursive: true, force: true });
}
