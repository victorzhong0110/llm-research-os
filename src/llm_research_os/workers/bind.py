"""Bind-address policy for the Worker HTTPS plane (ADR-0021).

HTTP (no TLS) stays loopback-only. Unspecified addresses stay forbidden.
A unicast bind with TLS is not a cross-machine proof by itself.
"""

from __future__ import annotations

import ipaddress

from llm_research_os.workers.errors import WorkerError


def require_worker_bind_host(host: str, *, tls: bool) -> None:
    """Refuse unspecified/multicast binds. HTTP remains loopback-only."""

    if type(host) is not str or host == "":
        raise WorkerError("worker server host is missing", code="bind-host-invalid")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not tls:
            raise WorkerError(
                "worker server host must be a loopback IP",
                code="bind-not-loopback",
            ) from None
        if host in {"*", "localhost."} or "/" in host or "\\" in host or ":" in host:
            raise WorkerError(
                "worker server hostname is not allowed",
                code="bind-host-invalid",
            ) from None
        return
    if ip.is_unspecified:
        raise WorkerError(
            "worker server cannot bind an unspecified address",
            code="bind-unspecified",
        )
    if ip.is_multicast:
        raise WorkerError(
            "worker server cannot bind a multicast address",
            code="bind-multicast",
        )
    if tls:
        return
    if not ip.is_loopback:
        raise WorkerError(
            "worker server host must be a loopback IP",
            code="bind-not-loopback",
        )
