"""CAS metric chunks. Heartbeats and per-step series must not fill EventStore."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import canonical_json
from llm_research_os.internal.jsonclone import snapshot_json_document

MAX_METRIC_SAMPLES_PER_CHUNK = 1_024
MAX_METRIC_CHUNKS_PER_ATTEMPT = 32
_API_VERSION = "researchos.dev/v0alpha1"
_KIND = "MetricChunk"


class MetricChunkError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MetricSample:
    step: int
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class MetricChunkRecord:
    digest: str
    sample_count: int
    first_step: int
    last_step: int


def put_metric_chunks(
    artifacts: LocalArtifactStore,
    samples: tuple[MetricSample, ...] | list[MetricSample],
) -> tuple[MetricChunkRecord, ...]:
    """Store sampled series as CAS JSON chunks. Does not append EventStore facts."""

    if type(samples) is list:
        ordered = tuple(samples)
    elif type(samples) is tuple:
        ordered = samples
    else:
        raise MetricChunkError("metric samples must be a list or tuple", code="metric-samples")
    if not ordered:
        raise MetricChunkError("metric samples must not be empty", code="metric-empty")
    chunks = _split_chunks(ordered)
    if len(chunks) > MAX_METRIC_CHUNKS_PER_ATTEMPT:
        raise MetricChunkError(
            "metric series exceeds the per-attempt chunk cap; sample or split the attempt",
            code="metric-chunk-limit",
        )
    recorded: list[MetricChunkRecord] = []
    for chunk in chunks:
        document = {
            "apiVersion": _API_VERSION,
            "kind": _KIND,
            "firstStep": chunk[0].step,
            "lastStep": chunk[-1].step,
            "samples": [{"step": item.step, "values": dict(item.values)} for item in chunk],
        }
        payload = canonical_json(snapshot_json_document(document)).encode("utf-8")
        digest = artifacts.put_bytes(payload).digest
        recorded.append(
            MetricChunkRecord(
                digest=digest,
                sample_count=len(chunk),
                first_step=chunk[0].step,
                last_step=chunk[-1].step,
            )
        )
    return tuple(recorded)


def _split_chunks(samples: tuple[MetricSample, ...]) -> tuple[tuple[MetricSample, ...], ...]:
    for item in samples:
        if type(item) is not MetricSample:
            raise MetricChunkError("metric sample is invalid", code="metric-sample-invalid")
        if type(item.step) is not int or item.step < 0:
            raise MetricChunkError("metric step must be a non-negative int", code="metric-step")
        if type(item.values) is not dict:
            raise MetricChunkError("metric values must be an object", code="metric-values")
        for key, value in item.values.items():
            if type(key) is not str or key == "" or type(value) is not str:
                raise MetricChunkError("metric values must be string fields", code="metric-values")
    chunks: list[tuple[MetricSample, ...]] = []
    offset = 0
    while offset < len(samples):
        chunks.append(samples[offset : offset + MAX_METRIC_SAMPLES_PER_CHUNK])
        offset += MAX_METRIC_SAMPLES_PER_CHUNK
    return tuple(chunks)
