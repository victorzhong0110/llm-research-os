# Metric chunk v0alpha1

> Status: Experimental CAS document (ADR-0047)  
> Domain version: `v0alpha1`

High-frequency series MUST NOT fill EventStore. A metric chunk is a
content-addressed JSON object. Events MAY cite its digest. Heartbeats
remain transport-only (ADR-0041, ADR-0046).

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are normative.

## Document

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "MetricChunk",
  "firstStep": 0,
  "lastStep": 1023,
  "samples": [{"step": 0, "values": {"loss": "0.01"}}]
}
```

| Field | Rule |
|---|---|
| `apiVersion` | `researchos.dev/v0alpha1` |
| `kind` | `MetricChunk` |
| `firstStep` / `lastStep` | non-negative integers; first and last sample steps |
| `samples` | 1..1024 objects `{step, values}`; `values` is string fields |

## Caps

- 1024 samples per chunk (`MAX_METRIC_SAMPLES_PER_CHUNK`)
- 32 chunks per attempt (`MAX_METRIC_CHUNKS_PER_ATTEMPT`)
- Exceeding the attempt cap is `metric-chunk-limit`
- Object bytes follow `LocalArtifactStore.put_bytes` (1 MiB)

There is no JSON Schema for this object. Digest is raw-byte `sha256:` of
canonical JSON. SimulatedRuntime `training.step` remains
`{kind: synthetic, step: 1}` and is not this series format.

## Citation

A later execution fact MAY include the chunk digest in its payload or in
an artifact ref. It MUST NOT append one `training.step` fact per optimizer
step.
