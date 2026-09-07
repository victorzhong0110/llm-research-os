from __future__ import annotations

import socket

import pytest

from llm_research_os.providers.endpoint import (
    EndpointKind,
    classify_literal_endpoint,
    endpoint_is_loopback,
    pin_endpoint,
)
from llm_research_os.providers.errors import ModelTransportError


def _info(ip: str, port: int) -> tuple[object, object, object, str, tuple[str, int]]:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (ip, port))


def test_literal_loopback_and_localhost() -> None:
    assert endpoint_is_loopback("http://127.0.0.1:8080/v1") is True
    assert endpoint_is_loopback("http://[::1]:8080/v1") is True
    assert endpoint_is_loopback("http://localhost:8080/v1") is True
    assert endpoint_is_loopback("http://127.0.0.2:8080/v1") is True
    assert classify_literal_endpoint("https://example.invalid/v1") is EndpointKind.REMOTE


def test_literal_private_metadata_and_query_fail_closed() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        classify_literal_endpoint("https://192.168.1.10/v1")
    with pytest.raises(ValueError, match="not allowed"):
        classify_literal_endpoint("https://169.254.169.254/v1")
    with pytest.raises(ValueError, match="query"):
        classify_literal_endpoint("http://127.0.0.1:8080/v1?x=1")
    with pytest.raises(ValueError, match="fragment"):
        classify_literal_endpoint("http://127.0.0.1:8080/v1#x")


def test_pin_rejects_private_and_mixed_answers() -> None:
    def private(_host: str, port: int, **_kwargs: object) -> list[object]:
        return [_info("10.0.0.8", port)]

    with pytest.raises(ModelTransportError) as blocked:
        pin_endpoint("https://internal.example/v1", resolver=private)
    assert blocked.value.code == "endpoint-blocked"

    def mixed(_host: str, port: int, **_kwargs: object) -> list[object]:
        return [_info("127.0.0.1", port), _info("8.8.8.8", port)]

    with pytest.raises(ModelTransportError) as rebound:
        pin_endpoint("https://mixed.example/v1", resolver=mixed)
    assert rebound.value.code == "dns-rebinding"


def test_pin_rewrites_public_hostname_onto_one_ip() -> None:
    def public(_host: str, port: int, **_kwargs: object) -> list[object]:
        return [_info("8.8.8.8", port)]

    pinned = pin_endpoint("https://example.invalid:443/v1", resolver=public)
    assert pinned.kind is EndpointKind.REMOTE
    assert pinned.request_url == "https://8.8.8.8:443/v1"
    assert pinned.host_header == "example.invalid:443"
    assert pinned.addresses == ("8.8.8.8",)
