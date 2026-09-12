# CUDA image for the unpaid GPU sheet

Issue #38 stays open. This directory is the **method** to build and verify
a digest-pinned image that contains `ms-swift==4.5.2`. It is not a GPU
run. Do not pass `--gpus`. Do not run `swift sft` with a model.

Default `verify.sh` does not pull `nvidia/cuda`. Ordinary hosts report
`skipped-no-runtime` (no docker) or `skipped-no-build` (docker present,
build not approved). Designated Linux OCI CI must not set
`RESEARCHOS_GPU_IMAGE_BUILD=1`; that job is the CPU brick, not this image.

## Build (Linux with disk; still unpaid, still no train)

```bash
docker build \
  --platform linux/amd64 \
  -t researchos-ms-swift:4.5.2 \
  -f examples/m2-gpu-image/Dockerfile \
  examples/m2-gpu-image
docker image inspect --format '{{.Id}}' researchos-ms-swift:4.5.2
```

Record that `sha256:` value on the grant. A tag is not identity. After
`docker pull` of the NVIDIA base, pin the base too:

```bash
docker image inspect --format '{{index .RepoDigests 0}}' \
  nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04
```

Do not invent a digest before that inspect.

## Verify

```bash
sh examples/m2-gpu-image/verify.sh
RESEARCHOS_GPU_IMAGE_BUILD=1 sh examples/m2-gpu-image/verify.sh
```

The second command builds and runs `swift sft --help` without `--gpus`.
Missing docker is `skipped-no-runtime`. Asking to build without a docker
engine is `failed-no-runtime` (exit 1), not a skip. Help-check is not a
training run.

See [M2 GPU experiment sheet](../../docs/guides/m2-gpu-experiment.md).
