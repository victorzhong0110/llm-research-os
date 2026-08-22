"""Command-line entry point for the M0 protocol toolchain."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from pydantic import ValidationError

from llm_research_os.spec.diff import semantic_diff
from llm_research_os.spec.io import SpecLoadError, load_spec
from llm_research_os.spec.schema import canonical_schema, schema_matches, write_schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="researchos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a ResearchSpec document")
    validate.add_argument("document", type=Path)

    schema = subparsers.add_parser("schema", help="print, write, or check the JSON Schema")
    schema_group = schema.add_mutually_exclusive_group()
    schema_group.add_argument("--output", type=Path)
    schema_group.add_argument("--check", type=Path)

    diff = subparsers.add_parser("diff", help="compare two immutable ResearchSpec revisions")
    diff.add_argument("old", type=Path)
    diff.add_argument("new", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return _validate(args.document)
    if args.command == "schema":
        return _schema(args.output, args.check)
    if args.command == "diff":
        return _diff(args.old, args.new)
    raise AssertionError(f"unhandled command: {args.command}")


def _validate(document: Path) -> int:
    try:
        spec = load_spec(document)
    except (SpecLoadError, ValidationError) as exc:
        print(json.dumps(_error_payload(exc), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "valid": True,
                "projectId": spec.metadata.id,
                "revision": spec.metadata.revision,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _schema(output: Path | None, check: Path | None) -> int:
    if check is not None:
        if schema_matches(check):
            print(f"schema is current: {check}")
            return 0
        print(f"schema differs from generated contract: {check}", file=sys.stderr)
        return 1
    if output is not None:
        write_schema(output)
        print(f"wrote schema: {output}")
        return 0
    print(canonical_schema(), end="")
    return 0


def _diff(old_path: Path, new_path: Path) -> int:
    try:
        old = load_spec(old_path)
        new = load_spec(new_path)
        changes = semantic_diff(old, new)
    except (SpecLoadError, ValidationError, ValueError) as exc:
        print(json.dumps(_error_payload(exc), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "projectId": old.metadata.id,
                "fromRevision": old.metadata.revision,
                "toRevision": new.metadata.revision,
                "changes": [change.as_dict() for change in changes],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _error_payload(exc: Exception) -> dict[str, object]:
    if isinstance(exc, ValidationError):
        errors = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors(include_url=False, include_context=False, include_input=False)
        ]
    else:
        errors = [{"location": [], "message": str(exc), "type": type(exc).__name__}]
    return {"valid": False, "errors": errors}


def entrypoint() -> NoReturn:
    raise SystemExit(main())
