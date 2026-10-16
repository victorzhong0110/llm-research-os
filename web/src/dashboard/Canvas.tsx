import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent } from "react";
import { absolute, clampPosition, hidden } from "./model";
import type { Node, State } from "./model";
import { CardContent } from "./CardContent";
import { summary } from "./data";
import type { Sources } from "./data";

export type Mode = "browse" | "edit" | "ai";
interface Props {
  state: State;
  data: Sources;
  mode: Mode;
  selected: string | null;
  relations: boolean;
  query: string;
  autoFit: boolean;
  onSelect: (id: string) => void;
  onChange: (state: State, history?: boolean) => void;
  onAgent: (id: string) => void;
}
export function Canvas({
  state,
  data,
  mode,
  selected,
  relations,
  query,
  autoFit,
  onSelect,
  onChange,
  onAgent,
}: Props) {
  const surface = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 1000, height: 700 });
  useEffect(() => {
    const target = surface.current;
    if (!target) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry)
        setSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, []);
  const gesture = useRef<{
    id: string | null;
    resize: boolean;
    x: number;
    y: number;
    state: State;
    moved: boolean;
  } | null>(null);
  const fitted = useRef(false);
  useEffect(() => {
    if (!autoFit || fitted.current || !surface.current) return;
    fitted.current = true;
    const rect = surface.current.getBoundingClientRect();
    const zoom = Math.max(
      0.1,
      Math.min(0.9, (rect.width - 60) / 1420, (rect.height - 80) / 1080),
    );
    onChange(
      {
        ...state,
        viewport: { x: (rect.width - 1420 * zoom) / 2, y: 24, zoom },
      },
      false,
    );
  }, [autoFit, onChange, state]);
  const [hover, setHover] = useState<string | null>(null);
  const { x, y, zoom } = state.viewport;
  const visible = useMemo(
    () => state.components.filter((node) => !hidden(node, state.components)),
    [state.components],
  );
  const positions = useMemo(
    () =>
      new Map(
        visible.map((node) => [node.id, absolute(node, state.components)]),
      ),
    [visible, state.components],
  );
  const rendered =
    visible.length <= 100
      ? visible
      : visible.filter((node) => {
          const p = positions.get(node.id);
          if (!p) return false;
          return (
            node.id === selected ||
            (p.x * zoom + x < size.width + 100 &&
              p.y * zoom + y < size.height + 100 &&
              (p.x + node.position.width) * zoom + x > -100 &&
              (p.y + (node.collapsed ? 52 : node.position.height)) * zoom + y >
                -100)
          );
        });
  const renderedIds = new Set(rendered.map((node) => node.id));
  const edges = state.relations.filter(
    (edge) =>
      positions.has(edge.source) &&
      positions.has(edge.target) &&
      (renderedIds.has(edge.source) || renderedIds.has(edge.target)) &&
      (selected === null ||
        edge.source === selected ||
        edge.target === selected),
  );
  const dim = (node: Node) =>
    query !== "" &&
    !`${node.title} ${node.type} ${node.body ?? ""}`
      .toLowerCase()
      .includes(query.toLowerCase());
  function start(
    event: PointerEvent<HTMLDivElement>,
    id: string | null,
    resize = false,
  ) {
    if (event.button !== 0) return;
    if (id && mode !== "edit") return;
    const node = state.components.find((n) => n.id === id);
    if (node?.pinned) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    if (id) onChange(state, true);
    gesture.current = {
      id,
      resize,
      x: event.clientX,
      y: event.clientY,
      state,
      moved: false,
    };
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const current = gesture.current;
    if (!current) return;
    const dx = event.clientX - current.x,
      dy = event.clientY - current.y;
    if (Math.abs(dx) + Math.abs(dy) < 4 && !current.moved) return;
    current.moved = true;
    if (current.id === null) {
      onChange(
        {
          ...state,
          viewport: {
            ...state.viewport,
            x: current.state.viewport.x + dx,
            y: current.state.viewport.y + dy,
          },
        },
        false,
      );
      return;
    }
    const original = current.state.components.find((n) => n.id === current.id);
    if (!original) return;
    const position = clampPosition(
      original,
      state.components,
      current.resize
        ? {
            ...original.position,
            width: original.position.width + dx / zoom,
            height: original.position.height + dy / zoom,
          }
        : {
            ...original.position,
            x: original.position.x + dx / zoom,
            y: original.position.y + dy / zoom,
          },
    );
    onChange(
      {
        ...state,
        components: state.components.map((n) =>
          n.id === current.id ? { ...n, position } : n,
        ),
      },
      false,
    );
  }
  function end(event: PointerEvent<HTMLDivElement>) {
    const current = gesture.current;
    if (!current) return;
    gesture.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
    if (current.id) onSelect(current.id);
  }
  function wheel(event: WheelEvent) {
    event.preventDefault();
    if (!event.ctrlKey && !event.metaKey) {
      onChange(
        {
          ...state,
          viewport: {
            ...state.viewport,
            x: x - event.deltaX,
            y: y - event.deltaY,
          },
        },
        false,
      );
      return;
    }
    event.preventDefault();
    const rect = surface.current?.getBoundingClientRect();
    if (!rect) return;
    const next = Math.min(
      2,
      Math.max(0.1, zoom * Math.exp(-event.deltaY * 0.004)),
    );
    const px = event.clientX - rect.left,
      py = event.clientY - rect.top;
    onChange(
      {
        ...state,
        viewport: {
          zoom: next,
          x: px - ((px - x) * next) / zoom,
          y: py - ((py - y) * next) / zoom,
        },
      },
      false,
    );
  }
  useEffect(() => {
    const target = surface.current;
    if (!target) return;
    target.addEventListener("wheel", wheel, { passive: false });
    return () => target.removeEventListener("wheel", wheel);
  }, [state, onChange]);
  const maxX = Math.max(
    1450,
    ...visible.map((n) => (positions.get(n.id)?.x ?? 0) + n.position.width),
  );
  const maxY = Math.max(
    1100,
    ...visible.map((n) => (positions.get(n.id)?.y ?? 0) + n.position.height),
  );
  return (
    <div
      className={`map-stage ${zoom < 0.65 ? "map-stage-overview" : ""}`}
      style={{ "--map-text-factor": 1 / Math.max(0.5, zoom) } as CSSProperties}
      ref={surface}
      aria-label="Workspace map"
      tabIndex={0}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) start(event, null);
      }}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        const delta = 60;
        const directions: Record<string, [number, number]> = {
          ArrowLeft: [delta, 0],
          ArrowRight: [-delta, 0],
          ArrowUp: [0, delta],
          ArrowDown: [0, -delta],
        };
        const d = directions[event.key];
        if (d) {
          event.preventDefault();
          onChange(
            {
              ...state,
              viewport: { ...state.viewport, x: x + d[0], y: y + d[1] },
            },
            false,
          );
        }
      }}
    >
      <div
        className="map-world"
        style={{ transform: `translate(${x}px,${y}px) scale(${zoom})` }}
      >
        {relations && (
          <svg
            className="map-edges"
            width={maxX}
            height={maxY}
            aria-label="View relationships"
          >
            <defs>
              <marker
                id="map-arrow"
                markerWidth="8"
                markerHeight="8"
                refX="7"
                refY="4"
                orient="auto"
              >
                <path d="M0,0 L8,4 L0,8" fill="currentColor" />
              </marker>
            </defs>
            {edges.map((edge) => {
              const a = positions.get(edge.source),
                b = positions.get(edge.target);
              const na = visible.find((n) => n.id === edge.source),
                nb = visible.find((n) => n.id === edge.target);
              if (!a || !b || !na || !nb) return null;
              const ax = a.x + na.position.width,
                ay = a.y + Math.min(na.position.height, 178) / 2,
                bx = b.x,
                by = b.y + Math.min(nb.position.height, 178) / 2;
              return (
                <g key={edge.id}>
                  <path
                    d={`M${ax},${ay} C${ax + 65},${ay} ${bx - 65},${by} ${bx},${by}`}
                    markerEnd={
                      edge.type === "peer" ? undefined : "url(#map-arrow)"
                    }
                  />
                  <text
                    x={(ax + bx) / 2}
                    y={(ay + by) / 2 - 10}
                    textAnchor="middle"
                  >
                    {edge.label} · view
                  </text>
                </g>
              );
            })}
          </svg>
        )}
        {rendered.map((node) => {
          const pos = positions.get(node.id);
          if (!pos) return null;
          const info = summary(node, data);
          const group = node.type === "group";
          return (
            <div
              key={node.id}
              data-node={node.id}
              className={`map-node ${group ? "map-group" : "map-card"} ${selected === node.id ? "is-selected" : ""} ${dim(node) ? "is-dim" : ""} ${mode === "edit" && !node.pinned ? "is-movable" : ""}`}
              style={{
                left: pos.x,
                top: pos.y,
                width: node.position.width,
                height: group && node.collapsed ? 52 : node.position.height,
                zIndex: group ? 1 : 3,
              }}
              onPointerDown={(event) => start(event, node.id)}
              onPointerMove={move}
              onPointerUp={end}
              onPointerCancel={end}
            >
              <button
                type="button"
                className="map-node-hit"
                aria-label={`Open ${node.title}`}
                aria-pressed={selected === node.id}
                onClick={() => onSelect(node.id)}
                onMouseEnter={() => setHover(node.id)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(node.id)}
                onBlur={() => setHover(null)}
              >
                <span className="map-card-top">
                  <span className={`map-dot tone-${info.tone}`} />
                  <span className="map-eyebrow">
                    {group ? "REGION" : node.type}
                  </span>
                  <span className="map-pin">{node.pinned ? "Pinned" : ""}</span>
                </span>
                <strong>{node.title}</strong>
                {!group && <CardContent node={node} data={data} info={info} />}
              </button>
              {group && (
                <button
                  type="button"
                  className="map-collapse"
                  aria-label={`${node.collapsed ? "Expand" : "Collapse"} ${node.title}`}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() =>
                    onChange({
                      ...state,
                      components: state.components.map((n) =>
                        n.id === node.id
                          ? { ...n, collapsed: !n.collapsed }
                          : n,
                      ),
                    })
                  }
                >
                  {node.collapsed ? "+" : "−"}
                </button>
              )}
              {!group && node.type === "agent" && (
                <button
                  type="button"
                  className="map-agent"
                  aria-label={`Inspect activity for ${node.title}`}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => onAgent(node.id)}
                >
                  ✦
                </button>
              )}
              {mode === "edit" && !node.pinned && (
                <div
                  role="button"
                  tabIndex={-1}
                  aria-label={`Resize ${node.title}`}
                  className="map-resize"
                  onPointerDown={(event) => start(event, node.id, true)}
                >
                  ◢
                </div>
              )}
              {hover === node.id && !group && mode === "browse" && (
                <div className="map-tooltip" role="tooltip">
                  <b>{info.status}</b>
                  <p>{info.detail}</p>
                  <small>
                    {node.binding?.source
                      ? `Source: ${node.binding.source}`
                      : "User-authored context"}{" "}
                    · Select for details
                  </small>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div
        className="map-navigation"
        onPointerDown={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() =>
            onChange(
              {
                ...state,
                viewport: {
                  ...state.viewport,
                  zoom: Math.max(0.1, zoom - 0.1),
                },
              },
              false,
            )
          }
        >
          −
        </button>
        <span>{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() =>
            onChange(
              {
                ...state,
                viewport: { ...state.viewport, zoom: Math.min(2, zoom + 0.1) },
              },
              false,
            )
          }
        >
          +
        </button>
        <button
          type="button"
          onClick={() => {
            const bounds = surface.current?.getBoundingClientRect();
            if (bounds)
              onChange(
                {
                  ...state,
                  viewport: {
                    x: 24,
                    y: 24,
                    zoom: Math.max(
                      0.1,
                      Math.min(
                        1,
                        (bounds.width - 48) / maxX,
                        (bounds.height - 48) / maxY,
                      ),
                    ),
                  },
                },
                false,
              );
          }}
        >
          Fit map
        </button>
      </div>
      <svg
        className="map-minimap"
        viewBox={`0 0 ${maxX} ${maxY}`}
        role="img"
        aria-label="Map overview. Select a region to navigate."
      >
        {visible
          .filter((n) => n.type === "group")
          .map((node) => {
            const p = positions.get(node.id);
            return (
              p && (
                <g
                  key={node.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Navigate to ${node.title}`}
                  onClick={() =>
                    onChange(
                      {
                        ...state,
                        viewport: {
                          ...state.viewport,
                          x: 40 - p.x * zoom,
                          y: 40 - p.y * zoom,
                        },
                      },
                      false,
                    )
                  }
                  onKeyDown={(event) => {
                    if (event.key === "Enter")
                      onChange(
                        {
                          ...state,
                          viewport: {
                            ...state.viewport,
                            x: 40 - p.x * zoom,
                            y: 40 - p.y * zoom,
                          },
                        },
                        false,
                      );
                  }}
                >
                  <rect
                    x={p.x}
                    y={p.y}
                    width={node.position.width}
                    height={node.collapsed ? 52 : node.position.height}
                  />
                </g>
              )
            );
          })}
        <rect
          className="map-minimap-viewport"
          x={-x / zoom}
          y={-y / zoom}
          width={(surface.current?.clientWidth ?? 1000) / zoom}
          height={(surface.current?.clientHeight ?? 700) / zoom}
        />
      </svg>
      <div className="map-canvas-hint">
        {mode === "edit"
          ? "Drag to arrange · Use detail controls for precise sizing"
          : "Drag empty space to pan · Ctrl + scroll to zoom · Select a card to explore"}
      </div>
    </div>
  );
}
