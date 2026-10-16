import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type {
  AgentAsk,
  AgentTask,
  DashboardWrite,
} from "../generated/local-api";
import { descendants } from "./model";
import type { State } from "./model";

export function download(name: string, value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
interface Props {
  active: boolean;
  projectId: string;
  revision: number;
  state: State;
  selected: string | null;
  dirty: boolean;
  busy: boolean;
  onApply: (write: DashboardWrite) => void;
}
export function AgentPanel({
  active,
  projectId,
  revision,
  state,
  selected,
  dirty,
  busy,
  onApply,
}: Props) {
  const [prompt, setPrompt] = useState("");
  const [tasks, setTasks] = useState<ReadonlyArray<AgentTask>>([]);
  const [proposal, setProposal] = useState<DashboardWrite | null>(null);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const pending = useRef<AgentAsk | null>(null);
  const node = state.components.find((n) => n.id === selected);
  useEffect(() => {
    if (!active) return;
    let live = true;
    const refresh = async () => {
      try {
        const inbox = await api.agentInbox();
        if (live) setTasks(inbox.tasks);
      } catch (failure) {
        if (live)
          setError(
            failure instanceof Error
              ? failure.message
              : "Agent inbox unavailable",
          );
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [active]);
  async function send() {
    if (sending) return;
    const request = pending.current ?? {
      kind: "DashboardAgentAsk",
      projectId,
      requestId: crypto.randomUUID(),
      expectedRevision: revision,
      scope: selected ? [...descendants(selected, state.components)] : null,
      prompt,
    };
    pending.current = request;
    setSending(true);
    setError("");
    try {
      const task = await api.askAgent(request);
      setTasks((old) => [
        task,
        ...old.filter((t) => t.request.requestId !== task.request.requestId),
      ]);
      pending.current = null;
      setPrompt("");
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Request could not be sent",
      );
    } finally {
      setSending(false);
    }
  }
  return (
    <>
      <h2>Compose with your Agent.</h2>
      <p className="map-context">
        Next message: <b>{node?.title ?? "Whole map"}</b>
      </p>
      <p>
        Your own Agent reads this workspace inbox. Each message keeps its saved
        revision and scope; replies appear here without changing your map.
      </p>
      <details className="map-agent-connect">
        <summary>Connect your Agent</summary>
        <p>
          Ask your Agent to read and follow the dashboard protocol, then poll:
        </p>
        <code>researchos dashboard inbox --root WORKSPACE</code>
        <p>It can return an explanation and optional DashboardWrite:</p>
        <code>researchos dashboard reply --root WORKSPACE reply.json</code>
        <p>No model provider is configured or called by this inbox.</p>
      </details>
      <label>
        Message to your Agent
        <textarea
          rows={4}
          maxLength={4000}
          value={prompt}
          disabled={sending || !!pending.current}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Bring shared compute next to the experiments that use it."
        />
      </label>
      <button
        type="button"
        className="map-primary"
        disabled={
          (!prompt.trim() && !pending.current) || dirty || busy || sending
        }
        onClick={() => void send()}
      >
        {sending
          ? "Sending…"
          : pending.current
            ? "Retry same message"
            : "Send to Agent inbox"}
      </button>
      {dirty && (
        <p className="map-small">
          Save the arrangement first to bind this message to a stable revision.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {!tasks.length && (
        <div className="map-empty">
          <b>No messages yet</b>
          <p>
            Describe what you want to understand or change. Messages wait here
            until your Agent responds.
          </p>
        </div>
      )}
      {tasks.map((task) => (
        <div className="map-chat" key={task.request.requestId}>
          <b>You · revision {task.request.expectedRevision}</b>
          <p>{task.request.prompt}</p>
          <small>
            Frozen scope:{" "}
            {task.request.scope
              ?.map(
                (id) =>
                  task.snapshot.state?.components?.find((n) => n.id === id)
                    ?.title ?? id,
              )
              .join(", ") ?? "Whole map"}
          </small>
          {task.reply ? (
            <>
              <hr />
              <b>{task.reply.author}</b>
              <p className="map-reply">{task.reply.message}</p>
              {task.reply.proposal && (
                <button
                  type="button"
                  onClick={() => setProposal(task.reply?.proposal ?? null)}
                >
                  Review proposed changes
                </button>
              )}
            </>
          ) : (
            <p className="map-small">
              Waiting for your Agent. No activity is inferred from a pending
              message.
            </p>
          )}
          <button
            type="button"
            className="map-export"
            onClick={() => download("map-agent-request.json", task)}
          >
            Export context
          </button>
        </div>
      ))}
      {proposal && (
        <div className="map-proposal">
          <h3>Proposed composition</h3>
          <p>
            {proposal.state.components?.length ?? 0} components ·{" "}
            {proposal.state.relations?.length ?? 0} relationships
          </p>
          <ul>
            {proposal.state.components
              ?.filter(
                (n) =>
                  JSON.stringify(n) !==
                  JSON.stringify(
                    state.components.find((old) => old.id === n.id),
                  ),
              )
              .map((n) => (
                <li key={n.id}>
                  {state.components.some((old) => old.id === n.id)
                    ? "Update"
                    : "Add"}
                  : {n.title}
                </li>
              ))}
            {state.components
              .filter(
                (n) =>
                  !proposal.state.components?.some((next) => next.id === n.id),
              )
              .map((n) => (
                <li key={n.id}>Remove: {n.title}</li>
              ))}
          </ul>
          <details>
            <summary>Inspect full proposal</summary>
            <pre>{JSON.stringify(proposal, null, 2)}</pre>
          </details>
          <p>
            The server checks scope and pins. A newer revision causes a
            conflict.
          </p>
          {proposal.expectedRevision !== revision && (
            <p role="alert">
              This proposal is stale. Ask your Agent to review the latest map.
            </p>
          )}
          <button
            type="button"
            className="map-primary"
            disabled={busy || dirty || proposal.expectedRevision !== revision}
            onClick={() => onApply(proposal)}
          >
            Apply reviewed Agent proposal
          </button>
          <button type="button" onClick={() => setProposal(null)}>
            Dismiss preview
          </button>
        </div>
      )}
    </>
  );
}
