# Build performance verification

The audit action caches pip downloads keyed by its pinned tooling requirements,
Python version and runner architecture. It still installs/verifies the tools and
runs the complete installed-package, Grype and CISA policy for every exact image.
No scan results or vulnerability feeds are restored from Actions caches. Release
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
source commit, exact image IDs, feed evidence and raw findings. It runs only for
benchmark changes or manual dispatch. This work does not switch the release
builder: adoption requires repeatable, qualified end-to-end gains across both
architectures. Previous QEMU/native timings do not establish Buildah performance.
