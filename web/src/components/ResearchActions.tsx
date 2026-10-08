/** Explicit research intents with editable drafts and exact-body retry. */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { CommandReceipt } from "../generated/local-api";

const id = (prefix: string) => `browser.${prefix}.${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`;

export function ResearchActions({ onRecorded }: { readonly onRecorded: () => void }) {
  const [project, setProject] = useState("");
  const [head, setHead] = useState(0);
  const [revision, setRevision] = useState(1);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const pending = useRef<string | null>(null);
  const [status, setStatus] = useState("");
  const [receipt, setReceipt] = useState<CommandReceipt | null>(null);
  const [profile, setProfile] = useState("");
  const [inspected, setInspected] = useState<{ id: string; digest: string } | null>(null);
  const [base, setBase] = useState("");
  const [candidate, setCandidate] = useState("");
  const [draft, setDraft] = useState("");
  const [validated, setValidated] = useState<string | null>(null);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState("reject");
  const [overrides, setOverrides] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [questionRequest, setQuestionRequest] = useState("");
  const [inbox, setInbox] = useState("");
  const [evidence, setEvidence] = useState("");
  const [source, setSource] = useState("");
  const [license, setLicense] = useState("LicenseRef-Unknown");
  const [rights, setRights] = useState("unknown");
  const [training, setTraining] = useState(false);
  const signature = JSON.stringify([draft, base, candidate, revision]);
  const [amended, setAmended] = useState(false);

  async function refresh() {
    try { const workspace = await api.workspace(); setProject(workspace.projectId); setHead(workspace.highWaterMark); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Workspace unavailable."); }
  }
  useEffect(() => { void refresh(); }, []);

  async function dispatch(body: string) {
    if (sending.current) return;
    sending.current = true; pending.current = body; setBusy(true);
    try {
      const next = await api.command(body); setReceipt(next); setHead(next.observedHead);
      const result = next.result;
      if (next.operation === "model.inspect" && typeof result["materialDigest"] === "string") {
        const intent = JSON.parse(body) as { operation: { profileId: string } };
        setInspected({ id: intent.operation.profileId, digest: result["materialDigest"] });
      }
      if (result["draft"] && typeof result["draft"] === "object") {
        const text = JSON.stringify(result["draft"], null, 2);
        const boundBase = typeof result["baseArtifact"] === "string" ? result["baseArtifact"] : base;
        const boundCandidate = typeof result["candidateArtifact"] === "string" ? result["candidateArtifact"] : candidate;
        setDraft(text); setAmended(false); setBase(boundBase); setCandidate(boundCandidate);
        setValidated(JSON.stringify([text, boundBase, boundCandidate, revision]));
        const proposal = result["draft"] as Record<string, unknown>;
        if (typeof proposal["proposalId"] === "string") setTarget(proposal["proposalId"]);
      }
      setStatus(`Receipt ${next.commandId}: ${String(result["observation"] ?? result["disposition"] ?? "recorded")}. Review the result below.`);
      if (next.factEventIds.length > 0) onRecorded();
    } catch (error) {
      setStatus(`${error instanceof Error ? error.message : "Response unconfirmed."} Inspect facts and budget; retry reuses the exact intent.`);
    } finally { sending.current = false; setBusy(false); }
  }
  function send(operation: Record<string, unknown>) {
    if (sending.current || project === "") return;
    void dispatch(JSON.stringify({ apiVersion: "researchos.dev/application/v0alpha1", kind: "ApplicationCommand",
      commandId: id("research"), actorId: "browser-operator", submittedAt: new Date().toISOString(),
      expectedHead: head, expectedRevision: revision, operation }));
  }
  function document(kind: string, subject: string) {
    return { apiVersion: "researchos.dev/v0alpha1", kind, projectId: project, experimentRevision: revision,
      source: "researchos://browser/research", subject, streamid: "stream.research",
      actor: { id: "browser-operator", kind: "human" }, event: { id: id("fact"), time: new Date().toISOString() }, evidenceRefs: [] };
  }
  function draftOperation(kind: string) {
    try {
      const proposal = JSON.parse(draft) as Record<string, unknown>;
      if (amended) {
        proposal["actor"] = { id: "browser-operator", kind: "human" };
        proposal["event"] = { id: id("amendment"), time: new Date().toISOString() };
      }
      send({ kind, proposal, baseArtifact: base, candidateArtifact: candidate });
    }
    catch { setStatus("Draft must be a valid structured proposal document."); }
  }
  return <section aria-labelledby="research-actions-heading">
    <h2 id="research-actions-heading">Research workflow</h2>
    <p>Review an editable draft, preserve questions and disagreement, then record a reasoned decision. These actions grant no execution permissions.</p>
    <p>Project <code>{project}</code>; fact head {head}. <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh research head</button></p>
    <label>Base revision <input type="number" min={1} value={revision} onChange={(event) => setRevision(Number(event.target.value))} /></label>
    <fieldset disabled={busy || project === ""}><legend>Model draft and budget</legend>
      <label>Installed model profile <input value={profile} onChange={(event) => setProfile(event.target.value)} /></label>
      <button type="button" onClick={() => send({ kind: "model.inspect", profileId: profile })}>Inspect model and budget</button>
      <button type="button" disabled={inspected?.id !== profile} onClick={() => send({ kind: "model.generate", profileId: profile, materialDigest: inspected?.digest })}>Generate draft</button>
      <button type="button" onClick={() => send({ kind: "research.budget" })}>Show research budget</button>
      <button type="button" onClick={() => send({ kind: "model.observe", profileId: profile })}>Observe model call</button>
      <p>Mock profiles work offline without a key. A configured compatible profile may send a model request and reserve budget. An uncertain dispatch stays reserved; another intent cannot redispatch the same call.</p>
    </fieldset>
    <fieldset disabled={busy || project === ""}><legend>Review or amend the proposal</legend>
      <label>Base specification artifact <input value={base} onChange={(event) => setBase(event.target.value)} /></label>
      <label>Candidate specification artifact <input value={candidate} onChange={(event) => setCandidate(event.target.value)} /></label>
      <label>Editable proposal: rationale, predictions, falsification, risks and citations<textarea rows={12} value={draft} onChange={(event) => { setDraft(event.target.value); setAmended(true); }} /></label>
      <button type="button" onClick={() => draftOperation("research.draft")}>Validate draft and recompute difference</button>
      <button type="button" disabled={validated !== signature} onClick={() => draftOperation("research.submit")}>Record validated proposal</button>
      <p>Editing requires fresh validation. The server verifies artifacts, base revision and every citation.</p>
    </fieldset>
    <fieldset disabled={busy || project === ""}><legend>Decision and disagreement</legend>
      <label>Proposal ID <input value={target} onChange={(event) => setTarget(event.target.value)} /></label>
      <label>Rationale or objection<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <label>Decision <select value={decision} onChange={(event) => setDecision(event.target.value)}><option value="reject">Reject</option><option value="accept">Accept</option><option value="modify">Request amendment</option></select></label>
      <label>Dissent IDs explicitly overridden (comma separated)<input value={overrides} onChange={(event) => setOverrides(event.target.value)} /></label>
      <button type="button" onClick={() => send({ kind: "research.record", document: { ...document("DecisionRecordRequest", target), decisionId: id("decision"), targetKind: "proposal", targetId: target, outcome: decision, rationale: reason, overriddenDissentIds: overrides.split(",").map((item) => item.trim()).filter(Boolean) } })}>Record human decision</button>
      <button type="button" onClick={() => send({ kind: "research.record", document: { ...document("DissentRecordRequest", target), dissentId: id("dissent"), targetKind: "proposal", targetId: target, objections: [{ kind: "other", statement: reason }] } })}>Preserve dissent</button>
    </fieldset>
    <fieldset disabled={busy || project === ""}><legend>Questions and answers</legend>
      <label>Structured question supplied by a model or system<textarea rows={4} value={questionRequest} onChange={(event) => setQuestionRequest(event.target.value)} /></label>
      <button type="button" onClick={() => { try {
        const supplied = JSON.parse(questionRequest) as Record<string, unknown>;
        if (supplied["kind"] !== "QuestionAskRequest") { setStatus("Supply a model or system question request."); return; }
        send({ kind: "research.record", document: supplied });
      } catch { setStatus("Question document is not valid JSON."); } }}>Record supplied question</button>
      <label>Question ID <input value={question} onChange={(event) => setQuestion(event.target.value)} /></label>
      <label>Human answer<textarea value={answer} onChange={(event) => setAnswer(event.target.value)} /></label>
      <button type="button" onClick={() => send({ kind: "research.record", document: { ...document("QuestionAnswerRequest", question), questionId: question, answer: { text: answer }, rights: { status: "unknown", allowedUses: ["research-read"] } } })}>Record answer</button>
      <p>Answers preserve unknown rights by default. Reading permission is separate from training permission.</p>
    </fieldset>
    <fieldset disabled={busy || project === ""}><legend>Import operator-staged evidence</legend>
      <label>File in evidence inbox <input value={inbox} onChange={(event) => setInbox(event.target.value)} /></label>
      <label>Evidence ID <input value={evidence} onChange={(event) => setEvidence(event.target.value)} /></label>
      <label>Versioned source URI <input value={source} onChange={(event) => setSource(event.target.value)} /></label>
      <label>License <input value={license} onChange={(event) => setLicense(event.target.value)} /></label>
      <label>Rights <select value={rights} onChange={(event) => setRights(event.target.value)}><option value="unknown">Unknown</option><option value="allowed">Allowed</option><option value="restricted">Restricted</option></select></label>
      <label><input type="checkbox" checked={training} onChange={(event) => setTraining(event.target.checked)} /> Source explicitly permits training</label>
      <button type="button" onClick={() => send({ kind: "evidence.import", inboxFile: inbox, document: { ...document("EvidenceImportRequest", evidence), streamid: "stream.evidence", evidenceId: evidence, sourceUri: source, mediaType: inbox.endsWith(".pdf") ? "application/pdf" : "text/markdown", sourceType: "note", license, rights, allowedUses: training ? ["research-read", "training"] : ["research-read"] } })}>Import evidence</button>
      <p>Only operator-staged Markdown or PDF files in the dedicated inbox are imported. Text cannot authorize tools or runs.</p>
    </fieldset>
    {status ? <p role="status">{status}</p> : null}
    <button type="button" disabled={busy || pending.current === null} onClick={() => { if (pending.current !== null) void dispatch(pending.current); }}>Retry exact research intent</button>
    {receipt ? <details open><summary>Verified receipt and review result</summary><pre>{JSON.stringify(receipt.result, null, 2)}</pre></details> : null}
  </section>;
}
