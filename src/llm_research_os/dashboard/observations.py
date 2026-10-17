"""Timestamped external observations, kept distinct from authoritative run facts."""

from datetime import UTC, datetime, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from llm_research_os.dashboard.models import Identifier, Model
from llm_research_os.dashboard.store import DashboardError, DashboardStore


class Sample(Model):
    at: AwareDatetime
    value: float


class Metric(Model):
    name: str = Field(min_length=1, max_length=100)
    value: float
    unit: str = Field(default="", max_length=24)
    meaning: Literal["observed", "allocated", "reserved", "estimated"] = "observed"
    history: tuple[Sample, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def ordered_history(self) -> Self:
        if any(a.at >= b.at for a, b in zip(self.history, self.history[1:], strict=False)):
            raise ValueError("metric history must be strictly ordered")
        return self


class Observation(Model):
    kind: Literal["DashboardObservation"] = "DashboardObservation"
    project_id: Identifier = Field(alias="projectId")
    source_id: Identifier = Field(alias="sourceId")
    entity_id: Identifier = Field(alias="entityId")
    category: Literal[
        "resource",
        "pool",
        "provider",
        "service",
        "availability",
        "cost",
        "dataset",
        "model",
        "recovery",
        "access",
        "custom",
    ]
    title: str = Field(min_length=1, max_length=160)
    reporter: str = Field(min_length=1, max_length=120)
    provenance: str = Field(min_length=1, max_length=1000)
    observed_at: AwareDatetime = Field(alias="observedAt")
    expires_at: AwareDatetime = Field(alias="expiresAt")
    origin: Literal["real", "synthetic"]
    status: Literal["up", "degraded", "down", "unknown"]
    metrics: tuple[Metric, ...] = Field(default=(), max_length=20)
    explanation: str = Field(default="", max_length=8000)
    explanation_author: str | None = Field(default=None, alias="explanationAuthor", max_length=120)

    @model_validator(mode="after")
    def temporal_bounds(self) -> Self:
        if self.expires_at <= self.observed_at:
            raise ValueError("observation expiry must follow its sample time")
        if self.observed_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("future observation")
        if any(
            sample.at > self.observed_at for metric in self.metrics for sample in metric.history
        ):
            raise ValueError("future history sample")
        if self.explanation and not self.explanation_author:
            raise ValueError("explanation needs an attributed author")
        return self


class ObservationList(Model):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(
        default="researchos.dev/local-api/v0alpha1", alias="apiVersion"
    )
    kind: Literal["DashboardObservations"] = "DashboardObservations"
    project_id: Identifier = Field(alias="projectId")
    observations: tuple[Observation, ...]


class ObservationStore(DashboardStore):
    def observations(self) -> ObservationList:
        if not self.path.exists():
            return ObservationList(projectId=self.project_id, observations=())
        with self._connect() as db:
            exists = db.execute(
                "SELECT name FROM sqlite_master WHERE name='observations'"
            ).fetchone()
            rows = (
                db.execute(
                    "SELECT body FROM observations WHERE project=? ORDER BY source",
                    (self.project_id,),
                ).fetchall()
                if exists
                else []
            )
        return ObservationList(
            projectId=self.project_id,
            observations=tuple(Observation.model_validate_json(row[0]) for row in rows),
        )

    def observe(self, observation: Observation) -> Observation:
        if observation.project_id != self.project_id:
            raise DashboardError("foreign observation")
        body = observation.model_dump_json(by_alias=True)
        if len(body.encode()) > 32768:
            raise DashboardError("observation exceeds source limit")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS observations (project TEXT, source TEXT, body TEXT, "
                "PRIMARY KEY(project,source))"
            )
            row = db.execute(
                "SELECT body FROM observations WHERE project=? AND source=?",
                (self.project_id, observation.source_id),
            ).fetchone()
            if row:
                previous = Observation.model_validate_json(row[0])
                if observation == previous:
                    return previous
                if observation.observed_at <= previous.observed_at:
                    raise DashboardError("observation does not advance source time")
            elif (
                db.execute(
                    "SELECT COUNT(*) FROM observations WHERE project=?", (self.project_id,)
                ).fetchone()[0]
                >= 100
            ):
                raise DashboardError("observation source capacity reached")
            db.execute(
                "INSERT OR REPLACE INTO observations VALUES (?,?,?)",
                (self.project_id, observation.source_id, body),
            )
        return observation
