"""``research-os`` CLI — create/validate/run/inspect the M0 vertical loop.

Subcommands:
  validate  Validate a spec document and explain any errors.
  diff      Show the semantic difference between two spec revisions.
  schema    Print the versioned JSON Schema contract.
  run       Validate a spec and execute it on the SimulatedRuntime.
  events    List recorded events (optionally scoped to a run) and run status.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from research_os.runtime import Outcome, SimulatedRuntime
from research_os.schema import research_spec_schema_json
from research_os.store import EventStore
from research_os.validation import load_yaml, semantic_diff, validate_document


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _cmd_validate(args: argparse.Namespace) -> int:
    result = validate_document(load_yaml(_read(args.spec)))
    if result.valid:
        assert result.spec is not None
        print(
            f"OK: {args.spec} is a valid ResearchSpec "
            f"(project={result.spec.metadata.id}, revision={result.spec.metadata.revision})"
        )
        return 0
    print(f"INVALID: {args.spec}", file=sys.stderr)
    for issue in result.issues:
        print(f"  - {issue}", file=sys.stderr)
    return 1


def _cmd_diff(args: argparse.Namespace) -> int:
    old = validate_document(load_yaml(_read(args.old)))
    new = validate_document(load_yaml(_read(args.new)))
    if not (old.valid and new.valid):
        print("Both specs must be valid to compute a semantic diff.", file=sys.stderr)
        return 1
    assert old.spec is not None and new.spec is not None
    diff = semantic_diff(old.spec, new.spec)
    if diff.empty:
        print("No semantic differences.")
        return 0
    for path, value in diff.added.items():
        print(f"+ {path} = {value!r}")
    for path, value in diff.removed.items():
        print(f"- {path} = {value!r}")
    for path, (before, after) in diff.changed.items():
        print(f"~ {path}: {before!r} -> {after!r}")
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    print(research_spec_schema_json())
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    result = validate_document(load_yaml(_read(args.spec)))
    if not result.valid:
        print(f"INVALID spec, refusing to run: {args.spec}", file=sys.stderr)
        for issue in result.issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1
    assert result.spec is not None
    store = EventStore(args.db)
    runtime = SimulatedRuntime(store)
    run_id = runtime.run(result.spec, steps=args.steps, outcome=Outcome(args.outcome))
    status = store.run_status(run_id)
    print(f"run_id={run_id} status={status} events={store.count()} db={args.db}")
    return 0


def _cmd_events(args: argparse.Namespace) -> int:
    store = EventStore(args.db)
    for event in store.read(run_id=args.run_id):
        if args.cloudevents:
            print(json.dumps(event.to_cloudevent(), sort_keys=True))
        else:
            print(f"{event.time}  {event.type:<28}  {event.subject}  {event.data}")
    if args.run_id:
        print(f"# run {args.run_id} status: {store.run_status(args.run_id)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-os", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="Validate a spec document.")
    p_validate.add_argument("spec")
    p_validate.set_defaults(func=_cmd_validate)

    p_diff = sub.add_parser("diff", help="Semantic diff between two spec revisions.")
    p_diff.add_argument("old")
    p_diff.add_argument("new")
    p_diff.set_defaults(func=_cmd_diff)

    p_schema = sub.add_parser("schema", help="Print the versioned JSON Schema.")
    p_schema.set_defaults(func=_cmd_schema)

    p_run = sub.add_parser("run", help="Validate then run on the SimulatedRuntime.")
    p_run.add_argument("spec")
    p_run.add_argument("--db", default="research_os.db")
    p_run.add_argument("--steps", type=int, default=3)
    p_run.add_argument(
        "--outcome", choices=[o.value for o in Outcome], default=Outcome.COMPLETE.value
    )
    p_run.set_defaults(func=_cmd_run)

    p_events = sub.add_parser("events", help="List recorded events.")
    p_events.add_argument("--db", default="research_os.db")
    p_events.add_argument("--run-id", dest="run_id", default=None)
    p_events.add_argument("--cloudevents", action="store_true")
    p_events.set_defaults(func=_cmd_events)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = args.func
    result: int = func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
