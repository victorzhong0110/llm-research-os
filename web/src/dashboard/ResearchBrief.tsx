import { useEffect, useRef, useState } from "react";
import type { Node, State } from "./model";

export interface BriefDraft {
  title: string;
  goal: string;
  success: string;
  materials: string;
  resources: string;
}
export const emptyBrief = (): BriefDraft => ({
  title: "", goal: "", success: "", materials: "", resources: "",
});

/** A brief is editable view intent. It does not introduce research or execution facts. */
export function appendBrief(state: State, draft: BriefDraft, id: string): State {
  if (state.components.length > 1995) throw new Error("This map has no room for five more components. Remove unused components first.");
  const y = Math.max(0, ...state.components.filter(n => !n.parentId).map(n => n.position.y + n.position.height)) + 40;
  if (y > 100000) throw new Error("The map has reached its vertical limit. Move a region upward before adding a brief.");
  const nodes: Node[] = [{
    id, type: "group", title: draft.title.trim(),
    body: "Research brief · human planning notes. Materials and resources still need to be verified before execution.",
    position: { x: 40, y, width: 920, height: 530 },
  }, ...[
    ["goal", "Research goal", draft.goal.trim()],
    ["success", "What would count as progress?", draft.success.trim()],
    ["materials", "Materials to prepare", draft.materials.trim() || "Not identified yet. Choose a baseline, data or source material and check its permitted use."],
    ["resources", "Resources to prepare", draft.resources.trim() || "Not identified yet. Decide whether this needs a model API, local compute or a remote machine."],
  ].map(([key, title, body], index): Node => ({
    id: `${id}.${key}`, type: "note", title: title!, body: body!, parentId: id,
    position: { x: index % 2 ? 476 : 24, y: index < 2 ? 64 : 296, width: 420, height: 210 },
  }))];
  return { ...state, components: [...state.components, ...nodes],
    viewport: { x: 20, y: 30 - y * 0.65, zoom: 0.65 } };
}

interface Props {
  draft: BriefDraft;
  onChange: (draft: BriefDraft) => void;
  busy: boolean;
  pending: boolean;
  complete: boolean;
  onSave: () => void;
  onView: () => void;
  onAgent: () => void;
  onNew: () => void;
}

export function ResearchBrief({ draft, onChange, busy, pending, complete, onSave, onView, onAgent, onNew }: Props) {
  const [step, setStep] = useState(pending ? 2 : 0);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    container.current?.closest(".map-inspector")?.scrollTo({ top: 0 });
    if (step === 2 || complete) container.current?.focus({ preventScroll: true });
  }, [step, complete]);
  const validGoal = !!draft.title.trim() && !!draft.goal.trim();
  const valid = validGoal && !!draft.success.trim();
  const locked = busy || pending;
  const field = (name: keyof BriefDraft, value: string) => onChange({ ...draft, [name]: value });
  if (complete) return <div className="map-brief" ref={container} tabIndex={-1}>
    <span className="map-eyebrow">BRIEF SAVED</span>
    <h2>Your research has a starting point.</h2>
    <p>Your goal, success criterion and preparation notes are now together on the map. Click a note to read it; use Edit to refine it.</p>
    <button type="button" className="map-primary" onClick={onView}>View my research brief</button>
    <h3>What comes next?</h3>
    <ol className="map-guide">
      <li><b>Prepare evidence.</b><p>Identify the baseline and source material. Check versions and permitted use before importing data.</p></li>
      <li><b>Choose resources.</b><p>Connect the model or machine you intend to use. A planning note is not a connected resource or an allocated budget.</p></li>
      <li><b>Review an executable plan.</b><p>Execution needs a prepared specification and reviewed resource configuration. This brief has not started a run.</p></li>
    </ol>
    <button type="button" onClick={onAgent}>Discuss this brief with my Agent</button>
    <p className="map-small">Opens your workspace inbox with this brief selected. Your own connected Agent supplies replies.</p>
    <button type="button" onClick={() => { onNew(); setStep(0); }}>Start another brief</button>
  </div>;
  return <div className="map-brief" ref={container} tabIndex={-1}>
    <span className="map-eyebrow">START WITH A QUESTION</span>
    <h2>What do you want to learn?</h2>
    <p>Turn an idea into a research brief on your map. You can begin before choosing a model or setting up a machine.</p>
    <p className="map-small">Your draft stays in this tab until saved.</p>
    <ol className="map-brief-steps" aria-label="Research brief steps">
      {["Goal", "Evidence", "Review"].map((label, index) => <li key={label} aria-current={step === index ? "step" : undefined}>{index + 1}. {label}</li>)}
    </ol>
    <form onSubmit={event => {
      event.preventDefault();
      if (busy || (step === 0 ? !validGoal : !valid)) return;
      if (step < 2) setStep(step + 1);
      else onSave();
    }}>
      <fieldset disabled={locked}>
        {step === 0 && <>
          <label>Brief title<input autoFocus maxLength={160} required value={draft.title} onChange={event => field("title", event.target.value)} placeholder="A short name you will recognize on the map" /></label>
          <label>Research goal<textarea rows={5} maxLength={4000} required value={draft.goal} onChange={event => field("goal", event.target.value)} placeholder="For example: can a smaller model answer questions about my documents accurately enough?" /></label>
          <p className="map-small">Use your own words. A question, a comparison or a concrete problem is enough to start.</p>
        </>}
        {step === 1 && <>
          <label>What would count as progress?<textarea autoFocus rows={4} maxLength={4000} required value={draft.success} onChange={event => field("success", event.target.value)} placeholder="What result would help you decide? What would show the idea did not work?" /></label>
          <label>Materials you already have (optional)<textarea rows={3} maxLength={4000} value={draft.materials} onChange={event => field("materials", event.target.value)} placeholder="A dataset, a paper, a baseline model, a few example questions…" /></label>
          <label>Resources you may use (optional)<textarea rows={3} maxLength={4000} value={draft.resources} onChange={event => field("resources", event.target.value)} placeholder="Your computer, a server, a model API, or still undecided" /></label>
          <p className="map-small">Names and notes are enough here. Leave uncertain items blank; the map will show what still needs preparation.</p>
        </>}
        {step === 2 && <>
          <h3>{draft.title}</h3>
          <dl className="map-brief-review">
            <dt>Goal</dt><dd>{draft.goal}</dd>
            <dt>Success criterion</dt><dd>{draft.success}</dd>
            <dt>Materials</dt><dd>{draft.materials || "Still to identify"}</dd>
            <dt>Resources</dt><dd>{draft.resources || "Still to identify"}</dd>
          </dl>
          <p>Save a new region with four editable planning notes, together with your current map arrangement. Execution setup comes after preparation.</p>
        </>}
      </fieldset>
      <div className="map-brief-actions">
        {step > 0 && <button type="button" disabled={locked} onClick={() => setStep(step - 1)}>Back</button>}
        <button type="submit" className="map-primary" disabled={busy || (pending && step < 2) || (step === 0 ? !validGoal : !valid)}>
          {busy ? "Saving…" : pending ? "Retry saving this brief" : step < 2 ? "Continue" : "Save brief to map"}
        </button>
      </div>
    </form>
  </div>;
}
