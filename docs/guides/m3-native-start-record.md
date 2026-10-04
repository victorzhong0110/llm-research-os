# R08 controller start-record integration

Configure the existing `LoopbackWorkerServer` with trusted
`NativeControllerContext(spec, registry)` and pinned TLS. Controller context
comes from its owner, never the remote Worker. The bridge is Python API only;
there is no new generic execution CLI.

The future Worker executor must prepare and recheck its reviewed workspace,
retain its own durable launch intent, and accept only a fresh fully-bound claim.
It must create a fixed trusted child blocked before import, persist and sync the
Worker-local identity, and verify its interpreter before contacting this endpoint.

`publish_native_start(client, NativeStartRequest(...))` from
`llm_research_os.workers.native_start_client` publishes the existing preparation
receipt, exact consumed lease and identity digest. It returns a validated
`NativeStartReceipt`. Calling it does not spawn, consume a new grant, create a
Run or observe a process. The returned false launch flag and digest are not
portable credentials. A future executor can release only its same existing
child after checking that live acknowledgement; a resumed claim or lost local
identity cannot justify another child.

Keep controller journal files next to the event database. Do not delete them to
recover or retry an Attempt. Restore observation or the same immutable recording;
changed identity, corrupted state and unknown outcomes require refusal. Process
identity stays on the Worker. Vendor stop acknowledgement and transport recovery
remain distinct from observed process-group stop.

The optional Ray resource probe is already merged in #124 at
`c8f0195c71947ea117c668c16209ba91c065e03e`; its main CI 37131649684 passed.
This start-record slice is the next controller boundary. Full Ray/native task
launch, output reconciliation, recovery, CUDA and new authorized-host evidence
remain pending at this slice's review identity. Later execution/recovery slices
are recorded in the [acceptance matrix](../evidence/m3/acceptance-matrix.md).
Checkpoint B remains open. The 2026-10-04 maintainer direction supersedes the
former freeze: complete sequentially through R16 after each predecessor is merged
and accepted. See the [live acceptance runbook](r08-live-acceptance.md).
