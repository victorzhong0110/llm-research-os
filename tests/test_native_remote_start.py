"""Real TLS start recording, immutable journal replay and no remote process launch."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_native_output_transport import _transport as _base_transport
from test_native_reviewed_preparation import PROJECT

from llm_research_os.canonical import canonical_json
from llm_research_os.execution.native_reviewed_runtime import _lifecycle
from llm_research_os.runs.control import RunControl
from llm_research_os.storage.store import EventStore
from llm_research_os.workers import native_start, native_start_client
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.http import LoopbackWorkerServer
from llm_research_os.workers.native_output import output_lock
from llm_research_os.workers.native_start_client import publish_native_start
from llm_research_os.workers.native_start_documents import NativeStartRequest


def _transport(tmp_path):  # type: ignore[no-untyped-def]
    result = _base_transport(tmp_path)
    result[0].prepare()
    return result


def _document(world, lease="lease.grant.native"):  # type: ignore[no-untyped-def]
    return NativeStartRequest.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "NativeStartRequest",
            "leaseId": lease,
            "preparation": json.loads((world.workspace / "receipt.json").read_bytes()),
            "identityDigest": "jcs-sha256:" + "a" * 64,
        }
    )


def _run(world, plane):  # type: ignore[no-untyped-def]
    return RunControl(plane.store, project_id=PROJECT, run_id=world.request.run_id)


def test_start_is_one_bound_fact_and_restart_only_replays(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    world, plane, tls, clock, server, client = _transport(tmp_path)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("start endpoint spawned"))
    try:
        claim = client.poll()
        document = _document(world, claim["leaseId"])
        before = plane.store.last_sequence()
        receipt = publish_native_start(client, document)
        assert receipt.sequence == before + 1 and receipt.launch_allowed is False
        assert _run(world, plane).rebuild().snapshot.attempts[0].status.value == "running"
        assert not list(tmp_path.rglob("*.identity.json"))
        journal = next(tmp_path.glob("native-start-*.json"))
        assert journal.stat().st_mode & 0o777 == 0o600
        assert world.token not in journal.read_text()
        port, context = server.port, server._native_context
        server.stop()
        server = LoopbackWorkerServer(
            world.database,
            plane.artifacts,
            hmac_key=world.hmac_key,
            project_id=PROJECT,
            source=plane.source,
            clock=lambda: clock[0],
            port=port,
            tls=tls,
            native_context=context,
        )
        server.start()
        assert publish_native_start(replace(client), document) == receipt
        assert plane.store.last_sequence() == receipt.sequence
        assert replace(client).poll()["resumed"] is True
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "fault",
    [
        "no-claim",
        "lease",
        "identity",
        "preparation",
        "context",
        "spec",
        "revoke",
        "expiry",
        "unknown",
        "missing-journal",
        "lock",
    ],
)
def test_start_refuses_without_new_fact(tmp_path, fault):  # type: ignore[no-untyped-def]
    world, plane, _, clock, server, client = _transport(tmp_path)
    held = None
    try:
        document = _document(world)
        if fault != "no-claim":
            client.poll()
        if fault in {"identity", "missing-journal"}:
            publish_native_start(client, document)
        if fault == "lease":
            document = document.model_copy(update={"lease_id": "lease.other"})
        elif fault == "identity":
            document = document.model_copy(update={"identity_digest": "jcs-sha256:" + "b" * 64})
        elif fault == "preparation":
            prepared = document.preparation.model_copy(update={"grant_id": "grant.other"})
            document = document.model_copy(update={"preparation": prepared})
        elif fault == "context":
            server._native_context = None
        elif fault == "spec":
            spec = server._native_context.spec.model_copy(deep=True)
            spec.metadata.title += " changed"
            server._native_context = replace(server._native_context, spec=spec)
        elif fault == "revoke":
            plane.revoke_grant(
                grant_id="grant.native",
                actor_id=world.request.actor_id,
                event_id="evt.revoke.start",
            )
        elif fault == "expiry":
            clock[0] += timedelta(minutes=30)
        elif fault == "unknown":
            publish_native_start(client, document)
            _lifecycle(
                _run(world, plane),
                world.request,
                "attempt.unknown",
                {"reasonCode": "native-outcome-uncertain"},
                attempt=True,
            )
        elif fault == "missing-journal":
            next(tmp_path.glob("native-start-*.json")).unlink()
        elif fault == "lock":
            held = output_lock(world.database)
            held.__enter__()
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="refused"):
            publish_native_start(client, document)
        assert plane.store.last_sequence() == before
    finally:
        if held:
            held.__exit__(None, None, None)
        server.stop()
        plane.store.close()


def test_partial_start_journal_never_changes_identity(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        client.poll()
        document = _document(world)
        original = native_start._append_bound

        def crash_on_start(*args, **kwargs):  # type: ignore[no-untyped-def]
            if args[3] == "attempt.started":
                raise OSError("crash")
            return original(*args, **kwargs)

        monkeypatch.setattr(native_start, "_append_bound", crash_on_start)
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="refused"):
            publish_native_start(client, document)
        assert plane.store.last_sequence() == before
        assert next(tmp_path.glob("native-start-*.json")).is_file()
        monkeypatch.setattr(native_start, "_append_bound", original)
        receipt = publish_native_start(client, document)
        assert receipt.sequence == before + 1
        assert publish_native_start(client, document) == receipt
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["symlink", "hardlink", "permissions", "corrupt", "oversize"])
def test_start_journal_refuses_substitution_without_repair(tmp_path, fault):  # type: ignore[no-untyped-def]
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        client.poll()
        document = _document(world)
        publish_native_start(client, document)
        path = next(tmp_path.glob("native-start-*.json"))
        if fault == "symlink":
            moved = path.with_suffix(".saved")
            path.rename(moved)
            path.symlink_to(moved)
        elif fault == "hardlink":
            os.link(path, path.with_suffix(".linked"))
        elif fault == "permissions":
            path.chmod(0o644)
        else:
            path.write_bytes(b"x" * (16385 if fault == "oversize" else 1))
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="refused"):
            publish_native_start(client, document)
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


def test_lost_start_response_retries_only_identical_record(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        client.poll()
        document = _document(world)
        original = native_start_client._connection
        attempts = []

        class LoseResponse:
            def __init__(self, connection):  # type: ignore[no-untyped-def]
                self.connection = connection

            def request(self, *a, **k):  # type: ignore[no-untyped-def]
                attempts.append(a[2])
                return self.connection.request(*a, **k)

            def getresponse(self):  # type: ignore[no-untyped-def]
                response = self.connection.getresponse()
                response.read()
                raise OSError("lost response")

            def close(self):  # type: ignore[no-untyped-def]
                self.connection.close()

        def connect(*a, **k):  # type: ignore[no-untyped-def]
            connection = original(*a, **k)
            return LoseResponse(connection) if not attempts else connection

        monkeypatch.setattr(native_start_client, "_connection", connect)
        before = plane.store.last_sequence()
        receipt = publish_native_start(client, document)
        assert receipt.sequence == before + 1
        assert attempts == [
            canonical_json(
                document.model_dump(mode="json", by_alias=True, exclude_none=True)
            ).encode()
        ]
        assert plane.store.last_sequence() == receipt.sequence
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["revoke", "spec", "unknown"])
def test_authority_or_outcome_drift_during_journal_refuses_ack(tmp_path, monkeypatch, fault):  # type: ignore[no-untyped-def]
    from contextlib import contextmanager

    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        client.poll()
        document = _document(world)
        original = native_start._journal

        @contextmanager
        def drift(*args, **kwargs):  # type: ignore[no-untyped-def]
            with (
                original(*args, **kwargs),
                EventStore(world.database, require_existing=True) as store,
            ):
                local_plane = server._plane(store)
                if fault == "revoke":
                    local_plane.revoke_grant(
                        grant_id="grant.native",
                        actor_id=world.request.actor_id,
                        event_id="evt.revoke.during.start",
                    )
                elif fault == "spec":
                    # Mutate the captured trusted context, not an HTTP body.
                    server._native_context.spec.metadata.title += " drift"
                else:
                    _lifecycle(
                        _run(world, local_plane), world.request, "attempt.started", {}, attempt=True
                    )
                    _lifecycle(
                        _run(world, local_plane),
                        world.request,
                        "attempt.unknown",
                        {"reasonCode": "native-outcome-uncertain"},
                        attempt=True,
                    )
                yield

        monkeypatch.setattr(native_start, "_journal", drift)
        with pytest.raises(WorkerError, match="refused"):
            publish_native_start(client, document)
        assert (
            plane.store.get_event(native_start._event_id(world.request, "attempt.started")) is None
        )
        assert next(tmp_path.glob("native-start-*.json")).is_file()
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["tls", "session", "pin"])
def test_start_transport_requires_tls_and_bound_session(tmp_path, fault):  # type: ignore[no-untyped-def]
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        client.poll()
        document = _document(world)
        if fault == "tls":
            client = replace(client, base_url=client.base_url.replace("https:", "http:"))
        elif fault == "session":
            client = replace(client, session=server.session_for("worker.other"))
        else:
            client = replace(client, tls_fingerprint="sha256:" + "0" * 64)
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError):
            publish_native_start(client, document)
        assert plane.store.last_sequence() == before
        assert not list(tmp_path.glob("native-start-*.json"))
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "fault", ["refused", "size", "encoding", "short", "json", "binding", "protocol"]
)
def test_start_client_bounds_and_refusal_never_poll_or_launch(tmp_path, monkeypatch, fault):  # type: ignore[no-untyped-def]
    from http.client import BadStatusLine

    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        document = _document(world)
        calls, closed = [], []

        class Response:
            status = 403 if fault == "refused" else 200

            def getheader(self, name):  # type: ignore[no-untyped-def]
                if name == "Content-Length":
                    return "4097" if fault == "size" else str(len(payload))
                if name == "Content-Type":
                    return "application/json"
                if name == "Content-Encoding" and fault == "encoding":
                    return "gzip"
                return None

            def read(self, size):  # type: ignore[no-untyped-def]
                assert size <= 4097
                return payload[:-1] if fault == "short" else payload

        payload = (
            b"x"
            if fault == "json"
            else canonical_json(
                {
                    "apiVersion": "researchos.dev/v0alpha1",
                    "kind": "NativeStartReceipt",
                    "leaseId": document.lease_id,
                    "bindingDigest": "jcs-sha256:" + "f" * 64,
                    "eventId": "evt.foreign",
                    "sequence": 1,
                    "launchAllowed": False,
                }
            ).encode()
        )

        class Connection:
            def request(self, method, path, *a, **k):  # type: ignore[no-untyped-def]
                calls.append((method, path))

            def getresponse(self):  # type: ignore[no-untyped-def]
                if fault == "protocol":
                    raise BadStatusLine(client.grant_token)
                return Response()

            def close(self):  # type: ignore[no-untyped-def]
                closed.append(1)

        monkeypatch.setattr(native_start_client, "_connection", lambda *a, **k: Connection())
        with pytest.raises(WorkerError) as exc:
            publish_native_start(client, document)
        assert client.grant_token not in str(exc.value)
        count = 3 if fault in {"short", "protocol"} else 1
        assert calls == [("POST", "/v0alpha1/native/start")] * count
        assert len(closed) == count
        assert not list(tmp_path.glob("native-start-*.json"))
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "filename,model",
    [
        ("request.valid.json", NativeStartRequest),
        ("receipt.valid.json", native_start.NativeStartReceipt),
    ],
)
def test_published_start_examples_and_closed_invalid_contracts(filename, model):  # type: ignore[no-untyped-def]
    from pydantic import ValidationError

    root = Path(__file__).parents[1] / "examples/native-remote-start"
    document = json.loads((root / filename).read_text())
    model.model_validate(document)
    invalid = (
        "request.invalid-pid.json"
        if filename.startswith("request")
        else "receipt.invalid-launch.json"
    )
    with pytest.raises(ValidationError):
        model.model_validate(json.loads((root / invalid).read_text()))
    if filename.startswith("receipt"):
        document["launchAllowed"] = 0
        with pytest.raises(ValidationError):
            model.model_validate(document)
