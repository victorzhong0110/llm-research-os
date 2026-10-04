"""Direct WSGI caller for the local API tests.

The app is exercised through the WSGI callable itself, so the tests need no
socket while still running the real middleware order: Host, then Origin, then
bootstrap/session, then CSRF, then the route.
"""

from __future__ import annotations

import io
import json
from typing import Any

from llm_research_os.web.app import LocalApi

HOST = "127.0.0.1:8787"
ORIGIN = f"http://{HOST}"
BOOTSTRAP = "test-bootstrap-secret-value"


class Client:
    """Minimal WSGI caller. Records status, headers and the joined body."""

    def __init__(self, api: LocalApi) -> None:
        self._api = api
        self.cookie: str | None = None
        self.csrf: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        query: str = "",
        host: str = HOST,
        origin: str | None = None,
        content_type: str | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        environ: dict[str, Any] = {
            "REQUEST_METHOD": method.upper(),
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(body),
            "wsgi.url_scheme": "http",
            "HTTP_HOST": host,
        }
        if self.cookie is not None:
            environ["HTTP_COOKIE"] = self.cookie
        if self.csrf is not None:
            environ["HTTP_X_RESEARCHOS_CSRF"] = self.csrf
        for name, value in (headers or {}).items():
            environ["HTTP_" + name.upper().replace("-", "_")] = value
        if origin is not None:
            environ["HTTP_ORIGIN"] = origin
        if content_type is not None:
            environ["CONTENT_TYPE"] = content_type
        if body:
            environ["CONTENT_LENGTH"] = str(len(body))

        captured: dict[str, Any] = {}

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            captured["status"] = int(status.split(" ", 1)[0])
            captured["headers"] = {key.lower(): value for key, value in response_headers}

        chunks = self._api.wsgi(environ, start_response)
        raw = b"".join(chunks)
        headers_out = dict(captured.get("headers", {}))
        set_cookie = headers_out.get("set-cookie")
        if set_cookie is not None and "=" in set_cookie:
            self.cookie = set_cookie.split(";", 1)[0]
        return int(captured["status"]), headers_out, _decode(raw)

    def bootstrap(self) -> tuple[int, dict[str, str], Any]:
        status, headers, payload = self.request(
            "POST",
            "/api/v0alpha1/session",
            headers={"X-ResearchOS-Bootstrap": BOOTSTRAP},
            origin=ORIGIN,
        )
        if status == 201 and isinstance(payload, dict):
            self.csrf = payload.get("csrfToken")
        return status, headers, payload


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return raw
