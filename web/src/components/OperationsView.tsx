/** Browser operations: preflight, cancel, and revoke through shared commands.
 *
 * R11's honesty rule is enforced here. A command identity is generated once and
 * reused on retry, so a double-click or an uncertain response replays the same
 * receipt instead of appending a second fact. A receipt that says a request was
 * committed is never rendered as a stopped process or a successful launch.
 */

import { useCallback, useRef, useState } from "react";
import { ApiRequestError, api, OfflineError, SessionExpiredError } from "../api";
import { Badge, Empty, KeyValue, Loading } from "./Primitives";
import type { CommandReceipt, RunItem } from "../generated/local-api";
import { presentObservation } from "../format";

/** A stable identity for one operator intent, reused across retries. */
function newCommandId(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replaceAll("-", "")
      : Math.random().toString(36).slice(2);
  return `browser.${prefix}.${random.slice(0, 16)}`;
}

type CommandState =
  | { readonly status: "idle" }
  | { readonly status: "sending"; readonly commandId: string }
  | { readonly status: "settled"; readonly receipt: CommandReceipt }
  | { readonly status: "uncertain"; readonly commandId: string; readonly detail: string }
  | { readonly status: "refused"; readonly detail: string };

function post(body: string): Promise<CommandReceipt> {
  return api.command(body);
}

export function OperationsView({ expectedHead: initialHead }: { readonly expectedHead: number }) {
  const [expectedHead, setExpectedHead] = useState(initialHead);
  const [inspected, setInspected] = useState<{profileId:string; digest:string} | null>(null);
  const [state, setState] = useState<CommandState>({ status: "idle" });
  const [requestPath, setRequestPath] = useState("");
  const [specPath, setSpecPath] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<{id:string; body:string} | null>(null);
  const sending = useRef(false);
  const [revision, setRevision] = useState(1);
  const [grantId, setGrantId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [runId, setRunId] = useState("");
  const [imageId, setImageId] = useState("");
  const [destinationId, setDestinationId] = useState("");

  const send = useCallback((commandId: string, document: unknown, label: string) => {
    if (sending.current) return;
    sending.current = true;
    const body = JSON.stringify(document);
    pending.current = {id:commandId,body};
    setBusy(true);
    setState({ status: "sending", commandId });
    post(body).then(
      (receipt) => {
        sending.current = false;
        setBusy(false);
        setState({ status: "settled", receipt });
        setExpectedHead(receipt.observedHead);
        if (receipt.operation === "native.inspect") {
          const operation = (document as {operation?:{profileId?:string}}).operation;
          const digest = receipt.result["materialDigest"];
          if (operation?.profileId && typeof digest === "string") {
            setInspected({profileId:operation.profileId, digest});
          }
        }
      },
      (error: unknown) => {
        sending.current = false;
        setBusy(false);
        if (error instanceof SessionExpiredError) {
          setState({
            status: "refused",
            detail: "The local session expired. Bootstrap again before operating.",
          });
          return;
        }
        if (error instanceof OfflineError || (error instanceof ApiRequestError && error.status >= 500)) {
          // The command may or may not have committed. The identity is kept so
          // a retry replays rather than duplicating.
          setState({
            status: "uncertain",
            commandId,
            detail: "The local API did not confirm this request. Retry with the same identity.",
          });
          return;
        }
        setState({
          status: "refused",
          detail: error instanceof Error ? error.message : label,
        });
      },
    );
  }, []);

  const envelope = useCallback(
    (commandId: string, operation: unknown, expectedHead?: number, expectedRevision?: number) => {
      const document: Record<string, unknown> = {
        apiVersion: "researchos.dev/application/v0alpha1",
        kind: "ApplicationCommand",
        commandId,
        actorId: "browser-operator",
        submittedAt: new Date().toISOString(),
        operation,
      };
      if (expectedHead !== undefined) {
        document["expectedHead"] = expectedHead;
      }
      if (expectedRevision !== undefined) {
        document["expectedRevision"] = expectedRevision;
      }
      return document;
    },
    [],
  );

  return (
    <section aria-labelledby="operations-heading">
      <h2 id="operations-heading">Operations</h2>
      <p className="note">
        These actions reuse the same shared services as the CLI, so an event replay or a CLI run sees exactly
        what the browser recorded. The browser cannot create authority: every command below is a document you
        supply, dispatched unchanged.
      </p>

      <p>Observed event head: {expectedHead}. <button type="button" disabled={busy}
        onClick={() => { api.workspace().then(value => setExpectedHead(value.highWaterMark), error =>
          setState({status:"refused", detail: error instanceof Error ? error.message : "Refresh failed"})); }}>
        Refresh event head</button></p>
      <article className="detail">
        <h3>Inspect a plan before authorizing</h3>
        <p className="note">
          A preflight reads only. It reports the plan identity, target, policy, declared resources and the
          limits this build enforces, and it never authorizes or launches anything.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const commandId = newCommandId("preflight");
            send(
              commandId,
              envelope(commandId, { kind: "plan.preflight", document: specPath }, undefined, revision),
              "preflight",
            );
          }}
        >
          <label htmlFor="spec">ResearchSpec path</label>
          <input
            id="spec"
            value={specPath}
            placeholder="path to a spec.yaml file"
            onChange={(event) => setSpecPath(event.target.value)}
          />
          <label htmlFor="revision">Expected revision</label>
          <input id="revision" type="number" min="1" value={revision}
            onChange={event => setRevision(Number(event.target.value))} />
          <button type="submit" disabled={busy || state.status === "uncertain" || specPath.trim() === ""}>
            Preflight
          </button>
        </form>
      </article>

      <article className="detail">
        <h3>Request cancellation</h3>
        <p className="note">
          This records a <strong>request</strong>. It is not an observed stop, and the receipt below will say
          so. A terminal run cannot be reopened; the shared service refuses that.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const commandId = newCommandId("cancel");
            send(
              commandId,
              envelope(
                commandId,
                { kind: "run.cancel", request: requestPath },
                expectedHead,
              ),
              "cancellation",
            );
          }}
        >
          <label htmlFor="request">Cancellation request path</label>
          <input
            id="request"
            value={requestPath}
            placeholder="path to a cancellation request JSON"
            onChange={(event) => setRequestPath(event.target.value)}
          />
          <button type="submit" disabled={busy || state.status === "uncertain" || requestPath.trim() === ""}>
            Request cancellation
          </button>
        </form>
      </article>

      <article className="detail">
        <h3>Revoke unused authority</h3>
        <p className="note">
          Revocation is a control-plane record. It is not a Worker action, and this surface holds no Worker
          credential. It never completes or launches work.
        </p>
        <form onSubmit={event => {
          event.preventDefault();
          const id = newCommandId("revoke");
          send(id, envelope(id, {kind:"authorization.revoke", grantId,
            eventId:`${id}.event`}, expectedHead), "revocation");
        }}>
          <label htmlFor="grant">Unused grant ID</label>
          <input id="grant" value={grantId} onChange={event=>setGrantId(event.target.value)} />
          <button type="submit" disabled={busy || state.status === "uncertain" || !grantId.trim()}>Revoke unused grant</button>
        </form>
      </article>

      <article className="detail">
        <h3>Execute reviewed native work</h3>
        <p className="note">The operator installs the profile, credentials and reviewed material outside
          this form. Start consumes its existing grant. Checkpoint restore requires a completed source,
          compatible state and a new authorized Run. If a response is uncertain, observe this identity.</p>
        <label htmlFor="native-profile">Installed native profile ID</label>
        <input id="native-profile" value={profileId} onChange={e => setProfileId(e.target.value)} />
        {(["inspect", "start", "restore", "observe"] as const).map(action => <button key={action} type="button"
          disabled={busy || state.status === "uncertain" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(profileId)
            || ((action === "start" || action === "restore") && inspected?.profileId !== profileId)}
          onClick={() => {
            const id = newCommandId(action);
            send(id, envelope(id, {kind:`native.${action}`, profileId,
              ...((action === "start" || action === "restore") ? {materialDigest:inspected?.digest} : {})},
              (action === "observe" || action === "inspect") ? undefined : expectedHead,
              (action === "observe" || action === "inspect") ? undefined : revision), action);
          }}>{action === "inspect" ? "Inspect installed work" : action === "start" ? "Start reviewed work" : action === "restore" ? "Restore checkpoint" : "Observe existing work"}</button>)}
      </article>
      <article className="detail">
        <h3>Reconnect to a Run</h3>
        <p className="note">Read the existing event-derived Run after a disconnect. This does not launch,
          poll a Worker or infer completion from request acceptance.</p>
        <form onSubmit={event => {
          event.preventDefault();
          const id = newCommandId("reconnect");
          send(id, envelope(id, {kind:"run.show", runId}, expectedHead), "reconnect");
        }}>
          <label htmlFor="reconnect-run">Existing Run ID</label>
          <input id="reconnect-run" value={runId} onChange={e => setRunId(e.target.value)} />
          <button type="submit" disabled={busy || state.status === "uncertain" || !runId.trim()}>Reconnect and read Run</button>
        </form>
      </article>
      <article className="detail">
        <h3>Verify or restore a backup</h3>
        <p className="note">The operator stages images under backups/. Restore creates a new workspace
          under restored/ and leaves historical active work unknown for reconciliation. It starts nothing.</p>
        <label htmlFor="backup-image">Staged backup image ID</label>
        <input id="backup-image" value={imageId} onChange={e => setImageId(e.target.value)} />
        <label htmlFor="restore-destination">New restored workspace ID</label>
        <input id="restore-destination" value={destinationId} onChange={e => setDestinationId(e.target.value)} />
        {(["verify", "restore"] as const).map(action => <button key={action} type="button"
          disabled={busy || state.status === "uncertain" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(imageId)
            || (action === "restore" && !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(destinationId))}
          onClick={() => {
            const id = newCommandId(`backup-${action}`);
            send(id, envelope(id, {kind:`backup.${action}`, imageId,
              ...(action === "restore" ? {destinationId} : {})},
              action === "restore" ? expectedHead : undefined), action);
          }}>{action === "verify" ? "Verify backup" : "Restore backup to new workspace"}</button>)}
      </article>

      <Outcome state={state} onRetry={() => {
        const request = pending.current;
        if (request) send(request.id, JSON.parse(request.body), "retry");
      }} />
    </section>
  );
}

function Outcome({
  state,
  onRetry,
}: {
  readonly state: CommandState;
  readonly onRetry: () => void;
}) {
  if (state.status === "idle") {
    return (
      <Empty
        title="No command sent"
        detail="Inspect a plan, execute installed reviewed work, reconnect, or verify a backup. Preflight records a receipt; cancellation and revocation record domain facts."
      />
    );
  }
  if (state.status === "sending") {
    return <Loading label={`Sending ${state.commandId}`} />;
  }
  if (state.status === "uncertain") {
    return (
      <div className="state state--error" role="alert">
        <h3>Outcome not confirmed</h3>
        <p>{state.detail}</p>
        <p className="note">
          Command identity <code>{state.commandId}</code> is retained. Sending it again replays the prior
          receipt if it committed, and does not repeat an already committed fact.
        </p>
        <button type="button" onClick={onRetry}>
          Retry same command
        </button>
      </div>
    );
  }
  if (state.status === "refused") {
    return (
      <div className="state state--error" role="alert">
        <h3>Command refused</h3>
        <p>{state.detail}</p>
        <p className="note">Inspect or observe an uncertain dispatch before making another intent.</p>
      </div>
    );
  }

  const { receipt } = state;
  const result = receipt.result as Record<string, unknown>;
  const isCancel = receipt.operation === "run.cancel";
  const observedStop = result["observedStop"] === true;
  const launchAllowed = result["launchAllowed"] === true;
  return (
    <div className="detail">
      <h3>Receipt</h3>
      <pre>{JSON.stringify(receipt.result, null, 2).slice(0, 65536)}</pre>
      <KeyValue
        items={[
          ["Command", <code key="c">{receipt.commandId}</code>],
          ["Operation", receipt.operation],
          [
            "Disposition",
            <Badge key="d" tone={receipt.disposition === "committed" ? "progress" : "neutral"}>
              {receipt.disposition === "committed" ? "Committed" : "Replayed (no new fact)"}
            </Badge>,
          ],
          ["Observed head", String(receipt.observedHead)],
          ["Result digest", <code key="r">{receipt.resultDigest.slice(0, 20)}…</code>],
          [
            "Facts appended",
            receipt.factEventIds.length === 0
              ? "None"
              : receipt.factEventIds.map((id) => <code key={id}>{id}</code>),
          ],
        ]}
      />
      {isCancel ? (
        <p className="note">
          {observedStop ? (
            <Badge tone="warning">Observed stop</Badge>
          ) : (
            <Badge tone="warning">Request recorded — no observed stop</Badge>
          )}{" "}
          A cancellation request is not an outcome. Watch the run index for the eventual observed state; until
          then the run remains in whatever state its facts support.
        </p>
      ) : null}
      {receipt.operation === "authorization.revoke" ? (
        <p className="note">
          <Badge tone="neutral">Authority revoked</Badge> Revocation does not launch, complete or stop
          anything.
        </p>
      ) : null}
      {launchAllowed ? (
        <p className="note">
          <Badge tone="warning">launchAllowed reported true</Badge> No command in this surface may report
          launch authority.
        </p>
      ) : null}
      {receipt.disposition === "replayed" ? (
        <p className="note">
          This command had already been committed. The receipt was replayed, so no second fact exists.
        </p>
      ) : null}
    </div>
  );
}

export { presentObservation, type RunItem };
