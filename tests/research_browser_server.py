"""Real API with an explicitly synthetic offline research-draft fixture."""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

from test_application_research_workflow import setup_research

from llm_research_os.application.service import ApplicationService
from llm_research_os.web.app import LocalApi
from llm_research_os.web.serve import BoundedWSGIServer, _QuietHandler
from llm_research_os.web.sessions import SessionStore

base = Path(sys.argv[1])
root = base / "workspace"
if not (root / "workspace.json").exists():
    service, data = setup_research(base)
    (base / "browser-fixture.json").write_text(
        json.dumps({"profile": "mock", "proposalId": data["proposal"]["proposalId"]})
    )
else:
    service = ApplicationService.open(root)
fixture = json.loads((base / "browser-fixture.json").read_text())
server = make_server(
    "127.0.0.1", 0, lambda *_: [], server_class=BoundedWSGIServer, handler_class=_QuietHandler
)
port = server.server_port
api = LocalApi(
    service.workspace,
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
