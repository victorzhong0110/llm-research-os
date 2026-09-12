"""Exercise hostile HTTP responses without a network or a real credential."""

import io
import urllib.error
import urllib.request
from email.message import Message
from types import SimpleNamespace

import pytest

from llm_research_os.providers import compat
from llm_research_os.providers.errors import ModelTransportError


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"x" * (compat.MAX_RESPONSE_BYTES + 1), "response-too-large"),
        (b"\xff", "invalid-response"),
        (b"not-json", "invalid-response"),
        (b"[]", "invalid-response"),
        (b"null", "invalid-response"),
    ],
)
def test_transport_bounds_and_decodes_response(
    monkeypatch: pytest.MonkeyPatch, payload: bytes, code: str
) -> None:
    monkeypatch.setattr(
        compat.urllib.request,
        "build_opener",
        lambda *handlers: SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(payload)),
    )
    with pytest.raises(ModelTransportError) as error:
        compat._urllib_transport("http://127.0.0.1/v1", b"{}", {})
    assert error.value.code == code


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (urllib.error.URLError("credential-must-not-escape"), "transport"),
        (TimeoutError("credential-must-not-escape"), "transport-timeout"),
        (ModelTransportError("blocked", code="redirect-forbidden"), "redirect-forbidden"),
    ],
)
def test_transport_errors_are_bounded_and_redacted(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: str
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(
        compat.urllib.request, "build_opener", lambda *handlers: SimpleNamespace(open=fail)
    )
    with pytest.raises(ModelTransportError) as caught:
        compat._urllib_transport("http://127.0.0.1/v1", b"{}", {})
    assert caught.value.code == code
    assert "credential-must-not-escape" not in str(caught.value)


def test_host_header_and_proxy_cannot_override_pinned_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {}

    def build(*handlers: object) -> object:
        observed["handlers"] = handlers

        def open_request(request: urllib.request.Request, **kwargs: object) -> io.BytesIO:
            observed["host"] = request.get_header("Host")
            observed["url"] = request.full_url
            return io.BytesIO(b'{"ok":true}')

        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(compat.urllib.request, "build_opener", build)
    assert compat._urllib_transport("https://127.0.0.1/v1", b"{}", {"Host": "evil.test"}) == {
        "ok": True
    }
    assert observed["host"] == "127.0.0.1"
    assert observed["url"] == "https://127.0.0.1:443/v1"
    assert any(
        isinstance(h, urllib.request.ProxyHandler) and h.proxies == {} for h in observed["handlers"]
    )


def test_redirect_and_tunnel_fail_before_a_second_connection() -> None:
    with pytest.raises(ModelTransportError, match="redirects"):
        compat._RejectRedirects().redirect_request(
            urllib.request.Request("https://example.org"),
            io.BytesIO(),
            302,
            "redirect",
            Message(),
            "https://evil.test",
        )
    connection = compat._PinnedHTTPSConnection("127.0.0.1", server_hostname="example.org")
    connection.set_tunnel("evil.test")
    with pytest.raises(ModelTransportError, match="proxies"):
        connection.connect()


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"choices": []},
        {"choices": [1]},
        {"choices": [{}]},
        {"choices": [{"message": []}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": 1}}]},
    ],
)
def test_malformed_model_completion_is_not_success(document: dict[str, object]) -> None:
    with pytest.raises(ModelTransportError) as error:
        compat._completion_text(document)
    assert error.value.code == "invalid-response"


def test_url_userinfo_is_rejected_without_echo() -> None:
    with pytest.raises(ModelTransportError) as error:
        compat._chat_completions_url("https://user:private@example.org/v1")
    assert error.value.code == "endpoint-userinfo"
    assert "private" not in str(error.value)
