"""Actual local CPU launch fixture for browser testing; no human acceptance evidence."""

from __future__ import annotations

import json
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from wsgiref.simple_server import make_server

from test_application_native import setup_native

from llm_research_os.application.workspace import load_workspace
from llm_research_os.recovery.backup import create_backup
from llm_research_os.web.app import LocalApi
from llm_research_os.web.serve import BoundedWSGIServer, _QuietHandler
from llm_research_os.web.sessions import SessionStore

base = Path(sys.argv[1])
if not (base / "controller/workspace.json").exists():
    workspace, world, _ = setup_native(base)
    create_backup(workspace, workspace.root / "backups/image1", now=datetime.now(UTC))
    (base / "fixture.json").write_text(json.dumps({"runId": world.request.run_id}))
workspace = load_workspace(base / "controller")
server = make_server(
    "127.0.0.1", 0, lambda *_: [], server_class=BoundedWSGIServer, handler_class=_QuietHandler
)
port = server.server_port
api = LocalApi(
    workspace,
    sessions=SessionStore(bootstrap_token="smoke-only-bootstrap"),
    allowed_hosts=frozenset({f"127.0.0.1:{port}"}),
    allowed_origin=f"http://127.0.0.1:{port}",
)
server.set_app(api.wsgi)
print(
    json.dumps(
        {"url": f"http://127.0.0.1:{port}", **json.loads((base / "fixture.json").read_text())}
    ),
    flush=True,
)


def stop(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, stop)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
