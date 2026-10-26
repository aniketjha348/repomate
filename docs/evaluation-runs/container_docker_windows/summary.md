# Container deployment verification (Docker Desktop on Windows)

**Date:** 2026-10-26  
**Runtime:** Docker Desktop 4.88.1 (237512), Engine 29.7.2, Linux containers  
**Host:** Windows 11; all Docker commands were run from Windows PowerShell with
`docker.exe`. WSL was not used to invoke Docker for this verification.  
**Result:** the Compose images build, the real API runs inside the container,
and repository tests execute under a real `bwrap` boundary with every tested
egress path refused.

This closes the previously recorded `NOT_VERIFIED` item for the
Compose/seccomp container path. It does **not** verify a public cloud
deployment such as Render.

## Images

| Image | ID |
|---|---|
| `deploy-api:latest` | `sha256:7f043b2e2b8a15703b86d35ba6d6bc1dce16f83bbad968839828d144fce43654` |
| `deploy-worker:latest` | `sha256:2d0d957fbab90351ca37c903f093bf778e248d290c40c41793c4d570b5132788` |

Both were rebuilt from the current working tree with
`docker compose -f deploy/compose.yaml up -d --build api worker`.

## Release gates

`docker compose ... run --rm --no-deps --entrypoint python <service>
scripts/verify_egress.py` was executed for both images:

| Gate | Exit | `network_mode` | `backend` | `policy_enforced` | `egress_validation` |
|---|---|---|---|---|---|
| API | 0 | `disabled` | `bwrap` | `true` | `PASSED` |
| Worker | 0 | `disabled` | `bwrap` | `true` | `PASSED` |

The probe's `output_tail` recorded:

- public HTTP — `blocked:OSError`
- public HTTPS — `blocked:gaierror`
- DNS — `blocked:gaierror`
- cloud metadata IPv4 and IPv6 — `blocked:OSError`
- RFC1918 `10/8`, `172.16/12`, `192.168/16` — `blocked:OSError`
- loopback PostgreSQL, Redis and API — `blocked:ConnectionRefusedError`

Raw output: [`gate-api.txt`](gate-api.txt), [`gate-worker.txt`](gate-worker.txt).

## The container had a network; the sandbox removed it

- Control without `bwrap`: `docker run ... deploy-api:latest` reached
  `1.1.1.1:80` and printed `control_reachable`.
  Evidence: [`control-network.txt`](control-network.txt).
- Default Docker seccomp profile (no custom profile): the gate exits **2** with
  `policy_enforced: false`, `egress_validation: FAILED`,
  `bwrap: No permissions to create a new namespace`. This is the fail-closed
  case: the product path returns `NOT_RUN`, never an unisolated test run.
  Evidence: [`gate-default-seccomp.txt`](gate-default-seccomp.txt).

## Adversarial suite inside the container

```text
docker run --rm --security-opt seccomp=D:/repomate/deploy/seccomp-bwrap.json \
  -v D:/repomate/tests:/app/tests:ro \
  --entrypoint python deploy-api:latest -m pytest -q \
  -p no:cacheprovider /app/tests/unit/test_egress_isolation.py
```

**32 passed** in 7.86 s. Evidence:
[`adversarial-tests.txt`](adversarial-tests.txt).

## End-to-end run through the containerized API

- **Run:** `run_20261026-103949_gxr0b2xr`
- **Input:** https://github.com/astanin/python-tabulate/issues/481
- **Pinned commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Status:** `COMPLETED`
- **Planner:** `heuristic-v1` (the Compose environment has no model key)
- **Artifact:** `DOCS_DIFF` touching `README.md`
- **Documents:** `CONTRIBUTION_PLAN.md`
- **Verification receipt:**
  - `patch-path-policy` — `PASSED`
  - `patch-applies-on-pinned-commit` — `PASSED`
  - `sandbox-egress-isolation` — `PASSED`
  - `repository-test-suite` — `PASSED` (366 passed, 17 skipped, twice:
    baseline and patched checkout)
- **Comparison:** `NO_REGRESSION_DETECTED`

Raw record, receipt and downloads:

- [`run.json`](run.json)
- [`receipt.json`](receipt.json)
- [`artifacts.json`](artifacts.json)
- [`documentation.patch`](documentation.patch) (1,393 bytes)
- [`CONTRIBUTION_PLAN.md`](CONTRIBUTION_PLAN.md) (9,007 bytes)
- [`container-run.json`](container-run.json) — condensed machine-readable result
- [`request.json`](request.json), [`health.json`](health.json),
  [`metrics.json`](metrics.json), [`compose-ps.txt`](compose-ps.txt),
  [`docker-version.txt`](docker-version.txt),
  [`bubblewrap-version.txt`](bubblewrap-version.txt),
  [`api-logs.txt`](api-logs.txt)

## Caveats

- This is Docker Desktop's Linux VM on a Windows host, not a public cloud
  runtime. The Render deployment path remains **`NOT_VERIFIED`** because Render
  does not expose a custom seccomp profile.
- The demo API used the deterministic `heuristic-v1` planner because no model
  key was supplied. This is a container/sandbox proof, not a live-model claim.
- The stack was stopped with `docker compose down` after evidence collection;
  named volumes were preserved. The API is not left running.
- Multi-replica fair-use scaling is still unverified; the limiter remains
  per-process.
