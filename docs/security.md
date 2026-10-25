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

**Untrusted repository commands never run on the API host.** Today that means
the repository test suite is reported `NOT_RUN` with an explicit reason — an
honest gap, not a hidden one. Phase 4 introduces a disposable sandbox with
CPU/memory/disk/wall-time limits; the git operations RepoMate itself performs
(apply --check, diff, reset) operate on its own clone with bounded timeouts
and `GIT_TERMINAL_PROMPT=0` so git can never hang on credentials.

## Secrets

- `VYCE_API_KEY` and `GITHUB_TOKEN` live in server-side environment
  variables only; they are never returned by any API route, never written
  into run records/events, and redacted from git error paths
- `GET /api/health` reports only *whether* a model is configured, never the key
- errors returned to clients are typed codes and messages — no stack traces

## Bounded runs

- wall-clock budget per run (`REPOMATE_MAX_RUN_SECONDS`), checked between stages
- subprocess timeouts on every git invocation (120s; clone 300s)
- model calls: hard timeout, ≤2 retries (429/5xx only), capped backoff
- patch size cap (2000 lines) and max 5 planned changes per plan
- cooperative cancellation marker checked between stages

## Patch integrity (`artifacts.patch`)

- diff paths parsed from `+++ b/` headers; traversal (`..`) and absolute paths rejected
- allow/deny path policy per artifact kind — the docs policy admits
  `README*`, `*.md`, `*.rst`, `docs/**` only; CI (`.github/**`), lockfiles,
  secrets-like files (`**/.env*`, `**/*.pem`, `**/*.key`) are always denied
- patches are generated against a clean snapshot and verified with
  `git apply --check` on a reset tree

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
