# Optional Ray Jobs compute host

Ray 2.59.0 is pinned for R08 resource probes and reviewed CPU project jobs. This extra belongs on
an explicitly owned compute host, not the controller's default environment.
There is no model download, training installation or cloud provisioning.

```bash
python -m pip install -r extras/ray-jobs/requirements.txt .
python examples/r08-ray-jobs/probe.py --device cpu --name cpu-1 --state /tmp/researchos-ray-cpu-1
```

The script creates a new owned token-authenticated local Ray cluster, submits
only a fixed finite probe and checks its result through `RayJobsProbe`. It
reconstructs the adapter after submission and observes the same job. A parent
120-second deadline includes native startup; the job itself has a 45-second
observation ceiling. It never reuses an existing cluster or executes `ray stop`.
Nonzero exit is an unavailable/failed probe, not an accepted capability.

For an existing CUDA/PyTorch host, including a candidate Kaggle notebook:

```bash
python examples/r08-ray-jobs/probe.py --device cuda --name cuda-1 --state /tmp/researchos-ray-cuda-1
```

CUDA is tested independently: Ray must advertise a GPU, the job reserves one
GPU, and the fixed PyTorch matrix operation must actually run on CUDA. The
result prints actual Python/platform/PyTorch/CUDA/GPU identities. CPU success
cannot substitute for this result. Do not install CUDA/PyTorch into the controller.
The repository requires Python 3.12+; check the notebook interpreter first.
This example does not certify Kaggle quotas, uptime, remote SSH or Docker support.

Keep the intent directory. Reusing a name with changed endpoint/token/device or
corrupted state refuses; cluster history loss never resubmits. Use a deliberately
new `--name` and state directory to authorize another diagnostic. Token values
are process-local and omitted from saved adapter state and output.

For an actual approved CPU project task, use the fixed driver adapter and
independent native outcome recovery in [the project-job guide](../../docs/guides/ray-native-cpu-jobs.md).
Resource probes remain separate [diagnostics](../../docs/protocols/ray-jobs-resource-probe-v0alpha1.md).
GPU execution profiles, selected two-host evidence and Checkpoint B acceptance
remain open; CPU project completion does not substitute for them.
