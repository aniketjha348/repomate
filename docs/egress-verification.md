# Egress isolation verification

**Date:** 2026-10-26  
**Result:** verified on Linux (WSL2) and inside the Docker Compose runtime on
Docker Desktop for Windows. The Windows *host* remains fail-closed because it
has no egress-enforcement backend; the Linux containers do have a real `bwrap`
boundary.

This page records actual commands and observed output from the baseline and
post-patch runs. It is evidence, not a design claim. Re-run the release gate on
the deployment host before exposing a public service.

## What was tested

The same hostile repository was executed through the real verification path
(`run_test_suite_check` and `run_verification`) against two checkouts:

| | |
|---|---|
| Baseline | commit `108c56f`, exported with `git archive` to `/mnt/d/repomate-baseline-linux` |
| Post-patch | the same commit plus the uncommitted working-tree changes under test (`/mnt/d/repomate`) |

The hostile pytest suite attempted real connections to public HTTP/HTTPS, DNS,
cloud metadata (`169.254.169.254`), RFC1918 addresses, and loopback PostgreSQL
(5432), Redis (6379) and the API (8000); the release probe additionally tests
the IPv6 metadata endpoint. It also
recorded any environment variables whose names looked like credentials. The
suite's own assertion is that public egress is blocked, so it *passes* only
when isolation is real.

The comparison harness used for the baseline/post run was a version-agnostic
wrapper around the same hostile scenario committed in
`tests/integration/test_egress_isolation_pipeline.py`, with public HTTPS added;
it was kept in the gitignored `var/` directory. Raw JSON outputs from this run
are also in `var/` and are not committed.

## Environment

| | |
|---|---|
| Host | Windows 11, WSL2 |
| Linux distribution | Ubuntu 26.04 LTS |
| Kernel | `6.18.33.2-microsoft-standard-WSL2` |
| bubblewrap | 0.11.1 (`/usr/bin/bwrap`, unprivileged) |
| Python (WSL suite) | 3.14.4, `/home/aniket/.venvs/repomate-egress` |
| Container runtime | Docker Desktop, Linux containers |
| Container image | `python:3.12-slim`, bubblewrap 0.12.0 |

## Baseline: network was reachable

Command (WSL):

```bash
cd /mnt/d/repomate
/home/aniket/.venvs/repomate-egress/bin/python \
  var/egress_comparison_harness.py \
  --repo /mnt/d/repomate-baseline-linux \
  --output var/egress-baseline.json
# exit 1: the hostile suite correctly failed because egress was not blocked
```

Observed hostile-suite findings:

| Target | Result |
|---|---|
| Public HTTP `1.1.1.1:80` | **reachable** |
| Public HTTPS `https://example.com` | **reachable** |
| DNS `example.com` | **reachable** |
| Loopback Redis `127.0.0.1:6379` | **reachable** |
| Cloud metadata `169.254.169.254:80` | `blocked:TimeoutError` |
| RFC1918 `10.0.0.1`, `172.16.0.1`, `192.168.0.1` | `blocked:TimeoutError` |
| Loopback PostgreSQL `127.0.0.1:5432` | `blocked:ConnectionRefusedError` |
| Loopback API `127.0.0.1:8000` | `blocked:ConnectionRefusedError` |
| Credential-shaped environment variables | none visible |

The baseline receipt had **no sandbox policy at all** (`"sandbox": null`), and
the repository test suite was `FAILED` because its assertion that public egress
is blocked did not hold. Public HTTP, HTTPS and DNS succeeded; the private and
metadata targets timed out rather than being refused. This is the negative
control: the old code can reach the network and a host service, and it does not
record a network policy.

Credential-shaped environment variables were already scrubbed in the baseline,
so this comparison does not show a secret-leak regression. Secret removal is
covered separately by the adversarial tests, which inject live-looking keys and
assert that neither the names nor the values reach the child.

## Post-patch: every tested egress path was refused

Command (WSL):

```bash
cd /mnt/d/repomate
/home/aniket/.venvs/repomate-egress/bin/python \
  var/egress_comparison_harness.py \
  --repo /mnt/d/repomate \
  --output var/egress-post.json
# exit 0
```

Observed hostile-suite findings:

| Target | Result |
|---|---|
| Public HTTP `1.1.1.1:80` | `blocked:OSError` |
| Public HTTPS `https://example.com` | `blocked:URLError` |
| DNS `example.com` | `blocked:gaierror` |
| Cloud metadata `169.254.169.254:80` | `blocked:OSError` |
| RFC1918 `10.0.0.1`, `172.16.0.1`, `192.168.0.1` | `blocked:OSError` |
| Loopback PostgreSQL `127.0.0.1:5432` | `blocked:ConnectionRefusedError` |
| Loopback Redis `127.0.0.1:6379` | `blocked:ConnectionRefusedError` |
| Loopback API `127.0.0.1:8000` | `blocked:ConnectionRefusedError` |
| Credential-shaped environment variables | none visible |

The suite status was `PASSED`. The receipt recorded:

```json
{
  "sandbox": {
    "network_mode": "disabled",
    "backend": "bwrap",
    "policy_enforced": true,
    "egress_validation": "PASSED",
    "egress_detail": "every egress attempt from inside the sandbox was refused"
  },
  "checks": [
    {"name": "sandbox-egress-isolation", "status": "PASSED", "reason": "every egress attempt from inside the sandbox was refused"},
    {"name": "repository-test-suite", "status": "PASSED", "reason": ""}
  ]
}
```

The receipt's overall status was `FAILED` only because the harness submitted an
empty patch (`patch touches no files`); the two security-relevant checks,
`sandbox-egress-isolation` and `repository-test-suite`, both passed.

## Release gate: WSL

`scripts/verify_egress.py` runs the live probe and exits non-zero unless the
boundary is proven:

```bash
cd /mnt/d/repomate
/home/aniket/.venvs/repomate-egress/bin/python scripts/verify_egress.py
# exit 0
```

Observed output:

```json
{
  "sandbox": {
    "network_mode": "disabled",
    "backend": "bwrap",
    "policy_enforced": true,
    "egress_validation": "PASSED",
    "egress_detail": "every egress attempt from inside the sandbox was refused"
  },
  "environment": "process sandbox (wall-time, CPU and memory limits, scrubbed env; network egress denied (bwrap))",
  "host": "Linux/x86_64"
}
```

The probe's own `output_tail` showed `blocked:OSError` for public HTTP, cloud
metadata IPv4/IPv6 and all three RFC1918 ranges; `blocked:ConnectionRefusedError`
for loopback PostgreSQL, Redis and the API; and `blocked:gaierror` for public
HTTPS and DNS.

## Release gate: Docker Compose runtime

The API and worker images install `bubblewrap`, copy `scripts/verify_egress.py`
into `/app/scripts/`, and Compose applies `deploy/seccomp-bwrap.json`. The gate
was run through Compose, not just `docker run`, so the documented command and
the relative seccomp profile path were both exercised:

```bash
docker compose -f deploy/compose.yaml run --rm --no-deps \
  --entrypoint python api scripts/verify_egress.py
# exit 0
```

Observed output: the same `sandbox` block as the WSL gate
(`network_mode: disabled`, `backend: bwrap`, `policy_enforced: true`,
`egress_validation: PASSED`), with every probe target blocked. The worker
image, built from `deploy/Dockerfile.worker`, was also run with the same
profile and gate; it exited `0` with the same `PASSED` record.

### The container really had a network

To prove the block comes from the sandbox rather than from the container having
no connectivity, the same API image was run without `bwrap`:

```bash
docker run --rm --entrypoint python repomate-api-egress-check \
  -c "import socket; s=socket.create_connection(('1.1.1.1',80),3); print('control_reachable'); s.close()"
# exit 0, prints: control_reachable
```

### Default seccomp fails closed

Without the custom profile, `bwrap` cannot create its namespace:

```bash
docker run --rm --entrypoint python repomate-api-egress-check \
  scripts/verify_egress.py
# exit 2
```

Observed:

```json
{
  "sandbox": {
    "network_mode": "disabled",
    "backend": "bwrap",
    "policy_enforced": false,
    "egress_validation": "FAILED",
    "egress_detail": "egress probe produced no verdict (exit 1): bwrap: No permissions to create a new namespace, ..."
  }
}
```

In the product path this is fail-closed: `run_test_suite_check` returns
`NOT_RUN` and does not execute the repository suite, rather than running it
with network access. The standalone gate reports `FAILED` because the probe
itself could not run.

### Profile fix found during this run

The first custom-seccomp attempt got past namespace creation but failed with:

```text
bwrap: Can't set hostname to repomate-sandbox: Operation not permitted
```

Docker's default seccomp profile allows `sethostname`/`setdomainname` only with
`CAP_SYS_ADMIN`, and the container runs as a non-root user. The profile now
allows those two syscalls for the private UTS namespace that `bwrap` creates;
kernel capability checks still apply. After that change the Compose gate
passed. The API and worker images also now copy the gate script into the image,
because the documented `exec api python scripts/verify_egress.py` command
would otherwise have no script to run.

## Re-verification on Docker Desktop for Windows (2026-10-26)

This run used Windows PowerShell with `docker.exe` for every Docker command;
WSL was not used to invoke Docker. Docker Desktop 4.88.1 (Engine 29.7.2) ran
Linux containers, and both images were rebuilt from the current working tree.

| Check | Observed | Evidence |
|---|---|---|
| API release gate through Compose | exit 0; `bwrap`, `policy_enforced=true`, `egress_validation=PASSED` | [`gate-api.txt`](evaluation-runs/container_docker_windows/gate-api.txt) |
| Worker release gate through Compose | exit 0; same `PASSED` record | [`gate-worker.txt`](evaluation-runs/container_docker_windows/gate-worker.txt) |
| Control without `bwrap` | `control_reachable` to `1.1.1.1:80` | [`control-network.txt`](evaluation-runs/container_docker_windows/control-network.txt) |
| Default Docker seccomp | exit 2; `policy_enforced=false`, `egress_validation=FAILED` | [`gate-default-seccomp.txt`](evaluation-runs/container_docker_windows/gate-default-seccomp.txt) |
| Adversarial suite in API image | 32 passed in 7.86 s | [`adversarial-tests.txt`](evaluation-runs/container_docker_windows/adversarial-tests.txt) |
| End-to-end issue run | `COMPLETED`, `DOCS_DIFF`, `CONTRIBUTION_PLAN.md`, suite `PASSED` (366 passed / 17 skipped, baseline and patched) | [`container-run.json`](evaluation-runs/container_docker_windows/container-run.json) |

The end-to-end run was `run_20261026-103949_gxr0b2xr` for
https://github.com/astanin/python-tabulate/issues/481 at pinned commit
`268615a5c27dc40e5c22454c07b44d5c50410da0`. Its receipt records
`sandbox-egress-isolation: PASSED` and `repository-test-suite: PASSED`, with
the 366-test suite executed once in a clean baseline checkout and once in a
patched checkout. Full raw evidence:
[`evaluation-runs/container_docker_windows/`](evaluation-runs/container_docker_windows/summary.md).

This proves the Compose images on Docker Desktop's Linux VM. It does not prove
Render or any runtime that cannot apply the custom seccomp profile.

## Test suites

| Environment | Command | Result |
|---|---|---|
| WSL2 (real `bwrap` boundary) | `python -m pytest -q` | **358 passed, 1 deselected** |
| Docker API image + custom seccomp | `pytest tests/unit/test_egress_isolation.py` (tests mounted read-only) | **32 passed** |
| Windows (no network namespace) | `python -m pytest -q` in a `[dev]` venv | **307 passed, 51 skipped, 1 deselected** |

The container run used the same adversarial unit tests against an API image
built from the same Dockerfile and the same seccomp profile as the gate:

```bash
docker run --rm --security-opt seccomp=D:/repomate/deploy/seccomp-bwrap.json \
  -v D:/repomate/tests:/app/tests:ro \
  --entrypoint python repomate-api-egress-check \
  -m pytest -q tests/unit/test_egress_isolation.py
# 32 passed
```

Its first run found a non-egress edge case: when `cwd` has no `.git`,
`build_sandbox_argv` tried to synthesize a `.git` mount inside a root-owned
`/app` and failed with `bwrap: Can't create file /app/.git: Permission
denied`. The helper now returns no `.git` mount when there is no git metadata
to protect; the retest passed. This does not affect repository workspaces
(which always have `.git`) but removes a startup failure for arbitrary
directories.

The WSL run includes the adversarial unit and integration tests
(`tests/unit/test_egress_isolation.py`,
`tests/integration/test_egress_isolation_pipeline.py`). They execute real
connection attempts against the real sandbox, including:

- public HTTP/HTTPS, DNS, cloud metadata IPv4/IPv6, RFC1918, and loopback
  PostgreSQL/Redis/API;
- a negative control proving the same probe reaches the network when the
  wrapper is removed;
- a probe-shim test proving a repository cannot fake the verdict with a
  hostile `sitecustomize.py` or a shadowing `socket.py`;
- `.git` read-only enforcement;
- install / build commands running under the same policy;
- missing dependencies producing `NOT_RUN` with the missing module name;
- the API rejecting `network`/`egress` override fields with 422.

Most of the 51 Windows skips are the live-boundary tests, which are `skipif`
POSIX or `skipif` no backend; one is the POSIX-only `RLIMIT_AS` test. They are
not silently treated as passes: the Windows product behavior is separately
asserted by `test_missing_backend_refuses_to_execute`, which checks that a
repository command is refused rather than run without a boundary.

## What this does and does not prove

**Proven on this host/runtime:**

- OS-level egress denial: public network, DNS, cloud metadata, private ranges
  and loopback control services are unreachable from inside the sandbox;
- the receipt cannot claim `egress_validation: PASSED` unless the live probe
  actually ran and passed;
- the same policy applies to repository tests and install/build commands;
- the Docker custom seccomp profile lets `bwrap` work while the container
  itself still has egress, so the block is the sandbox boundary;
- without that profile the sandbox refuses to execute (`NOT_RUN`), never
  silently falls back to network access.

**Not proven / remaining limits:**

- `bwrap` is not a VM. The host kernel is shared; a kernel vulnerability or a
  future namespace bug is out of scope for this control.
- Runtimes that cannot apply the custom seccomp profile (for example, the
  Render Docker path documented in `docs/deployment.md`) will fail closed:
  `bwrap` may be unable to create namespaces and repository suites will be
  `NOT_RUN`. Do not set `REPOMATE_SANDBOX_NETWORK=host` to make them run.
- Dependency installation that needs the network is not silently enabled; it
  is reported `NOT_RUN` with the missing requirement. A controlled package
  cache/proxy is future work.
- Windows has no egress-enforcement backend; repository commands are refused
  unless the operator explicitly chooses host mode, which is recorded as
  `policy_enforced: false`.
- Only WSL2 and Docker Desktop were exercised here. Run
  `python scripts/verify_egress.py` and the adversarial suite on the actual
  deployment host before exposure.

## Reproduce

```bash
# WSL/Linux host with bwrap and unprivileged user namespaces
cd /path/to/repomate
python scripts/verify_egress.py                 # must exit 0
python -m pytest -q tests/unit/test_egress_isolation.py \
  tests/integration/test_egress_isolation_pipeline.py

# Docker Compose
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml run --rm --no-deps \
  --entrypoint python api scripts/verify_egress.py
```

## Implementation references

- `packages/repomate_core/verification/network_policy.py` — bwrap policy,
  mount set, probe, receipt record
- `packages/repomate_core/verification/sandbox.py` — refusal before execution,
  probe before every run, `NOT_RUN` on missing dependencies
- `packages/repomate_core/verification/runner.py` — records the probe verdict
  in the receipt
- `scripts/verify_egress.py` — release gate
- `deploy/seccomp-bwrap.json` — Docker profile used by Compose
- `deploy/Dockerfile.api`, `deploy/Dockerfile.worker` — install `bubblewrap`,
  copy the gate script
