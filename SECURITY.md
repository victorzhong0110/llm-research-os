# Security Policy

LLM Research OS is pre-release research software. No released version is currently supported for production or security-critical use.

## Reporting a vulnerability

Use this repository's private GitHub vulnerability-reporting or security-advisory channel when available. Do not place exploit details, credentials, private data, or unpublished vulnerabilities in a public issue.

If no private channel is visible, open a minimal public issue requesting a private contact method without including sensitive details.

## Scope

Security reports are especially useful for:

- policy or approval bypasses;
- secret, evidence, dataset, or cross-project data exposure;
- unbounded cost or execution paths;
- artifact, event, or revision-integrity failures;
- plugin, Worker, container, or supply-chain escapes;
- unsafe handling of untrusted evidence or model output.

The current system boundary and open mitigations are maintained in the [living threat model](docs/security/threat-model.md).

