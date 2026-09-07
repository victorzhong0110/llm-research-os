# Isolated ms-swift 4.5.2 for Apple Silicon MPS

This directory is **not** part of the core control-plane environment
([ADR-0012](../../docs/adr/0012-python-and-dependencies.md)). Do not add
`ms-swift` or `torch` to `pyproject.toml` / `uv.lock`.

The `.venv/` and `.cache/` trees are gitignored. Weights and checkpoints
must not be committed.

Isolation for `macos-mps-process` is a POSIX process group, an environment
allowlist, a closed workspace cwd, offline Hub flags, and a 1800 s wall.
It is **not** NativeProcessRuntime and does **not** inherit OCI namespaces,
cgroups, seccomp, or mount jails ([ADR-0058](../../docs/adr/0058-macos-mps-training-profile.md)).

## Install (once)

```bash
uv venv extras/ms-swift-mps/.venv --python 3.12
uv pip install --python extras/ms-swift-mps/.venv/bin/python \
  -r extras/ms-swift-mps/requirements.txt
extras/ms-swift-mps/.venv/bin/python -c \
  "import torch,swift; print(torch.__version__, swift.__version__, torch.backends.mps.is_available())"
```

`requirements.txt` pins `ms-swift==4.5.2` only. Torch is whatever that
release resolves; the live environment artifact records `torch`,
`sitecustomizeDigest`, `deviceMapArgv: absent`, and `tmpdir: /tmp`.
Changing `pythonpath/sitecustomize.py` changes `imageDigest`, so old
grants cannot be reused.

## Prefetch (Hub, not cloud GPU)

Pin `Qwen/Qwen2.5-0.5B-Instruct` at
`7ae557604adf67be50417f59c2c2f167def9a775`. Dataset is the corpus
`examples/m2-mps-checkpoint/data/sft.jsonl` (synthetic Alpaca-style rows).

```bash
mkdir -p extras/ms-swift-mps/.cache/run/{model,data,output}
extras/ms-swift-mps/.venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    "Qwen/Qwen2.5-0.5B-Instruct",
    revision="7ae557604adf67be50417f59c2c2f167def9a775",
    local_dir="extras/ms-swift-mps/.cache/run/model",
)
PY
cp examples/m2-mps-checkpoint/data/sft.jsonl extras/ms-swift-mps/.cache/run/data/sft.jsonl
```

## Direct argv check (before the Worker chain)

Do **not** pass `--device_map mps`. PyTorch 2.14 deadlocks that load
path on Metal. `PYTHONPATH` must include `extras/ms-swift-mps/pythonpath`
so Swift's default device map returns `None`; weights load on CPU and
HuggingFace Trainer moves the model to `mps`.

From the workspace root `extras/ms-swift-mps/.cache/run`:

```bash
cd extras/ms-swift-mps/.cache/run
export PYTHONPATH="$PWD/../../pythonpath${PYTHONPATH:+:$PYTHONPATH}"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 MODELSCOPE_OFFLINE=1 \
  PYTORCH_ENABLE_MPS_FALLBACK=1 \
  ../../.venv/bin/swift sft \
  --model model \
  --model_revision 7ae557604adf67be50417f59c2c2f167def9a775 \
  --model_type qwen2 \
  --template qwen2_5 \
  --use_hf true \
  --tuner_type lora \
  --dataset data/sft.jsonl \
  --torch_dtype float32 \
  --max_steps 20 \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 1 \
  --learning_rate 1e-4 \
  --lora_rank 8 \
  --lora_alpha 16 \
  --output_dir output \
  --save_steps 10 \
  --logging_steps 1 \
  --max_length 256 \
  --seed 42 \
  --fp16 false \
  --bf16 false \
  --attn_impl eager \
  --dataloader_num_workers 0 \
  --eval_strategy no \
  --save_total_limit 2 \
  --report_to none \
  --add_version false \
  --check_model false \
  --optim adamw_torch \
  --gradient_checkpointing false
```

Adjust the `swift` path if this README is followed from the repository
root (`extras/ms-swift-mps/.venv/bin/swift`). Record the actual device
(`mps:0` vs CPU), wall time, and peak RSS. If the probe is not MPS, stop
and disclose CPU fallback; do not call that a Mac/MPS pass.

## Worker chain (required)

A standalone `swift sft` is not acceptance. After the argv check:

```bash
export RESEARCHOS_MPS_PYTHON="$PWD/extras/ms-swift-mps/.venv/bin/python"
export RESEARCHOS_MPS_WORK="$PWD/extras/ms-swift-mps/.cache/run"
uv run researchos m2 mps \
  examples/m2-mps-checkpoint \
  /tmp/m2-mps.db \
  --format json
```

That command authorizes `execute.mps`, leases `macos-mps-process`, runs
the native argv, uploads checkpoint bytes into CAS (256 MiB bound), and
records `work.completed`. `executed: false` plan receipts are not this
row.

Resume overlay (full checkpoint vs adapter-only):

```bash
uv run researchos training overlay \
  examples/m2-mps-checkpoint/plan.json \
  --resume full-checkpoint \
  --checkpoint output/checkpoint-10 \
  --format json
```

Collect with the MPS profile (GPU collect stays 1 MiB):

```bash
uv run researchos training collect \
  extras/ms-swift-mps/.cache/run/output \
  --artifacts /tmp/m2-mps-artifacts \
  --profile mps \
  --format json
```

Worker `TMPDIR` is `/tmp` so macOS `AF_UNIX` sockets stay under the path
limit. Do not point `TMPDIR` at the long workspace path.

Live pytest (`RESEARCHOS_MPS_REQUIRED=1`) is optional and is **not** set
in GitHub Actions. Ordinary `pytest` uses the stub interpreter.

