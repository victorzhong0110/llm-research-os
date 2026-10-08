/** Explicit native training, evidence replay and editable human report workflow. */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { CommandReceipt } from "../generated/local-api";

export function EvaluationActions() {
  const [head, setHead] = useState(0);
  const [revision, setRevision] = useState(1);
  const [profile, setProfile] = useState("");
  const [material, setMaterial] = useState<{ profile: string; digest: string } | null>(null);
  const [output, setOutput] = useState("");
  const [decision, setDecision] = useState("");
  const [baseline, setBaseline] = useState("");
  const [candidate, setCandidate] = useState("");
  const [preview, setPreview] = useState<{ pair: string; digest: string } | null>(null);
  const [narrative, setNarrative] = useState("");
  const [verdict, setVerdict] = useState("");
  const [rationale, setRationale] = useState("");
  const [evidence, setEvidence] = useState("");
  const [report, setReport] = useState("");
  const [status, setStatus] = useState("");
  const [receipt, setReceipt] = useState<CommandReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const pending = useRef<string | null>(null);
  const pair = JSON.stringify([baseline, candidate, revision]);
  async function refresh() {
    try { setHead((await api.workspace()).highWaterMark); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Workspace unavailable."); }
  }
  useEffect(() => { void refresh(); }, []);
  async function dispatch(body: string) {
    if (sending.current) return;
    sending.current = true; pending.current = body; setBusy(true);
    try {
      const next = await api.command(body); setReceipt(next); setHead(next.observedHead);
      const result = next.result;
      const intent = JSON.parse(body) as { operation: Record<string, unknown>; expectedRevision: number };
      if (next.operation === "native.inspect" && typeof result["materialDigest"] === "string") {
        setMaterial({ profile: String(intent.operation["profileId"]), digest: result["materialDigest"] });
      }
      if (next.operation === "native.start" && typeof result["artifactDigest"] === "string") setOutput(result["artifactDigest"]);
      if (next.operation === "evaluation.collect" && typeof result["baselineArtifact"] === "string" && typeof result["candidateArtifact"] === "string") {
        setBaseline(result["baselineArtifact"]); setCandidate(result["candidateArtifact"]); setPreview(null); setVerdict("");
      }
      if (next.operation === "evaluation.report" && typeof result["comparisonDigest"] === "string" && typeof result["narrative"] === "string") {
        setPreview({ pair: JSON.stringify([intent.operation["baseline"], intent.operation["candidate"], intent.expectedRevision]), digest: result["comparisonDigest"] });
        setNarrative(result["narrative"]); setVerdict(""); setRationale("");
      }
      if (typeof result["reportArtifact"] === "string") setReport(result["reportArtifact"]);
      setStatus(`Receipt ${next.commandId}: ${String(result["observation"] ?? "recorded")}.`);
    } catch (error) { setStatus(`${error instanceof Error ? error.message : "Response unconfirmed."} Observe the Run; exact retry retains the original identity.`); }
    finally { sending.current = false; setBusy(false); }
  }
  function send(operation: Record<string, unknown>) {
    if (sending.current) return;
    void dispatch(JSON.stringify({ apiVersion: "researchos.dev/application/v0alpha1", kind: "ApplicationCommand",
      commandId: `browser.evaluation.${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`,
      actorId: "browser-operator", submittedAt: new Date().toISOString(),
      expectedHead: operation["kind"] === "native.start" || operation["kind"] === "conclusion.publish" ? head : null,
      expectedRevision: revision, operation }));
  }
  return <section aria-labelledby="evaluation-heading">
    <h2 id="evaluation-heading">Real evaluation and human report</h2>
    <p>Fixed public Iris development benchmark: 80 training rows, 20 held-out rows, seed 0. CPU integration is not a research improvement or independent validation. The 12-row synthetic evaluator remains separately labelled.</p>
    <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh evaluation head</button>
    <label>Training revision <input type="number" min={1} value={revision} onChange={(event) => setRevision(Number(event.target.value))} /></label>
    <fieldset disabled={busy}><legend>Explicit reviewed CPU Run</legend>
      <label>Training native profile <input value={profile} onChange={(event) => setProfile(event.target.value)} /></label>
      <button type="button" onClick={() => send({ kind: "native.inspect", profileId: profile })}>Inspect training material</button>
      <button type="button" disabled={material?.profile !== profile} onClick={() => send({ kind: "native.start", profileId: profile, materialDigest: material?.digest })}>Start explicitly authorized training</button>
      <button type="button" onClick={() => send({ kind: "native.observe", profileId: profile })}>Observe training Run</button>
      <p>The operator must install reviewed material and a valid Worker grant. A research decision alone grants no launch permission. Unknown outcomes are observed without redispatch.</p>
      <label>Completed training output artifact <input value={output} onChange={(event) => setOutput(event.target.value)} /></label>
      <label>Accepted research decision ID (optional)<input value={decision} onChange={(event) => setDecision(event.target.value)} /></label>
      <button type="button" onClick={() => send({ kind: "evaluation.collect", profileId: profile, outputArtifact: output, decisionId: decision || null })}>Recompute completed baseline and candidate</button>
    </fieldset>
    <fieldset disabled={busy}><legend>Preserved reports</legend>
      <button type="button" onClick={() => send({ kind: "conclusion.list" })}>List recorded human reports</button>
      <label>Recorded report artifact <input value={report} onChange={(event) => setReport(event.target.value)} /></label>
      <button type="button" onClick={() => send({ kind: "conclusion.inspect", reportArtifact: report })}>Read recorded human report</button>
      <p>Reports are immutable artifacts cited by durable receipts. Reading a historical report never starts training or changes its judgement.</p>
    </fieldset>
    <fieldset disabled={busy}><legend>Comparison and editable report</legend>
      <label>Trained baseline artifact <input value={baseline} onChange={(event) => setBaseline(event.target.value)} /></label>
      <label>Trained candidate artifact <input value={candidate} onChange={(event) => setCandidate(event.target.value)} /></label>
      <button type="button" onClick={() => send({ kind: "evaluation.report", baseline, candidate })}>Preview evidence-linked report</button>
      <label>Editable report narrative<textarea rows={12} value={narrative} onChange={(event) => setNarrative(event.target.value)} /></label>
      <label>Human conclusion <select value={verdict} onChange={(event) => setVerdict(event.target.value)}><option value="">Choose explicitly</option><option value="insufficient-evidence">Insufficient evidence</option><option value="supported">Supported</option><option value="unsupported">Unsupported</option></select></label>
      <label>Human conclusion rationale<textarea value={rationale} onChange={(event) => setRationale(event.target.value)} /></label>
      <label>Additional imported evidence IDs (comma separated)<input value={evidence} onChange={(event) => setEvidence(event.target.value)} /></label>
      <button type="button" disabled={preview?.pair !== pair || verdict === "" || rationale.trim() === "" || narrative.trim() === ""} onClick={() => send({ kind: "conclusion.publish", baseline, candidate, comparisonDigest: preview?.digest,
        reportId: `report.${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`, narrative, verdict, rationale,
        evidenceRefs: evidence.split(",").map((item) => item.trim()).filter(Boolean) })}>Record explicit human conclusion</button>
      <p>Editing the narrative cannot rewrite verified metrics, configuration or provenance. Every recorded report preserves the comparison and its limitations.</p>
    </fieldset>
    <p role="status">{status}</p>
    {report !== "" ? <p>Recorded report artifact: <code>{report}</code></p> : null}
    <button type="button" disabled={busy || pending.current === null} onClick={() => { if (pending.current) void dispatch(pending.current); }}>Retry exact evaluation intent</button>
    {receipt ? <details open><summary>Evaluation receipt and preserved evidence</summary><pre>{JSON.stringify(receipt, null, 2)}</pre></details> : null}
  </section>;
}
