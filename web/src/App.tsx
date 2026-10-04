/** Workbench shell: bootstrap, navigation, and the read-only view switch. */

import { useCallback, useEffect, useState } from "react";
import { api, exchangeBootstrap, SessionExpiredError, takeBootstrapSecret } from "./api";
import type { WorkspaceView } from "./generated/local-api";
import { ArtifactsView, EventsView, OutcomeLegend, RunsView } from "./components/DataViews";
import { OperationsView } from "./components/OperationsView";
import { EnvironmentView, GraphView, ProjectView, RevisionsView } from "./components/ProjectViews";
import { Failure, Loading } from "./components/Primitives";

type ViewId =
  | "artifacts"
  | "environment"
  | "events"
  | "graph"
  | "legend"
  | "operations"
  | "project"
  | "revisions"
  | "runs";

const VIEWS: ReadonlyArray<{ readonly id: ViewId; readonly label: string }> = [
  { id: "project", label: "Project" },
  { id: "revisions", label: "Spec revisions" },
  { id: "graph", label: "Execution graph" },
  { id: "runs", label: "Runs" },
  { id: "operations", label: "Operations" },
  { id: "events", label: "Events and logs" },
  { id: "artifacts", label: "Artifacts" },
  { id: "environment", label: "Environment" },
  { id: "legend", label: "How to read this" },
];

type Phase =
  | { readonly status: "bootstrapping" }
  | { readonly status: "needs-secret" }
  | { readonly status: "ready"; readonly projectId: string }
  | { readonly status: "refused"; readonly message: string };

export function App() {
  const [phase, setPhase] = useState<Phase>({ status: "bootstrapping" });
  const [view, setView] = useState<ViewId>("project");
  const [workspace, setWorkspace] = useState<WorkspaceView | null>(null);
  const expectedHead = workspace?.highWaterMark;

  const establish = useCallback(async () => {
    setPhase({ status: "bootstrapping" });
    const secret = takeBootstrapSecret();
    try {
      if (secret !== null) {
        await exchangeBootstrap(secret);
      }
      // Always read the session, not just on bootstrap: a reload keeps the
      // HttpOnly cookie but loses the double-submit CSRF value, and without it
      // every write would be refused.
      await api.session();
      const loaded = await api.workspace();
      setWorkspace(loaded);
      setPhase({ status: "ready", projectId: loaded.projectId });
    } catch (error) {
      if (error instanceof SessionExpiredError) {
        setPhase({ status: "needs-secret" });
        return;
      }
      const message = error instanceof Error ? error.message : "The local API could not be reached.";
      setPhase({ status: "refused", message });
    }
  }, []);

  useEffect(() => {
    void establish();
  }, [establish]);

  if (phase.status === "bootstrapping") {
    return (
      <main className="shell shell--center">
        <Loading label="Opening the local session" />
      </main>
    );
  }

  if (phase.status === "refused") {
    return (
      <main className="shell shell--center">
        <Failure error={new Error(phase.message)} onRetry={() => void establish()} />
      </main>
    );
  }

  if (phase.status === "needs-secret") {
    return (
      <main className="shell shell--center">
        <div className="state state--error" role="alert">
          <h2>Session required</h2>
          <p>
            The one-time bootstrap secret has already been used, or this browser has no local session. Restart
            the server with <code>researchos web serve</code> and open the bootstrap URL it prints. A session
            cannot be created any other way, and a browser session is never a Worker credential.
          </p>
          <button type="button" onClick={() => void establish()}>
            Check again
          </button>
        </div>
      </main>
    );
  }

  return (
    <div className="shell">
      <header className="shell__head">
        <h1>Research workbench</h1>
        <p className="shell__sub">
          Read-only view of <code>{phase.projectId}</code>. This surface cannot launch, cancel or record
          anything.
        </p>
      </header>
      <nav className="tabs" aria-label="Workbench views">
        {VIEWS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={view === entry.id ? "tab tab--active" : "tab"}
            aria-current={view === entry.id ? "page" : undefined}
            onClick={() => setView(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </nav>
      <main className="shell__body">
        {view === "project" ? <ProjectView onError={() => undefined} /> : null}
        {view === "revisions" ? <RevisionsView /> : null}
        {view === "graph" ? <GraphView /> : null}
        {view === "runs" ? <RunsView /> : null}
        {view === "events" ? <EventsView /> : null}
        {view === "artifacts" ? <ArtifactsView /> : null}
        {view === "environment" ? <EnvironmentView /> : null}
        {view === "legend" ? <OutcomeLegend /> : null}
        {view === "operations" && expectedHead !== undefined ? (
          <OperationsView expectedHead={expectedHead} />
        ) : null}
      </main>
    </div>
  );
}
