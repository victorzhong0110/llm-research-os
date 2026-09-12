# M1/M2 maintenance evidence and disposition

Baseline: integrated `main` at `229d1b0ced56689fabd1be2bcf715d29f0f12bed`.
Historical M2 evidence: `57ffdae1358484b047a091e5d9a60d41c9615d3e`.
This maintenance change does not rerun GPU jobs or rewrite experiment receipts.

| Finding | Treatment | Verification / limitation |
| --- | --- | --- |
| Coverage rounding accepts less than 85% | Three-digit precision plus independent integer-count gate | Synthetic 84.77% fails; 85% passes. Full GitHub matrix must pass on this change |
| GPU preparation can implicitly elevate / follow host links | Remove sudo and setfacl fallbacks; descriptor-based no-follow access and hardlink rejection | Permission/link regression tests; no new CUDA live claim |
| Separate capability names | Central kernel/execution/preflight name set, reject unknown authorization | Existing native preflight retained; known plan strings/digests unchanged |
| Core event payload contracts hard to discover | Generated catalog from six domain registries, schema validity/drift checks | Envelope stays extensible; consumer authority checks remain required |
| Money accepts non-contract forms | Validate canonical money syntax before Decimal arithmetic | Nonfinite, exponent, excess precision, negative and range tests |
| Wheel can silently rely on checkout/training extras | New installed-wheel accept/reject smoke in CI | Local wheel import used an isolated venv with copied locked runtime dependencies; CI performs normal wheel dependency installation |
| README contradicts accepted live evidence | Generated bilingual tables from docs/status.json | Generator drift gate; experiment records preserved |
| Charter errata scattered | Consolidated v0.2 reading with source clause map | Review candidate, no new constitutional or spending decision |
| M1 checkpoint / cancellation (#38, #40) | Revalidate existing research and cancellation paths | wheel-smoke.json; test_m1_checkpoint.py and test_simulated_runtime.py |
| Authorization lifecycle (#53) | M2 already implements HMAC grants/session, expiry and revoke | Worker tests and accepted two-host evidence. Asymmetric signatures on facts and NativeProcessRuntime remain outside delivered scope |

## Local verification limits

The full protocol attempt in this execution environment encountered an unsupported
Unix-domain socket and unavailable /proc/ps process observations. Those tests
remain unchanged and required on supported CI hosts. A separate compatibility
failure caused by omitting the historical process.native capability was fixed;
all 66 native-preflight tests then passed. Local aggregate coverage from this
failed full run is not a passing gate and must not be used as such.

`wheel-smoke.json` records fresh offline accept/reject receipts from the built
wheel outside the source checkout, with no torch or ms-swift installed. It proves
the packaging/research loop only. Historical CUDA and paid-cloud claims do not
follow from it.

## Explicitly separate M3 work

Unified ExecutionProfile and module decomposition, SSH configuration/password/key/
ProxyJump onboarding, public Web UX, a restricted non-OCI process runtime and
third-party adapter isolation are feature/security projects. They are not marked
complete by this maintenance patch. No public tag or release is created as an
administrative substitute for their acceptance.
