# GitHub throttling maps to a typed RATE_LIMITED error

- **Case:** `github_rate_limit_injected`
- **Repository:** `astanin/python-tabulate`
- **Input:** https://github.com/astanin/python-tabulate/issues/481
- **Upstream commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Prepared commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Planner observed:** `none`
- **Status:** `FAILED`
- **Expected:** FAILED with ErrorCode.RATE_LIMITED and no artifact
- **Verdict:** PASS — FAILED with RATE_LIMITED; injection labelled in provenance

## Fault injection

The GitHub issue fetch was replaced with a typed `RateLimitedError`. This is not evidence that the live quota was exhausted.

## Error

- **Code:** `RATE_LIMITED`
- **Message:** injected GitHub rate-limit response (evaluation only)

## Provenance

- Case workspace: `var/eval-real/cases/github_rate_limit_injected`
- Elapsed: 0.18s
- Sandbox backend: `bwrap`
- Planner requested: `none`

## Notes

The GitHub issue fetch is replaced with a RateLimitedError. The repository clone and snapshot are real; the quota exhaustion is an explicit fault injection.
