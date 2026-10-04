# Review and invoke a local extension

This partial Python API accepts reviewed same-user code. It provides resource
bounds, not isolation from the operator's files or network. Compatible declared
read permissions are requests only; parsing/installation grants no handles.

1. Inspect a local regular-file manifest and its inline entryModule before
   admitting code. `load_manifest(path)` is inert and returns an immutable copy.
2. Install the reviewed manifest with
   `ExtensionRegistry.install(path, trust="reviewed-same-user")`. The default
   trust="inert" permits inspection only. Unknown/untrusted trust is refused.
3. Call `registry.run(id, version, request, timeout=...)`. Messages must be finite
   JSON objects below 64 KiB. Duration is positive and at most ten seconds.
4. Inspect AdapterResult.public_document(): outcome, exitCode, timedOut,
   outputLimitExceeded, retained stdoutBytes/stderrBytes and the exact invocation's
   effectiveResourceLimits. An overflow is an error, never a successful partial
   answer. Resource limits can differ by platform.
5. Disable to refuse future resolve/dispatch; enable to restore that reviewed
   registration. Disable does not cancel an in-flight call. Uninstall removes the
   registry entry and preserves the operator's manifest file.

The registry has at most 32 installed entries, including disabled entries; its
identity binds manifest digests, trust and enabled state. It is process-local and
not persisted. The low-level run_adapter function is an explicit operator call
for reviewed code; it does not consult a registry. Registry callers should use
registry.run so disabled/inert state is checked immediately before dispatch.

Contract: [extension boundary](../protocols/extension-boundary-v0alpha1.md).
Generate/check the combined input/output schema with
`researchos schema --contract extension-document` and `researchos schema --check-all`.
Typed third-party integrations, a CLI and full R14/D acceptance remain open.
