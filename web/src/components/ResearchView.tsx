/** Research ledger: proposals, dissent, decisions and questions.
 *
 * R12's requirement is that disagreement stays visible. A decision that
 * overrides a dissent is shown next to the dissent it overrode, not instead of
 * it, and every rationale is rendered verbatim so a refresh cannot quietly drop
 * the reason a proposal was refused.
 */

import { useCallback } from "react";
import { api, type Paged } from "../api";
import { Badge, BoundedList, Empty, Failure, Loading } from "./Primitives";
import { usePage } from "./usePage";
import type { LedgerEntry, ResearchLedgerView } from "../generated/local-api";

/** One ledger row tagged with the kind it came from. */
interface Row {
  readonly kind: "decision" | "dissent" | "proposal" | "question";
  readonly entry: LedgerEntry;
}

const LIST_CAP = 100;

export function ResearchView() {
  const load = useCallback(
    async (): Promise<Paged<Row>> => {
      const ledger: ResearchLedgerView = await api.research();
      return {
        items: [
          ...ledger.proposals.map((entry) => ({ kind: "proposal" as const, entry })),
          ...ledger.dissents.map((entry) => ({ kind: "dissent" as const, entry })),
          ...ledger.decisions.map((entry) => ({ kind: "decision" as const, entry })),
          ...ledger.questions.map((entry) => ({ kind: "question" as const, entry })),
        ],
        nextCursor: null,
        highWaterMark: ledger.lastSequence,
      };
    },
    [],
  );
  const { page, error, reload } = usePage<Row>(load, null);

  if (error !== null) {
    return <Failure error={error} onRetry={reload} />;
  }
  if (page === null) {
    return <Loading label="Loading the research ledger" />;
  }
  if (page.items.length === 0) {
    return (
      <Empty
        title="No research facts yet"
        detail="Proposals, dissent, decisions and questions appear here once they are appended to this project's event store."
      />
    );
  }

  return (
    <section aria-labelledby="research-heading">
      <h2 id="research-heading">Research</h2>
      <p className="note">
        Every entry is a verified fact from this project's event store, read against high-water mark{" "}
        {page.highWaterMark}. A decision that overrides a dissent is shown next to the dissent, not instead
        of it. Nothing on this page is a draft.
      </p>
      <BoundedList
        items={page.items}
        cap={LIST_CAP}
        totalLabel="research facts"
        row={(row) => <LedgerRow kind={row.kind} entry={row.entry} />}
      />
    </section>
  );
}

function LedgerRow({ kind, entry }: { readonly kind: Row["kind"]; readonly entry: LedgerEntry }) {
  const body = entry as unknown as Record<string, unknown>;
  const overridden = Array.isArray(body["overriddenDissentIds"])
    ? (body["overriddenDissentIds"] as string[])
    : [];
  const outcome = typeof body["outcome"] === "string" ? body["outcome"] : null;
  const rationale = typeof body["rationale"] === "string" ? body["rationale"] : "";
  return (
    <tr>
      <td>
        <Badge tone={kind === "decision" ? "progress" : "neutral"}>{kind}</Badge>
      </td>
      <td>
        <code>{entry.eventId}</code>
      </td>
      <td>{outcome === null ? null : <Badge tone={toneForOutcome(outcome)}>{outcome}</Badge>}</td>
      <td>
        {rationale}
        {overridden.length > 0 ? (
          <span className="note"> — overrides {overridden.join(", ")}</span>
        ) : null}
      </td>
    </tr>
  );
}

function toneForOutcome(outcome: string): "success" | "warning" | "danger" | "neutral" {
  switch (outcome) {
    case "accept":
      return "success";
    case "reject":
      return "danger";
    case "modify":
      return "warning";
    default:
      return "neutral";
  }
}
