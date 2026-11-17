# Security and legacy CPU qualification follow-up

Follow-up to #273 and #280. Production NumPy caps, default images, vulnerability
policy and deployments are unchanged.
Work started November 17 and continued November 18 (Europe/Stockholm); evidence
timestamps are recorded in UTC.

## DHI refresh

The Python 3.11 Debian 13 builder tag now resolves to
`sha256:a4ccb5b75d709d9a23b2576cec305412f9852ccb9a461859a4e2c109ac8587f3`.
All four optional DHI Dockerfiles select this same immutable index. The runtime
tag still resolves to the existing
`sha256:1bb857892e25f7df5c34a6bd5f8695a450e85c8ab8511c02f98ad9282943435e`.
A builder refresh alone does not resolve runtime findings.

Local Docker-key VEX verification passes for both bases and architectures; all
four attestations require the documented missing-public-log-entry fallback, so
transparency-log inclusion is not established. Builder VEX retains 16 unresolved
statements across five CVEs; runtime VEX retains two unresolved CVEs.

All four native AMD64 service startup/owned-volume checks and audits of those
exact image IDs pass. Each image has 192 raw scanner matches, no installed-Python
advisories and no findings blocked by the existing KEV/available-Debian-fix policy.
[Machine-readable evidence](security-qualification-2026-11-17.json) records image
IDs, VEX hashes, scanner/feed metadata and raw report hashes.
[Run 44192794291](https://github.com/murre87/energywizard/actions/runs/44192794291)
passes signatures and all eight native AMD64/ARM64 runtime/image audits at
`305ed40`; all eight scans retain 192 raw matches. Downloaded evidence archives
match GitHub's SHA256 digests. Vendor
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

The new OpenBLAS library is source-installed rather than Debian-managed. The
image policy does not establish complete scanner coverage of that library;
production adoption also needs explicit component inventory/provenance and a
maintained security-update path for it.
An OSV query for the upstream release commit on November 18 (Stockholm) returns
no known advisories; this is dated database evidence, not complete coverage.

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

71 focused tooling/policy tests pass. The locally built NumPy 2.4.6/OpenBLAS
0.3.34 image passes all three strict legacy profiles, including the original
`qemu64` rejection case. Every profile passes Python and capped controls and
reproduces the upstream-wheel CPU rejection. The new image also passes native
numerical smoke, dependency integrity and the existing image security policy.

Local native AMD64 candidate/capped median ratios are 1.00 matrix multiply,
0.97 solve, 1.00 FFT, 1.04 pandas and 0.97 scikit-learn. These five warmed samples
per workload range from 0.97 to 1.04 on this host; they are not a
physical legacy CPU benchmark or a universal performance guarantee.

[Run 44192794372](https://github.com/murre87/energywizard/actions/runs/44192794372)
passes all nine evaluation jobs at `305ed40`, including the new candidate's three
strict legacy profiles and both native numerical/performance/image-audit jobs.
The scanned image IDs match the numerical reports. Both candidate image scans
retain 252 raw matches, with no Python advisories or policy-blocking findings.
All downloaded artifact archives match GitHub's SHA256 digests.

| Workload | AMD64 candidate/capped | ARM64 candidate/capped |
|---|---:|---:|
| Matrix multiply | 1.01 | 1.00 |
| Linear solve | 0.94 | 1.04 |
| FFT | 0.98 | 1.00 |
| pandas grouping | 0.99 | 1.07 |
| scikit-learn fit | 0.97 | 1.01 |

Each ratio compares stacks on the same native runner, using the existing five
warmed samples and two-CPU/2-GiB limits. These are measured results, not a new
performance acceptance threshold. Both standard application CI runs also pass;
they continue testing the unchanged production NumPy requirements.

Neither issue is considered resolved by adding a candidate or refreshing a
digest. #273 retains the recorded vendor investigations/unreleased OpenSSL
fixes. #280 retains physical older-CPU and full application-image adoption
requirements; the production cap is unchanged.
