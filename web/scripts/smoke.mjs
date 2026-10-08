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
async function startServer(script = "tests/workbench_smoke_server.py", directory = fixtureRoot) {
  server = spawn(process.env.RESEARCHOS_PYTHON ?? join(root, ".venv/bin/python"),
    [script, directory],
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
async function restartServer(page, script, directory) {
  // Retire browser requests while the old API is still alive. Stopping a server
  // under an active document can turn intentional restart into ERR_EMPTY_RESPONSE.
  // Unexpected browser errors remain subject to the unchanged assertion below.
  await page.goto("about:blank");
  await stopServer();
  return await startServer(script, directory);
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
  await page.getByRole("button", {name:"Research",exact:true}).click();
  await page.getByRole("heading", {name:"Research",exact:true}).waitFor();
  await page.getByRole("cell").filter({hasText:/^reject$/}).waitFor();
  await page.reload();
  await page.getByRole("button", {name:"Research",exact:true}).click();
  await page.getByRole("cell").filter({hasText:/^reject$/}).waitFor();
  for (const tab of ["Project","Spec revisions","Logs","Artifacts","Environment","How to read this"]) {
    await page.getByRole("button", {name:tab,exact:true}).click();
    await page.locator("main section").first().waitFor();
  }
  await page.getByRole("button", {name:"Operations",exact:true}).click();
  await page.getByRole("textbox", {name:"ResearchSpec path",exact:true}).fill(fixture.inputSpec);
  let lost = false;
  await page.route("**/api/v0alpha1/commands", async route => {
    if (!lost) {lost = true; await route.fetch(); await route.abort();}
    else await route.continue();
  });
  await page.getByRole("button", {name:"Preflight",exact:true}).click();
  await page.getByRole("heading", {name:"Outcome not confirmed",exact:true}).waitFor();
  await page.getByRole("button", {name:"Retry same command",exact:true}).click();
  await page.getByText("Replayed (no new fact)",{exact:true}).waitFor();
  await page.getByText(/"launchAllowed": false/).waitFor();
  await page.getByRole("textbox", {name:"Unused grant ID",exact:true}).fill("unknown-grant");
  await page.getByRole("button", {name:"Revoke unused grant",exact:true}).click();
  await page.getByRole("heading", {name:"Command refused",exact:true}).waitFor();
  await page.unroute("**/api/v0alpha1/commands");
  await page.route("**/api/v0alpha1/events*", route => route.abort());
  await page.getByRole("button", {name:"Events and logs",exact:true}).click();
  await page.getByRole("heading", {name:"Local API unreachable",exact:true}).waitFor();
  await page.unroute("**/api/v0alpha1/events*");
  fixture = await restartServer(page);
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page.getByRole("heading", {name:"Research workbench"}).waitFor();
  await page.getByRole("button", {name:"Runs",exact:true}).click();
  await page.getByText("Cancellation requested", {exact:true}).waitFor();
  fixture = await restartServer(page, "tests/native_browser_server.py", join(fixtureRoot, "native"));
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page.getByRole("button", {name:"Operations",exact:true}).click();
  await page.getByRole("textbox", {name:"Installed native profile ID",exact:true}).fill("cpu");
  assert.equal(await page.getByRole("button", {name:"Start reviewed work",exact:true}).isEnabled(), false);
  await page.getByRole("button", {name:"Inspect installed work",exact:true}).click();
  await page.getByText(/"materialDigest":/).waitFor();
  let launchLost = false;
  await page.route("**/api/v0alpha1/commands", async route => {
    if (!launchLost) {launchLost = true; await route.fetch(); await route.abort();}
    else await route.continue();
  });
  await page.getByRole("button", {name:"Start reviewed work",exact:true}).click();
  await page.getByRole("heading", {name:"Outcome not confirmed",exact:true}).waitFor();
  await page.getByRole("button", {name:"Retry same command",exact:true}).click();
  await page.getByText("Replayed (no new fact)",{exact:true}).waitFor();
  await page.getByText(/"observation": "completed"/).waitFor();
  await page.unroute("**/api/v0alpha1/commands");
  await page.reload();
  await page.getByRole("button", {name:"Operations",exact:true}).click();
  await page.getByRole("textbox", {name:"Existing Run ID",exact:true}).fill(fixture.runId);
  await page.getByRole("button", {name:"Reconnect and read Run",exact:true}).click();
  await page.getByText(/"status": "completed"/).waitFor();
  await page.getByRole("textbox", {name:"Staged backup image ID",exact:true}).fill("image1");
  await page.getByRole("button", {name:"Verify backup",exact:true}).click();
  await page.getByText(/"verified": true/).waitFor();
  await page.getByRole("textbox", {name:"New restored workspace ID",exact:true}).fill("copy1");
  await page.getByRole("button", {name:"Restore backup to new workspace",exact:true}).click();
  await page.getByText(/"relaunchPolicy": "not-relaunched"/).waitFor();
  fixture = await restartServer(page, "tests/research_browser_server.py", join(fixtureRoot, "research"));
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page.getByRole("button", {name:"Research",exact:true}).click();
  await page.getByRole("heading", {name:"Research workflow",exact:true}).waitFor();
  await page.getByRole("textbox", {name:"Installed model profile",exact:true}).fill(fixture.profile);
  assert.equal(await page.getByRole("button", {name:"Generate draft",exact:true}).isEnabled(), false);
  await page.getByRole("button", {name:"Inspect model and budget",exact:true}).click();
  await page.getByText(/"materialDigest":/).waitFor();
  let modelLost = false;
  await page.route("**/api/v0alpha1/commands", async route => {
    if (!modelLost) {modelLost = true; await route.fetch(); await route.abort();}
    else await route.continue();
  });
  await page.getByRole("button", {name:"Generate draft",exact:true}).click();
  await page.getByRole("status").filter({hasText:/exact intent/}).waitFor();
  await page.getByRole("button", {name:"Retry exact research intent",exact:true}).click();
  await page.getByText(/"observation": "completed-validated-draft"/).waitFor();
  await page.unroute("**/api/v0alpha1/commands");
  const draftEditor = page.getByRole("textbox", {name:/Editable proposal:/});
  const draft = JSON.parse(await draftEditor.inputValue());
  draft.rationale = "Browser synthetic amendment preserved after refresh.";
  await draftEditor.fill(JSON.stringify(draft, null, 2));
  assert.equal(await page.getByRole("button", {name:"Record validated proposal",exact:true}).isEnabled(), false);
  await page.getByRole("button", {name:"Validate draft and recompute difference",exact:true}).click();
  await page.getByText(/"disposition": "validated-draft"/).waitFor();
  await page.getByRole("button", {name:"Record validated proposal",exact:true}).click();
  await page.getByText(/"disposition": "recorded"/).waitFor();
  await page.getByRole("textbox", {name:"Rationale or objection",exact:true}).fill("Synthetic dissent remains visible.");
  await page.getByRole("button", {name:"Preserve dissent",exact:true}).click();
  await page.getByRole("cell", {name:"dissent",exact:true}).waitFor();
  await page.getByRole("textbox", {name:"Rationale or objection",exact:true}).fill("Synthetic rejection: no real research evidence.");
  await page.getByRole("button", {name:"Record human decision",exact:true}).click();
  await page.getByRole("cell", {name:/Synthetic rejection:/}).waitFor();
  await page.reload();
  await page.getByRole("button", {name:"Research",exact:true}).click();
  await page.getByRole("cell", {name:/Synthetic rejection:/}).waitFor();
  await page.getByRole("cell", {name:"dissent",exact:true}).waitFor();
  await page.getByRole("textbox", {name:"Installed model profile",exact:true}).fill(fixture.profile);
  await page.getByRole("button", {name:"Observe model call",exact:true}).click();
  await page.getByText(/"observation": "completed-validated-draft"/).waitFor();
  fixture = await restartServer(page, "tests/trained_browser_server.py", join(fixtureRoot, "trained"));
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page.getByRole("button", {name:"Research",exact:true}).click();
  await page.getByRole("textbox", {name:"Installed model profile",exact:true}).fill("mock");
  await page.getByRole("button", {name:"Inspect model and budget",exact:true}).click();
  await page.getByText(/"materialDigest":/).waitFor();
  await page.getByRole("button", {name:"Generate draft",exact:true}).click();
  await page.getByText(/"observation": "completed-validated-draft"/).waitFor();
  await page.getByRole("button", {name:"Record validated proposal",exact:true}).click();
  await page.getByRole("cell", {name:"proposal",exact:true}).waitFor();
  await page.getByRole("textbox", {name:"Rationale or objection",exact:true}).fill("Synthetic acceptance for CPU integration only.");
  await page.getByRole("combobox", {name:"Decision",exact:true}).selectOption("accept");
  const decisionRequest = page.waitForRequest(request => request.method() === "POST" && (request.postData() ?? "").includes("DecisionRecordRequest"));
  await page.getByRole("button", {name:"Record human decision",exact:true}).click();
  const acceptedDecision = (await decisionRequest).postDataJSON().operation.document.decisionId;
  await page.getByRole("cell", {name:/Synthetic acceptance for CPU/}).waitFor();
  await page.getByRole("spinbutton", {name:"Training revision",exact:true}).fill("2");
  await page.getByRole("textbox", {name:"Training native profile",exact:true}).fill("cpu");
  await page.getByRole("button", {name:"Inspect training material",exact:true}).click();
  await page.getByRole("button", {name:"Start explicitly authorized training",exact:true}).waitFor({state:"visible"});
  await page.getByRole("button", {name:"Start explicitly authorized training",exact:true}).click();
  await page.getByRole("textbox", {name:"Completed training output artifact",exact:true}).waitFor();
  await page.getByText(/"observation": "completed"/).waitFor();
  await page.getByRole("textbox", {name:"Accepted research decision ID (optional)",exact:true}).fill(acceptedDecision);
  await page.getByRole("button", {name:"Recompute completed baseline and candidate",exact:true}).click();
  await page.getByText(/"accuracy": "0.950000"/).waitFor();
  await page.getByRole("button", {name:"Preview evidence-linked report",exact:true}).click();
  await page.getByText(/"humanDecisionRequired": true/).waitFor();
  assert.equal(await page.getByRole("button", {name:"Record explicit human conclusion",exact:true}).isEnabled(), false);
  await page.getByRole("textbox", {name:"Editable report narrative",exact:true}).fill("Synthetic browser report: public development split; no scientific acceptance.");
  await page.getByRole("combobox", {name:"Human conclusion",exact:true}).selectOption("insufficient-evidence");
  await page.getByRole("textbox", {name:"Human conclusion rationale",exact:true}).fill("Needs independent data and repeated evaluation.");
  let reportLost = false;
  await page.route("**/api/v0alpha1/commands", async route => {
    if (!reportLost) {reportLost = true; await route.fetch(); await route.abort();}
    else await route.continue();
  });
  await page.getByRole("button", {name:"Record explicit human conclusion",exact:true}).click();
  await page.getByRole("status").filter({hasText:/original identity/}).waitFor();
  await page.getByRole("button", {name:"Retry exact evaluation intent",exact:true}).click();
  await page.getByText(/"disposition": "replayed"/).waitFor();
  await page.unroute("**/api/v0alpha1/commands");
  const savedReport = await page.getByRole("textbox", {name:"Recorded report artifact",exact:true}).inputValue();
  assert.match(savedReport, /^sha256:[a-f0-9]{64}$/);
  fixture = await restartServer(page, "tests/trained_browser_server.py", join(fixtureRoot, "trained"));
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page.getByRole("button", {name:"Research",exact:true}).click();
  await page.getByRole("button", {name:"List recorded human reports",exact:true}).click();
  await page.getByText(new RegExp(savedReport)).waitFor();
  await page.getByRole("textbox", {name:"Recorded report artifact",exact:true}).fill(savedReport);
  await page.getByRole("button", {name:"Read recorded human report",exact:true}).click();
  await page.getByText(/"historicalRecordedReport": true/).waitFor();
  await page.getByText(/"verdict": "insufficient-evidence"/).waitFor();
  assert.deepEqual(consoleErrors.filter(text => !text.includes("net::ERR_FAILED") && !text.includes("409 (Conflict)")), []);
  console.log("Browser smoke passed: existing R11/R12 chains plus synthetic proposal/accepted decision -> exact-spec real CPU training -> recomputed baseline/candidate -> edited explicit human-labelled conclusion; lost report response replay and persisted report restart. Synthetic actors are not human acceptance.");
} finally {
  if (browser) await browser.close();
  await stopServer();
  await rm(fixtureRoot, {recursive:true,force:true});
}
