import json
from pathlib import Path

import jsonschema
import pytest

from llm_research_os.events.catalog import core_payload_models, payload_catalog
from llm_research_os.workers.models import PAYLOAD_MODELS


def test_catalog_publishes_domain_models_without_drift() -> None:
    catalog = payload_catalog()
    committed = Path(__file__).parents[1] / "schemas/research-event-payloads/catalog.json"
    assert json.loads(committed.read_text()) == catalog
    assert set(PAYLOAD_MODELS).issubset(core_payload_models())
    for schema in catalog["payloads"].values():
        jsonschema.Draft202012Validator.check_schema(schema)


def test_registered_completion_rejects_missing_fields() -> None:
    schema = payload_catalog()["payloads"]["work.completed"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({}, schema)


def test_extensions_not_silently_granted_authority() -> None:
    assert "extension.execute" not in core_payload_models()
