"""`ProblemReport.type` is a stable code, not an exception class name.

A caller is expected to branch on `type`, so the value has to be a closed,
documented identifier rather than whatever the class happens to be called. These
tests pin that for the control-store family specifically, because adopting the
rule changed three existing CLI tests from `EventStoreSchemaError` to a code.

The other half of the contract is that these messages carry no host path: they
reach stderr, logs, and issue reports. Both properties are asserted together,
because a code that carries a path would be worse than the class name it replaced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm_research_os.application.workspace import init_workspace
from llm_research_os.cli.output import problem_report
from llm_research_os.storage.errors import EventStoreSchemaError
from llm_research_os.storage.store import EventStore

# The documented control-store vocabulary. Adding a code is allowed; changing or
# removing one of these is a breaking change to a published surface.
STORE_CODES = {
    "event-store-absent",
    "event-store-unwritable",
    "event-store-unreadable",
    "event-store-schema-invalid",
}


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    init_workspace(
        root,
        project_id="example",
        control_db=Path("control/events.sqlite"),
        cas_root=Path("cas"),
        worker_root=Path("worker"),
    )
    return root


def test_a_missing_control_store_reports_the_closed_absent_code(tmp_path: Path) -> None:
    """A fresh workspace has no EventStore until the first append (R02 contract).

    The error must still be a typed, coded ProblemReport rather than a traceback,
    and it must say which condition it is reporting.
    """
    root = _workspace(tmp_path)
    missing = root / "control" / "events.sqlite"
    assert not missing.exists()

    with pytest.raises(EventStoreSchemaError) as captured:
        EventStore(missing, create=False)

    report = problem_report(captured.value)
    assert report.valid is False
    assert len(report.errors) == 1
    assert report.errors[0].type == "event-store-absent"


def test_the_default_code_is_the_schema_invalid_one() -> None:
    """An un-coded construction still lands in the documented vocabulary.

    This is what a future store error gets if it forgets to pass a code, so the
    default is the generic member of the family rather than a bare class name.
    """
    report = problem_report(EventStoreSchemaError("something is wrong"))
    assert report.errors[0].type == "event-store-schema-invalid"


@pytest.mark.parametrize("code", sorted(STORE_CODES))
def test_every_store_code_is_documented_and_reaches_the_report(code: str) -> None:
    """No store code may be constructible and then invisible in the report.

    A code that `problem_report` dropped to the class name would be a code that
    the protocol documents but the CLI never emits, which is worse than not
    documenting it.
    """
    report = problem_report(EventStoreSchemaError("message", code=code))
    assert report.errors[0].type == code


def test_the_absent_message_carries_no_host_path_and_says_what_to_do(tmp_path: Path) -> None:
    """The path is the caller's; the shared error must not leak it.

    The whole reason this error was given a code was to make it say *what* went
    wrong. It must not do that by printing where the database was.
    """
    _workspace(tmp_path)
    # The parent must exist, or this hits the missing-parent rejection instead
    # of the absent-database one this test is about.
    control = tmp_path / "customer-customer-42" / "control"
    control.mkdir(parents=True)
    secret_ish = control / "events.sqlite"

    with pytest.raises(EventStoreSchemaError) as captured:
        EventStore(secret_ish, create=False)

    report = problem_report(captured.value)
    rendered = json.dumps(report.model_dump())
    assert str(secret_ish) not in rendered
    assert "customer-customer-42" not in rendered
    # The actionable half of the message must survive the scrubbing.
    assert "backup" in report.errors[0].message


def _rejected_paths(tmp_path: Path) -> dict[str, Path]:
    """Paths that reach the rejection raises in ``_validate_database_path``.

    Each of these was, at some point, the message that broke the rule: the
    rejection said what was wrong *and* printed where it looked.
    """
    control = tmp_path / "control"
    control.mkdir(parents=True, exist_ok=True)

    regular = control / "regular.sqlite"
    regular.write_bytes(b"")

    link = control / "link.sqlite"
    if link.is_symlink():
        link.unlink()
    link.symlink_to(regular)

    return {
        "missing parent directory": tmp_path / "absent" / "control" / "events.sqlite",
        "symbolic link": link,
        "not a regular file": control,
    }


@pytest.mark.parametrize(
    "condition", ("missing parent directory", "symbolic link", "not a regular file")
)
def test_no_path_rejection_message_leaks_the_path(tmp_path: Path, condition: str) -> None:
    """Every rejection in the path validator is subject to the same rule.

    Parameterised rather than repeated: the first version of this test only
    covered the missing-database case, and the four rejections beside it each
    still printed the host path unnoticed.
    """
    target = _rejected_paths(tmp_path)[condition]

    with pytest.raises(EventStoreSchemaError) as captured:
        EventStore(target, create=False)

    rendered = json.dumps(problem_report(captured.value).model_dump())
    assert str(tmp_path) not in rendered
    assert str(target) not in rendered
    assert "/control" not in rendered
    # The condition itself must still be legible to whoever has to act on it.
    assert problem_report(captured.value).errors[0].message


def test_an_uncoded_error_still_falls_back_to_its_class_name() -> None:
    """The rule is one-directional.

    Routing codes must not change what happens to an error that has no code:
    class name, as before. If this ever starts failing, the fallback was replaced
    rather than extended.
    """

    class UnrelatedError(Exception):
        pass

    assert problem_report(UnrelatedError("boom")).errors[0].type == "UnrelatedError"


def test_sqlite_initialization_error_does_not_disclose_host_path(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import sqlite3

    import llm_research_os.storage.store as module

    path = tmp_path / "customer-private.sqlite"

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("private sqlite detail")

    monkeypatch.setattr(module.sqlite3, "connect", fail)
    with pytest.raises(EventStoreSchemaError) as captured:
        EventStore(path)
    rendered = json.dumps(problem_report(captured.value).model_dump())
    assert str(path) not in rendered
    assert "customer-private" not in rendered
    assert "private sqlite detail" not in rendered
