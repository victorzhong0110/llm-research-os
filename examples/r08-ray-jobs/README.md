# Finite Ray Jobs integration example

Run [the compute-host instructions](../../extras/ray-jobs/README.md).
`probe.py` executes the real Ray adapter, not a simulated job. The designated
Linux Ray CI job is the CPU integration gate. CUDA needs an actual authorized
CUDA/PyTorch host and is not exercised by CPU CI.

The valid/invalid logs here are parser fixtures, not execution evidence. The
valid CPU result has the fixed sum-of-squares value 85344; the invalid log lacks
a compute marker, so a successful vendor status alone must refuse it. The
resource-probe bridge uses Ray's existing vendor API and has no new public
ResearchOS JSON task or launch credential.
