# Security Policy

LLM Research OS is pre-release research software. No released version is currently supported for production or security-critical use.

## Reporting a vulnerability

Use this repository's [private vulnerability reporting](https://github.com/victorzhong0110/llm-research-os/security/advisories/new) channel. Do not place exploit details, credentials, private data, or unpublished vulnerabilities in a public issue.

## Scope

Security reports are especially useful for:

- policy or approval bypasses;
- secret, evidence, dataset, or cross-project data exposure;
- unbounded cost or execution paths;
- artifact, event, or revision-integrity failures;
- plugin, Worker, container, or supply-chain escapes;
- unsafe handling of untrusted evidence or model output.

The current system boundary and open mitigations are maintained in the [living threat model](docs/security/threat-model.md).

