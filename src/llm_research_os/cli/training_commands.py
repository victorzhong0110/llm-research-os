"""Parse a pinned training-backend plan. This command does not launch GPU work."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.spec.io import SpecLoadError
from llm_research_os.training.errors import TrainingBackendError, TrainingBackendRequestError
from llm_research_os.training.ms_swift import plan_ms_swift
from llm_research_os.training.requests import load_training_backend_plan

_INPUT_ERRORS = (
    OSError,
    SpecLoadError,
    ValidationError,
    ValueError,
)


def run_training(args: argparse.Namespace) -> int:
    if args.training_command == "plan":
        return _plan(args.request, args.format)
    raise AssertionError(f"unhandled training command: {args.training_command}")


def _plan(request_path: Path, output_format: str) -> int:
    try:
        receipt = plan_ms_swift(load_training_backend_plan(request_path))
    except TrainingBackendRequestError as exc:
        print_error(exc, output_format)
        return 2
    except TrainingBackendError as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    payload = {
        "apiVersion": "researchos.dev/v0alpha1",
        **receipt.as_json(),
    }
    if output_format == "json":
        print(dumps_json(payload))
        return 0
    print("training plan: recorded")
    print(f"backend: {safe_text(receipt.backend_id)} {safe_text(receipt.backend_version)}")
    print(f"executed: {receipt.executed}")
    print(f"gpu: {safe_text(receipt.gpu)}")
    print(f"backendInstalled: {receipt.backend_installed}")
    print(f"costKnown: {receipt.cost_known}")
    print(f"argv: {safe_text(' '.join(receipt.argv))}")
    return 0
