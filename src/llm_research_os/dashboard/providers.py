"""Fixed public status-page collectors; reports never become execution authority."""

from __future__ import annotations

import http.client
import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from llm_research_os.application.workspace import Workspace
from llm_research_os.dashboard.observations import Metric, Observation, ObservationStore
from llm_research_os.dashboard.store import DashboardError
from llm_research_os.spec.io import decode_document_text

PROVIDERS = {
    "openai": ("OpenAI", "https://status.openai.com/api/v2/summary.json"),
    "claude": ("Claude", "https://status.claude.com/api/v2/summary.json"),
}
MAX_RESPONSE_BYTES = 262144
FRESH_FOR = timedelta(minutes=5)


class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class _Status(_PublicModel):
    indicator: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=400)


class _Page(_PublicModel):
    updated_at: AwareDatetime


class _Component(_PublicModel):
    name: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=64)


class _Incident(_PublicModel):
    name: str = Field(min_length=1, max_length=300)


class _Summary(_PublicModel):
    page: _Page
    status: _Status
    components: tuple[_Component, ...] = Field(max_length=500)
    # OpenAI does not always include incidents; absent must not become zero.
    incidents: tuple[_Incident, ...] | None = Field(default=None, max_length=100)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def fetch_summary(provider: str) -> bytes:
    """TM-101: only fixed HTTPS URLs, no redirects, proxy credentials or cookies."""
    if provider not in PROVIDERS:
        raise DashboardError("unknown official status provider")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect(),
    )
    request = urllib.request.Request(  # noqa: S310 - TM-101 fixed HTTPS allowlist above
        PROVIDERS[provider][1],
        headers={"Accept": "application/json", "User-Agent": "ResearchOS-status/0alpha1"},
        method="GET",
    )
    deadline = time.monotonic() + 8
    try:
        with opener.open(request, timeout=2) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise DashboardError("official status response is not JSON")
            chunks: list[bytes] = []
            size = 0
            while size <= MAX_RESPONSE_BYTES:
                if time.monotonic() > deadline:
                    raise DashboardError("official status read deadline exceeded")
                chunk = response.read1(min(16384, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    return b"".join(chunks)
                size += len(chunk)
                chunks.append(chunk)
            raise DashboardError("official status response exceeds limit")
    except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
        raise DashboardError("official status could not be retrieved") from exc


def provider_observation(provider: str, project_id: str, raw: bytes) -> Observation:
    """Translate a source assertion, preserving unknown and partial information."""
    if provider not in PROVIDERS or len(raw) > MAX_RESPONSE_BYTES:
        raise DashboardError("invalid official status source")
    try:
        decoded = decode_document_text(raw.decode("utf-8"), suffix=".json")
        report = _Summary.model_validate_json(json.dumps(decoded))
    except ValueError as exc:
        raise DashboardError("invalid official status report") from exc
    now = datetime.now(UTC)
    if report.page.updated_at > now + timedelta(minutes=5):
        raise DashboardError("official status page has a future timestamp")
    states = [component.status for component in report.components]
    operational = states.count("operational")
    affected = sum(
        s in {"degraded_performance", "partial_outage", "major_outage", "under_maintenance"}
        for s in states
    )
    unknown = len(states) - operational - affected
    indicator = report.status.indicator
    status: Literal["up", "degraded", "down", "unknown"] = "unknown"
    if indicator == "critical":
        status = "down"
    elif indicator in {"minor", "major", "maintenance"} or affected:
        status = "degraded"
    elif indicator == "none" and states and not unknown:
        status = "up"
    title, url = PROVIDERS[provider]
    details = [report.status.description, "Reported components:"]
    details.extend(f"{item.name}: {item.status}" for item in report.components[:20])
    if len(report.components) > 20:
        details.append(
            f"Showing 20 of {len(report.components)} components; see the official page for all."
        )
    metrics = [
        Metric(name="Reported components", value=float(len(states)), unit="components"),
        Metric(name="Affected components", value=float(affected), unit="components"),
        Metric(name="Unknown component states", value=float(unknown), unit="components"),
    ]
    if report.incidents is not None:
        metrics.append(
            Metric(name="Listed incidents", value=float(len(report.incidents)), unit="incidents")
        )
        details.extend(f"Incident: {item.name}" for item in report.incidents[:5])
        if len(report.incidents) > 5:
            details.append(f"Showing 5 of {len(report.incidents)} listed incidents.")
    else:
        details.append("Incident list not supplied by this response.")
    details.append("Official aggregate report; your account, region and request health may differ.")
    return Observation(
        projectId=project_id,
        sourceId=f"official.{provider}",
        entityId=f"provider.{provider}",
        category="provider",
        title=f"{title} official status",
        reporter="ResearchOS public-status collector",
        provenance=(
            f"{url} · page updated {report.page.updated_at.isoformat()}. "
            "Observed time is retrieval time, not a request-health measurement."
        ),
        observedAt=now,
        expiresAt=now + FRESH_FOR,
        origin="real",
        status=status,
        metrics=tuple(metrics),
        explanation="\n".join(details),
        explanationAuthor=f"{title} status page (formatted by ResearchOS)",
    )


def collect_provider_status(workspace: Workspace, provider: str) -> Observation:
    observation = provider_observation(provider, workspace.project_id, fetch_summary(provider))
    return ObservationStore(workspace).observe(observation)
