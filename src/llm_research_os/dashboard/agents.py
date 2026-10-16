"""Durable scoped requests for the operator's own external Agent."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from llm_research_os.dashboard.models import (
    DashboardDocument,
    DashboardWrite,
    Identifier,
    Model,
    check_agent_edit,
)
from llm_research_os.dashboard.store import DashboardError, DashboardStore


class AgentAsk(Model):
    kind: Literal["DashboardAgentAsk"] = "DashboardAgentAsk"
    project_id: Identifier = Field(alias="projectId")
    request_id: Identifier = Field(alias="requestId")
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    scope: tuple[Identifier, ...] | None = Field(default=None, max_length=2000)
    prompt: str = Field(min_length=1, max_length=4000)


class AgentReply(Model):
    kind: Literal["DashboardAgentReply"] = "DashboardAgentReply"
    request_id: Identifier = Field(alias="requestId")
    author: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=8000)
    proposal: DashboardWrite | None = None


class AgentTask(Model):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(
        default="researchos.dev/local-api/v0alpha1", alias="apiVersion"
    )
    request: AgentAsk
    snapshot: DashboardDocument
    created_at: str = Field(alias="createdAt")
    reply: AgentReply | None = None


class AgentInboxDocument(Model):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(
        default="researchos.dev/local-api/v0alpha1", alias="apiVersion"
    )
    kind: Literal["DashboardAgentInbox"] = "DashboardAgentInbox"
    project_id: Identifier = Field(alias="projectId")
    tasks: tuple[AgentTask, ...]


class AgentInbox(DashboardStore):
    def list_tasks(self) -> AgentInboxDocument:
        if not self.path.exists():
            return AgentInboxDocument(projectId=self.project_id, tasks=())
        with self._connect() as db:
            exists = db.execute(
                "SELECT name FROM sqlite_master WHERE name='agent_tasks'"
            ).fetchone()
            rows = (
                db.execute(
                    "SELECT body FROM agent_tasks WHERE project=? ORDER BY rowid DESC LIMIT 20",
                    (self.project_id,),
                ).fetchall()
                if exists
                else []
            )
        return AgentInboxDocument(
            projectId=self.project_id,
            tasks=tuple(AgentTask.model_validate_json(row[0]) for row in rows),
        )

    def ask(self, request: AgentAsk) -> AgentTask:
        if request.project_id != self.project_id:
            raise DashboardError("foreign Agent request")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS agent_tasks (project TEXT, id TEXT, body TEXT, "
                "PRIMARY KEY(project,id))"
            )
            row = db.execute(
                "SELECT body FROM agent_tasks WHERE project=? AND id=?",
                (self.project_id, request.request_id),
            ).fetchone()
            if row:
                task = AgentTask.model_validate_json(row[0])
                if task.request != request:
                    raise DashboardError("Agent request identity reused")
                return task
            # Read through this transaction so a map write cannot race the frozen scope.
            row = db.execute(
                "SELECT body FROM revisions WHERE project=? ORDER BY revision DESC LIMIT 1",
                (self.project_id,),
            ).fetchone()
            if not row:
                raise DashboardError("save the map before asking an Agent")
            snapshot = self._decode(row[0])
            if snapshot.revision != request.expected_revision:
                raise DashboardError("Agent request revision conflict")
            ids = {node.id for node in snapshot.state.components}
            if request.scope is not None and (
                not request.scope or not set(request.scope).issubset(ids)
            ):
                raise DashboardError("invalid Agent scope")
            check_agent_edit(snapshot.state, snapshot.state, request.scope)
            count = db.execute(
                "SELECT COUNT(*) FROM agent_tasks WHERE project=?", (self.project_id,)
            ).fetchone()[0]
            if count >= 100:
                raise DashboardError("Agent inbox capacity reached")
            task = AgentTask(
                request=request, snapshot=snapshot, createdAt=datetime.now(UTC).isoformat()
            )
            db.execute(
                "INSERT INTO agent_tasks VALUES (?,?,?)",
                (self.project_id, request.request_id, task.model_dump_json(by_alias=True)),
            )
            return task

    def reply(self, reply: AgentReply) -> AgentTask:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM agent_tasks WHERE project=? AND id=?",
                (self.project_id, reply.request_id),
            ).fetchone()
            if not row:
                raise DashboardError("Agent request missing")
            task = AgentTask.model_validate_json(row[0])
            if task.reply is not None:
                if task.reply != reply:
                    raise DashboardError("Agent response already recorded")
                return task
            proposal = reply.proposal
            if proposal is not None:
                if (
                    proposal.project_id != self.project_id
                    or proposal.expected_revision != task.snapshot.revision
                    or proposal.author_kind != "agent"
                    or proposal.scope != task.request.scope
                ):
                    raise DashboardError("Agent proposal scope or revision mismatch")
                check_agent_edit(task.snapshot.state, proposal.state, task.request.scope)
            answered = task.model_copy(update={"reply": reply})
            db.execute(
                "UPDATE agent_tasks SET body=? WHERE project=? AND id=?",
                (answered.model_dump_json(by_alias=True), self.project_id, reply.request_id),
            )
            return answered
