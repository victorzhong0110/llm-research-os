"""Local same-origin browser sessions for the read API.

TM-081. A browser session is not a Worker credential and must never be usable
as one. The only way in is a one-time bootstrap secret printed by
``researchos web serve``; it is exchanged for an opaque, in-memory session
cookie. No token is accepted from a URL query, a bearer header, or any path
that a cross-site request could ride, and nothing is persisted to disk.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Final

from llm_research_os.web.errors import LocalApiError, bad_request, forbidden

SESSION_COOKIE_NAME: Final = "researchos_session"
CSRF_HEADER_NAME: Final = "X-ResearchOS-CSRF"
BOOTSTRAP_HEADER_NAME: Final = "X-ResearchOS-Bootstrap"
SESSION_IDLE_SECONDS: Final = 12 * 60 * 60
MAX_SESSIONS: Final = 8
UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class BrowserSession:
    """One live local session. ``token`` and ``csrf`` never leave the cookie flow."""

    token: str
    csrf: str
    created_at: float

    def document(self) -> dict[str, Any]:
        """Session view for same-origin JavaScript.

        The cookie is HttpOnly, so the double-submit value is handed out here
        instead. Cross-origin script cannot read this body, and a cross-origin
        request cannot set the header without a preflight this server never
        approves.
        """

        return {
            "csrfToken": self.csrf,
            "csrfHeader": CSRF_HEADER_NAME,
            "idleTimeoutSeconds": SESSION_IDLE_SECONDS,
        }


class SessionStore:
    """Bounded, in-memory session table with a one-time bootstrap secret."""

    def __init__(
        self,
        *,
        bootstrap_token: str | None = None,
        idle_seconds: int = SESSION_IDLE_SECONDS,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        if idle_seconds < 1 or max_sessions < 1:
            raise ValueError("session limits must be positive")
        self._bootstrap = bootstrap_token or secrets.token_urlsafe(32)
        self._bootstrap_consumed = False
        self._idle_seconds = idle_seconds
        self._max_sessions = max_sessions
        self._lock = threading.Lock()
        self._sessions: dict[str, BrowserSession] = {}

    @property
    def bootstrap_token(self) -> str:
        """The one-time secret the operator pastes into their own browser."""

        return self._bootstrap

    def exchange_bootstrap(self, presented: str | None) -> BrowserSession:
        """Trade the one-time secret for a session, or refuse."""

        if not presented:
            raise bad_request(
                "bootstrap-invalid",
                "Open the bootstrap URL printed by researchos web serve.",
            )
        with self._lock:
            if self._bootstrap_consumed:
                raise LocalApiError(
                    "bootstrap-consumed",
                    "The bootstrap secret was already used; restart the server for a new one.",
                    status=409,
                )
            if not hmac.compare_digest(presented, self._bootstrap):
                raise forbidden("bootstrap-invalid", "The bootstrap secret is not valid.")
            self._bootstrap_consumed = True
            if len(self._sessions) >= self._max_sessions:
                self._evict_locked()
            session = BrowserSession(
                token=secrets.token_urlsafe(32),
                csrf=secrets.token_urlsafe(32),
                created_at=time.time(),
            )
            self._sessions[session.token] = session
            return session

    def authenticate(self, token: str | None) -> BrowserSession:
        """Resolve a session cookie value, or refuse without leaking which part failed."""

        if not token:
            raise LocalApiError(
                "session-required",
                "Open the bootstrap URL printed by researchos web serve.",
                status=401,
            )
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                raise LocalApiError(
                    "session-expired", "The local session is not valid.", status=401
                )
            if time.time() - session.created_at > self._idle_seconds:
                del self._sessions[token]
                raise LocalApiError(
                    "session-expired", "The local session expired; bootstrap again.", status=401
                )
            return session

    def check_csrf(self, session: BrowserSession, presented: str | None, *, method: str) -> None:
        """Double-submit CSRF check for unsafe methods only."""

        if method.upper() not in UNSAFE_METHODS:
            return
        if not presented or not hmac.compare_digest(presented, session.csrf):
            raise forbidden("csrf-invalid", "The CSRF token is missing or does not match.")

    def forget(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def _evict_locked(self) -> None:
        oldest = min(self._sessions.items(), key=lambda item: item[1].created_at)
        del self._sessions[oldest[0]]


def parse_cookies(header: str | None) -> dict[str, str]:
    """Parse one Cookie header without a permissive or lenient cookie library."""

    cookies: dict[str, str] = {}
    if not header:
        return cookies
    for part in header.split(";"):
        name, separator, value = part.partition("=")
        if not separator:
            continue
        key = name.strip()
        if key and key not in cookies:
            cookies[key] = value.strip().strip('"')
    return cookies


def check_host(environ: dict[str, Any], *, allowed_hosts: frozenset[str]) -> None:
    """Refuse DNS-rebinding: only the exact configured loopback authority answers."""

    host = environ.get("HTTP_HOST") or ""
    if host.lower() not in allowed_hosts:
        raise forbidden(
            "host-forbidden",
            "Requests must use the exact local origin that started this server.",
        )


def check_origin(environ: dict[str, Any], *, method: str, allowed_origin: str) -> None:
    """Same-origin enforcement for unsafe methods. Absent Origin on a read is fine."""

    if method.upper() not in UNSAFE_METHODS:
        return
    origin = environ.get("HTTP_ORIGIN")
    if not origin:
        raise forbidden("origin-forbidden", "Unsafe requests must send an explicit Origin header.")
    if origin != allowed_origin:
        raise forbidden("origin-forbidden", "Cross-origin requests are not accepted.")


def session_cookie_header(session: BrowserSession) -> str:
    """Build the Set-Cookie value. Secure is omitted: the listener is loopback HTTP."""

    return (
        f"{SESSION_COOKIE_NAME}={session.token}; Path=/; HttpOnly; SameSite=Strict; "
        f"Max-Age={SESSION_IDLE_SECONDS}"
    )
