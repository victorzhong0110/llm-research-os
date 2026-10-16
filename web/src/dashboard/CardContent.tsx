import type { Node } from "./model";
import type { Sources, Summary } from "./data";
import { eventsFor, observationFor } from "./data";

/** The renderer consumes the selected source; it never invents placeholder measurements. */
export function CardContent({
  node,
  data,
  info,
}: {
  node: Node;
  data: Sources;
  info: Summary;
}) {
  const renderer = node.renderer ?? "summary";
  if (renderer === "summary" || renderer === "metric")
    return (
      <>
        <span className="map-value">
          {info.value}
          <small>{info.label}</small>
        </span>
        <span className={`map-status tone-${info.tone}`}>{info.status}</span>
        {node.type === "note" && <span className="map-note">{node.body}</span>}
      </>
    );
  const observation = observationFor(node, data);
  if (renderer === "chart") {
    const metric = observation?.metrics?.[0];
    const values = metric?.history ?? [];
    if (values.length > 1) {
      const min = Math.min(...values.map((point) => point.value)),
        max = Math.max(...values.map((point) => point.value));
      const first = values[0]!,
        last = values.at(-1)!;
      const duration = Date.parse(last.at) - Date.parse(first.at) || 1;
      return (
        <span className="map-card-chart">
          <svg
            viewBox="0 0 240 70"
            aria-label={`${metric?.name}: ${min} to ${max} ${metric?.unit}`}
            role="img"
          >
            <polyline
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              points={values
                .map(
                  (point) =>
                    `${25 + ((Date.parse(point.at) - Date.parse(first.at)) * 210) / duration},${50 - ((point.value - min) * 40) / (max - min || 1)}`,
                )
                .join(" ")}
            />
            <text x="0" y="12">
              {max}
            </text>
            <text x="0" y="52">
              {min}
            </text>
          </svg>
          <small>
            {metric?.name} · {metric?.unit} · {info.status}
          </small>
        </span>
      );
    }
    return (
      <span className="map-note">
        No timestamped series. Connect a source with at least two samples.
      </span>
    );
  }
  if (renderer === "table" && observation)
    return (
      <span className="map-card-table">
        {observation.metrics?.slice(0, 3).map((metric) => (
          <span key={metric.name}>
            <span>{metric.name}</span>
            <b>
              {metric.value} {metric.unit}
            </b>
          </span>
        ))}
        <small>{info.status}</small>
      </span>
    );
  if (node.binding?.source === "runs")
    return (
      <span className="map-card-table">
        {data.runs?.items
          .filter(
            (run) =>
              !node.binding?.entityId || run.runId === node.binding.entityId,
          )
          .slice(0, 3)
          .map((run) => (
            <span key={run.runId}>
              <span>{run.runId}</span>
              <b>{run.observation}</b>
            </span>
          ))}
        <small>{info.status}</small>
      </span>
    );
  const events = eventsFor(node, data).slice(-3).reverse();
  return (
    <span className="map-card-table">
      {events.map((event) => (
        <span key={event.eventId}>
          <span>{event.type}</span>
          <small>{new Date(event.occurredAt).toLocaleTimeString()}</small>
        </span>
      ))}
      {!events.length && <small>No source records available.</small>}
      <small>{info.status}</small>
    </span>
  );
}
