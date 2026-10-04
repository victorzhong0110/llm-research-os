"""Real local API with deterministic, explicitly synthetic browser-test evidence."""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

from test_run_control import _draft, _queued_draft, _started_draft
from test_web_regressions import _append, _root

from llm_research_os.application.workspace import load_workspace
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.research.control import ResearchControl
from llm_research_os.research.requests import (
    DecisionRecordRequestDocument,
    ProposalSubmitRequestDocument,
)
from llm_research_os.runs.control import RunControl
from llm_research_os.spec.io import load_spec
from llm_research_os.storage import EventStore
from llm_research_os.web.app import LocalApi
from llm_research_os.web.serve import BoundedWSGIServer, _QuietHandler
from llm_research_os.web.sessions import SessionStore

base = Path(sys.argv[1])
root = base / "project"
if not (root / "workspace.json").exists():
    _root(base)
    artifacts = LocalArtifactStore(root / "cas")
    spec = load_spec(Path(__file__).parents[1] / "examples/valid/minimal.yaml")
    spec_doc = spec.model_dump(mode="json", by_alias=True)
    graph = spec_doc["workflows"][0]["graph"]
    node = dict(graph["nodes"][0])
    node["id"] = "second"
    graph["nodes"].append(node)
    graph["edges"] = [{"source": graph["nodes"][0]["id"], "target": "second"}]
    spec_obj = artifacts.put_bytes(json.dumps(spec_doc).encode())
    data_obj = artifacts.put_bytes(b'{"source":"synthetic fixture","rows":3}')
    code_obj = artifacts.put_bytes(b'print("synthetic fixture")\n')
    config_obj = artifacts.put_bytes(b'{"seed":0,"synthetic":true}')
    result_obj = artifacts.put_bytes(
        json.dumps(
            {
                "synthetic": True,
                "metrics": {"loss": 0.25},
                "logs": "fixture only; no execution",
                "dataDigest": data_obj.digest,
                "codeDigest": code_obj.digest,
                "configDigest": config_obj.digest,
                "decisionEventId": "decision.smoke",
            }
        ).encode()
    )
    with EventStore(root / "control.db") as store:
        for i in range(1, 252):
            _append(store, i, project="proj-foreign")
        control = RunControl(store, project_id="proj-alpha", run_id="run-late")
        control.append(_queued_draft(project="proj-alpha", run="run-late"))
        control.append(_started_draft(project="proj-alpha", run="run-late"))
        control.append(
            _draft(
                "run.cancel.requested",
                {"reasonCode": "fixture-cancel"},
                event_id="evt.cancel.smoke",
                project="proj-alpha",
                run="run-late",
            )
        )
        examples = Path(__file__).parents[1] / "examples/research-decisions/valid"
        proposal = json.loads((examples / "proposal-submit.json").read_text())
        proposal.update(projectId="proj-alpha", rationale="browser smoke fixture only")
        proposal["event"]["id"] = "proposal.smoke"
        research = ResearchControl(store, project_id="proj-alpha")
        research.append(ProposalSubmitRequestDocument.model_validate(proposal).event_draft())
        decision = json.loads((examples / "decision-record.json").read_text())
        decision.update(
            projectId="proj-alpha",
            rationale="browser smoke fixture only",
            overriddenDissentIds=[],
            outcome="reject",
        )
        decision["event"]["id"] = "decision.smoke"
        research.append(DecisionRecordRequestDocument.model_validate(decision).event_draft())
    (base / "fixture.json").write_text(
        json.dumps({"spec": spec_obj.digest, "result": result_obj.digest})
    )
fixture = json.loads((base / "fixture.json").read_text())
input_spec = load_spec(Path(__file__).parents[1] / "examples/valid/minimal.yaml").model_dump(
    mode="json", by_alias=True
)
input_spec["metadata"]["id"] = "proj-alpha"
input_path = root / "browser-spec.json"
input_path.write_text(json.dumps(input_spec))
fixture["inputSpec"] = str(input_path)
# Bind before constructing the Host boundary, so an ephemeral port is exact.
server = make_server(
    "127.0.0.1", 0, lambda *_: [], server_class=BoundedWSGIServer, handler_class=_QuietHandler
)
port = server.server_port
api = LocalApi(
    load_workspace(root),
    sessions=SessionStore(bootstrap_token="smoke-only-bootstrap"),
    allowed_hosts=frozenset({f"127.0.0.1:{port}"}),
    allowed_origin=f"http://127.0.0.1:{port}",
)
server.set_app(api.wsgi)
print(json.dumps({"url": f"http://127.0.0.1:{port}", **fixture}), flush=True)


def stop(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, stop)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
