# CUDA 12.4 + ms-swift==4.5.2. Pin the built image by digest at grant time.
# Do not train against a floating tag. Do not use this file as a GPU proof.
FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir "ms-swift==4.5.2"

# Triton/PyTorch native JIT compiles a CUDA utils extension against Python.h.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Help-check only. Training is the unpaid GPU sheet, not this build.
RUN python3 -c "import importlib.util; assert importlib.util.find_spec('swift')"
