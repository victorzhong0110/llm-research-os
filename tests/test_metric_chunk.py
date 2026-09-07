from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.metrics import (
    MAX_METRIC_CHUNKS_PER_ATTEMPT,
    MAX_METRIC_SAMPLES_PER_CHUNK,
    MetricChunkError,
    MetricSample,
    put_metric_chunks,
)


def test_metric_chunks_store_series_in_cas_not_events(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    artifacts = LocalArtifactStore(root)
    samples = tuple(MetricSample(step=index, values={"loss": "0.01"}) for index in range(10_000))
    records = put_metric_chunks(artifacts, samples)
    assert len(records) == 10
    assert records[0].sample_count == MAX_METRIC_SAMPLES_PER_CHUNK
    assert records[-1].last_step == 9_999
    with artifacts.open(records[0].digest) as handle:
        raw = handle.read()
    payload = json.loads(raw.decode("utf-8"))
    assert payload["kind"] == "MetricChunk"
    assert payload["apiVersion"] == "researchos.dev/v0alpha1"
    assert len(payload["samples"]) == MAX_METRIC_SAMPLES_PER_CHUNK
    assert raw.startswith(b"{")


def test_metric_chunks_reject_more_than_cap(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    artifacts = LocalArtifactStore(root)
    limit = MAX_METRIC_CHUNKS_PER_ATTEMPT * MAX_METRIC_SAMPLES_PER_CHUNK
    samples = tuple(MetricSample(step=index, values={"loss": "0.01"}) for index in range(limit + 1))
    with pytest.raises(MetricChunkError, match="chunk cap") as exc_info:
        put_metric_chunks(artifacts, samples)
    assert exc_info.value.code == "metric-chunk-limit"


def test_metric_chunks_reject_bool_step(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    artifacts = LocalArtifactStore(root)
    with pytest.raises(MetricChunkError, match="non-negative int") as exc_info:
        put_metric_chunks(
            artifacts,
            (MetricSample(step=True, values={"loss": "0.01"}),),  # type: ignore[arg-type]
        )
    assert exc_info.value.code == "metric-step"
