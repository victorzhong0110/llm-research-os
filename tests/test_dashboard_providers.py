"""Public provider reports stay bounded, attributed and separate from run health."""

import http.client
import io
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from email.message import Message

import pytest
from test_dashboard import workspace
from web_helpers import BOOTSTRAP, HOST, ORIGIN, Client

from llm_research_os.cli import main
from llm_research_os.dashboard import providers
from llm_research_os.dashboard.observations import ObservationStore
from llm_research_os.dashboard.store import DashboardError
from llm_research_os.web.app import LocalApi
from llm_research_os.web.sessions import SessionStore


def summary(indicator="none", states=("operational",), **extra):
    return json.dumps(
        {
            "page": {"updated_at": "2025-01-01T00:00:00Z"},
            "status": {"indicator": indicator, "description": "Synthetic test report"},
            "components": [
                {"name": f"Fixture {i}", "status": state} for i, state in enumerate(states)
            ],
            **extra,
        }
    ).encode()


@pytest.mark.parametrize(
    "indicator,states,expected",
    [
        ("none", ("operational",), "up"),
        ("none", (), "unknown"),
        ("none", ("new-state",), "unknown"),
        ("new-indicator", ("operational",), "unknown"),
        ("none", ("operational", "partial_outage"), "degraded"),
        ("critical", ("major_outage",), "down"),
        ("maintenance", ("under_maintenance",), "degraded"),
    ],
)
def test_report_state_is_conservative(indicator, states, expected):
    observation = providers.provider_observation("openai", "demo", summary(indicator, states))
    assert observation.status == expected
    assert observation.source_id == "official.openai"
    assert observation.expires_at - observation.observed_at == timedelta(minutes=5)
    assert "2025-01-01" in observation.provenance
    assert "retrieval time" in observation.provenance
    assert "Incident list not supplied" in observation.explanation
    assert not any(metric.name == "Listed incidents" for metric in observation.metrics)


def test_details_are_bounded_and_absent_incidents_differ_from_empty():
    raw = summary(states=("operational",) * 30, incidents=[{"name": "Synthetic incident"}] * 6)
    observation = providers.provider_observation("claude", "demo", raw)
    assert "Showing 20 of 30" in observation.explanation
    assert "Showing 5 of 6" in observation.explanation
    assert observation.explanation_author == "Claude status page (formatted by ResearchOS)"
    assert observation.metrics[-1].value == 6
    empty = providers.provider_observation("claude", "demo", summary(incidents=[]))
    assert empty.metrics[-1].value == 0


@pytest.mark.parametrize(
    "raw",
    [
        b'{"status":{"indicator":"none","description":"synthetic"},' + summary()[1:],
        b"{}",
        b"not JSON",
        b"\xff",
        b" " * (providers.MAX_RESPONSE_BYTES + 1),
        summary(states=("operational",) * 501),
        summary(page={"updated_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}),
    ],
)
def test_invalid_reports_refused(raw):
    with pytest.raises(DashboardError, match=r"invalid|future"):
        providers.provider_observation("openai", "demo", raw)


class Response(io.BytesIO):
    def __init__(self, body, status=200, content_type="application/json"):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type


class Opener:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_transport_has_no_caller_url_proxy_or_redirect(monkeypatch):
    captured = []
    opener = Opener(Response(summary()))

    def build(*handlers):
        captured.extend(handlers)
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", build)
    assert providers.fetch_summary("claude") == summary()
    request, timeout = opener.calls[0]
    assert request.full_url == "https://status.claude.com/api/v2/summary.json"
    assert request.data is None and timeout == 2
    assert not request.has_header("Authorization") and not request.has_header("Cookie")
    assert captured[0].proxies == {}
    assert captured[2].redirect_request(None, None, 302, "", {}, "http://127.0.0.1/") is None
    with pytest.raises(DashboardError, match="unknown official"):
        providers.fetch_summary("https://127.0.0.1/")
    assert len(opener.calls) == 1


@pytest.mark.parametrize(
    "response,match",
    [
        (Response(b"{}", status=302), "not JSON"),
        (Response(b"{}", content_type="text/html"), "not JSON"),
        (Response(b"x" * (providers.MAX_RESPONSE_BYTES + 1)), "exceeds limit"),
        (urllib.error.URLError("private diagnostic"), "could not be retrieved"),
        (http.client.BadStatusLine("private diagnostic"), "could not be retrieved"),
    ],
)
def test_transport_refusals(monkeypatch, response, match):
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener(response))
    with pytest.raises(DashboardError, match=match):
        providers.fetch_summary("openai")


def test_read_deadline(monkeypatch):
    times = iter([0, 9])
    monkeypatch.setattr(providers.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener(Response(b"{}")))
    with pytest.raises(DashboardError, match="deadline"):
        providers.fetch_summary("openai")


def test_cli_and_failed_refresh_preserve_last_report(tmp_path, monkeypatch, capsys):
    ws = workspace(tmp_path)
    monkeypatch.setattr(providers, "fetch_summary", lambda provider: summary())
    assert main(["dashboard", "provider-status", "--root", str(tmp_path), "openai"]) == 0
    assert json.loads(capsys.readouterr().out)["sourceId"] == "official.openai"
    before = ObservationStore(ws).observations()
    monkeypatch.setattr(providers, "fetch_summary", lambda provider: b"{}")
    assert main(["dashboard", "provider-status", "--root", str(tmp_path), "openai"]) == 1
    assert ObservationStore(ws).observations() == before
    assert not ws.control_db.exists() and not ws.receipt_db.exists()


def test_api_session_csrf_method_body_and_failure(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    client = Client(
        LocalApi(
            ws,
            sessions=SessionStore(bootstrap_token=BOOTSTRAP),
            allowed_hosts=frozenset({HOST}),
            allowed_origin=ORIGIN,
        )
    )
    calls = []

    def fetch(provider):
        calls.append(provider)
        return summary()

    monkeypatch.setattr(providers, "fetch_summary", fetch)
    path = "/api/v0alpha1/dashboard/providers/openai/refresh"
    assert client.request("POST", path, origin=ORIGIN)[0] == 401
    client.bootstrap()
    assert client.request("GET", path)[0] == 405
    csrf = client.csrf
    client.csrf = None
    assert client.request("POST", path, origin=ORIGIN)[0] == 403
    client.csrf = csrf
    assert client.request("POST", path, body=b"{}", origin=ORIGIN)[0] == 400
    assert calls == []
    status, _, response = client.request("POST", path, origin=ORIGIN)
    assert status == 200 and response["observations"][0]["sourceId"] == "official.openai"
    before = ObservationStore(ws).observations()
    monkeypatch.setattr(providers, "fetch_summary", lambda provider: b"{}")
    status, _, response = client.request("POST", path, origin=ORIGIN)
    assert status == 503 and response["code"] == "source-unavailable"
    assert ObservationStore(ws).observations() == before
    assert not ws.control_db.exists() and not ws.receipt_db.exists()
