"""Classify and pin HTTP endpoints before a secret or socket is used (TM-042)."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import ParseResult, urlparse, urlunparse

from llm_research_os.providers.errors import ModelTransportError

LOOPBACK_HOSTNAMES = frozenset({"localhost"})
AddrInfo = tuple[object, object, object, str, tuple[object, ...]]
Resolver = Callable[..., Sequence[AddrInfo]]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
METADATA_IPV4 = ipaddress.ip_network("169.254.169.254/32")
METADATA_IPV6 = ipaddress.ip_network("fd00:ec2::254/128")
CGNAT_IPV4 = ipaddress.ip_network("100.64.0.0/10")


class EndpointKind(StrEnum):
    LOOPBACK = "loopback"
    REMOTE = "remote"


@dataclass(frozen=True, slots=True)
class PinnedEndpoint:
    kind: EndpointKind
    request_url: str
    host_header: str
    addresses: tuple[str, ...]


def endpoint_is_loopback(endpoint: str) -> bool:
    return classify_literal_endpoint(endpoint) is EndpointKind.LOOPBACK


def classify_literal_endpoint(endpoint: str) -> EndpointKind:
    """Classify without DNS. Literal private/metadata/multicast addresses fail closed."""

    parsed = parse_endpoint_url(endpoint)
    host = parsed.hostname
    if host is None:
        raise ValueError("endpoint must include a hostname")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host.casefold() in LOOPBACK_HOSTNAMES:
            return EndpointKind.LOOPBACK
        return EndpointKind.REMOTE
    kind = _ip_kind(_canonical_ip(ip))
    if kind is None:
        raise ValueError("endpoint address is not allowed")
    return kind


def pin_endpoint(endpoint: str, *, resolver: Resolver | None = None) -> PinnedEndpoint:
    """Resolve once, reject mixed/blocked answers, and rewrite the URL onto one IP."""

    try:
        parsed = parse_endpoint_url(endpoint)
    except ValueError as exc:
        raise ModelTransportError(str(exc), code="endpoint-url") from None
    host = parsed.hostname
    if host is None:
        raise ModelTransportError("endpoint must include a hostname", code="endpoint-host")
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    addresses = _resolve_addresses(host, port, resolver=resolver or socket.getaddrinfo)
    kinds = {_ip_kind(ip) for ip in addresses}
    if None in kinds:
        raise ModelTransportError("endpoint address is not allowed", code="endpoint-blocked")
    if EndpointKind.LOOPBACK in kinds and EndpointKind.REMOTE in kinds:
        raise ModelTransportError(
            "endpoint resolved to mixed loopback and public addresses",
            code="dns-rebinding",
        )
    if kinds == {EndpointKind.LOOPBACK}:
        kind = EndpointKind.LOOPBACK
    elif kinds == {EndpointKind.REMOTE}:
        kind = EndpointKind.REMOTE
    else:
        raise ModelTransportError("endpoint address is not allowed", code="endpoint-blocked")
    pinned = addresses[0]
    netloc = _netloc(pinned, port)
    request_url = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, "", ""))
    host_header = host if parsed.port is None else f"{host}:{parsed.port}"
    return PinnedEndpoint(
        kind=kind,
        request_url=request_url,
        host_header=host_header,
        addresses=tuple(str(item) for item in addresses),
    )


def parse_endpoint_url(endpoint: str) -> ParseResult:
    parsed = urlparse(endpoint)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("endpoint must not contain userinfo")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("endpoint scheme must be http or https")
    if parsed.query:
        raise ValueError("endpoint must not contain a query")
    if parsed.fragment:
        raise ValueError("endpoint must not contain a fragment")
    if parsed.hostname is None:
        raise ValueError("endpoint must include a hostname")
    return parsed


def _resolve_addresses(host: str, port: int, *, resolver: Resolver) -> tuple[IPAddress, ...]:
    try:
        return (_canonical_ip(ipaddress.ip_address(host)),)
    except ValueError:
        pass
    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ModelTransportError(
            "endpoint hostname could not be resolved",
            code="endpoint-dns",
        ) from None
    if type(infos) is not list and type(infos) is not tuple:
        raise ModelTransportError(
            "endpoint hostname could not be resolved",
            code="endpoint-dns",
        )
    addresses: list[IPAddress] = []
    seen: set[str] = set()
    for info in infos:
        if type(info) is not tuple or len(info) < 5:
            continue
        sockaddr = info[4]
        if type(sockaddr) is not tuple or not sockaddr:
            continue
        raw = sockaddr[0]
        if type(raw) is not str:
            continue
        try:
            ip = _canonical_ip(ipaddress.ip_address(raw))
        except ValueError:
            continue
        key = str(ip)
        if key in seen:
            continue
        seen.add(key)
        addresses.append(ip)
    if not addresses:
        raise ModelTransportError(
            "endpoint hostname could not be resolved",
            code="endpoint-dns",
        )
    return tuple(addresses)


def _canonical_ip(ip: IPAddress) -> IPAddress:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _ip_kind(ip: IPAddress) -> EndpointKind | None:
    if ip.is_loopback:
        return EndpointKind.LOOPBACK
    if ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_private or ip.is_reserved:
        return None
    if isinstance(ip, ipaddress.IPv4Address) and (ip in METADATA_IPV4 or ip in CGNAT_IPV4):
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip in METADATA_IPV6:
        return None
    if not ip.is_global:
        return None
    return EndpointKind.REMOTE


def _netloc(ip: IPAddress, port: int) -> str:
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    return f"{host}:{port}"
