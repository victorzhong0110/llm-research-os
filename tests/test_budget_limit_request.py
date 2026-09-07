from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.budget.errors import BudgetRequestError
from llm_research_os.budget.requests import (
    BudgetLimitRequestDocument,
    load_budget_limit_request,
)
from llm_research_os.budget.schema import budget_limit_request_schema_matches
from llm_research_os.cli import main
from llm_research_os.spec.io import load_document
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "budget-limit-requests"
SCHEMA = ROOT / "schemas" / "budget-limit-request" / "v0alpha1.schema.json"
VALID = EXAMPLES / "valid" / "minimal.json"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_committed_budget_limit_schema_is_current() -> None:
    assert budget_limit_request_schema_matches(SCHEMA)
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_valid_budget_limit_example() -> None:
    document = load_document(VALID)
    _validator().validate(document)
    request = BudgetLimitRequestDocument.model_validate(document)
    assert request.actor.kind == "human"
    assert request.cap == "1.00"


@pytest.mark.parametrize(
    "path",
    sorted((EXAMPLES / "invalid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_budget_limit_examples(path: Path) -> None:
    document = load_document(path)
    assert list(_validator().iter_errors(document))
    with pytest.raises(ValidationError):
        BudgetLimitRequestDocument.model_validate(document)
    with pytest.raises(BudgetRequestError):
        load_budget_limit_request(path)


def test_record_limit_cli_appends_one_fact(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "research.db"
    with EventStore(database):
        pass
    assert (
        main(
            [
                "budget",
                "record-limit",
                str(VALID),
                str(database),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["type"] == "budget.limit.recorded"
    assert payload["projectId"] == "example-minimal"
    with EventStore(database, require_existing=True) as store:
        assert store.last_sequence() == 1


def test_record_limit_rejects_ai_actor(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database):
        pass
    assert (
        main(
            [
                "budget",
                "record-limit",
                str(EXAMPLES / "invalid" / "ai-actor.json"),
                str(database),
            ]
        )
        == 2
    )
    with EventStore(database, require_existing=True) as store:
        assert store.last_sequence() == 0


def test_record_limit_does_not_create_a_missing_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing.db"
    assert (
        main(
            [
                "budget",
                "record-limit",
                str(VALID),
                str(database),
            ]
        )
        == 2
    )
    assert not database.exists()
