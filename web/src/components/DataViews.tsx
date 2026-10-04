/** Run, event, log, metric and artifact views. */

import { useCallback, useState } from "react";
import { api } from "../api";
import {
  formatBytes,
  formatTime,
  isReportableOutcome,
  isSuccessful,
  presentObservation,
  presentOrigin,
  originTone,
  shortDigest,
} from "../format";
import { Badge, BoundedList, Code, Empty, Failure, KeyValue, Loading } from "./Primitives";
import { usePage } from "./usePage";
import type { EventItem, RunItem } from "../generated/local-api";
import type { Paged } from "../api";

const PAGE_LIMIT = 50;
const LIST_CAP = 200;

export function RunsView() {
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const load = useCallback((next: string | null) => api.runs(next, PAGE_LIMIT), []);
  const { page, error, reload } = usePage<RunItem>(load, cursor);

  if (error !== null) {
    return <Failure error={error} onRetry={reload} />;
  }
  if (page === null) {
    return <Loading label="Loading runs" />;
  }
  if (page.items.length === 0) {
    return (
      <Empty
        title="No runs recorded"
        detail="A run appears here once a run lifecycle fact is appended to this project's event store."
      />
    );
  }
  return (
    <section aria-labelledby="runs-heading">
      <h2 id="runs-heading">Runs</h2>
      <p className="note">
        The index is newest-first. A run whose outcome was never observed stays unknown, and a cancellation
        request is shown as a request rather than as a stop.
      </p>
      <BoundedList
        items={page.items}
        cap={LIST_CAP}
        totalLabel="runs"
        row={(item) => {
          const state = presentObservation(item.observation);
          return (
            <tr key={item.runId} className={selected === item.runId ? "row row--selected" : "row"}>
              <td>
                <button
                  type="button"
                  className="linkish"
                  aria-expanded={selected === item.runId}
                  onClick={() => setSelected(selected === item.runId ? null : item.runId)}
                >
                  {item.runId}
                </button>
              </td>
              <td>{item.lastEventType}</td>
              <td>{item.lastSequence}</td>
              <td>
                <Badge tone={state.tone}>{state.label}</Badge>
              </td>
              <td>
                <Badge tone={originTone(item.origin)}>{presentOrigin(item.origin)}</Badge>
              </td>
            </tr>
          );
        }}
      />
      {page.nextCursor !== null ? (
        <button type="button" onClick={() => setCursor(page.nextCursor)}>
          Older runs
        </button>
      ) : null}
      {selected === null ? null : (
        <RunDetail runId={selected} onClose={() => setSelected(null)} />
      )}
    </section>
  );
}

function RunDetail({ runId, onClose }: { readonly runId: string; readonly onClose: () => void }) {
  const load = useCallback(async (): Promise<Paged<EventItem>> => {
    const collected: Array<EventItem> = [];
    let cursor: string | null = null;
    for (let page = 0; page < 5; page += 1) {
      const result = await api.events(cursor, PAGE_LIMIT);
      collected.push(...result.items.filter((item) => item.runId === runId));
      if (result.nextCursor === null) {
        break;
      }
      cursor = result.nextCursor;
    }
    return { items: collected, nextCursor: null, highWaterMark: 0 };
  }, [runId]);
  const { page, error, reload } = usePage<EventItem>(load, null);

  return (
    <article className="detail" aria-label={`Run ${runId}`}>
      <header className="detail__head">
        <h3>{runId}</h3>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </header>
      {error !== null ? <Failure error={error} onRetry={reload} /> : null}
      {page === null && error === null ? <Loading label="Loading run facts" /> : null}
      {page !== null && page.items.length === 0 ? (
        <Empty title="No facts for this run" detail="The run is listed but its facts are not in this page." />
      ) : null}
      {page !== null && page.items.length > 0 ? (
        <BoundedList
          items={page.items}
          cap={LIST_CAP}
          totalLabel="run facts"
          row={(item) => (
            <tr key={item.sequence}>
              <td>{item.sequence}</td>
              <td>{item.type}</td>
              <td>{formatTime(item.occurredAt)}</td>
              <td>
                <code title={item.eventId}>{item.eventId}</code>
              </td>
            </tr>
          )}
        />
      ) : null}
    </article>
  );
}

export function EventsView() {
  const [cursor, setCursor] = useState<string | null>(null);
  const load = useCallback((next: string | null) => api.events(next, PAGE_LIMIT), []);
  const { page, error, reload } = usePage<EventItem>(load, cursor);

  if (error !== null) {
    return <Failure error={error} onRetry={reload} />;
  }
  if (page === null) {
    return <Loading label="Loading events" />;
  }
  return (
    <section aria-labelledby="events-heading">
      <h2 id="events-heading">Events</h2>
      <p className="note">
        Verified append-only facts for this project, read against high-water mark {page.highWaterMark}. A
        refresh resumes from the same cursor, so nothing is silently skipped.
      </p>
      {page.items.length === 0 ? (
        <Empty title="No events yet" detail="This project has no facts at or after the current cursor." />
      ) : (
        <BoundedList
          items={page.items}
          cap={LIST_CAP}
          totalLabel="events"
          row={(item) => (
            <tr key={item.sequence}>
              <td>{item.sequence}</td>
              <td>{item.type}</td>
              <td>{formatTime(item.occurredAt)}</td>
              <td>
                <code title={item.eventId}>{item.eventId}</code>
              </td>
            </tr>
          )}
        />
      )}
      {page.nextCursor !== null ? (
        <button type="button" onClick={() => setCursor(page.nextCursor)}>
          Older events
        </button>
      ) : null}
    </section>
  );
}

export function ArtifactsView() {
  const [digest, setDigest] = useState("");
  const [state, setState] = useState<
    | { readonly status: "idle" }
    | { readonly status: "loading" }
    | { readonly status: "failed"; readonly error: unknown }
    | { readonly status: "loaded"; readonly document: Awaited<ReturnType<typeof api.artifact>> }
  >({ status: "idle" });

  const open = useCallback(() => {
    setState({ status: "loading" });
    api.artifact(digest.trim()).then(
      (document) => setState({ status: "loaded", document }),
      (error: unknown) => setState({ status: "failed", error }),
    );
  }, [digest]);

  return (
    <section aria-labelledby="artifacts-heading">
      <h2 id="artifacts-heading">Artifacts</h2>
      <p className="note">
        Artifacts are addressed by content digest and are visible only when a verified event of this project
        references them. The whole content store is never exposed.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          open();
        }}
      >
        <label htmlFor="digest">Content digest</label>
        <input
          id="digest"
          name="digest"
          value={digest}
          placeholder="sha256:…"
          onChange={(event) => setDigest(event.target.value)}
        />
        <button type="submit" disabled={digest.trim() === ""}>
          Open
        </button>
      </form>
      {state.status === "loading" ? <Loading label="Verifying artifact" /> : null}
      {state.status === "failed" ? <Failure error={state.error} onRetry={open} /> : null}
      {state.status === "loaded" ? (
        <div className="detail">
          <KeyValue
            items={[
              ["Digest", <code key="d" title={state.document.digest}>{shortDigest(state.document.digest, 20)}</code>],
              ["Size", formatBytes(state.document.byteLength)],
              [
                "Inlined",
                state.document.inline ? "Yes" : "No — too large to inline",
              ],
            ]}
          />
          {state.document.text === null || state.document.text === undefined ? null : (
            <Code>{state.document.text}</Code>
          )}
        </div>
      ) : null}
    </section>
  );
}

/** Metric and outcome honesty panel.
 *
 * R10 requires that a value is labelled as measured, synthetic, or absent, and
 * that an unobserved run is never summarised as a result.
 */
export function OutcomeLegend() {
  return (
    <section aria-labelledby="legend-heading">
      <h2 id="legend-heading">How to read this workbench</h2>
      <KeyValue
        items={[
          [
            "Succeeded",
            <span key="s">
              only an <strong>observed, successful</strong> terminal outcome. Nothing else is styled as success.
            </span>,
          ],
          ["Cancellation requested", "a request was recorded; it is not an observed stop"],
          ["Stopped (observed)", "the process was observed to stop, without reporting success"],
          ["Unknown / Lost", "the outcome was never observed and must not be compared as a result"],
          [
            "Synthetic",
            <span key="y">
              a deterministic or simulated value. It is <strong>not</strong> a measurement and is never
              summarised as one.
            </span>,
          ],
          [
            "Reportable outcome",
            <span key="r">
              succeeded, failed or an observed stop.{" "}
              {isReportableOutcome("unknown") ? "" : null}
              <code>isReportableOutcome()</code> gates any comparison built on this data.
            </span>,
          ],
        ]}
      />
      <p className="note">
        <code>isSuccessful(&quot;unknown&quot;)</code> is <code>{String(isSuccessful("unknown"))}</code>: an
        unobserved run is never reported as a success.
      </p>
    </section>
  );
}
