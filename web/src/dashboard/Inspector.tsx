import { useEffect, useState } from "react";
import { api } from "../api";
import type { InspectionView } from "../generated/local-api";
import type { Node, State } from "./model";
import { absolute, clampPosition, descendants } from "./model";
import type { Mode } from "./Canvas";
import type { Sources } from "./data";
import { eventsFor, summary, observationFor } from "./data";
import { OfficialStatus } from "./OfficialStatus";

interface Props {
  node: Node;
  state: State;
  data: Sources;
  mode: Mode;
  onChange: (state: State) => void;
  onClose: () => void;
  onNavigate: (view: string) => void;
  onAgent: () => void;
  onRefreshSources: () => void;
}
export function Inspector({
  node,
  state,
  data,
  mode,
  onChange,
  onClose,
  onNavigate,
  onAgent,
  onRefreshSources,
}: Props) {
  const info = summary(node, data);
  const observation = observationFor(node, data);
  const [evidence, setEvidence] = useState<InspectionView | null>(null);
  const [error, setError] = useState("");
  const [target, setTarget] = useState("");
  const [label, setLabel] = useState("Related to");
  const [relationType, setRelationType] =
    useState<State["relations"][number]["type"]>("association");
  useEffect(() => {
    setEvidence(null);
    setError("");
    setTarget("");
  }, [node.id]);
  function update(patch: Partial<Node>) {
    onChange({
      ...state,
      components: state.components.map((n) =>
        n.id === node.id ? { ...n, ...patch } : n,
      ),
    });
  }
  const runs = (data.runs?.items ?? []).filter(
    (run) => !node.binding?.entityId || node.binding.entityId === run.runId,
  );
  const related = state.relations.filter(
    (edge) => edge.source === node.id || edge.target === node.id,
  );
  const children = descendants(node.id, state.components);
  async function inspect(id: string) {
    setError("");
    try {
      setEvidence(await api.inspect("event", id));
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Cannot inspect source",
      );
    }
  }
  return (
    <aside className="map-inspector" aria-label="Component details">
      <div className="map-panel-heading">
        <span className="map-eyebrow">
          {mode === "edit" ? "EDIT COMPONENT" : "DETAILS"}
        </span>
        <button type="button" aria-label="Close details" onClick={onClose}>
          ×
        </button>
      </div>
      <h2>{node.title}</h2>
      <p className={`map-status tone-${info.tone}`}>{info.status}</p>
      <p>{info.detail}</p>
      {node.type === "provider" && node.binding?.source === "telemetry" && (
        <OfficialStatus
          key={`${node.id}:${node.binding.sourceId}`}
          sourceId={node.binding.sourceId}
          onRefreshed={onRefreshSources}
        />
      )}
      {mode === "edit" ? (
        <>
          <label>
            Title
            <input
              value={node.title}
              maxLength={160}
              onChange={(event) => update({ title: event.target.value })}
            />
          </label>
          <label>
            Context
            <textarea
              aria-label="Context"
              rows={3}
              value={node.body ?? ""}
              maxLength={4000}
              onChange={(event) => update({ body: event.target.value })}
            />
          </label>
          <label className="map-check">
            <input
              type="checkbox"
              checked={node.pinned ?? false}
              onChange={(event) => update({ pinned: event.target.checked })}
            />
            Pin position and identity against Agent edits
          </label>
          <div className="map-fields">
            {(["x", "y", "width", "height"] as const).map((key) => (
              <label key={key}>
                {key}
                <input
                  type="number"
                  value={Math.round(node.position[key])}
                  disabled={node.pinned}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    if (Number.isFinite(value))
                      update({
                        position: clampPosition(node, state.components, {
                          ...node.position,
                          [key]: value,
                        }),
                      });
                  }}
                />
              </label>
            ))}
          </div>
          {node.binding?.source === "telemetry" && (
            <label>
              Observation source
              <select
                value={node.binding.sourceId ?? ""}
                onChange={(event) =>
                  update({
                    binding: {
                      ...node.binding!,
                      sourceId: event.target.value || null,
                    },
                  })
                }
              >
                <option value="">Match this category (only if unique)</option>
                {data.observations.map((item) => (
                  <option key={item.sourceId} value={item.sourceId}>
                    {item.title} · {item.sourceId}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            Contained in
            <select
              value={node.parentId ?? ""}
              disabled={node.pinned}
              onChange={(event) => {
                const parent = state.components.find(
                  (n) => n.id === event.target.value,
                );
                const p = absolute(node, state.components);
                const pp = parent
                  ? absolute(parent, state.components)
                  : { x: 0, y: 0 };
                const reparented = { ...node, parentId: parent?.id ?? null };
                update({
                  parentId: reparented.parentId,
                  position: clampPosition(reparented, state.components, {
                    ...node.position,
                    x: p.x - pp.x,
                    y: p.y - pp.y,
                  }),
                });
              }}
            >
              <option value="">Map root</option>
              {state.components
                .filter(
                  (n) =>
                    n.type === "group" &&
                    !children.has(n.id) &&
                    n.position.width >= node.position.width &&
                    n.position.height >= node.position.height + 48,
                )
                .map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.title}
                  </option>
                ))}
            </select>
          </label>
          {node.type !== "group" && (
            <>
              <label>
                Data source
                <select
                  value={node.binding?.source ?? ""}
                  onChange={(event) => {
                    const source = event.target.value as NonNullable<
                      Node["binding"]
                    >["source"];
                    update({ binding: source ? { source } : null });
                  }}
                >
                  <option value="">Human context</option>
                  {["workspace", "runs", "research", "events", "telemetry"].map(
                    (source) => (
                      <option key={source}>{source}</option>
                    ),
                  )}
                </select>
              </label>
              {node.binding && (
                <label>
                  Entity ID (optional)
                  <input
                    value={node.binding.entityId ?? ""}
                    maxLength={128}
                    onChange={(event) =>
                      update({
                        binding: {
                          ...node.binding!,
                          entityId: event.target.value || null,
                        },
                      })
                    }
                  />
                </label>
              )}
              <label>
                Presentation
                <select
                  value={node.renderer ?? "summary"}
                  onChange={(event) =>
                    update({
                      renderer: event.target.value as NonNullable<
                        Node["renderer"]
                      >,
                    })
                  }
                >
                  {["summary", "metric", "table", "chart", "timeline"].map(
                    (renderer) => (
                      <option key={renderer}>{renderer}</option>
                    ),
                  )}
                </select>
              </label>
            </>
          )}
          <h3>View relationship</h3>
          <p className="map-small">
            This annotation explains your arrangement. It does not change
            execution dependencies.
          </p>
          <label>
            Connect to
            <select
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            >
              <option value="">Choose a component</option>
              {state.components
                .filter((n) => n.id !== node.id)
                .map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.title}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Relationship type
            <select
              value={relationType}
              onChange={(event) =>
                setRelationType(event.target.value as typeof relationType)
              }
            >
              <option value="association">Association</option>
              <option value="dependency">Dependency</option>
              <option value="evidence">Evidence</option>
              <option value="shared">Shared resource</option>
              <option value="peer">Peer</option>
            </select>
          </label>
          <label>
            Relationship label
            <input
              value={label}
              maxLength={100}
              onChange={(event) => setLabel(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={!target || !label}
            onClick={() => {
              onChange({
                ...state,
                relations: [
                  ...state.relations,
                  {
                    id: crypto.randomUUID(),
                    source: node.id,
                    target,
                    type: relationType,
                    label,
                    scope: "view",
                  },
                ],
              });
              setTarget("");
            }}
          >
            Add arrow
          </button>
          <button
            type="button"
            className="map-danger"
            onClick={() => {
              onChange({
                ...state,
                components: state.components.filter((n) => !children.has(n.id)),
                relations: state.relations.filter(
                  (edge) =>
                    !children.has(edge.source) && !children.has(edge.target),
                ),
              });
              onClose();
            }}
          >
            Remove{" "}
            {node.type === "group" ? "group and its components" : "component"}
          </button>
        </>
      ) : (
        <>
          {node.type === "group" && (
            <p>
              {children.size - 1} contained components. Collapse this region to
              focus elsewhere.
            </p>
          )}
          {node.binding?.source === "runs" && (
            <>
              <h3>Observed lifecycle</h3>
              <div className="map-bars" aria-label="Run observations">
                {[
                  "running",
                  "queued",
                  "succeeded",
                  "failed",
                  "unknown",
                  "lost",
                  "cancel-requested",
                ].map((status) => {
                  const count = runs.filter(
                    (run) => run.observation === status,
                  ).length;
                  return (
                    <div key={status}>
                      <span>{status}</span>
                      <meter
                        min={0}
                        max={Math.max(1, runs.length)}
                        value={count}
                      />
                      <b>{count}</b>
                    </div>
                  );
                })}
              </div>
              <ul className="map-records">
                {runs.slice(0, 12).map((run) => (
                  <li key={run.runId}>
                    <strong>{run.runId}</strong>
                    <span>
                      {run.observation} · {run.origin}
                    </span>
                    <small>Event sequence {run.lastSequence}</small>
                  </li>
                ))}
              </ul>
              {data.runs?.nextCursor && (
                <p className="map-small">
                  This overview is partial; open Runs to load more.
                </p>
              )}
              <button type="button" onClick={() => onNavigate("runs")}>
                Inspect runs and evidence ↗
              </button>
            </>
          )}
          {node.binding?.source === "events" && (
            <>
              <h3>Recorded activity</h3>
              <ul className="map-records">
                {eventsFor(node, data)
                  .slice(-12)
                  .reverse()
                  .map((event) => (
                    <li key={event.eventId}>
                      <button
                        type="button"
                        onClick={() => void inspect(event.eventId)}
                      >
                        {event.type}
                      </button>
                      <time>{event.occurredAt}</time>
                      <small>{event.runId ?? "Workspace event"}</small>
                    </li>
                  ))}
              </ul>
              {!eventsFor(node, data).length && (
                <p>No matching events in this snapshot.</p>
              )}
              <button
                type="button"
                onClick={() =>
                  onNavigate(node.type === "evaluation" ? "results" : "events")
                }
              >
                Explore{" "}
                {node.type === "evaluation" ? "results" : "event history"} ↗
              </button>
            </>
          )}
          {node.binding?.source === "research" && data.research && (
            <>
              <dl className="map-facts">
                <dt>Open questions</dt>
                <dd>{data.research.openQuestionCount}</dd>
                <dt>Answered</dt>
                <dd>{data.research.answeredQuestionCount}</dd>
                <dt>Decisions</dt>
                <dd>{data.research.decisionCount}</dd>
              </dl>
              <button type="button" onClick={() => onNavigate("research")}>
                Read rationale and evidence ↗
              </button>
            </>
          )}
          {node.type === "provider" && (
            <>
              <h3>Connect provider observations</h3>
              <p>
                Official status, your request success rate, latency and rate
                limits need separate sources. A green provider page cannot prove
                your own requests work.
              </p>
            </>
          )}
          {node.binding?.source === "telemetry" && !observation && (
            <div className="map-empty">
              <strong>No telemetry connected</strong>
              <p>
                No utilization, uptime or spend has been measured for this
                component. Import a timestamped DashboardObservation with
                “researchos dashboard observe --root WORKSPACE
                observation.json”, then select its source in Edit. If several
                sources match, choose one explicitly.
              </p>
            </div>
          )}
          {node.type === "recovery" && (
            <button type="button" onClick={() => onNavigate("environment")}>
              Inspect workspace recovery tools ↗
            </button>
          )}
          {observation && (
            <>
              <h3>Measured context</h3>
              <p>
                {observation.origin} · {observation.reporter}
              </p>
              <p className="map-small">{observation.provenance}</p>
              <p className="map-small">
                Observed {new Date(observation.observedAt).toLocaleString()} ·
                expires {new Date(observation.expiresAt).toLocaleString()}
              </p>
              {observation.metrics?.map((metric) => (
                <div className="map-measure" key={metric.name}>
                  <b>{metric.name}</b>
                  <strong>
                    {metric.value.toLocaleString()} {metric.unit}
                  </strong>
                  <small>{metric.meaning ?? "observed"}</small>
                  {(metric.history?.length ?? 0) > 1 && (
                    <MetricChart
                      values={metric.history ?? []}
                      unit={metric.unit ?? ""}
                    />
                  )}
                </div>
              ))}
              {observation.explanation && (
                <div className="map-context">
                  <b>Interpretation · {observation.explanationAuthor}</b>
                  <p style={{ whiteSpace: "pre-wrap" }}>{observation.explanation}</p>
                  <small>
                    Source-attributed interpretation; inspect the measurements
                    above.
                  </small>
                </div>
              )}
            </>
          )}
          {node.body && node.type !== "note" && (
            <p className="map-context">{node.body}</p>
          )}
          <h3>Relationships</h3>
          {related.length ? (
            related.map((edge) => (
              <p key={edge.id}>
                {state.components.find((n) => n.id === edge.source)?.title} →{" "}
                {edge.label} →{" "}
                {state.components.find((n) => n.id === edge.target)?.title}
                <small className="map-block">
                  User-authored view relationship
                </small>
              </p>
            ))
          ) : (
            <p className="map-small">
              {node.parentId
                ? `Contained in ${state.components.find((n) => n.id === node.parentId)?.title}. `
                : ""}
              No explicit view arrows. Add them in Edit mode when useful.
            </p>
          )}
          <button type="button" className="map-primary" onClick={onAgent}>
            ✦ Ask your Agent about this
          </button>
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {evidence && (
        <section>
          <h3>Source evidence</h3>
          <p>Immutable recorded event · {evidence.identity}</p>
          <pre>{JSON.stringify(evidence.document, null, 2)}</pre>
        </section>
      )}
      <footer className="map-source">
        {node.binding
          ? `Source: ${node.binding.source}`
          : "Source: user-authored context"}
        <br />
        {data.sampledAt
          ? `Snapshot fetched ${new Date(data.sampledAt).toLocaleTimeString()}`
          : "Source snapshot pending"}
      </footer>
    </aside>
  );
}

function MetricChart({
  values,
  unit,
}: {
  values: ReadonlyArray<{ at: string; value: number }>;
  unit: string;
}) {
  const min = Math.min(...values.map((point) => point.value)),
    max = Math.max(...values.map((point) => point.value));
  const first = values[0],
    last = values.at(-1);
  if (!first || !last) return null;
  const duration = Date.parse(last.at) - Date.parse(first.at) || 1;
  const points = values
    .map(
      (point) =>
        `${35 + ((Date.parse(point.at) - Date.parse(first.at)) * 235) / duration},${80 - ((point.value - min) * 60) / (max - min || 1)}`,
    )
    .join(" ");
  return (
    <figure className="map-chart">
      <svg
        viewBox="0 0 290 115"
        role="img"
        aria-label={`${unit} from ${min} to ${max} between ${first.at} and ${last.at}`}
      >
        <path
          d="M35 12V82H272"
          fill="none"
          stroke="currentColor"
          opacity=".2"
        />
        <polyline
          points={points}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        />
        <text x="0" y="20">
          {max}
        </text>
        <text x="0" y="82">
          {min}
        </text>
        <text x="35" y="105">
          {new Date(first.at).toLocaleTimeString()}
        </text>
        <text x="270" y="105" textAnchor="end">
          {new Date(last.at).toLocaleTimeString()}
        </text>
      </svg>
      <figcaption>{unit} · timestamped samples</figcaption>
    </figure>
  );
}
