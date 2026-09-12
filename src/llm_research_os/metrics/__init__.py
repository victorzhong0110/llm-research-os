"""High-frequency metric sampling. Series live in CAS; events cite digests."""

from llm_research_os.metrics.chunk import (
    MAX_METRIC_CHUNKS_PER_ATTEMPT,
    MAX_METRIC_SAMPLES_PER_CHUNK,
    MetricChunkError,
    MetricSample,
    put_metric_chunks,
)

__all__ = [
    "MAX_METRIC_CHUNKS_PER_ATTEMPT",
    "MAX_METRIC_SAMPLES_PER_CHUNK",
    "MetricChunkError",
    "MetricSample",
    "put_metric_chunks",
]
