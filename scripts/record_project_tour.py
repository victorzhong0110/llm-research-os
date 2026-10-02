"""Capture the offline CLI tour; optional authoring dependencies: Pillow and ffmpeg."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/assets/project-tour"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = root / ".venv/bin/researchos"
    ffmpeg = shutil.which("ffmpeg")
    git = shutil.which("git")
    if not executable.is_file() or ffmpeg is None or git is None:
        raise RuntimeError("Run uv sync; install ffmpeg and git before recording")
    font = ImageFont.truetype(str(args.font), 18)
    title_font = ImageFont.truetype(str(args.font), 25)
    small_font = ImageFont.truetype(str(args.font), 15)
    records: list[dict[str, object]] = []
    cast: list[list[object]] = []
    frames: list[Image.Image] = []
    cursor = 0
    with tempfile.TemporaryDirectory(prefix="researchos-tour-") as directory:
        commands = [
            ("1 / 5  Validate an experiment", ["validate", "examples/valid/minimal.yaml"], 8),
            (
                "2 / 5  Inspect a plan before executing",
                ["dry-run", "examples/valid/minimal.yaml", "--format", "text"],
                13,
            ),
            (
                "3 / 5  Reject: no Run is queued",
                [
                    "m1",
                    "prove",
                    "examples/m1-checkpoint",
                    f"{directory}/reject.db",
                    "--decision",
                    "reject",
                ],
                14,
            ),
            (
                "4 / 5  Accept: record the complete offline loop",
                ["m1", "prove", "examples/m1-checkpoint", f"{directory}/accept.db"],
                33,
            ),
            (
                "5 / 5  Verify the durable event log",
                ["events", "verify", f"{directory}/accept.db"],
                12,
            ),
        ]
        for index, (caption, command, duration) in enumerate(commands):
            start = time.monotonic()
            result = subprocess.run(  # noqa: S603 -- fixed local CLI; no shell or external input
                [str(executable), *command], cwd=root, capture_output=True, text=True, check=True
            )
            elapsed = time.monotonic() - start
            shown = "researchos " + " ".join(command).replace(directory + "/", "")
            stdout = result.stdout.replace(directory + "/", "")
            stderr = result.stderr.replace(directory + "/", "")
            records.append(
                {
                    "command": shown,
                    "stdout": stdout,
                    "stderr": stderr,
                    "exitCode": result.returncode,
                    "executionSeconds": elapsed,
                    "displaySeconds": duration,
                }
            )
            cast.extend(
                [
                    [cursor, "o", "$ " + shown + "\r\n"],
                    [cursor + 0.4, "o", stdout.replace("\n", "\r\n")],
                ]
            )
            image = Image.new("RGB", (1280, 800), "#0a1525")
            draw = ImageDraw.Draw(image)
            draw.text(
                (32, 24),
                "LLM RESEARCH OS  /  OFFLINE RESEARCH LOOP",
                font=title_font,
                fill="#e8f1ff",
            )
            draw.text((32, 80), caption, font=font, fill="#53d8c9")
            draw.text((32, 130), "$ " + shown, font=small_font, fill="#abc9ff")
            lines = (stdout + stderr).splitlines()
            visible = lines if len(lines) <= 23 else lines[:14]
            for row, line in enumerate(visible):
                draw.text((32, 176 + row * 23), line[:108], font=font, fill="#dbe7f5")
            if len(lines) > 23:
                draw.text(
                    (32, 720),
                    "First 14 output lines shown; full output: recording.json / research-loop.cast",
                    font=small_font,
                    fill="#a8b8cf",
                )
            draw.text(
                (32, 758),
                "Actual CLI output | Mock model | Simulated Run | No GPU",
                font=small_font,
                fill="#f6ca7d",
            )
            if index == 2:
                image.save(output / "recording-poster.png")
            frames.extend([image] * duration)
            cursor += duration
    revision = subprocess.run(  # noqa: S603 -- fixed git arguments, no shell
        [git, "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="researchos-tour-frames-") as frame_directory:
        for index, frame in enumerate(frames):
            frame.save(Path(frame_directory) / f"{index:03}.png")
        subprocess.run(  # noqa: S603 -- fixed encoder and locally created frames
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-framerate",
                "1",
                "-i",
                f"{frame_directory}/%03d.png",
                "-c:v",
                "libx264",
                "-r",
                "8",
                "-crf",
                "26",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output / "research-loop.mp4"),
            ],
            check=True,
        )
    frames[0].resize((960, 600)).save(
        output / "research-loop.gif",
        save_all=True,
        append_images=[frame.resize((960, 600)) for frame in frames[1:]],
        duration=1000,
        loop=0,
    )
    if (output / "research-loop.gif").read_bytes()[-1:] != b";":
        raise RuntimeError("GIF recording is incomplete")
    (output / "recording.json").write_text(
        json.dumps(
            {
                "sourceRevision": revision,
                "provider": "DeterministicMockProvider",
                "runtime": "SimulatedRuntime",
                "gpuUsed": False,
                "durationSeconds": cursor,
                "presentation": "Actual terminal snapshots with reading pauses",
                "commands": records,
            },
            indent=2,
        )
        + "\n"
    )
    header = {"version": 2, "width": 108, "height": 28, "title": "Offline research loop"}
    (output / "research-loop.cast").write_text(
        "\n".join(json.dumps(row) for row in [header, *cast]) + "\n"
    )


if __name__ == "__main__":
    main()
