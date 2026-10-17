import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { api } from "../api";
import type { DashboardDocument, DashboardWrite } from "../generated/local-api";
import { Canvas } from "./Canvas";
import { ResearchBrief, appendBrief, emptyBrief } from "./ResearchBrief";
import type { Mode } from "./Canvas";
import { Inspector } from "./Inspector";
import { AgentPanel, download } from "./AgentPanel";
import { useSources } from "./data";
import { absolute, normalize, presets, starter } from "./model";
import type { State } from "./model";
import "./dashboard.css";

interface Props {
  active: boolean;
  projectId: string;
  onNavigate: (view: string) => void;
}
export function Dashboard({ active, projectId, onNavigate }: Props) {
  const [saved, setSaved] = useState<DashboardDocument | null>(null);
  const [state, setState] = useState<State>(starter);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Mode>("browse");
  const [selected, setSelected] = useState<string | null>(null);
  const [relations, setRelations] = useState(false);
  const [query, setQuery] = useState("");
  const [panel, setPanel] = useState<
    "none" | "add" | "appearance" | "ai" | "help" | "history" | "brief"
  >("none");
  const [briefDraft, setBriefDraft] = useState(emptyBrief);
  const [briefId, setBriefId] = useState<string | null>(null);
  const briefComplete = !!briefId && !!saved?.state?.components?.some(n => n.id === briefId);
  const briefDirty = !briefComplete && Object.values(briefDraft).some(value => value.trim());
  const [history, setHistory] = useState<ReadonlyArray<State>>([]);
  const [restoreRevision, setRestoreRevision] = useState(0);
  const pending = useRef<DashboardWrite | null>(null);
  const { data, busy: refreshing, refresh } = useSources(active);
  const node = state.components.find((n) => n.id === selected);
  const dirty =
    loaded &&
    JSON.stringify(state) !== JSON.stringify(normalize(saved?.state ?? {}));
  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const doc = await api.dashboard();
      setSaved(doc);
      setState(
        (doc.revision ?? 0) === 0 ? starter() : normalize(doc.state ?? {}),
      );
      setLoaded(true);
      setHistory([]);
      pending.current = null;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Map unavailable");
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!dirty && !briefDirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, briefDirty]);
  function change(next: State, remember = true) {
    if (busy || pending.current) return;
    if (remember) setHistory((old) => [...old.slice(-29), state]);
    setState({
      ...next,
      viewport: {
        x: Math.max(-200000, Math.min(200000, next.viewport.x)),
        y: Math.max(-200000, Math.min(200000, next.viewport.y)),
        zoom: Math.max(0.1, Math.min(2, next.viewport.zoom)),
      },
    });
    setNotice("");
  }
  async function save(request?: DashboardWrite) {
    if (busy) return;
    const write = request ??
      pending.current ?? {
        apiVersion: "researchos.dev/dashboard/v0alpha1",
        kind: "DashboardWrite",
        projectId,
        requestId: crypto.randomUUID(),
        expectedRevision: saved?.revision ?? 0,
        author: "workspace operator",
        authorKind: "human",
        state,
      };
    pending.current = write;
    setBusy(true);
    setError("");
    try {
      const doc = await api.saveDashboard(write);
      setSaved(doc);
      setState(normalize(doc.state ?? {}));
      pending.current = null;
      setHistory([]);
      setNotice(`Saved revision ${doc.revision}`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }
  async function createBrief() {
    if (busy) return;
    if (pending.current) { await save(); return; }
    try {
      const id = `brief.${crypto.randomUUID()}`;
      const next = appendBrief(state, briefDraft, id);
      setBriefId(id);
      await save({
        apiVersion: "researchos.dev/dashboard/v0alpha1", kind: "DashboardWrite",
        projectId, requestId: crypto.randomUUID(), expectedRevision: saved?.revision ?? 0,
        author: "workspace operator", authorKind: "human", state: next,
      });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not prepare the brief");
    }
  }
  function focus(id: string) {
    const found = state.components.find((n) => n.id === id);
    if (!found) return;
    const pos = absolute(found, state.components);
    const ancestors = new Set<string>();
    let parent = found.parentId;
    while (parent && !ancestors.has(parent)) {
      ancestors.add(parent);
      parent = state.components.find((n) => n.id === parent)?.parentId;
    }
    setSelected(id);
    setPanel("none");
    change(
      {
        ...state,
        components: state.components.map((n) =>
          ancestors.has(n.id) ? { ...n, collapsed: false } : n,
        ),
        viewport: {
          ...state.viewport,
          x: 80 - pos.x * state.viewport.zoom,
          y: 100 - pos.y * state.viewport.zoom,
        },
      },
      false,
    );
  }
  function agent(id?: string) {
    if (id) setSelected(id);
    setMode("ai");
    setPanel("ai");
  }
  const matched = query
    ? state.components.filter((n) =>
        `${n.title} ${n.type} ${n.body ?? ""}`
          .toLowerCase()
          .includes(query.toLowerCase()),
      )
    : [];
  const running = data.runs?.items.filter(
    (run) => run.observation === "running",
  ).length;
  const attention = data.runs?.items.filter((run) =>
    ["unknown", "lost", "failed", "cancel-requested"].includes(
      run.observation ?? "absent",
    ),
  ).length;
  const style = {
    "--map-bg":
      state.appearance.skin === "custom"
        ? state.appearance.background
        : undefined,
    "--map-accent":
      state.appearance.skin === "custom" ? state.appearance.accent : undefined,
    "--map-scale": state.appearance.textScale,
  } as CSSProperties;
  return (
    <section
      className={`dashboard skin-${state.appearance.skin} density-${state.appearance.density}`}
      style={style}
      aria-label="Research workspace dashboard"
    >
      <header className="map-header">
        <div>
          <div className="map-eyebrow">
            YOUR RESEARCH STUDIO <span> / {projectId}</span>
          </div>
          <h2>One workspace. The whole picture.</h2>
          <p>
            Follow the work, understand the evidence, decide what comes next.
          </p>
        </div>
        <div className="map-header-actions">
          <button type="button" onClick={() => setPanel("brief")}>Research brief</button>
          <button
            type="button"
            onClick={() =>
              setPanel(panel === "appearance" ? "none" : "appearance")
            }
          >
            ◐ Appearance
          </button>
          <button
            type="button"
            onClick={() => setPanel(panel === "help" ? "none" : "help")}
          >
            Quick guide
          </button>
          <button
            type="button"
            className="map-primary"
            disabled={!loaded || busy || (!dirty && !pending.current)}
            onClick={() => void save()}
          >
            {busy
              ? "Saving…"
              : pending.current
                ? "Retry same save"
                : "Save map"}
          </button>
        </div>
      </header>
      {loaded && (saved?.revision ?? 0) === 0 && panel !== "brief" && (
        <div className="map-first-use">
          <div><strong>Start with your research question.</strong><p>Create a brief, then use the map to prepare materials, resources and your next decision.</p></div>
          <button type="button" className="map-primary" onClick={() => setPanel("brief")}>Create my first brief</button>
        </div>
      )}
      <div className="map-situation">
        <div>
          <span className="map-dot tone-active" />
          <strong>{running ?? "—"}</strong> recorded running
        </div>
        <div>
          <span className="map-dot tone-attention" />
          <strong>{attention ?? "—"}</strong> to inspect
        </div>
        <div>
          <strong>{data.research?.openQuestionCount ?? "—"}</strong> open
          questions
        </div>
        <span className="map-snapshot">
          {data.runs?.nextCursor ? "Partial run overview · " : ""}
          {data.sampledAt
            ? `Snapshot ${new Date(data.sampledAt).toLocaleTimeString()}`
            : "Loading sources…"}
        </span>
        <button
          type="button"
          disabled={refreshing}
          onClick={() => void refresh()}
        >
          {refreshing ? "Refreshing…" : "Refresh data"}
        </button>
      </div>
      <div className="map-commandbar">
        <div className="map-search">
          <span>⌕</span>
          <input
            aria-label="Find a component"
            placeholder="Find an experiment, resource, service…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {query && (
            <div className="map-search-results">
              {matched.length ? (
                matched.slice(0, 30).map((n) => (
                  <button
                    type="button"
                    key={n.id}
                    onClick={() => {
                      focus(n.id);
                      setQuery("");
                    }}
                  >
                    {n.title}
                    <small>{n.type}</small>
                  </button>
                ))
              ) : (
                <p>No matching components</p>
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          aria-pressed={relations}
          onClick={() => setRelations(!relations)}
        >
          ↗ {relations ? "Hide" : "Show"} relationships
        </button>
        <span className="map-save-state">
          {dirty ? "Unsaved arrangement" : `Revision ${saved?.revision ?? 0}`}
        </span>
        <button
          type="button"
          aria-label="Map history"
          onClick={() => setPanel(panel === "history" ? "none" : "history")}
        >
          ↶ History
        </button>
      </div>
      {(error || notice) && (
        <div
          className={`map-message ${error ? "map-message-error" : ""}`}
          role={error ? "alert" : "status"}
        >
          {error || notice}
          {error && (
            <>
              <button
                type="button"
                onClick={() =>
                  download(
                    "unsaved-map.json",
                    pending.current ?? { projectId, state },
                  )
                }
              >
                Export local changes
              </button>
              <button type="button" onClick={() => void load()}>
                Reload saved map
              </button>
            </>
          )}
        </div>
      )}
      <div className="map-workspace">
        <aside className="map-toolbox" aria-label="Map tools">
          {(
            [
              { id: "browse", icon: "↖", label: "Browse" },
              { id: "edit", icon: "✎", label: "Edit" },
              { id: "ai", icon: "✦", label: "AI" },
            ] as const
          ).map((tool) => (
            <button
              type="button"
              key={tool.id}
              aria-label={tool.label}
              aria-pressed={mode === tool.id}
              onClick={() => {
                setMode(tool.id);
                setPanel(tool.id === "ai" ? "ai" : "none");
              }}
            >
              <span>{tool.icon}</span>
              {tool.label}
            </button>
          ))}
          <hr />
          <button
            type="button"
            aria-label="Add component"
            onClick={() => {
              setMode("edit");
              setPanel(panel === "add" ? "none" : "add");
            }}
          >
            <span>+</span>Add
          </button>
          <button
            type="button"
            aria-label="Undo"
            disabled={!history.length || busy || !!pending.current}
            onClick={() => {
              const previous = history.at(-1);
              if (previous) {
                setState(previous);
                setHistory(history.slice(0, -1));
              }
            }}
          >
            <span>↶</span>Undo
          </button>
        </aside>
        {loaded ? (
          <Canvas
            autoFit={(saved?.revision ?? 0) === 0}
            state={state}
            data={data}
            mode={mode}
            selected={selected}
            relations={relations}
            query={query}
            onSelect={(id) => {
              setSelected(id);
              if (mode !== "ai") setPanel("none");
            }}
            onChange={change}
            onAgent={(id) => {
              setSelected(id);
              setMode("browse");
              setPanel("none");
            }}
          />
        ) : (
          <div className="map-loading">
            {error
              ? "Map unavailable. Reload to retry."
              : "Opening your workspace map…"}
          </div>
        )}
        {node && panel === "none" && (
          <Inspector
            node={node}
            state={state}
            data={data}
            mode={mode}
            onChange={change}
            onClose={() => setSelected(null)}
            onNavigate={onNavigate}
            onAgent={() => agent(node.id)}
          />
        )}
        {panel !== "none" && (
          <aside className="map-inspector" aria-label="Map settings">
            <div className="map-panel-heading">
              <span className="map-eyebrow">{panel}</span>
              <button
                type="button"
                aria-label="Close panel"
                onClick={() => setPanel("none")}
              >
                ×
              </button>
            </div>
            {panel === "add" && (
              <>
                <h2>Make this space yours.</h2>
                <p>
                  Choose a component, then adjust its source and presentation.
                </p>
                <div className="map-library">
                  {presets.map((preset) => (
                    <button
                      type="button"
                      key={preset.type}
                      onClick={() => {
                        const id = crypto.randomUUID();
                        change({
                          ...state,
                          components: [
                            ...state.components,
                            {
                              id,
                              title: preset.title,
                              type: preset.type,
                              position: {
                                x: Math.max(
                                  0,
                                  (-state.viewport.x + 160) /
                                    state.viewport.zoom,
                                ),
                                y: Math.max(
                                  0,
                                  (-state.viewport.y + 160) /
                                    state.viewport.zoom,
                                ),
                                width: preset.type === "group" ? 640 : 280,
                                height: preset.type === "group" ? 470 : 190,
                              },
                              ...(preset.source
                                ? { binding: { source: preset.source } }
                                : {}),
                            },
                          ],
                        });
                        setSelected(id);
                        setPanel("none");
                      }}
                    >
                      <span>+</span>
                      {preset.title}
                    </button>
                  ))}
                </div>
              </>
            )}
            {panel === "appearance" && (
              <>
                <h2>A familiar atmosphere.</h2>
                <div className="map-skins">
                  {(["graphite", "paper", "custom"] as const).map((skin) => (
                    <button
                      type="button"
                      key={skin}
                      aria-pressed={state.appearance.skin === skin}
                      onClick={() =>
                        change({
                          ...state,
                          appearance: { ...state.appearance, skin },
                        })
                      }
                    >
                      <span className={`skin-swatch swatch-${skin}`} />
                      {skin === "graphite"
                        ? "Graphite"
                        : skin === "paper"
                          ? "Warm paper"
                          : "Custom"}
                    </button>
                  ))}
                </div>
                {state.appearance.skin === "custom" && (
                  <>
                    {(["background", "accent"] as const).map((key) => (
                      <label key={key}>
                        {key}
                        <input
                          type="color"
                          value={state.appearance[key]}
                          onChange={(event) =>
                            change({
                              ...state,
                              appearance: {
                                ...state.appearance,
                                [key]: event.target.value,
                              },
                            })
                          }
                        />
                      </label>
                    ))}
                  </>
                )}
                <label>
                  Text size
                  <input
                    type="range"
                    min="0.9"
                    max="1.4"
                    step="0.05"
                    value={state.appearance.textScale}
                    onChange={(event) =>
                      change({
                        ...state,
                        appearance: {
                          ...state.appearance,
                          textScale: Number(event.target.value),
                        },
                      })
                    }
                  />
                </label>
                <label>
                  Density
                  <select
                    value={state.appearance.density}
                    onChange={(event) =>
                      change({
                        ...state,
                        appearance: {
                          ...state.appearance,
                          density: event.target.value as
                            | "comfortable"
                            | "compact",
                        },
                      })
                    }
                  >
                    <option value="comfortable">Comfortable</option>
                    <option value="compact">Compact</option>
                  </select>
                </label>
              </>
            )}
            {panel === "help" && (
              <>
                <h2>Your whole studio, in one map.</h2>
                <ol className="map-guide">
                  <li>
                    <b>Get your bearings.</b>
                    <p>
                      Regions contain related work. Numbers come from recorded
                      sources. “Not connected” means no observation is
                      available.
                    </p>
                  </li>
                  <li>
                    <b>Follow a question.</b>
                    <p>
                      Hover for a summary, select for evidence. Open a detailed
                      workbench to execute an operation.
                    </p>
                  </li>
                  <li>
                    <b>Arrange your attention.</b>
                    <p>
                      Edit to drag, resize or group. Pin what should stay in
                      place, then save your map.
                    </p>
                  </li>
                  <li>
                    <b>Ask your Agent.</b>
                    <p>
                      Send a scoped message to your Agent inbox. Review its
                      explanation and proposed changes before applying.
                    </p>
                  </li>
                </ol>
                <button
                  type="button"
                  className="map-primary"
                  onClick={() => setPanel("brief")}
                >
                  Create a research brief
                </button>
              </>
            )}
            {panel === "history" && (
              <>
                <h2>Keep your bearings.</h2>
                <p>
                  Saved revision {saved?.revision ?? 0}. The last 30 saved
                  revisions are retained.
                </p>
                <button
                  type="button"
                  onClick={() =>
                    download("research-map.json", saved ?? { projectId, state })
                  }
                >
                  Export saved map
                </button>
                <label>
                  Revision to restore
                  <input
                    type="number"
                    min={0}
                    max={saved?.revision ?? 0}
                    value={restoreRevision}
                    onChange={(event) =>
                      setRestoreRevision(Number(event.target.value))
                    }
                  />
                </label>
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    try {
                      const old = await api.dashboard(restoreRevision);
                      change(normalize(old.state ?? {}));
                      setNotice(
                        `Revision ${restoreRevision} loaded as an unsaved draft. Save to create a new revision.`,
                      );
                    } catch (failure) {
                      setError(
                        failure instanceof Error
                          ? failure.message
                          : "Revision unavailable",
                      );
                    }
                  }}
                >
                  Load revision as draft
                </button>
                <p className="map-small">
                  Export the map separately with older workspace backup formats.
                </p>
              </>
            )}
            {panel === "brief" && pending.current && !pending.current.state.components?.some(n => n.id === briefId) && (
              <p>Retry the current map save or reload the saved map before creating a brief. Your brief draft stays here.</p>
            )}
            {panel === "brief" && (!pending.current || pending.current.state.components?.some(n => n.id === briefId)) && (
              <ResearchBrief
                draft={briefDraft} onChange={setBriefDraft} busy={busy}
                pending={!!pending.current} complete={briefComplete}
                onSave={() => void createBrief()}
                onView={() => { if (briefId) { setMode("browse"); focus(briefId); } }}
                onAgent={() => { if (briefId) agent(briefId); }}
                onNew={() => { setBriefDraft(emptyBrief()); setBriefId(null); }}
              />
            )}
            {panel === "ai" && (
              <AgentPanel
                active={active}
                projectId={projectId}
                revision={saved?.revision ?? 0}
                state={state}
                selected={selected}
                dirty={dirty}
                busy={busy}
                onApply={(write) => void save(write)}
              />
            )}
          </aside>
        )}
      </div>
      <footer className="map-footer">
        <span>
          ○ Local workspace · View changes never allocate compute or authorize
          execution.
        </span>
        <span>
          {state.components.length} components · {state.relations.length} view
          relations
        </span>
      </footer>
    </section>
  );
}
