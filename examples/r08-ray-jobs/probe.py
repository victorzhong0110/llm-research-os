"""Start an owned local Ray cluster and verify the finite CPU/CUDA adapter probe."""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path


def child(args: argparse.Namespace) -> int:
    # Explicit local cluster and token prevent reuse of a notebook's existing cluster.
    os.environ["RAY_USAGE_STATS_ENABLED"] = "0"
    os.environ["RAY_AUTH_MODE"] = "token"
    os.environ["RAY_AUTH_TOKEN"] = secrets.token_hex(32)
    os.environ["RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER"] = "0"
    os.environ["RAY_gcs_rpc_server_connect_timeout_s"] = "5"  # noqa: SIM112 - Ray's exact key
    import ray

    from llm_research_os.execution.native_transfer import _directory
    from llm_research_os.workers.ray_probe import RAY_PROBE_VERSION, RayJobsProbe

    if ray.__version__ != RAY_PROBE_VERSION:
        raise RuntimeError("unexpected Ray version")
    args.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    cluster = args.state / "owned-cluster"
    cluster.mkdir(mode=0o700, exist_ok=True)
    for directory in (args.state, cluster):
        with _directory(directory, create=False) as descriptor:
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise RuntimeError("probe state directory is not private")
    try:
        context = ray.init(
            address="local",
            num_cpus=1,
            include_dashboard=True,
            dashboard_host="127.0.0.1",
            dashboard_port=0,
            _node_ip_address="127.0.0.1",
            _temp_dir=str(cluster.absolute()),
            object_store_memory=80 * 1024 * 1024,
            _memory=256 * 1024 * 1024,
            logging_level="ERROR",
        )
        resources = ray.cluster_resources()
        print("ray_version", ray.__version__, flush=True)
        print("ray_resources", resources, flush=True)
        if args.device == "cuda" and resources.get("GPU", 0) < 1:
            print("cuda_probe unavailable: this cluster advertises no GPU", flush=True)
            return 2
        client = RayJobsProbe("http://" + context.dashboard_url, os.environ["RAY_AUTH_TOKEN"])
        observation = client.submit_once(name=args.name, device=args.device, state_root=args.state)
        # A new adapter instance restores observation from durable intent, never a new POST.
        client = RayJobsProbe(client.endpoint, os.environ["RAY_AUTH_TOKEN"])
        replay = client.submit_once(name=args.name, device=args.device, state_root=args.state)
        if replay.submission_id != observation.submission_id:
            raise RuntimeError("probe replay changed submission identity")
        deadline = time.monotonic() + 45
        while replay.backend_status in {"PENDING", "RUNNING"} and time.monotonic() < deadline:
            time.sleep(0.25)
            replay = client.observe(name=args.name, device=args.device, state_root=args.state)
        print("submission_id", replay.submission_id, flush=True)
        print("backend_status", replay.backend_status, flush=True)
        print("probe_result", replay.result, flush=True)
        print("project_task_starts", replay.project_task_starts, flush=True)
        print("lifecycle_facts_appended", replay.lifecycle_facts_appended, flush=True)
        if replay.backend_status != "SUCCEEDED" or replay.result is None:
            requested = client.request_stop(
                name=args.name, device=args.device, state_root=args.state
            )
            print("backend_stop_requested", requested, flush=True)
            return 2
        return 0
    finally:
        # Only the explicitly owned cluster is shut down; no global `ray stop`.
        ray.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--name", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args)
    command = [
        sys.executable,
        str(Path(__file__).absolute()),
        "--child",
        "--device",
        args.device,
        "--name",
        args.name,
        "--state",
        str(args.state.absolute()),
    ]
    # A parent deadline also covers native GCS calls that defer Python signal handlers.
    with subprocess.Popen(command, start_new_session=True) as process:  # noqa: S603
        try:
            return process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            print("ray_probe unavailable: owned cluster/probe deadline exceeded", flush=True)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
