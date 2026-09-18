from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from llm_research_os.cli.parser import build_parser
from llm_research_os.execution import (
    NATIVE_RUNTIME_PROFILE_V1,
    NATIVE_RUNTIME_PROFILES,
    NativeSshError,
    NativeSshTarget,
    parse_ssh_target,
    write_native_ssh_pack,
    write_onboarding_page,
)

HOST_KEY = "ssh-ed25519:" + "A" * 68
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


def test_pack_refuses_symlink_output_and_writes_nothing(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "pack-link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(NativeSshError, match="output directory is invalid") as captured:
        write_native_ssh_pack(link, _target(), project_id=PROJECT, source=SOURCE)
    assert captured.value.code == "pack-output-invalid"
    assert list(outside.iterdir()) == []


def test_pack_refuses_file_output(tmp_path: Path) -> None:
    taken = tmp_path / "file-output"
    taken.write_text("existing", encoding="utf-8")
    with pytest.raises(NativeSshError, match="output directory is invalid") as captured:
        write_native_ssh_pack(taken, _target(), project_id=PROJECT, source=SOURCE)
    assert captured.value.code == "pack-output-invalid"


def test_page_refuses_symlink_output(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    link = tmp_path / "page-link"
    link.symlink_to(target_dir, target_is_directory=True)
    with pytest.raises(NativeSshError, match="output is invalid") as captured:
        write_onboarding_page(link, _target(), project_id=PROJECT, source=SOURCE)
    assert captured.value.code == "ssh-output-invalid"
    assert list(target_dir.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only")
def test_key_body_pack_files_are_owner_only(tmp_path: Path) -> None:
    output = tmp_path / "pack"
    write_native_ssh_pack(output, _target(), project_id=PROJECT, source=SOURCE)
    assert stat.S_IMODE((output / "STATUS.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((output / "ssh_config.fragment").stat().st_mode) == 0o600


def test_cli_profile_choices_match_the_registry() -> None:
    parser = build_parser()
    run_base = [
        "native",
        "run",
        "spec.yaml",
        "authorization-request.json",
        "preflight-request.json",
        "native.db",
        "--registry",
        "manifest.yaml",
        "--authorization-event-id",
        "evt.auth.native.1",
        "--authorization-sequence",
        "1",
    ]
    onboard_base = [
        "native",
        "ssh-onboard",
        "pack",
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
    assert parser.parse_args([*run_base]).profile == NATIVE_RUNTIME_PROFILE_V1
    assert parser.parse_args([*onboard_base]).profile == NATIVE_RUNTIME_PROFILE_V1
    for profile in NATIVE_RUNTIME_PROFILES:
        assert parser.parse_args([*run_base, "--profile", profile]).profile == profile
        assert parser.parse_args([*onboard_base, "--profile", profile]).profile == profile
    with pytest.raises(SystemExit):
        parser.parse_args([*run_base, "--profile", "restricted-v0alpha9"])
    with pytest.raises(SystemExit):
        parser.parse_args([*onboard_base, "--profile", "restricted-v0alpha9"])
