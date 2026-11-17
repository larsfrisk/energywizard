# Security and legacy CPU qualification follow-up

Follow-up to #273 and #280. Production NumPy caps, default images, vulnerability
policy and deployments are unchanged.

## DHI refresh

The Python 3.11 Debian 13 builder tag now resolves to
`sha256:a4ccb5b75d709d9a23b2576cec305412f9852ccb9a461859a4e2c109ac8587f3`.
All four optional DHI Dockerfiles select this same immutable index. The runtime
tag still resolves to the existing
`sha256:1bb857892e25f7df5c34a6bd5f8695a450e85c8ab8511c02f98ad9282943435e`.
A builder refresh alone does not resolve runtime findings.

Docker-key VEX verification, native AMD64/ARM64 service startup, owned-volume
checks and audits of the exact tested images remain required. Vendor
`under_investigation` statements remain unresolved; no exemptions are added.
The [OpenSSL November 10 advisory](https://openssl-library.org/news/secadv/20261110.txt)
still schedules releases containing the five previously recorded Low fixes for
December 1. No claim of CVE-free images or completed vendor resolution is made.

## Current OpenBLAS experiment

[OpenBLAS 0.3.34](https://github.com/OpenMathLib/OpenBLAS/releases/tag/v0.3.34)
includes autodetection support for QEMU's Opteron-like CPUID. The separate
`candidate-openblas-current` evaluation target builds the SHA256-pinned upstream
release and NumPy 2.4.6 with `cpu-baseline=none`, explicit BLAS/LAPACK selection
and dynamic OpenBLAS architecture dispatch. It sets no CPU/kernel override.
The earlier Debian OpenBLAS experiment and its recorded rejection are retained.

The new candidate must pass the original `qemu64`, Intel-v1 and AMD-with-3DNow
controls strictly. It cannot use experimental CPU-rejection recording. QEMU
here emulates legacy x86 instruction sets only; architecture performance and
image audits use native AMD64 and ARM64 runners. These tests do not replace
physical older-CPU acceptance or complete application-image qualification.

A Dockerfile-specific context allowlist restores the numerical probe files
excluded by the newer root UI build context. Production contexts are unchanged.

Fresh PyPI/OSV queries on November 17 report Python >=3.11 and no known OSV
advisories for NumPy 2.3.5 and 2.4.6. The November 17 CISA catalog contains 1,782
entries and no matches for the ten previously recorded DHI investigation/OpenSSL
IDs. These are dated query results, not security-support or exploitability
guarantees. The existing daily image gate remains authoritative for releases.

## Validation checkpoint

57 focused tooling/policy tests pass. Source-build execution and refreshed
signature/runtime/image-audit results are pending at this checkpoint. Neither
issue is considered resolved by adding a candidate or refreshing a digest.
