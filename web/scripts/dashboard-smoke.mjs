// Exercise the actual map API, CLI Agent inbox and committed browser bundle.
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
const root = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const directory = await mkdtemp(join(tmpdir(), "researchos-dashboard-"));
const python = process.env.RESEARCHOS_PYTHON ?? join(root, ".venv/bin/python");
const workspace = join(directory, "project");
let server, browser;
const failures = [];
function cli(...args) {
  return JSON.parse(
    execFileSync(python, ["-m", "llm_research_os", ...args], {
      cwd: root,
      env: { ...process.env, PYTHONPATH: root + "/src" },
      encoding: "utf8",
    }),
  );
}
try {
  server = spawn(python, ["tests/workbench_smoke_server.py", directory], {
    cwd: root,
    env: { ...process.env, PYTHONPATH: `${root}/src:${root}/tests` },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const fixture = await new Promise((ok, fail) => {
    const timer = setTimeout(
      () => fail(new Error("Fixture startup timeout")),
      15000,
    );
    const lines = createInterface({ input: server.stdout });
    lines.once("line", (line) => {
      clearTimeout(timer);
      lines.close();
      ok(JSON.parse(line));
    });
    server.once("error", fail);
    server.stderr.on("data", (chunk) => failures.push(chunk.toString()));
  });
  const custom = process.env.RESEARCHOS_CHROMIUM_EXECUTABLE;
  browser = await chromium.launch({
    headless: true,
    ...(custom
      ? {
          executablePath: custom,
          args: [
            "--no-sandbox",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
          ],
        }
      : {}),
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.on("pageerror", (error) => failures.push(String(error)));
  await page.goto(`${fixture.url}/#bootstrap=smoke-only-bootstrap`);
  await page
    .getByRole("button", { name: "Open Experiments", exact: true })
    .waitFor();
  let lostSave = false;
  await page.route("**/api/v0alpha1/dashboard", async (route) => {
    if (route.request().method() === "POST" && !lostSave) {
      lostSave = true;
      await route.fetch();
      await route.abort();
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Save map", exact: true }).click();
  await page
    .getByRole("button", { name: "Retry same save", exact: true })
    .click();
  await page.unroute("**/api/v0alpha1/dashboard");
  await page.getByText("Saved revision 1", { exact: true }).waitFor();
  assert.equal(
    cli("dashboard", "show", "--root", workspace).state.components.length,
    20,
  );
  await page
    .getByRole("button", { name: "Open Experiments", exact: true })
    .click();
  await page.getByRole("heading", { name: "Observed lifecycle" }).waitFor();
  await page.getByRole("button", { name: "Close details" }).click();
  await page.getByRole("button", { name: "Appearance" }).click();
  await page.getByRole("button", { name: "Warm paper", exact: true }).click();
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Save map", exact: true }).click();
  await page.getByText("Saved revision 2", { exact: true }).waitFor();
  await page.reload();
  await page.locator(".dashboard.skin-paper").waitFor();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page
    .getByRole("button", { name: "Open Your next question", exact: true })
    .click();
  await page.getByLabel("Title", { exact: true }).fill("My research question");
  await page
    .getByLabel("Context", { exact: true })
    .fill("How can I improve this baseline?");
  await page.getByRole("button", { name: "Save map", exact: true }).click();
  await page.getByText("Saved revision 3", { exact: true }).waitFor();
  // Drag preserves containment, and undo restores the gesture's original state.
  await page.getByRole("button", { name: "Close details" }).click();
  const before = cli("dashboard", "show", "--root", workspace).state;
  const card = page.locator('[data-node="intent"] .map-node-hit');
  const box = await card.boundingBox();
  await page.mouse.move(box.x + 30, box.y + 30);
  await page.mouse.down();
  await page.mouse.move(box.x + 36, box.y + 36, { steps: 4 });
  await page.mouse.up();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await page.getByRole("button", { name: "Browse", exact: true }).click();
  await page.getByRole("button", { name: "Close details" }).click();
  await page
    .getByRole("button", { name: "Open My research question", exact: true })
    .click();
  await page.getByRole("button", { name: "AI", exact: true }).click();
  await page
    .getByLabel("Message to your Agent")
    .fill("Explain the current layout without changing it.");
  // Selecting another object after send must not change the saved request scope.
  await page
    .getByRole("button", { name: "Send to Agent inbox", exact: true })
    .click();
  await page
    .getByText(
      "Waiting for your Agent. No activity is inferred from a pending message.",
    )
    .waitFor();
  const task = cli("dashboard", "inbox", "--root", workspace).tasks[0];
  assert.equal(task.request.expectedRevision, 3);
  assert.deepEqual(task.request.scope, ["intent"]);
  await page
    .getByRole("button", { name: "Open Experiments", exact: true })
    .click();
  const proposed = structuredClone(before);
  proposed.components.find((node) => node.id === "intent").body =
    "Agent-proposed context, synthetic browser fixture";
  const replyPath = join(directory, "reply.json");
  await writeFile(
    replyPath,
    JSON.stringify({
      kind: "DashboardAgentReply",
      requestId: task.request.requestId,
      author: "browser-test Agent (synthetic)",
      proposal: {
        kind: "DashboardWrite",
        projectId: "proj-alpha",
        requestId: "browser-agent-proposal",
        expectedRevision: 3,
        author: "browser-test Agent",
        authorKind: "agent",
        scope: task.request.scope,
        state: proposed,
      },
      message:
        "The pinned research context is preserved. This is a synthetic Agent reply for a browser check.",
    }),
  );
  cli("dashboard", "reply", "--root", workspace, replyPath);
  await page
    .getByText(
      "The pinned research context is preserved. This is a synthetic Agent reply for a browser check.",
    )
    .waitFor();
  assert.deepEqual(cli("dashboard", "show", "--root", workspace).state, before);
  await page
    .getByRole("button", { name: "Review proposed changes", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Apply reviewed Agent proposal", exact: true })
    .click();
  await page.getByText("Saved revision 4", { exact: true }).waitFor();
  assert.equal(
    cli("dashboard", "show", "--root", workspace).state.components.find(
      (node) => node.id === "intent",
    ).body,
    "Agent-proposed context, synthetic browser fixture",
  );
  // A collector supplies timestamped metrics; the browser labels synthetic data.
  const now = Date.now();
  const observationPath = join(directory, "observation.json");
  await writeFile(
    observationPath,
    JSON.stringify({
      kind: "DashboardObservation",
      projectId: fixture.projectId ?? "proj-alpha",
      sourceId: "test-compute",
      entityId: "test-host",
      category: "resource",
      title: "Test compute",
      reporter: "browser-test collector",
      provenance: "Synthetic browser fixture; not a live host",
      observedAt: new Date(now).toISOString(),
      expiresAt: new Date(now + 60000).toISOString(),
      origin: "synthetic",
      status: "unknown",
      metrics: [
        {
          name: "GPU utilization",
          value: 31,
          unit: "%",
          meaning: "observed",
          history: [
            { at: new Date(now - 10000).toISOString(), value: 22 },
            { at: new Date(now).toISOString(), value: 31 },
          ],
        },
      ],
    }),
  );
  cli("dashboard", "observe", "--root", workspace, observationPath);
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Browse", exact: true }).click();
  await page.getByRole("button", { name: "Refresh data", exact: true }).click();
  await page
    .getByRole("button", { name: "Open Compute resources", exact: true })
    .click();
  await page.getByRole("heading", { name: "Measured context" }).waitFor();
  await page
    .getByText("Synthetic browser fixture; not a live host", { exact: true })
    .waitFor();
  assert.equal(await page.locator(".map-chart polyline").count(), 1);
  await page.getByRole("button", { name: "Close details" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.getByRole("button", { name: "Quick guide", exact: true }).click();
  await page
    .getByRole("heading", { name: "Your whole studio, in one map." })
    .waitFor();
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  const latest = cli("dashboard", "show", "--root", workspace);
  const large = {
    ...latest.state,
    components: Array.from({ length: 1000 }, (_, i) => ({
      id: `scale-${i}`,
      type: "note",
      title: `Scale node ${i}`,
      position: {
        x: (i % 20) * 300,
        y: Math.floor(i / 20) * 200,
        width: 280,
        height: 180,
      },
      body: "Synthetic scale fixture",
    })),
    relations: [],
    viewport: { x: 20, y: 20, zoom: 0.7 },
  };
  const largePath = join(directory, "large-map.json");
  await writeFile(
    largePath,
    JSON.stringify({
      projectId: "proj-alpha",
      requestId: "scale-map",
      expectedRevision: latest.revision,
      author: "browser-test operator",
      authorKind: "human",
      state: large,
    }),
  );
  cli("dashboard", "apply", "--root", workspace, largePath);
  await page.reload();
  await page
    .getByRole("button", { name: "Open Scale node 0", exact: true })
    .waitFor();
  assert.ok(
    (await page.locator(".map-card").count()) < 100,
    "large maps should cull offscreen nodes",
  );
  await page
    .getByRole("textbox", { name: "Find a component" })
    .fill("Scale node 999");
  await page.locator(".map-search-results button").click();
  await page
    .getByRole("button", { name: "Open Scale node 999", exact: true })
    .waitFor();
  assert.deepEqual(failures, []);
  console.log(
    "Dashboard: persistence, theme reload, editing/undo, scoped Agent inbox/reply, real collector ingestion, chart and mobile checks passed.",
  );
} finally {
  if (browser) await browser.close();
  if (server && server.exitCode === null) {
    const ended = new Promise((ok) => server.once("exit", ok));
    server.kill("SIGTERM");
    await ended;
  }
  await rm(directory, { recursive: true, force: true });
}
