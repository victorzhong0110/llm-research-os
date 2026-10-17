/** Bounded source snapshots. Partial, synthetic and unavailable are never live success. */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Paged } from "../api";
import type {
  ActivitySnapshot,
  EventItem,
  ResearchLedgerView,
  RunItem,
  Observation,
} from "../generated/local-api";
import type { Node } from "./model";
export interface Sources {
  observations: ReadonlyArray<Observation>;
  runs: Paged<RunItem> | null;
  events: ActivitySnapshot | null;
  research: ResearchLedgerView | null;
  errors: Readonly<Record<string, string>>;
  sampledAt: string | null;
}
export function useSources(visible: boolean) {
  const [data, setData] = useState<Sources>({
    observations: [],
    runs: null,
    events: null,
    research: null,
    errors: {},
    sampledAt: null,
  });
  const [busy, setBusy] = useState(false);
  const active = useRef(false);
  const mounted = useRef(true);
  const refresh = useCallback(async () => {
    if (active.current) return;
    active.current = true;
    setBusy(true);
    const [runs, events, research, observations] = await Promise.allSettled([
      api.runs(null, 500),
      api.activity(),
      api.research(),
      api.observations(),
    ]);
    if (mounted.current)
      setData({
        observations:
          observations.status === "fulfilled"
            ? observations.value.observations
            : [],
        runs: runs.status === "fulfilled" ? runs.value : null,
        events: events.status === "fulfilled" ? events.value : null,
        research: research.status === "fulfilled" ? research.value : null,
        sampledAt: new Date().toISOString(),
        errors: Object.fromEntries(
          (
            [
              ["runs", runs],
              ["events", events],
              ["research", research],
              ["telemetry", observations],
            ] as const
          ).flatMap(([key, result]) =>
            result.status === "rejected"
              ? [
                  [
                    key,
                    result.reason instanceof Error
                      ? result.reason.message
                      : "Source unavailable",
                  ],
                ]
              : [],
          ),
        ),
      });
    active.current = false;
    if (mounted.current) setBusy(false);
  }, []);
  useEffect(() => {
    mounted.current = true;
    if (!visible) return;
    void refresh();
    const timer = setInterval(() => void refresh(), 30000);
    return () => {
      mounted.current = false;
      clearInterval(timer);
    };
  }, [refresh, visible]);
  return { data, busy, refresh };
}
export interface Summary {
  value: string;
  label: string;
  status: string;
  tone: "neutral" | "active" | "attention" | "missing";
  detail: string;
}
const missing: Summary = {
  value: "—",
  label: "No observation",
  status: "Not connected",
  tone: "missing",
  detail: "Connect an observation source to see measured data here.",
};
export function summary(node: Node, data: Sources): Summary {
  const source = node.binding?.source;
  if (node.type === "group")
    return {
      ...missing,
      label: "Workspace region",
      status: "View arrangement",
      detail:
        "Contains related components. Grouping does not create execution dependencies.",
    };
  if (node.type === "note")
    return {
      value: "",
      label: "Human intent",
      status: node.pinned ? "Pinned" : "Note",
      tone: "neutral",
      detail: node.body ?? "Add your research intent.",
    };
  if (source === "telemetry") {
    const observed = observationFor(node, data);
    if (observed) {
      const stale = Date.parse(observed.expiresAt) <= Date.now();
      const metric = observed.metrics?.[0];
      return {
        value: metric
          ? `${metric.value.toLocaleString()} ${metric.unit ?? ""}`
          : "—",
        label: metric
          ? `${metric.name} · ${metric.meaning ?? "observed"}`
          : observed.title,
        status: `${observed.origin === "synthetic" ? "Synthetic · " : "Reported · "}${stale ? "Stale" : observed.status}`,
        tone:
          stale || observed.status === "unknown"
            ? "missing"
            : observed.status === "up"
              ? "neutral"
              : "attention",
        detail: `${observed.provenance}. Observed ${new Date(observed.observedAt).toLocaleString()} by ${observed.reporter}.`,
      };
    }
    return {
      ...missing,
      detail: data.errors["telemetry"] ?? node.body ?? missing.detail,
    };
  }
  if (!source) return { ...missing, detail: node.body || missing.detail };
  if (data.errors[source])
    return {
      ...missing,
      status: "Source unavailable",
      detail: data.errors[source] ?? missing.detail,
    };
  if (source === "runs" && data.runs) {
    const items = data.runs.items.filter(
      (run) => !node.binding?.entityId || run.runId === node.binding.entityId,
    );
    const active = items.filter(
      (run) => run.observation === "running" || run.observation === "queued",
    ).length;
    const attention = items.filter((run) =>
      ["unknown", "lost", "failed", "cancel-requested"].includes(
        run.observation ?? "absent",
      ),
    ).length;
    const synthetic = items.some((run) => run.origin === "synthetic");
    return {
      value: String(items.length),
      label: node.binding?.entityId ? "Selected run" : "Recorded runs",
      status: synthetic
        ? "Includes synthetic data"
        : active
          ? `${active} active / queued`
          : "Recorded snapshot",
      tone: attention ? "attention" : active ? "active" : "neutral",
      detail: `${active} running or queued · ${attention} need inspection. ${data.runs.nextCursor ? "Partial overview: more runs are available in Runs." : "All runs in this bounded snapshot."}`,
    };
  }
  if (source === "research" && data.research) {
    const ledger = data.research;
    return {
      value: String(
        node.type === "access"
          ? ledger.decisionCount
          : ledger.openQuestionCount,
      ),
      label: node.type === "access" ? "Recorded decisions" : "Open questions",
      status: ledger.openQuestionCount
        ? "Needs your attention"
        : "Recorded snapshot",
      tone: ledger.openQuestionCount ? "attention" : "neutral",
      detail: `${ledger.decisionCount} decisions · ${ledger.openQuestionCount} open questions. Evidence and rationale are available in Research.`,
    };
  }
  if (source === "events" && data.events) {
    const items = eventsFor(node, data);
    return {
      value: String(items.length),
      label: node.type === "agent" ? "Recorded AI events" : "Recorded events",
      status: data.events.olderAvailable
        ? "Partial snapshot"
        : "Recorded snapshot",
      tone: "neutral",
      detail:
        node.type === "agent"
          ? "Recorded model activity is not proof that an Agent is currently running."
          : "Open the source event to inspect its evidence. This snapshot does not imply live availability.",
    };
  }
  return missing;
}
export function eventsFor(node: Node, data: Sources): ReadonlyArray<EventItem> {
  return (data.events?.items ?? []).filter(
    (event) =>
      (!node.binding?.entityId ||
        event.runId === node.binding.entityId ||
        event.eventId === node.binding.entityId) &&
      (node.type !== "agent" || /model\.|agent\./.test(event.type)) &&
      (node.type !== "evaluation" ||
        /evaluation|comparison|run.completed|attempt.succeeded/.test(
          event.type,
        )),
  );
}

export function observationFor(
  node: Node,
  data: Sources,
): Observation | undefined {
  if (node.binding?.source !== "telemetry") return undefined;
  const matches = data.observations.filter(
    (item) =>
      (node.binding?.sourceId
        ? item.sourceId === node.binding.sourceId
        : item.category === node.type) &&
      (!node.binding?.entityId || item.entityId === node.binding.entityId),
  );
  return matches.length === 1 ? matches[0] : undefined;
}
