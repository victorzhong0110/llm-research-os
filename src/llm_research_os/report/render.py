"""Static HTML and Markdown renderers. Every claim cites an ``eventId``."""

from __future__ import annotations

import html

from llm_research_os.report.fold import RunReport, format_consumed


def render_markdown(report: RunReport) -> str:
    lines = [
        f"# Run `{_md(report.run_id)}`",
        "",
        f"Project `{_md(report.project_id)}`. Store head sequence {report.last_sequence}.",
        "This document is a projection. EventStore remains the fact source.",
        "",
        "## Research",
        *_research_markdown(report),
        "",
        "## Training",
        *_training_markdown(report),
        "",
        "## Cost",
        *_cost_markdown(report),
        "",
        "## Lineage",
        *_lineage_markdown(report),
        "",
        "## Event index",
        *_index_markdown(report),
        "",
    ]
    return "\n".join(lines)


def render_html(report: RunReport) -> str:
    body = [
        f"<h1>Run <code>{_html(report.run_id)}</code></h1>",
        (
            f"<p>Project <code>{_html(report.project_id)}</code>. "
            f"Store head sequence {report.last_sequence}. "
            "This document is a projection. EventStore remains the fact source.</p>"
        ),
        '<h2 id="research">Research</h2>',
        *_research_html(report),
        '<h2 id="training">Training</h2>',
        *_training_html(report),
        '<h2 id="cost">Cost</h2>',
        *_cost_html(report),
        '<h2 id="lineage">Lineage</h2>',
        *_lineage_html(report),
        '<h2 id="event-index">Event index</h2>',
        *_index_html(report),
    ]
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8"/>\n'
        f"<title>Run {_html(report.run_id)}</title>\n"
        "<style>body{font-family:sans-serif;max-width:52rem;margin:2rem auto;padding:0 1rem}"
        "code{font-size:0.95em} li{margin:0.25rem 0}</style>\n"
        "</head>\n"
        "<body>\n" + "\n".join(body) + "\n</body>\n</html>\n"
    )


def _research_markdown(report: RunReport) -> list[str]:
    ledger = report.ledger
    if not ledger.proposals and not ledger.dissents and not ledger.decisions:
        return ["No proposal, dissent, or decision facts for this project."]
    lines: list[str] = []
    for proposal in ledger.proposals:
        lines.append(
            f"- Proposal `{_md(proposal.proposal_id)}` "
            f"{_md_link(proposal.event_id)} state `{_md(proposal.revision_state.value)}`."
        )
    for dissent in ledger.dissents:
        lines.append(
            f"- Dissent `{_md(dissent.dissent_id)}` {_md_link(dissent.event_id)} "
            f"targets `{_md(dissent.target_id)}`."
        )
    for decision in ledger.decisions:
        lines.append(
            f"- Decision `{_md(decision.decision_id)}` {_md_link(decision.event_id)} "
            f"outcome `{_md(decision.outcome.value)}`."
        )
    return lines


def _training_markdown(report: RunReport) -> list[str]:
    if not report.training and not report.evaluation:
        return ["No `training.step` or `evaluation.metric` facts for this run."]
    lines: list[str] = []
    for step in report.training:
        lines.append(
            f"- Synthetic step {step.payload.step} loss `{_md(step.payload.loss)}` "
            f"{_md_link(step.stored.event.id)}."
        )
    for metric in report.evaluation:
        lines.append(
            f"- Synthetic `{_md(metric.payload.name)}` `{_md(metric.payload.value)}` "
            f"split `{_md(metric.payload.split)}` {_md_link(metric.stored.event.id)}."
        )
    return lines


def _cost_markdown(report: RunReport) -> list[str]:
    if not report.budget_events:
        return ["No `budget.*` facts for this project."]
    lines = [
        f"- Consumed `{_md(format_consumed(report.budget))}` CNY "
        f"{_md_link(report.budget_events[-1].event.id)}."
    ]
    for stored in report.budget_events:
        amount = _budget_amount(stored.event.data.payload)
        lines.append(
            f"- `{_md(stored.event.type)}` `{_md(amount)}` CNY {_md_link(stored.event.id)}."
        )
    return lines


def _lineage_markdown(report: RunReport) -> list[str]:
    if report.snapshot is None:
        status = "none"
        snapshot_id = report.lineage[0].event.id
    else:
        status = report.snapshot.status.value
        snapshot_id = report.snapshot.last_event_id
    lines = [f"- Run status `{_md(status)}` {_md_link(snapshot_id)}."]
    for stored in report.lineage:
        lines.append(
            f"- `{_md(stored.event.type)}` sequence {stored.sequence} {_md_link(stored.event.id)}."
        )
    return lines


def _index_markdown(report: RunReport) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for stored in (*report.lineage, *report.budget_events):
        event_id = stored.event.id
        if event_id in seen:
            continue
        seen.add(event_id)
        lines.append(
            f'- <a id="{_html(event_id)}"></a>`{_md(event_id)}` `{_md(stored.event.type)}`'
        )
    for event_id in _ledger_event_ids(report):
        if event_id in seen:
            continue
        seen.add(event_id)
        lines.append(f'- <a id="{_html(event_id)}"></a>`{_md(event_id)}`')
    return lines or ["No events."]


def _research_html(report: RunReport) -> list[str]:
    ledger = report.ledger
    if not ledger.proposals and not ledger.dissents and not ledger.decisions:
        return ["<p>No proposal, dissent, or decision facts for this project.</p>"]
    items: list[str] = []
    for proposal in ledger.proposals:
        items.append(
            "<li>Proposal <code>"
            f"{_html(proposal.proposal_id)}</code> {_html_link(proposal.event_id)} "
            f"state <code>{_html(proposal.revision_state.value)}</code>.</li>"
        )
    for dissent in ledger.dissents:
        items.append(
            "<li>Dissent <code>"
            f"{_html(dissent.dissent_id)}</code> {_html_link(dissent.event_id)} "
            f"targets <code>{_html(dissent.target_id)}</code>.</li>"
        )
    for decision in ledger.decisions:
        items.append(
            "<li>Decision <code>"
            f"{_html(decision.decision_id)}</code> {_html_link(decision.event_id)} "
            f"outcome <code>{_html(decision.outcome.value)}</code>.</li>"
        )
    return ["<ul>", *items, "</ul>"]


def _training_html(report: RunReport) -> list[str]:
    if not report.training and not report.evaluation:
        return [
            "<p>No <code>training.step</code> or "
            "<code>evaluation.metric</code> facts for this run.</p>"
        ]
    items: list[str] = []
    for step in report.training:
        items.append(
            f"<li>Synthetic step {step.payload.step} loss "
            f"<code>{_html(step.payload.loss)}</code> "
            f"{_html_link(step.stored.event.id)}.</li>"
        )
    for metric in report.evaluation:
        items.append(
            f"<li>Synthetic <code>{_html(metric.payload.name)}</code> "
            f"<code>{_html(metric.payload.value)}</code> split "
            f"<code>{_html(metric.payload.split)}</code> "
            f"{_html_link(metric.stored.event.id)}.</li>"
        )
    return ["<ul>", *items, "</ul>"]


def _cost_html(report: RunReport) -> list[str]:
    if not report.budget_events:
        return ["<p>No <code>budget.*</code> facts for this project.</p>"]
    items = [
        "<li>Consumed <code>"
        f"{_html(format_consumed(report.budget))}</code> CNY "
        f"{_html_link(report.budget_events[-1].event.id)}.</li>"
    ]
    for stored in report.budget_events:
        amount = _budget_amount(stored.event.data.payload)
        items.append(
            f"<li><code>{_html(stored.event.type)}</code> "
            f"<code>{_html(amount)}</code> CNY {_html_link(stored.event.id)}.</li>"
        )
    return ["<ul>", *items, "</ul>"]


def _lineage_html(report: RunReport) -> list[str]:
    if report.snapshot is None:
        status = "none"
        snapshot_id = report.lineage[0].event.id
    else:
        status = report.snapshot.status.value
        snapshot_id = report.snapshot.last_event_id
    items = [f"<li>Run status <code>{_html(status)}</code> {_html_link(snapshot_id)}.</li>"]
    for stored in report.lineage:
        items.append(
            f"<li><code>{_html(stored.event.type)}</code> sequence {stored.sequence} "
            f"{_html_link(stored.event.id)}.</li>"
        )
    return ["<ul>", *items, "</ul>"]


def _index_html(report: RunReport) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for stored in (*report.lineage, *report.budget_events):
        event_id = stored.event.id
        if event_id in seen:
            continue
        seen.add(event_id)
        items.append(
            f'<li id="{_html(event_id)}"><code>{_html(event_id)}</code> '
            f"<code>{_html(stored.event.type)}</code></li>"
        )
    for event_id in _ledger_event_ids(report):
        if event_id in seen:
            continue
        seen.add(event_id)
        items.append(f'<li id="{_html(event_id)}"><code>{_html(event_id)}</code></li>')
    if not items:
        return ["<p>No events.</p>"]
    return ["<ul>", *items, "</ul>"]


def _ledger_event_ids(report: RunReport) -> tuple[str, ...]:
    ledger = report.ledger
    return tuple(
        entry.event_id
        for group in (ledger.proposals, ledger.dissents, ledger.decisions)
        for entry in group
    )


def _budget_amount(payload: dict[str, object]) -> str:
    for key in ("amount", "attempted"):
        value = payload.get(key)
        if type(value) is str:
            return value
    return "0.00"


def _html(value: str) -> str:
    return html.escape(value, quote=True)


def _html_link(event_id: str) -> str:
    escaped = _html(event_id)
    return f'<a href="#{escaped}"><code>{escaped}</code></a>'


def _md(value: str) -> str:
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")


def _md_link(event_id: str) -> str:
    return f"[`{_md(event_id)}`](#{event_id})"
