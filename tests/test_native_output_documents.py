"""Published native output contracts agree with runtime validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.workers.native_output_documents import (
    NativeOutputReceipt,
    NativeReviewedTaskOutput,
)

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("name", "model", "schema"),
    [
        ("task-output", NativeReviewedTaskOutput, "native-reviewed-task-output"),
        ("receipt", NativeOutputReceipt, "native-output-receipt"),
    ],
)
def test_contract_examples(name, model, schema):  # type: ignore[no-untyped-def]
    validator = Draft202012Validator(
        json.loads((ROOT / "schemas" / schema / "v0alpha1.schema.json").read_text())
    )
    examples = ROOT / "examples" / "native-output-transfer"
    valid = json.loads((examples / f"{name}.valid.json").read_text())
    validator.validate(valid)
    assert model.model_validate(valid).model_dump(by_alias=True) == valid
    for path in examples.glob(f"{name}.invalid-*.json"):
        invalid = json.loads(path.read_text())
        assert not validator.is_valid(invalid)
        with pytest.raises(ValidationError):
            model.model_validate(invalid)
    for field in valid:
        invalid = {key: value for key, value in valid.items() if key != field}
        assert not validator.is_valid(invalid)
        with pytest.raises(ValidationError):
            model.model_validate(invalid)


@pytest.mark.parametrize("output", [None, True, 1, 1.5, "value", [], {}, [1, None, {"a": False}]])
def test_task_output_keeps_json_values(output: object) -> None:
    payload = json.loads(
        (ROOT / "examples/native-output-transfer/task-output.valid.json").read_text()
    )
    payload["output"] = output
    assert NativeReviewedTaskOutput.model_validate(payload).output == output
