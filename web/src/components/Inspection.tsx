/** Immutable inspection with navigable, project-scoped evidence references. */
import { useEffect, useState } from "react";
import { api } from "../api";
import type { InspectionView, LineageLink } from "../generated/local-api";
import { Empty, Failure, Loading } from "./Primitives";

function object(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function Topology({ value }: { readonly value: unknown }) {
  const graph = object(value);
  const graphs = graph !== null && Array.isArray(graph.graphs) ? graph.graphs : [];
  if (graphs.length === 0) return <p>No supported spec/plan topology in this object.</p>;
  return <section aria-label="Recorded workflow topology">
    {graphs.slice(0, 20).map((value: unknown, index: number) => {
      const item = object(value);
      if (item === null) return null;
      if (item.unsupported === true) return <p key={index}>Unsupported nested or over-limit graph. Inspect the immutable document below.</p>;
      const nodes = Array.isArray(item.nodes) ? item.nodes : [];
      const edges = Array.isArray(item.edges) ? item.edges : [];
      return <article key={index}><h4>{String(item.id)}</h4>
        <ul>{nodes.slice(0, 200).map((node: unknown, i: number) => {
          const n = object(node); return n === null ? null : <li key={i}><code>{String(n.id)}</code> ({String(n.kind)})</li>;
        })}</ul>
        <table><caption>Recorded dependencies</caption><thead><tr><th>Source</th><th>Target</th></tr></thead>
          <tbody>{edges.slice(0, 400).map((edge: unknown, i: number) => {
            const e = object(edge); return e === null ? null : <tr key={i}><td>{String(e.source)}</td><td>{String(e.target)}</td></tr>;
          })}</tbody></table>
        {edges.length === 0 ? <p>This graph records no dependency edges.</p> : null}
      </article>;
    })}
  </section>;
}

export function Inspector({ kind, identity }: {
  readonly kind: LineageLink["kind"]; readonly identity: string;
}) {
  const [target, setTarget] = useState({ kind, identity, via: [] as ReadonlyArray<string> });
  const [result, setResult] = useState<InspectionView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [nonce, setNonce] = useState(0);
  useEffect(() => { setTarget({kind, identity, via:[]}); }, [kind, identity]);
  useEffect(() => {
    let live = true; setResult(null); setError(null);
    api.inspect(target.kind, target.identity, target.via).then(
      data => { if (live) setResult(data); },
      failure => { if (live) setError(failure); },
    );
    return () => { live = false; };
  }, [target, nonce]);
  if (error !== null) return <Failure error={error} onRetry={() => setNonce(n => n + 1)} />;
  if (result === null) return <Loading label="Inspecting recorded evidence" />;
  const text = JSON.stringify(result.document, null, 2);
  return <article className="detail" aria-label="Immutable evidence inspector">
    <h3>{result.identity}</h3><p>Immutable identity and recorded facts. Missing links and non-inlined bytes are reported explicitly. Numeric values require measurement provenance in the recorded evidence.</p>
    <button type="button" onClick={() => setTarget({kind, identity, via:[]})}>Return to selected record</button>
    <nav aria-label="Evidence lineage"><ul>{result.links.slice(0, 100).map((link, i) =>
      <li key={i}><button type="button" className="linkish" onClick={() => setTarget({kind:link.kind, identity:link.target, via:link.via ?? []})}>
        {link.label}: {link.target}
      </button></li>)}</ul></nav>
    {result.links.length === 0 ? <Empty title="No recorded lineage links" detail="No evidence reference is inferred." /> : null}
    {target.kind === "revision" ? <button type="button" onClick={() => setTarget({kind:"artifact", identity:target.identity, via:[]})}>Inspect stored spec bytes, if present</button> : null}
    {target.kind === "artifact" ? <Topology value={result.document.graph} /> : null}
    <pre className="code" tabIndex={0}>{text.slice(0, 65536)}</pre>
    {text.length > 65536 ? <p>Rendering capped at 64 KiB; the API document is bounded separately.</p> : null}
  </article>;
}

export function ObjectInspectionView({ title }: { readonly title: string }) {
  const [digest, setDigest] = useState(""); const [selected, setSelected] = useState<string | null>(null);
  return <section><h2>{title}</h2><p>Inspect a project-linked spec, plan, result, metric, log or environment artifact. Select a digest from a recorded fact or revision lineage.</p>
    <form onSubmit={event => {event.preventDefault(); setSelected(digest.trim());}}>
      <label>Artifact digest <input value={digest} onChange={event => setDigest(event.target.value)} /></label>
      <button type="submit" disabled={digest.trim() === ""}>Inspect</button>
    </form>
    {selected === null ? <Empty title="Select a recorded object" detail="The view does not infer data, topology or execution environment." /> : <Inspector kind="artifact" identity={selected} />}
  </section>;
}
