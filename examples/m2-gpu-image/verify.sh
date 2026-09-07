#!/bin/sh
# Verify the unpaid CUDA image method. MUST NOT request a GPU device or train.
# Default does not pull nvidia/cuda. Set RESEARCHOS_GPU_IMAGE_BUILD=1 to build.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
IMAGE=${IMAGE:-researchos-ms-swift:4.5.2}

if [ "${RESEARCHOS_GPU_IMAGE_BUILD:-0}" != "1" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo '{"status":"skipped-no-runtime","gpu":"not-run","executed":false}'
  else
    echo '{"status":"skipped-no-build","gpu":"not-run","executed":false}'
  fi
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo '{"status":"failed-no-runtime","gpu":"not-run","executed":false}' >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo '{"status":"failed-no-runtime","gpu":"not-run","executed":false}' >&2
  exit 1
fi

docker build --platform linux/amd64 -t "$IMAGE" \
  -f "$ROOT/examples/m2-gpu-image/Dockerfile" \
  "$ROOT/examples/m2-gpu-image"
DIGEST=$(docker image inspect --format '{{.Id}}' "$IMAGE")
HELP=$(docker run --rm --network=none "$IMAGE" swift sft --help)
echo "$HELP" | grep -F -- "--tuner_type" >/dev/null
echo "{\"status\":\"help-checked\",\"gpu\":\"not-run\",\"executed\":false,\"imageDigest\":\"$DIGEST\"}"
