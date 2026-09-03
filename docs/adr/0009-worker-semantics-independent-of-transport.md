# ADR-0009: Worker Semantics Independent of Transport

- Status: Accepted
- Date: 2026-08-21

## Context

Remote execution will eventually use HTTPS, long polling, SSE, WebSocket, SSH
bootstraps or, much later, gRPC. If Worker identity, leases, heartbeats,
cancellation and artifact return are defined inside a single transport, every
new channel forks the protocol. Charter §8.4 already says the semantic Worker
protocol should be independent of the byte transport. Chapter 18 decision 5-WA
chose HTTPS/JSON with worker-initiated long polling as the first transport
experiment, deferred to M2.

M0 has no remote Worker. SimulatedRuntime and NativeProcessPreflight are local
control-plane slices. The accepted decoupling still needs a record so M2 cannot
bake lease semantics into an HTTP client.

## Decision

Worker meaning is a semantic protocol: registration, capability advertisement,
heartbeat, leased work, native or OCI execution, event/metric/log emission,
artifact return, completion/failure/lost, and control-plane retry or human
escalation.

Transport is a replaceable binding. The first remote binding, when M2 runs the
experiment, is worker-initiated outbound HTTPS/JSON with long polling, so NAT
and self-hosted machines need no inbound ports. SSH, Tailscale or a controlled
tunnel may bootstrap connectivity; that bootstrap is not the Worker protocol.

gRPC, NATS, Kafka and similar buses are out of scope until there is evidence
that the semantic protocol is stable and that a second transport is required.
Adding a transport MUST NOT change ResearchSpec.

This ADR does not schedule NativeProcessRuntime, OCIContainerRuntime, or any
remote Worker implementation.

## Consequences

- M2 transport prototypes implement the same lease, heartbeat and lost/unknown
  rules the local Run/Attempt machine already uses.
- A cloud-provider adapter may create machines; it is not a second Worker
  protocol.

## Validation

No M0 executable test covers a remote Worker. The record is validated by
charter §8.4 and chapter 18 5-WA remaining the source of the first-binding
experiment, and by M0 refusing to treat SimulatedRuntime as a network Worker.

## References

- [Project charter v0.1 §8.4](../charter-v0.1.md)
- [Chapter 18 decision 5-WA](../chapter-18-decision-guide-v0.1.md)
- [ADR-0008 Native Process and OCI Runtimes](0008-native-process-and-oci-runtimes.md)
- [ADR-0021](README.md) remains the deferred first remote-binding experiment; it has no standalone record yet.
