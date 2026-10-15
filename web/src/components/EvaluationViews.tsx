/** Readable views of server-verified evaluation evidence and human judgements. */
import { useState } from "react";
import type { ResearchReport, TrainedComparison, TrainedEvaluationDetail } from "../generated/local-api";
import { Badge, KeyValue } from "./Primitives";

export const METRIC_NAMES: Record<string, string> = {
  accuracy: "Accuracy", macro_f1: "Macro F1", mean_absolute_error: "Mean absolute error",
};
export const VERDICT_NAMES: Record<ResearchReport["verdict"], string> = {
  "insufficient-evidence": "Insufficient evidence", supported: "Supported", unsupported: "Unsupported",
};
export function ratio(value: string): string {
  return `${(Number(value) * 100).toFixed(2)}%`;
}

export function ComparisonView({ comparison }: { readonly comparison: TrainedComparison }) {
  const facts = comparison.comparison;
  return <article className="evaluation-card" aria-label="Verified comparison">
    <h3>Metric comparison</h3>
    <p><Badge tone={facts.outcome === "incomparable" ? "warning" : "neutral"}>{facts.outcome}</Badge> Observed metric direction; human interpretation remains separate.</p>
    {facts.refusal ? <p role="alert">{facts.refusal}</p> : null}
    {facts.missingMetrics.length ? <p role="alert">Missing metrics: {facts.missingMetrics.map(name => METRIC_NAMES[name]).join(", ")}</p> : null}
    <div className="evaluation-table"><table>
      <caption>Baseline versus candidate metrics</caption>
      <thead><tr><th scope="col">Metric</th><th scope="col">Baseline</th><th scope="col">Candidate</th><th scope="col">Change</th><th scope="col">Direction</th></tr></thead>
      <tbody>{facts.deltas.map(delta => <tr key={delta.metric}>
        <th scope="row">{METRIC_NAMES[delta.metric]}<small>{delta.metric === "mean_absolute_error" ? "Lower is better" : "Higher is better"}</small></th>
        <td title={delta.baseline}>{ratio(delta.baseline)}</td><td title={delta.candidate}>{ratio(delta.candidate)}</td>
        <td title={delta.change}>{Number(delta.change) > 0 ? "+" : ""}{(Number(delta.change) * 100).toFixed(2)} pp</td><td>{delta.direction}</td>
      </tr>)}</tbody>
    </table></div>
    <p className="note">pp means percentage points. Accuracy and binary MAE are complementary measures.</p>
    <h3>Evidence and limitations</h3>
    <ul>{Array.from(new Set([...comparison.limitations, ...facts.limitations])).map(item => <li key={item}>{item}</li>)}</ul>
    <details><summary>Run and model provenance</summary><KeyValue items={[
      ["Baseline Run / Attempt", `${comparison.baseline.runId} / ${comparison.baseline.attemptId}`],
      ["Candidate Run / Attempt", `${comparison.candidate.runId} / ${comparison.candidate.attemptId}`],
      ["Revision", String(comparison.candidate.experimentRevision)],
      ["Proposal / decision", `${comparison.candidate.proposalId ?? "Not linked"} / ${comparison.candidate.decisionId ?? "Not linked"}`],
      ["Baseline model", comparison.baseline.modelDigest], ["Candidate model", comparison.candidate.modelDigest],
      ["Training data", comparison.candidate.trainingDatasetDigest], ["Configuration", comparison.candidate.configDigest],
      ["Source", comparison.candidate.sourceDigest],
    ]} /></details>
  </article>;
}

type Filter = "errors" | "regressions" | "fixed" | "all";
export function ExamplesView({ baseline, candidate }: { readonly baseline: TrainedEvaluationDetail; readonly candidate: TrainedEvaluationDetail }) {
  const [filter, setFilter] = useState<Filter>("errors");
  const left = new Map(baseline.detail.examples.map(example => [example.exampleId, example]));
  const rows = candidate.detail.examples.map(right => ({ left: left.get(right.exampleId), right }));
  const filtered = rows.filter(row => filter === "all" || (filter === "errors" && (!row.left?.correct || !row.right.correct))
    || (filter === "regressions" && row.left?.correct && !row.right.correct)
    || (filter === "fixed" && row.left && !row.left.correct && row.right.correct));
  const shown = filtered.slice(0, 100);
  return <article className="evaluation-card" aria-label="Prediction review">
    <h3>Review individual predictions</h3>
    <KeyValue items={[
      ["Evaluator", `${candidate.detail.evaluatorName} ${candidate.detail.evaluatorVersion}`],
      ["Evaluation split / seed", `${candidate.detail.split} / ${candidate.detail.seed}`],
      ["Evaluation data", candidate.detail.datasetDigest],
      ["Evaluated examples", String(candidate.detail.exampleCount)],
      ["Baseline errors", String(baseline.failureExampleIds.length)],
      ["Candidate errors", String(candidate.failureExampleIds.length)],
    ]} />
    <label>Prediction filter <select value={filter} onChange={event => setFilter(event.target.value as Filter)}>
      <option value="errors">Errors in either model</option><option value="regressions">New candidate errors</option>
      <option value="fixed">Fixed baseline errors</option><option value="all">All examples</option>
    </select></label>
    <p>{filtered.length} of {rows.length} examples match this filter.</p>
    {shown.length === 0 ? <p>No examples match this filter.</p> : <div className="evaluation-table"><table>
      <caption>Per-example predictions</caption>
      <thead><tr><th scope="col">Example</th><th scope="col">Expected class</th><th scope="col">Baseline class</th><th scope="col">Candidate class</th><th scope="col">Change</th></tr></thead>
      <tbody>{shown.map(({ left: example, right }) => <tr key={right.exampleId}>
        <th scope="row">{right.exampleId}</th><td>{right.expected}</td><td>{example ? `${example.predicted} (${example.correct ? "correct" : "error"})` : "Missing"}</td>
        <td>{right.predicted} ({right.correct ? "correct" : "error"})</td>
        <td>{!example ? "Missing baseline" : example.correct && !right.correct ? "New error" : !example.correct && right.correct ? "Fixed error" : right.correct ? "Both correct" : "Both incorrect"}</td>
      </tr>)}</tbody>
    </table></div>}
    {filtered.length > shown.length ? <p>Showing the first {shown.length} matching examples.</p> : null}
  </article>;
}

export function RecordedReportView({ report }: { readonly report: ResearchReport }) {
  return <article className="evaluation-card" aria-label="Recorded human report">
    <h3>{report.reportId}</h3>
    <p><Badge tone="neutral">{VERDICT_NAMES[report.verdict]}</Badge> Human conclusion by {report.actorId}</p>
    <p className="note">Revision {report.experimentRevision} · {report.submittedAt}</p>
    <h4>Rationale</h4><p className="evaluation-prose">{report.rationale}</p>
    <h4>Research narrative</h4><p className="evaluation-prose">{report.narrative}</p>
    <ComparisonView comparison={report.comparison} />
    {report.evidenceRefs.length ? <><h4>Additional evidence</h4><ul>{report.evidenceRefs.map(id => <li key={id}>{id}</li>)}</ul></> : null}
    <p className="note">Immutable recorded judgement. To write a new interpretation, select an evaluation and record a separate report.</p>
  </article>;
}
