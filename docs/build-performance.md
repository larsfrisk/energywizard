# Build performance verification

The audit action installs its pinned tooling requirements in one pip invocation,
then runs the complete installed-package, Grype and CISA policy for every exact
image. A persistent pip download cache was tested but not retained: paired native
installs saved about 1–2 seconds, while observed Actions restore/setup overhead
was 2.9–5.2 seconds. Pip-only savings are not a demonstrated whole-job improvement.
Only Grype's downloaded database is restored, keyed by pinned audit implementation,
runner architecture and day. Before every image, an explicit online `grype db update`
must succeed; a network failure blocks the job. The complete image scan then still
validates database status and obtains current CISA evidence. Reports/inventories
are never cached. Release
`pull`/`no-cache`, daily security builds and publication gates remain unchanged.

`build-benchmarks.yml` measures two fresh virtual environments per cold/warm pip
cache pair, twice on native AMD64 and ARM64. It rejects changed dependency
inventories instead of interpreting different resolutions as a speed improvement.

The image benchmark compares pinned BuildKit and Buildah images on the same
runner for each of five image contexts and both native architectures. It runs two
counterbalanced repeats, each with isolated builder storage and cold/warm trials.
Both trials use pull and no-cache: warm means already downloaded base/builder
state, not reuse of finished apt/dependency layers. This reflects the release
freshness requirement rather than an unsafe best-case layer-cache benchmark.

Each trial records setup, combined build/export, Docker import, isolated startup
and complete image audit time. BuildKit combines build/export, so these stages are
compared together for both builders. Every image must match the checked-out source
and the first trial's OS/Python inventories. Mismatches, failed scans and startup
failures are rejected; partial findings and timings remain in uploaded artifacts.
Each builder/repeat has its own scanner cache: cold audits download their own
feeds, warm audits reuse only that pair's cache and still validate/update feeds.
Sharing one cache across builders would bias the first builder's total. One-time
tool image preparation is recorded separately from per-image trial totals.
Buildah uses a privileged container with dedicated overlay storage on disposable
GitHub runners; fork PRs cannot run that job. Nothing is pushed or deployed.

The workflow records tool versions, immutable tool images, runner CPU count,
source commit, exact image IDs, feed evidence and raw findings. After the initial
qualification run it is manual-only, so PR updates do not repeatedly launch the
80-trial matrix. This work does not switch the release
builder: adoption requires repeatable, qualified end-to-end gains across both
architectures. Previous QEMU/native timings do not establish Buildah performance.

## Measured results, 2026-11-17

[Controlled run](https://github.com/murre87/energywizard/actions/runs/44053159806) at `cc3be9456cd11671683aa573d026007c07b278eb`: all 80 trials qualified. Downloaded artifact hashes, exact image IDs, valid Grype databases, Python findings, CISA evidence hashes and identical source/package fingerprints were independently checked. Raw reports remain in run artifacts; [durable measurements](build-performance-results-2026-11-17.json) record artifact digests and tool versions.

Median seconds include build/export, import, startup and complete audit; two counterbalanced repeats per cell. One-time tool preparation is recorded separately in the measurements.

| Native context | Cold BuildKit | Cold Buildah | Warm BuildKit | Warm Buildah |
|---|---:|---:|---:|---:|
| amd64/ewapp | 74.6 | 72.2 | 29.1 | 27.9 |
| amd64/ha-addon/smartbox | 110.1 | 111.0 | 62.7 | 67.0 |
| amd64/smartbox | 88.7 | 87.6 | 39.9 | 42.6 |
| amd64/telemetry-collector | 62.0 | 61.0 | 14.7 | 16.2 |
| amd64/webdashboard | 81.0 | 83.8 | 34.0 | 39.5 |
| arm64/ewapp | 146.1 | 147.4 | 41.3 | 44.5 |
| arm64/ha-addon/smartbox | 188.0 | 194.5 | 84.1 | 94.5 |
| arm64/smartbox | 163.3 | 166.9 | 54.3 | 64.9 |
| arm64/telemetry-collector | 126.8 | 131.8 | 22.8 | 27.0 |
| arm64/webdashboard | 143.2 | 143.7 | 39.6 | 41.9 |

**Decision: retain BuildKit.** Results vary across contexts and architectures; two repeats do not establish a general Buildah improvement. No release builder was changed.

The pinned Grype online-update probe took 26.542 seconds with an empty cache and 0.667 seconds with a current cache. With networking disabled, an explicit update failed even with that current cache, confirming the refresh gate fails closed. These are scanner-update timings, not a claimed whole-workflow speedup. Native pip-cache trials saved 1.09 seconds on AMD64 and 1.82 seconds on ARM64, less than observed remote cache overhead; persistent pip caching was rejected.
