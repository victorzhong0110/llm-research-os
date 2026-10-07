# Operate an evidence-linked research draft

Use [the protocol](../protocols/research-workflow-v0alpha1.md) for exact binding and recovery rules. This workflow records research reasoning; native authorization and execution remain separate operations.

## Offline demonstration

From a source checkout with locked core/test dependencies installed, choose a new directory:

```bash
uv run python examples/research-workflow/create-demo.py /tmp/researchos-research-demo
uv run researchos web serve --root /tmp/researchos-research-demo
```

Open the locally printed bootstrap URL. In **Research**, enter profile `mock`, inspect the model/budget, then generate a draft. The staged material and all output are explicitly synthetic. Creating the demo sends no model request and creates no Run. Mock generation appends actual local model facts and stores the output; it requires no API key or paid provider.

Review the actual difference, source references, predictions, falsification conditions, risks and resource needs. Edit the proposal if necessary; validate it again before recording. An amendment is attributed to the human operator, while the generated draft stays in CAS. Record dissent and a reasoned accept/reject/amendment decision; refresh to see the preserved ledger. A decision does not start a task.

To import a source, stage a Markdown/PDF file in the dedicated `evidence-inbox`, give it a distinct evidence ID, versioned source URI and actual license/rights, and import it through Research. The demo includes `demo.md` as synthetic text. Unknown rights default to research reading only. Add its evidence ID to a proposal's `evidenceRefs` and revalidate; the preview shows the original version and allowed uses. Never place keys or private execution credentials in the inbox.

Questions supplied by a model/system can be recorded as existing strict `QuestionAskRequest` documents. Humans answer recorded question IDs; unknown reading/training rights remain distinct. Explicit dissent override IDs are retained next to the decision.

## A configured compatible provider

The operator stages an existing `OpenAICompatGenerateRequest` and `ModelFixture` under the workspace and installs a `ResearchModelProfile` with actual base/candidate CAS IDs. It uses the same endpoint, granted-capability, SecretRef and budget rules as `researchos models generate`. No endpoint or secret can be supplied in the browser command. Inspection shows declared reservation/capabilities and the project's current budget before the user chooses generation. The provider's response must be a strict proposal JSON document bound to the staged candidate/diff, never executable instructions.

Local loopback contract servers require no secret and zero CNY declared cap/reservation/consumption. This is a local contract rule, not a claim that remote providers cost zero. Remote configuration requires existing explicit network/paid authorization, an env secret reference and approved project budget. This engineering validation makes no paid-provider calls.

## An unconfirmed response

Retry the exact research intent to obtain its receipt; the UI retains the exact serialized body while mounted. After refresh/restart, enter the installed profile and choose **Observe model call**. Observation only reads recorded facts/CAS and budget. An incomplete call remains unknown and must not be rerun automatically. Open budget reservations remain visible; consumed/project budget numbers are not a provider invoice.

For an old path-based application proposal command, supply `baseArtifact` and `candidateArtifact` as well as the staged request path. The shared service recomputes the same diff. Historical M1 CLI examples remain historical; their asserted digests alone do not satisfy the new application workflow.

Actual tests cover loopback HTTP, Mock drafts, hostile text, invalid output, material/diff/citation refusal, concurrent CAS heads, lost receipts, observation, rejection, questions and preserved disagreement. Browser CI operates the committed bundle against real EventStore/CAS. Those synthetic tests do not represent a human research session, a scientific conclusion or Checkpoint C acceptance.
