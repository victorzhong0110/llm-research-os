from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import llm_research_os.execution.native_web as web_module
from llm_research_os.cli import main
from llm_research_os.execution import (
    NativeSshError,
    NativeSshTarget,
    parse_ssh_target,
    write_native_ssh_pack,
    write_onboarding_page,
)

HOST_KEY = "ssh-ed25519:" + "A" * 68
HOST_KEY_BODY = HOST_KEY.split(":", 1)[1]
PROJECT = "example-native"
SOURCE = "https://researchos.dev/projects/example-native"


def _target() -> NativeSshTarget:
    return parse_ssh_target(
        host="192.0.2.10",
        port=2222,
        user="researcher",
        workdir="/home/researcher/native",
        host_key=HOST_KEY,
        profile="restricted-v0alpha1",
    )


def test_web_writer_is_network_and_spawn_free() -> None:
    source = Path(web_module.__file__).read_text(encoding="utf-8")
    for banned in ("socket", "subprocess", "urllib", "http.client", "Popen", "os.system"):
        assert banned not in source


def test_page_shape_and_pending_live_labels(tmp_path: Path) -> None:
    target = _target()
    output = tmp_path / "pack"
    output.mkdir()
    name = write_onboarding_page(output, target, project_id=PROJECT, source=SOURCE)
    assert name == "ONBOARDING.html"
    page = (output / name).read_text(encoding="utf-8")
    assert "pending-live" in page
    assert "not-provisioned" in page
    assert "not a public service" in page
    assert "192.0.2.10" in page
    assert "ssh-ed25519" in page
    assert HOST_KEY_BODY not in page
    assert "PasswordAuthentication no" in page
    assert "no-agent-forwarding" in page


def test_page_has_no_script_or_network_surface(tmp_path: Path) -> None:
    target = _target()
    output = tmp_path / "pack"
    output.mkdir()
    write_onboarding_page(output, target, project_id=PROJECT, source=SOURCE)
    page = (output / "ONBOARDING.html").read_text(encoding="utf-8")
    assert "<script" not in page.lower()
    assert "http://" not in page
    assert "fetch(" not in page
    assert "XMLHttpRequest" not in page
    assert "<a " not in page.lower()


def test_page_escapes_operator_text(tmp_path: Path) -> None:
    target = _target()
    output = tmp_path / "pack"
    output.mkdir()
    tricky = "https://researchos.dev/projects/example-native?lang=en&mode=full"
    write_onboarding_page(output, target, project_id=PROJECT, source=tricky)
    page = (output / "ONBOARDING.html").read_text(encoding="utf-8")
    assert "lang=en&amp;mode=full" in page
    assert "lang=en&mode=full" not in page


def test_page_refuses_bad_target_or_output(tmp_path: Path) -> None:
    target = _target()
    with pytest.raises(NativeSshError, match="target is invalid") as captured:
        write_onboarding_page(tmp_path, "not-a-target", project_id=PROJECT, source=SOURCE)
    assert captured.value.code == "ssh-target-invalid"
    missing = tmp_path / "missing-dir"
    with pytest.raises(NativeSshError, match="output is invalid") as captured_output:
        write_onboarding_page(missing, target, project_id=PROJECT, source=SOURCE)
    assert captured_output.value.code == "ssh-output-invalid"
    with pytest.raises(NativeSshError, match="output is invalid") as captured_str:
        write_onboarding_page(str(tmp_path), target, project_id=PROJECT, source=SOURCE)  # type: ignore[arg-type]
    assert captured_str.value.code == "ssh-output-invalid"


def test_pack_without_web_has_no_page_and_null_web_status(tmp_path: Path) -> None:
    target = _target()
    output = tmp_path / "pack"
    status = write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE)
    assert status["webPage"] is None
    assert not (output / "ONBOARDING.html").exists()
    stored = json.loads((output / "STATUS.json").read_text(encoding="utf-8"))
    assert stored["webPage"] is None


def test_pack_with_web_writes_page_and_records_it(tmp_path: Path) -> None:
    target = _target()
    output = tmp_path / "pack"
    status = write_native_ssh_pack(
        output, target, project_id=PROJECT, source=SOURCE, include_web=True
    )
    assert status["webPage"] == "ONBOARDING.html"
    assert (output / "ONBOARDING.html").is_file()
    assert HOST_KEY_BODY not in (output / "ONBOARDING.html").read_text(encoding="utf-8")


def test_cli_web_flag_writes_page_and_stays_off_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = [
        "native",
        "ssh-onboard",
        "--host",
        "192.0.2.10",
        "--user",
        "researcher",
        "--workdir",
        "/home/researcher/native",
        "--host-key",
        HOST_KEY,
        "--project",
        PROJECT,
        "--source",
        SOURCE,
    ]
    plain = tmp_path / "plain"
    assert main([*base, str(plain), "--format", "json"]) == 0
    rendered = capsys.readouterr()
    assert json.loads(rendered.out)["webPage"] is None
    assert not (plain / "ONBOARDING.html").exists()
    with_web = tmp_path / "with-web"
    assert main([*base, str(with_web), "--web", "--format", "text"]) == 0
    text = capsys.readouterr()
    assert "ONBOARDING.html" in text.out
    assert "no server" in text.out
    assert (with_web / "ONBOARDING.html").is_file()


def test_no_socket_or_spawn_in_pack_or_page_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def tripwire(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"network/spawn called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "Popen", tripwire)
    import socket as socket_module

    monkeypatch.setattr(socket_module, "socket", tripwire)
    target = _target()
    output = tmp_path / "pack"
    write_native_ssh_pack(output, target, project_id=PROJECT, source=SOURCE, include_web=True)
    assert (output / "ONBOARDING.html").is_file()
