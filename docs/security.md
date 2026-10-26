# Security

## Threat model

Users submit GitHub URLs and task text. The system clones third-party
repositories, sends derived context to a model gateway, and produces patches.
Primary risks: SSRF, execution of untrusted repository code, secret leakage,
runaway model/gateway costs, quota exhaustion, malicious patch content.

## Input policy (`safety.url_guard`)

- `https://` only; host must be exactly `github.com`
- no userinfo, explicit port, or fragment
- path shape limited to `/{owner}/{repo}` or `/{owner}/{repo}/issues/{n}`
- pull-request URLs rejected (unsupported input, MVP)
- tracking query params (`utm_*` etc.) stripped; all others rejected

## Network egress (`safety.network`)

All outbound fetches on behalf of a user go through `SafeHttpClient`:

- https only; DNS-resolved addresses must be public — loopback, RFC1918,
  link-local (incl. `169.254.169.254` cloud metadata), CGNAT, reserved and
  multicast ranges are refused **before connecting**
- redirects followed manually, max 3 hops, every hop re-validated against a
  GitHub host allowlist
- response bodies size-capped

The model gateway endpoint is operator-configured (never user-supplied) and
refuses redirects and non-https URLs.

## Execution isolation

Untrusted repository commands run only through the **process sandbox**
(`repomate_core.verification.sandbox`), never bare on the host.

### Network egress: default-deny, fail-closed

Egress is denied by default and enforced at the OS layer, not by environment
variables or Python-level checks (untrusted code can ignore those). On Linux
the command runs inside an unprivileged namespace via `bwrap`:

- `--unshare-net` — no interface but a down loopback. Internet, DNS, private
  addresses, `169.254.169.254` / `fd00:ec2::254` cloud metadata, and loopback
  services (PostgreSQL 5432, Redis 6379, the API on 8000) are all unreachable
- `--unshare-pid` — the sandbox gets its own process table. Without it a
  fresh procfs still enumerated every **host** process (33 on the dev
  machine); with it, only the sandbox's own processes appear
- `--unshare-user-try`, `--unshare-ipc`, `--unshare-uts`,
  `--unshare-cgroup-try`, `--cap-drop ALL` — no shared memory with host
  processes, private hostname, hidden cgroups, no capabilities
- **filesystem**: only read-only system paths (`/usr`, `/bin`, `/sbin`,
  `/lib*`), selected `/etc` files needed by the loader/libc/Python, the
  interpreter, and the repository under test are visible. `/run`, `/var/run`,
  `/tmp`, `/var/tmp` and `/dev/shm` are replaced with empty tmpfs mounts,
  `/proc` and `/dev` are synthesized, and the repository's `.git` directory
  is read-only. `/etc` is **not** bound wholesale, because it can contain
  credentials (git/apt auth, cloud-init, service environment files).

**Fail-closed.** If no enforcing backend exists on the host, the sandbox
**refuses to execute** rather than running with network access; the check is
`NOT_RUN` with the reason. There is no model-facing or user-facing switch to
enable networking. The only way to permit egress is the operator setting
`REPOMATE_SANDBOX_NETWORK=host`, and the receipt then records
`network_mode: host` with `policy_enforced: false`. Unknown fields on the
`POST /api/runs` request are rejected (422), so a caller cannot ask for
network access through an ignored `network`/`egress` field.

**The boundary is verified, not assumed.** `run_egress_probe_check` runs real
connection attempts from inside the sandbox (public HTTP/HTTPS, DNS, cloud
metadata IPv4/IPv6, RFC1918 ranges, loopback Postgres/Redis/API) and passes
only when every one is refused. A receipt may claim
`egress_validation: PASSED` only because that probe executed.

The probe runs with `python -I` in a fresh empty directory. It must not run
from the repository under test: a hostile `sitecustomize.py` or a shadowing
`socket.py` could otherwise fake the verdict and admit the suite with network
access. This is regression-tested.

### Why the filesystem bind set matters

A network namespace does **not** cover unix domain sockets. An early version
of this wrapper used `--dev-bind / /`, which exposed the whole host
filesystem — a hostile test suite connected to a host control socket from
inside the sandbox and drove it (confirmed, then fixed). The narrow bind set
and the masked socket directories are the regression guard, tested in
`tests/unit/test_egress_isolation.py`.

The workspace is writable so repository tests can create fixtures, but
`.git` is bind-mounted read-only. Otherwise a hostile test could edit
`.git/config` to install a smudge/clean filter or `core.fsmonitor`, and the
host-side `git reset --hard` after verification would run it outside the
sandbox.

### Baseline and patched workspaces

Verification never patches the run workspace in place. It resets that
workspace to the pinned commit, creates two independent
`git clone --no-hardlinks` checkouts at the same commit, applies the validated
patch to only one, and runs the selected command in each with the same
sandbox limits and scrubbed environment. Both checkouts are removed after the
receipt data is captured. The receipt's `comparison` block records the base
commit, the patch SHA-256, each run's command, exit code, duration and output
summary, plus the deterministic outcome. `NOT_RUN` on either side makes the
comparison incomplete; it is never inferred from model judgment. A passing
post-patch run is reported as evidence of a selected check passing, not as a
"verified fix".

### Resource limits

- wall-time kill: the child process tree is SIGKILLed on POSIX
  (`killpg`) and via `taskkill /T /F` on Windows
- CPU budget via `RLIMIT_CPU`; memory budget via `RLIMIT_AS`; file-size
  cap via `RLIMIT_FSIZE` (POSIX only — see limitations below)
- environment scrubbing: only PATH/HOME/locale (plus Windows system
  variables such as `SYSTEMROOT`) reach the child — model keys, GitHub
  tokens and database URLs never do (regression-tested)
- stdout/stderr captured and tailed to a fixed size
- permitted toolchains are an explicit allowlist (pytest via RepoMate's
  own interpreter, make); Node toolchains wait for the container backend

### Dependencies

The sandbox has no network, so a repository that must download dependencies
cannot install them. The behaviour is explicit, never a silent
download-enabled run:

1. cached dependencies and prebuilt runtimes already present are used;
2. if the suite runs without network, it runs and the real result is recorded;
3. if a dependency is missing, the check is `NOT_RUN` with the exact missing
   module/requirement and the reason that installing it needs network access —
   never a fabricated pass and never a silent network-enabled run;
4. a controlled package cache/proxy is future work, with narrowly restricted
   routes and no reusable credentials exposed to the sandbox.

### Honest limitations

The sandbox denies egress, masks socket-bearing host paths and narrows the
process table, but it is not a full VM: the host kernel is shared and
`RLIMIT_NPROC` is deliberately unused (it is per-UID and would break the host
session). `bwrap` requires an unprivileged user namespace. Where the kernel or
a container policy forbids it, no backend is available and the sandbox refuses
to execute. Repository tests run with RepoMate's interpreter and installed
dependencies; a repo-specific virtualenv is not created, so a missing
dependency is reported `NOT_RUN` with the module name (the receipt never
records it as a pass).

Windows has no `resource` module and no network namespace, so a Windows host
has no egress-enforcement backend: repository commands are refused unless the
operator explicitly sets `REPOMATE_SANDBOX_NETWORK=host`. The Docker images
install `bubblewrap`, but Docker's default seccomp profile blocks the
namespace syscalls it needs for a non-root process. Run the containers with
`deploy/seccomp-bwrap.json` (the local Compose file already does); it adds
only the namespace/mount syscalls `bwrap` needs, including
`sethostname`/`setdomainname` for the private UTS namespace, and kernel
capability checks still apply. Without that profile the sandbox still fails
closed: repository tests are `NOT_RUN`, not run with network access.

The Compose images were verified on Docker Desktop for Windows (Linux
containers) on 2026-10-26: the API and worker gates passed, the
default-seccomp control failed closed, 32 adversarial tests passed inside the
API image, and a real issue run completed with 366 tests executed under
`bwrap`. See
[`evaluation-runs/container_docker_windows/`](evaluation-runs/container_docker_windows/summary.md).
The Windows host itself remains fail-closed. The baseline/post run inside WSL
and the container gate (including the default-seccomp fail-closed case) are
recorded in [egress-verification.md](egress-verification.md).

RepoMate's own git operations (apply --check, diff, reset) run on its private
clone with bounded timeouts, `GIT_TERMINAL_PROMPT=0`, and a read-only `.git`
inside the sandbox so sandboxed code cannot poison those operations.

## Secrets

- `OLLAMA_API_KEY` and
  `GITHUB_TOKEN` live in server-side environment
  variables only; they are never returned by any API route, never written
  into run records/events, and redacted from git error paths
- `GET /api/health` reports only *whether* a model is configured, never the key
- errors returned to clients are typed codes and messages — no stack traces

## Bounded runs

- wall-clock budget per run (`REPOMATE_MAX_RUN_SECONDS`), checked between stages
- Celery backstop: a soft task time limit equal to the run budget finalises the
  run `FAILED`/`TIMEOUT`, and a hard limit kills a wedged worker child
- evidence-retrieval budgets (`REPOMATE_RETRIEVAL_*`): files examined, bytes
  per file, total bytes, matching search results and wall-clock; a hit stops
  retrieval and records `PARTIAL` with the exact work left unexamined
- model budget (`REPOMATE_MODEL_*`): per-run call and token caps, enforced
  before each call. A gateway that omits `usage` is charged a conservative
  estimate and the run record labels the source `estimated` or `mixed`
- bounded model tool loop (`REPOMATE_TOOL_*`): only the typed, read-only
  `search_text`, `read_file` and `inspect_manifest` tools; global caps on tool
  calls, bytes and wall-clock. Every retrieved file item is re-read from the
  pinned workspace and its snippet rebuilt by deterministic evidence
  validation, so a fabricated path, line range or snippet is rejected rather
  than cited. A global cap hit ends the run as `PARTIAL` with the remaining
  work
- subprocess timeouts on every git invocation (120s; clone 300s)
- model calls: hard timeout, ≤2 retries (429/5xx only), capped backoff
- patch size cap (2000 lines) and max 5 planned changes per plan
- cooperative cancellation marker checked between stages
- workspace cleanup on every terminal path (unless
  `REPOMATE_KEEP_WORKSPACE=1`), plus a startup sweep for stale workspaces

## Fair-use admission

`POST /api/runs` is admitted through `services/api/fair_use.py`:

- a per-client sliding window (`REPOMATE_RATE_LIMIT_REQUESTS` per
  `REPOMATE_RATE_LIMIT_WINDOW_SECONDS`) returns a typed `429 RATE_LIMITED`
  with `Retry-After`
- a global cap on `PENDING`+`RUNNING` runs (`REPOMATE_MAX_CONCURRENT_RUNS`)
  rejects new work rather than queueing it without bound; short in-process
  reservations cover the gap between the check and saving the run record
- `X-Forwarded-For` is trusted only when the socket peer matches
  `REPOMATE_TRUSTED_PROXIES`, and is walked right-to-left; with no configured
  proxy the peer address is the client identity

The sliding window and reservations are per API process.
Multiple replicas share the persisted active-run count but can still admit
concurrently, and each replica maintains its own request window. A shared
limiter (Redis) is required before horizontally scaling the API under hostile
traffic. Metrics at `GET /api/metrics` are aggregate-only: status/planner
counts and active/max/admitted/rate-limited/concurrency-limited counters.
They do not include run identifiers, prompts, environment contents or
filesystem paths.

## Patch integrity (`artifacts.patch`)

- diff paths parsed from `+++ b/` headers; traversal (`..`) and absolute paths rejected
- allow/deny path policy per artifact kind — the docs policy admits
  `README*`, `*.md`, `*.rst`, `docs/**` only; CI (`.github/**`), lockfiles,
  secrets-like files (`**/.env*`, `**/*.pem`, `**/*.key`) are always denied
- patches are generated against a clean snapshot, checked with
  `git apply --check`, and applied only to a separate patched checkout used
  for the post-patch verification run

## Rate-limit handling

Unauthenticated GitHub REST access is limited (60 req/h per source IP).
`repository.github.fetch_issue` inspects `X-RateLimit-*`, waits at most
once (≤30s), retries once, then surfaces a typed `RATE_LIMITED` error.
An optional `GITHUB_TOKEN` raises the ceiling.

## Licensing honesty

License status (RECOGNIZED + SPDX id / UNKNOWN / ABSENT) is detected during
snapshot pinning, displayed in run output, and non-RECOGNIZED statuses are
injected into plan limitations. A public repository is not automatically an
openly-licensed one; PS04 demonstrations must use clearly licensed targets.
