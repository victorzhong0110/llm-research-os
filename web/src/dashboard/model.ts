/** View intent is independent of authoritative research and execution state. */
import type {
  Component,
  MapState,
  Relation,
  Position,
  Appearance,
  Viewport,
} from "../generated/local-api";

export type Node = Omit<Component, "position"> & {
  readonly position: Required<Position>;
};
export interface State {
  readonly components: ReadonlyArray<Node>;
  readonly relations: ReadonlyArray<Relation>;
  readonly appearance: Required<Appearance>;
  readonly viewport: Required<Viewport>;
}
export const appearance: Required<Appearance> = {
  skin: "graphite",
  background: "#f5f5f4",
  accent: "#262626",
  density: "comfortable",
  textScale: 1,
};
export function normalize(state: MapState): State {
  return {
    components: (state.components ?? []).map((node) => ({
      ...node,
      position: { width: 280, height: 190, ...node.position },
    })),
    relations: state.relations ?? [],
    appearance: { ...appearance, ...state.appearance },
    viewport: { x: 36, y: 30, zoom: 0.65, ...state.viewport },
  };
}

function card(
  id: string,
  title: string,
  type: Component["type"],
  x: number,
  y: number,
  parentId: string,
  source?: NonNullable<Component["binding"]>["source"],
  body = "",
): Node {
  return {
    id,
    title,
    type,
    parentId,
    position: { x, y, width: 420, height: 145 },
    body,
    ...(source ? { binding: { source } } : {}),
  };
}
export function starter(): State {
  const groups: Node[] = [
    {
      id: "research-zone",
      title: "Research & experiments",
      type: "group",
      position: { x: 40, y: 40, width: 920, height: 400 },
    },
    {
      id: "compute-zone",
      title: "Compute & execution",
      type: "group",
      position: { x: 1020, y: 40, width: 920, height: 400 },
    },
    {
      id: "service-zone",
      title: "Serving & reliability",
      type: "group",
      position: { x: 1020, y: 480, width: 920, height: 400 },
    },
    {
      id: "governance-zone",
      title: "Decisions & stewardship",
      type: "group",
      position: { x: 40, y: 480, width: 920, height: 400 },
    },
  ];
  return normalize({
    components: [
      ...groups,
      card(
        "research",
        "Research questions",
        "research",
        24,
        64,
        "research-zone",
        "research",
      ),
      card(
        "experiments",
        "Experiments",
        "run",
        476,
        64,
        "research-zone",
        "runs",
      ),
      card(
        "datasets",
        "Datasets & lineage",
        "dataset",
        24,
        231,
        "research-zone",
        undefined,
        "Track source, version, license and downstream use.",
      ),
      card(
        "evaluation",
        "Evaluation & results",
        "evaluation",
        476,
        231,
        "research-zone",
        "events",
      ),
      card(
        "activity",
        "Agent activity",
        "agent",
        24,
        64,
        "compute-zone",
        "events",
      ),
      card(
        "resources",
        "Compute resources",
        "resource",
        476,
        64,
        "compute-zone",
        "telemetry",
        "Allocation and measured utilization are different signals.",
      ),
      card(
        "pool",
        "Scheduling & pools",
        "pool",
        24,
        231,
        "compute-zone",
        "telemetry",
        "Queues, capacity, placement and load balancing.",
      ),
      card(
        "training",
        "Training progress",
        "model",
        476,
        231,
        "compute-zone",
        "runs",
      ),
      card(
        "services",
        "Models & endpoints",
        "service",
        24,
        64,
        "service-zone",
        "telemetry",
        "Latency, traffic, errors and version rollouts.",
      ),
      card(
        "availability",
        "Availability & incidents",
        "availability",
        476,
        64,
        "service-zone",
        "telemetry",
        "Observed uptime, incidents and recovery signals.",
      ),
      card(
        "providers",
        "Provider status",
        "provider",
        24,
        231,
        "service-zone",
        "telemetry",
        "Official provider status is separate from your request health.",
      ),
      card(
        "observability",
        "Logs & observability",
        "custom",
        476,
        231,
        "service-zone",
        "events",
      ),
      card(
        "decisions",
        "Decisions & approvals",
        "access",
        24,
        64,
        "governance-zone",
        "research",
      ),
      card(
        "costs",
        "Cost & budgets",
        "cost",
        476,
        64,
        "governance-zone",
        "telemetry",
        "Recorded spend, reservations and estimates remain distinct.",
      ),
      card(
        "recovery",
        "Backup & recovery",
        "recovery",
        24,
        231,
        "governance-zone",
        undefined,
        "A backup exists only when recorded; restoration needs verification.",
      ),
      card(
        "intent",
        "Your next question",
        "note",
        476,
        231,
        "governance-zone",
        undefined,
        "What do you want to learn? Edit this card, or ask your Agent to organize the map around your goal.",
      ),
    ],
    relations: [],
    appearance,
    viewport: { x: 28, y: 24, zoom: 0.68 },
  });
}
export function absolute(
  node: Node,
  nodes: ReadonlyArray<Node>,
): { x: number; y: number } {
  let { x, y } = node.position;
  let parent = node.parentId;
  const visited = new Set([node.id]);
  while (parent && !visited.has(parent)) {
    visited.add(parent);
    const found = nodes.find((n) => n.id === parent);
    if (!found) break;
    x += found.position.x;
    y += found.position.y;
    parent = found.parentId;
  }
  return { x, y };
}
export function hidden(node: Node, nodes: ReadonlyArray<Node>): boolean {
  let parent = node.parentId;
  const seen = new Set([node.id]);
  while (parent && !seen.has(parent)) {
    seen.add(parent);
    const found = nodes.find((n) => n.id === parent);
    if (!found) break;
    if (found.collapsed) return true;
    parent = found.parentId;
  }
  return false;
}
export function descendants(
  id: string,
  nodes: ReadonlyArray<Node>,
): Set<string> {
  const result = new Set([id]);
  for (let depth = 0; depth < 8; depth++)
    for (const node of nodes)
      if (node.parentId && result.has(node.parentId)) result.add(node.id);
  return result;
}
export function clampPosition(
  node: Node,
  nodes: ReadonlyArray<Node>,
  candidate: Required<Position>,
): Required<Position> {
  const parent = nodes.find((n) => n.id === node.parentId);
  const children = nodes.filter((n) => n.parentId === node.id);
  const minW = Math.max(
    180,
    ...children.map((n) => n.position.x + n.position.width),
  );
  const minH = Math.max(
    120,
    ...children.map((n) => n.position.y + n.position.height),
  );
  const width = Math.max(
    minW,
    Math.min(candidate.width, parent?.position.width ?? 20000),
  );
  const height = Math.max(
    minH,
    Math.min(candidate.height, parent ? parent.position.height - 48 : 20000),
  );
  return {
    width,
    height,
    x: Math.max(
      0,
      Math.min(candidate.x, parent ? parent.position.width - width : 100000),
    ),
    y: Math.max(
      parent ? 48 : 0,
      Math.min(candidate.y, parent ? parent.position.height - height : 100000),
    ),
  };
}
export const presets: ReadonlyArray<{
  type: Component["type"];
  title: string;
  source?: NonNullable<Component["binding"]>["source"];
}> = [
  { type: "group", title: "Group" },
  { type: "note", title: "Note" },
  { type: "research", title: "Research questions", source: "research" },
  { type: "run", title: "Experiments", source: "runs" },
  { type: "agent", title: "Agent activity", source: "events" },
  { type: "resource", title: "Compute", source: "telemetry" },
  { type: "pool", title: "Load balancing", source: "telemetry" },
  { type: "provider", title: "Provider status", source: "telemetry" },
  { type: "availability", title: "Availability", source: "telemetry" },
  { type: "cost", title: "Costs", source: "telemetry" },
  { type: "dataset", title: "Dataset" },
  { type: "model", title: "Model", source: "runs" },
  { type: "service", title: "Endpoint", source: "telemetry" },
  { type: "evaluation", title: "Evaluation", source: "events" },
  { type: "access", title: "Access & decisions", source: "research" },
  { type: "recovery", title: "Recovery" },
  { type: "custom", title: "Custom component", source: "events" },
];
