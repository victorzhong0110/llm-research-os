# Packaged offline demonstration corpus

This directory ships inside the wheel so `researchos workspace demo` has a real
corpus to run from an installed package, with no source checkout, no model key,
no GPU, and no Node.

It is the smallest complete M1 research chain: one workflow spec, a Mock
provider fixture, a generated proposal, a question, a dissent, both decisions, a
plan authorization, and a simulation request. Every step is local and
deterministic; nothing here contacts a provider, a Worker, or a remote host.

The demonstration copies this directory to a temporary location before running,
so running it can never mutate the installed artifact.
