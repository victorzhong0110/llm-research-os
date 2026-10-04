/** Read-only project, revision, graph and environment views. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { formatBytes, formatTime, shortDigest } from "../format";
import { Badge, BoundedList, Empty, Failure, KeyValue, Loading } from "./Primitives";
import { usePage } from "./usePage";
import type { RevisionItem, WorkspaceView } from "../generated/local-api";

const PAGE_LIMIT = 50;
const LIST_CAP = 100;

export function ProjectView({ onError }: { readonly onError: (error: unknown) => void }) {
  const [workspace, setWorkspace] = useState<WorkspaceView | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let live = true;
    api.workspace().then(
      (result) => {
        if (live) {
          setWorkspace(result);
        }
      },
      (failure: unknown) => {
        if (live) {
          setError(failure);
          onError(failure);
        }
      },
    );
    return () => {
      live = false;
    };
  }, [onError]);

  if (error !== null) {
    return <Failure error={error} onRetry={() => window.location.reload()} />;
  }
  if (workspace === null) {
    return <Loading label="Loading project" />;
  }
  return (
    <section aria-labelledby="project-heading">
      <h2 id="project-heading">Project</h2>
      <KeyValue
        items={[
          ["Project id", <code key="id">{workspace.projectId}</code>],
          ["Event high-water mark", String(workspace.highWaterMark)],
          ["Control store", <code key="db">{workspace.controlDb}</code>],
          ["Artifact root", <code key="cas">{workspace.casRoot}</code>],
          ["Worker root", <code key="worker">{workspace.workerRoot}</code>],
        ]}
      />
      <p className="note">
        Paths are shown relative to the workspace manifest. The server reports no absolute host path, and no
        control database, private TLS key or Worker credential is exposed by this surface.
      </p>
    </section>
  );
}

export function RevisionsView() {
  const [cursor, setCursor] = useState<string | null>(null);
  const load = useCallback(
    (next: string | null) => api.revisions(next, PAGE_LIMIT),
    [],
  );
  const { page, error, reload } = usePage<RevisionItem>(load, cursor);

  if (error !== null) {
    return <Failure error={error} onRetry={reload} />;
  }
  if (page === null) {
    return <Loading label="Loading revisions" />;
  }
  if (page.items.length === 0) {
    return (
      <Empty
        title="No spec revisions recorded"
        detail="A revision appears here once a ResearchSpec digest has been appended to this project's event store."
      />
    );
  }
  return (
    <section aria-labelledby="revisions-heading">
      <h2 id="revisions-heading">Spec revisions</h2>
      <p className="note">
        Immutable: a revision is the first-seen digest of a ResearchSpec. Editing one is a new revision, never a
        rewrite.
      </p>
      <BoundedList
        items={page.items}
        cap={LIST_CAP}
        totalLabel="spec revisions"
        row={(item) => (
          <tr key={`${item.revision}-${item.specDigest}`}>
            <td>{item.revision}</td>
            <td>
              <code title={item.specDigest}>{shortDigest(item.specDigest, 16)}</code>
            </td>
            <td>{item.firstSeenSequence}</td>
          </tr>
        )}
      />
      {page.nextCursor !== null ? (
        <button type="button" onClick={() => setCursor(page.nextCursor)}>
          Next page
        </button>
      ) : null}
    </section>
  );
}

/** Read-only graph derived from verified Run facts.
 *
 * The layout is presentation only. It is derived from sequences and never
 * feeds back into a digest, so moving a node cannot change a semantic identity.
 */
export function GraphView() {
  const load = useCallback((cursor: string | null) => api.runs(cursor, PAGE_LIMIT), []);
  const { page, error, reload } = usePage(load, null);

  if (error !== null) {
    return <Failure error={error} onRetry={reload} />;
  }
  if (page === null) {
    return <Loading label="Loading execution graph" />;
  }
  if (page.items.length === 0) {
    return (
      <Empty
        title="No runs to graph"
        detail="The graph draws one node per run that has lifecycle facts in this project. Nothing is inferred."
      />
    );
  }
  return (
    <section aria-labelledby="graph-heading">
      <h2 id="graph-heading">Execution graph</h2>
      <p className="note">
        Read-only and derived from verified facts. Node placement is layout only and is not part of any digest.
        Execution graphs this workbench cannot represent are left unsupported rather than approximated.
      </p>
      <ol className="graph">
        {page.items.slice(0, LIST_CAP).map((item) => (
          <li key={item.runId} className="graph__node">
            <span className="graph__label">{item.runId}</span>
            <span className="graph__meta">
              {item.lastEventType} · seq {item.lastSequence}
              {item.attemptId === null || item.attemptId === undefined ? "" : ` · ${item.attemptId}`}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Environment and enforced-limit view, straight from `/capabilities`. */
export function EnvironmentView() {
  const [capabilities, setCapabilities] = useState<Awaited<ReturnType<typeof api.capabilities>> | null>(
    null,
  );
  const [error, setError] = useState<unknown>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let live = true;
    setCapabilities(null);
    setError(null);
    api.capabilities().then(
      (result) => {
        if (live) {
          setCapabilities(result);
        }
      },
      (failure: unknown) => {
        if (live) {
          setError(failure);
        }
      },
    );
    return () => {
      live = false;
    };
  }, [nonce]);

  if (error !== null) {
    return <Failure error={error} onRetry={() => setNonce((value) => value + 1)} />;
  }
  if (capabilities === null) {
    return <Loading label="Loading environment" />;
  }
  return (
    <section aria-labelledby="environment-heading">
      <h2 id="environment-heading">Environment and limits</h2>
      <p className="note">
        These are the limits the server actually enforces, read from the API rather than assumed by the client.
      </p>
      <KeyValue
        items={[
          [
            "Mode",
            <Badge key="mode" tone={capabilities.readOnly ? "neutral" : "warning"}>
              {capabilities.readOnly ? "Read-only" : "Writable"}
            </Badge>,
          ],
          ["Max request body", formatBytes(capabilities.limits.maxBodyBytes)],
          ["Max concurrent requests", String(capabilities.limits.maxConcurrentRequests)],
          ["Max decoded depth", String(capabilities.limits.maxDecodedDepth)],
          ["Max decoded nodes", String(capabilities.limits.maxDecodedNodes)],
          ["Max evidence size", formatBytes(capabilities.limits.maxEvidenceBytes)],
          ["Max extracted characters", String(capabilities.limits.maxExtractedChars)],
          ["Max PDF pages", String(capabilities.limits.maxPdfPages)],
          ["Polling fallback interval", `${capabilities.pollFallbackSeconds}s`],
        ]}
      />
      <p className="note">
        This session is a browser session, not a Worker credential. It cannot launch a task, consume a grant or
        record a fact.
      </p>
    </section>
  );
}

export { formatTime };
