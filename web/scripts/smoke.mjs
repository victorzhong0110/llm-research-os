// Drives the committed bundle against actual EventStore/CAS reads. Fixtures are synthetic.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const fixtureRoot = await mkdtemp(join(tmpdir(), "researchos-browser-"));
let server;
let browser;
const errors = [];
async function startServer() {
  server = spawn(process.env.RESEARCHOS_PYTHON ?? join(root, ".venv/bin/python"),
    ["tests/workbench_smoke_server.py", fixtureRoot],
    {cwd:root, env:{...process.env,PYTHONPATH:`${root}/src:${root}/tests`}, stdio:["ignore","pipe","pipe"]});
  server.stderr.on("data", chunk => errors.push(chunk.toString()));
  return await new Promise((ok, fail) => {
    const lines = createInterface({input:server.stdout});
    const timeout = setTimeout(() => fail(new Error("API startup deadline exceeded")), 15000);
    server.once("error", fail);
    server.once("exit", code => {clearTimeout(timeout); fail(new Error(`API exited: ${code}; ${errors.join("")}`));});
    lines.once("line", line => {clearTimeout(timeout); lines.close(); ok(JSON.parse(line));});
  });
}
async function stopServer() {
  if (!server || server.exitCode !== null) return;
  const exited = new Promise(ok => server.once("exit", ok));
  server.kill("SIGTERM"); await exited;
}
try {
  let fixture = await startServer();
  browser = await chromium.launch({headless:true});
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("pageerror", error => consoleErrors.push(String(error)));
  page.on("console", message => {if(message.type() === "error") consoleErrors.push(message.text());});
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page.getByRole("heading", {name:"Research workbench"}).waitFor();
  assert.equal(new URL(page.url()).hash, "");
  await page.getByRole("button", {name:"Runs",exact:true}).click();
  await page.getByText("Cancellation requested", {exact:true}).waitFor();
  await page.getByRole("button", {name:"run-late",exact:true}).click();
  await page.getByRole("button", {name:"252",exact:true}).waitFor();
  await page.getByRole("button", {name:"254",exact:true}).waitFor();
  await page.reload();
  await page.getByRole("heading", {name:"Research workbench"}).waitFor();
  await page.getByRole("button", {name:"Runs",exact:true}).click();
  await page.getByText("Cancellation requested", {exact:true}).waitFor();
  await page.getByRole("button", {name:"Execution graph",exact:true}).click();
  await page.getByRole("textbox", {name:"Artifact digest"}).fill(fixture.spec);
  await page.getByRole("button", {name:"Inspect",exact:true}).click();
  await page.getByRole("cell", {name:"second",exact:true}).waitFor();
  await page.getByRole("button", {name:"Metrics",exact:true}).click();
  await page.getByRole("textbox", {name:"Artifact digest"}).fill(fixture.result);
  await page.getByRole("button", {name:"Inspect",exact:true}).click();
  await page.getByRole("button", {name:/configDigest:/}).click();
  await page.getByText(/"seed": 0/).waitFor();
  await page.getByRole("button", {name:"Decisions and authority",exact:true}).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", {name:"255",exact:true}).click();
  await page.getByText(/browser smoke fixture only/).waitFor();
  for (const tab of ["Project","Spec revisions","Logs","Artifacts","Environment","How to read this"]) {
    await page.getByRole("button", {name:tab,exact:true}).click();
    await page.locator("main section").first().waitFor();
  }
  await page.route("**/api/v0alpha1/events*", route => route.abort());
  await page.getByRole("button", {name:"Events and logs",exact:true}).click();
  await page.getByRole("heading", {name:"Local API unreachable",exact:true}).waitFor();
  await page.unroute("**/api/v0alpha1/events*");
  await stopServer();
  fixture = await startServer();
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page.getByRole("heading", {name:"Research workbench"}).waitFor();
  await page.getByRole("button", {name:"Runs",exact:true}).click();
  await page.getByText("Cancellation requested", {exact:true}).waitFor();
  assert.deepEqual(consoleErrors.filter(text => !text.includes("net::ERR_FAILED")), []);
  console.log("Browser smoke passed: bootstrap, scoped late Run, cancellation, topology, lineage, 11 views, keyboard, offline, refresh and persisted-store restart.");
} finally {
  if (browser) await browser.close();
  await stopServer();
  await rm(fixtureRoot, {recursive:true,force:true});
}
