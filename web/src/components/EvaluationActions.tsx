/** Explicit native training, evidence replay and editable human report workflow. */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { CommandReceipt, Metrics, ResearchReport, TrainedComparison, TrainedEvaluationDetail, TrainingProvenance } from "../generated/local-api";
import { ComparisonView, ExamplesView, RecordedReportView, ratio, VERDICT_NAMES } from "./EvaluationViews";

interface EvaluationSummary {
  commandId: string;
  baselineArtifact: string;
  candidateArtifact: string;
  provenance: TrainingProvenance;
  baselineMetrics: Metrics;
  candidateMetrics: Metrics;
  exampleCount: number;
}
interface ReportSummary {
  reportId: string;
  reportArtifact: string;
  actorId: string;
  verdict: ResearchReport["verdict"];
  experimentRevision: number;
  submittedAt: string;
}

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
  const [comparison, setComparison] = useState<TrainedComparison | null>(null);
  const [details, setDetails] = useState<{ baseline: TrainedEvaluationDetail; candidate: TrainedEvaluationDetail } | null>(null);
  const [evaluations, setEvaluations] = useState<EvaluationSummary[] | null>(null);
  const [evaluationsWithheld, setEvaluationsWithheld] = useState(0);
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [reportsWithheld, setReportsWithheld] = useState(0);
  const [recordedReport, setRecordedReport] = useState<{ artifact: string; document: ResearchReport } | null>(null);
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
        setComparison(result["comparison"] as unknown as TrainedComparison);
        setDetails({ baseline: result["baselineDetail"] as unknown as TrainedEvaluationDetail, candidate: result["candidateDetail"] as unknown as TrainedEvaluationDetail });
      }
      if (next.operation === "evaluation.list" && Array.isArray(result["evaluations"])) {
        setEvaluations(result["evaluations"] as EvaluationSummary[]); setEvaluationsWithheld(Number(result["withheld"]));
      }
      if (next.operation === "conclusion.list" && Array.isArray(result["reports"])) {
        setReports(result["reports"] as ReportSummary[]); setReportsWithheld(Number(result["withheld"]));
      }
      if (typeof result["reportArtifact"] === "string") {
        setReport(result["reportArtifact"]);
        setRecordedReport({ artifact: result["reportArtifact"], document: result["report"] as unknown as ResearchReport });
      }
      setStatus(`Receipt ${next.commandId}: ${String(result["observation"] ?? "recorded")}.`);
    } catch (error) { setStatus(`${error instanceof Error ? error.message : "Response unconfirmed."} Observe the Run; exact retry retains the original identity.`); }
    finally { sending.current = false; setBusy(false); }
  }
  function send(operation: Record<string, unknown>, selectedRevision = revision) {
    if (sending.current) return;
    void dispatch(JSON.stringify({ apiVersion: "researchos.dev/application/v0alpha1", kind: "ApplicationCommand",
      commandId: `browser.evaluation.${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`,
      actorId: "browser-operator", submittedAt: new Date().toISOString(),
      expectedHead: operation["kind"] === "native.start" || operation["kind"] === "conclusion.publish" ? head : null,
      expectedRevision: selectedRevision, operation }));
  }
  function chooseEvaluation(item: EvaluationSummary) {
    setRevision(item.provenance.experimentRevision); setBaseline(item.baselineArtifact); setCandidate(item.candidateArtifact);
    setPreview(null); setVerdict(""); setRationale(""); setNarrative(""); setEvidence("");
    send({ kind: "evaluation.report", baseline: item.baselineArtifact, candidate: item.candidateArtifact }, item.provenance.experimentRevision);
  }
  const currentPreview = preview?.pair === pair;
  return <section className="evaluation-workbench" aria-labelledby="evaluation-heading">
    <h2 id="evaluation-heading">Real evaluation and human report</h2>
    <p>Fixed public Iris development benchmark: 80 training rows, 20 held-out rows, seed 0. CPU integration is not a research improvement or independent validation. The 12-row synthetic evaluator remains separately labelled.</p>
    <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh evaluation head</button>
    <label>Training revision <input type="number" min={1} value={revision} onChange={(event) => setRevision(Number(event.target.value))} /></label>
    <fieldset disabled={busy}><legend>1. Select a completed evaluation</legend>
      <p>Load previously collected results, then select a pair to compare. Each listed pair is checked against its recorded Run and replayed predictions.</p>
      <button type="button" onClick={() => send({ kind: "evaluation.list" })}>Load recent evaluations</button>
      {evaluations === null ? <p className="note">Load evaluations to see the latest ten recorded pairs.</p> : evaluations.length === 0 ? <p>No collected evaluations yet. Complete a reviewed Run and recompute its results below.</p> : <div className="evaluation-table"><table>
        <caption>Recorded evaluations</caption>
        <thead><tr><th scope="col">Run / revision</th><th scope="col">Examples</th><th scope="col">Baseline accuracy</th><th scope="col">Candidate accuracy</th><th scope="col">Action</th></tr></thead>
        <tbody>{evaluations.map((item, index) => <tr key={item.commandId}>
          <th scope="row">{item.provenance.runId}<small>Revision {item.provenance.experimentRevision}</small></th><td>{item.exampleCount}</td>
          <td>{ratio(item.baselineMetrics.accuracy)}</td><td>{ratio(item.candidateMetrics.accuracy)}</td>
          <td><button type="button" aria-label={`Compare ${item.provenance.runId} revision ${item.provenance.experimentRevision} record ${index + 1}`} onClick={() => chooseEvaluation(item)}>Compare</button></td>
        </tr>)}</tbody>
      </table></div>}
      {evaluationsWithheld > 0 ? <p>{evaluationsWithheld} older evaluation records are withheld. You can still enter their artifact IDs below.</p> : null}
    </fieldset>
    <details><summary>Run and collect a reviewed CPU evaluation</summary>
    <fieldset disabled={busy}><legend>Collect results from a reviewed CPU Run</legend>
      <label>Training native profile <input value={profile} onChange={(event) => setProfile(event.target.value)} /></label>
      <button type="button" onClick={() => send({ kind: "native.inspect", profileId: profile })}>Inspect training material</button>
      <button type="button" disabled={material?.profile !== profile} onClick={() => send({ kind: "native.start", profileId: profile, materialDigest: material?.digest })}>Start explicitly authorized training</button>
      <button type="button" onClick={() => send({ kind: "native.observe", profileId: profile })}>Observe training Run</button>
      <p>The operator must install reviewed material and a valid Worker grant. A research decision alone grants no launch permission. Unknown outcomes are observed without redispatch.</p>
      <label>Completed training output artifact <input value={output} onChange={(event) => setOutput(event.target.value)} /></label>
      <label>Accepted research decision ID (optional)<input value={decision} onChange={(event) => setDecision(event.target.value)} /></label>
      <button type="button" onClick={() => send({ kind: "evaluation.collect", profileId: profile, outputArtifact: output, decisionId: decision || null })}>Recompute completed baseline and candidate</button>
    </fieldset>
    </details>
    <fieldset disabled={busy}><legend>2. Compare evidence and write a conclusion</legend>
      <details><summary>Enter evaluation artifact IDs manually</summary>
      <label>Trained baseline artifact <input value={baseline} onChange={(event) => setBaseline(event.target.value)} /></label>
      <label>Trained candidate artifact <input value={candidate} onChange={(event) => setCandidate(event.target.value)} /></label>
      <button type="button" disabled={!baseline || !candidate} onClick={() => send({ kind: "evaluation.report", baseline, candidate })}>Preview evidence-linked report</button></details>
      {!currentPreview ? <p>Select a recorded evaluation, or enter artifact IDs and preview the comparison.</p> : null}
      {currentPreview && comparison ? <ComparisonView comparison={comparison} /> : null}
      {currentPreview && details ? <ExamplesView key={pair} baseline={details.baseline} candidate={details.candidate} /> : null}
      <label>Editable report narrative<textarea rows={12} value={narrative} onChange={(event) => setNarrative(event.target.value)} /></label>
      <label>Human conclusion <select value={verdict} onChange={(event) => setVerdict(event.target.value)}><option value="">Choose explicitly</option><option value="insufficient-evidence">Insufficient evidence</option><option value="supported" disabled={!currentPreview || !comparison?.comparison.supportsAConclusion}>Supported</option><option value="unsupported" disabled={!currentPreview || !comparison?.comparison.supportsAConclusion}>Unsupported</option></select></label>
      <label>Human conclusion rationale<textarea value={rationale} onChange={(event) => setRationale(event.target.value)} /></label>
      <label>Additional imported evidence IDs (comma separated)<input value={evidence} onChange={(event) => setEvidence(event.target.value)} /></label>
      <button type="button" disabled={!currentPreview || (verdict !== "insufficient-evidence" && !comparison?.comparison.supportsAConclusion) || verdict === "" || rationale.trim() === "" || narrative.trim() === ""} onClick={() => send({ kind: "conclusion.publish", baseline, candidate, comparisonDigest: preview?.digest,
        reportId: `report.${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`, narrative, verdict, rationale,
        evidenceRefs: evidence.split(",").map((item) => item.trim()).filter(Boolean) })}>Record explicit human conclusion</button>
      <p>Editing the narrative cannot rewrite verified metrics, configuration or provenance. Every recorded report preserves the comparison and its limitations.</p>
    </fieldset>
    <fieldset disabled={busy}><legend>3. Read preserved human reports</legend>
      <button type="button" onClick={() => send({ kind: "conclusion.list" })}>List recorded human reports</button>
      {reports === null ? <p className="note">List reports to find a preserved conclusion.</p> : reports.length === 0 ? <p>No recorded human reports yet.</p> : <div className="evaluation-table"><table>
        <caption>Recorded human reports</caption>
        <thead><tr><th scope="col">Report</th><th scope="col">Conclusion</th><th scope="col">Author / revision</th><th scope="col">Recorded at</th><th scope="col">Action</th></tr></thead>
        <tbody>{reports.map(item => <tr key={item.reportArtifact}><th scope="row">{item.reportId}</th><td>{VERDICT_NAMES[item.verdict]}</td>
          <td>{item.actorId} / {item.experimentRevision}</td><td>{item.submittedAt}</td>
          <td><button type="button" onClick={() => { setReport(item.reportArtifact); setRecordedReport(null); send({ kind: "conclusion.inspect", reportArtifact: item.reportArtifact }); }}>Read {item.reportId}</button></td>
        </tr>)}</tbody>
      </table></div>}
      {reportsWithheld > 0 ? <p>{reportsWithheld} older reports are withheld. You can still read a known report artifact.</p> : null}
      <details><summary>Open a report by artifact ID</summary>
      <label>Recorded report artifact <input value={report} onChange={(event) => { setReport(event.target.value); setRecordedReport(null); }} /></label>
      <button type="button" onClick={() => send({ kind: "conclusion.inspect", reportArtifact: report })}>Read recorded human report</button>
      </details>
      {recordedReport && recordedReport.artifact === report ? <RecordedReportView report={recordedReport.document} /> : null}
      <p>Reports are immutable artifacts cited by durable receipts. Reading a historical report never starts training or changes its judgement.</p>
    </fieldset>
    <p role="status">{status}</p>
    {report !== "" ? <p>Recorded report artifact: <code>{report}</code></p> : null}
    <button type="button" disabled={busy || pending.current === null} onClick={() => { if (pending.current) void dispatch(pending.current); }}>Retry exact evaluation intent</button>
    {receipt ? <details><summary>Evaluation receipt and preserved evidence</summary><pre>{JSON.stringify(receipt, null, 2)}</pre></details> : null}
  </section>;
}
