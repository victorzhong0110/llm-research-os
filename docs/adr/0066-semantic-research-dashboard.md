# ADR-0066: A semantic research dashboard with human layout intent

- Status: Product direction accepted by the maintainer on 2026-10-15;
  implementation and detailed contracts pending
- Date: 2026-10-15
- Delivery plan: [Research dashboard](../plans/research-dashboard.md)

## Context

The maintainer's checkpoint experience exposed a product problem: a first-time
user cannot naturally understand the workbench and complete useful work. Passing
engineering checks and improving individual tabs do not establish usability.
The maintainer paused the existing checkpoint trial campaign and requested a
dashboard-centered redesign, with the visual and interaction direction agreed
before implementation.

A fixed column pipeline cannot express research that branches, compares, shares
resources, and accumulates evidence. An unconstrained canvas loses meaning.
A graph using only connecting lines also cannot communicate containment,
subordination, and peer relationships clearly.

## Decision

The primary work surface is a research map: a concise spatial overview of current
work, observable AI activity, resource allocation, recent results, and items
needing human attention. Position and grouping convey logic without imposing a
single top-to-bottom or left-to-right workflow. Hover provides a short preview;
selection opens evidence, visualizations, AI interpretation, and relevant actions.
Keyboard and touch users can reach the same information without hovering.

Represent containment with regions, subordinate activity with attached elements,
peers with comparable treatment and grouping, dependencies with selective directed
edges, and references/shared resources with explicit associations. Do not force
every relation into a tree or display every edge at overview scale.

Keep research facts separate from view intent. Moving, resizing, pinning, or
visually grouping components records how the user organizes and attends to work.
It does not alter ownership, execution dependencies, resource assignments, or
authorization. An operation that changes a semantic relationship identifies its
meaning and affected objects before it is applied. A visual group is not
automatically a domain container. Layout-derived AI interpretations remain
inferences until expressed as explicit user intent or supported by evidence.

Layout follows hard semantic constraints and user pins while allowing flexible
local placement. Updates preserve the user's spatial context, support undo, and
avoid rearranging the whole map when new activity arrives.

The product supplies a framework of reusable components and inspectable view
definitions. The user's AI can compose and maintain views using those contracts;
humans can edit and retain their arrangement. Built-in and custom components share
theme, data provenance, lifecycle, accessibility, and interaction conventions.
AI-authored view changes do not grant execution or network authority, and custom
component declarations do not authorize arbitrary code execution.

Provide two interchangeable skins: restrained black/white surfaces, inspired by
Apple/OpenAI, and low-saturation warm paper, inspired by Anthropic/Claude. Offer
user customization within common readability and state conventions. A skin
changes presentation, not data, relations, authority, or layout meaning.

## Consequences and trade-offs

- The first useful experience must work without knowledge of internal IDs,
  digest formats, or JSON editing. Advanced inspection remains available.
- A semantic map requires more interaction design than a grid of cards. Use
  constrained grouping, stable anchors, progressive detail, and explicit editing
  modes to keep it understandable; do not require users to draw a map first.
- Shared resources may have several contextual representations of one entity.
  Those representations must not create duplicate facts or imply exclusive
  ownership.
- Missing, stale, simulated, and observed data remain distinguishable. An AI
  activity indicator refers to recorded work, not imagined internal reasoning.
  Official provider status, local request health, requested resource allocation,
  and measured utilization remain separate observations.
- Detailed persistence, schemas, layout algorithms, rendering dependencies, and
  custom-code isolation are implementation decisions still to be reviewed. This
  ADR does not claim those capabilities exist.
- Existing EventStore/CAS, Run/Attempt, Worker grants, and human authorization
  retain their meaning. The redesign does not close any checkpoint or replace
  pending live evidence. Its delivery is a continuation under the existing M3
  plan, not a renumbering of R01–R16.

## Alternatives considered

- Fixed hierarchical dashboard or pipeline: easy to scan, but makes branching,
  comparison, and shared resources subordinate to an arbitrary stage order.
- Fully free canvas: expressive, but does not preserve the logical relationships
  the maintainer wants the map to communicate.
- Pure node-and-edge graph: useful for dependencies, insufficient for the other
  relationships and too dense as an always-visible overview.
- Chat as the main interface: useful for requesting changes and explanations,
  but does not provide the persistent shared overview requested here.
