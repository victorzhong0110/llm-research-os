"""Export/check the independently valid JSON Schemas for core event payloads."""

import argparse
import json
from pathlib import Path

from llm_research_os.events.catalog import payload_catalog

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
path = Path(__file__).resolve().parents[1] / "schemas/research-event-payloads/catalog.json"
expected = json.dumps(payload_catalog(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
if args.check:
    raise SystemExit(0 if path.exists() and path.read_text() == expected else 1)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(expected)
