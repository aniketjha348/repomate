#!/usr/bin/env python3
"""Release gate: prove the verification sandbox's egress boundary is real.

Run this on the host/container that will execute untrusted repository code.
It performs live connection attempts from inside the sandbox (public HTTP/
HTTPS, DNS, cloud metadata IPv4/IPv6, private ranges, loopback PostgreSQL/
Redis/API) and exits non-zero unless every one is refused and the policy is
recorded as enforced.

Exit codes:
  0  boundary verified (network_mode=disabled, policy_enforced=true)
  2  no enforcing backend, host mode, or an unverified/failed boundary
  3  the probe ran but returned an unexpected result
"""

from __future__ import annotations

import json
import platform

from repomate_core.contracts import VerificationStatus
from repomate_core.verification.network_policy import (
    NetworkMode,
    network_policy_record,
    resolve_network_policy,
)
from repomate_core.verification.sandbox import (
    run_egress_probe_check,
    sandbox_environment_description,
)


def main() -> int:
    policy = resolve_network_policy()
    if policy.mode is NetworkMode.HOST:
        print(
            json.dumps(
                {
                    "sandbox": network_policy_record(
                        policy,
                        egress_validation="NOT_RUN",
                        egress_detail=(
                            "REPOMATE_SANDBOX_NETWORK=host permits egress; "
                            "isolation was not validated"
                        ),
                    ),
                    "checks": [],
                },
                indent=2,
            )
        )
        return 2

    check = run_egress_probe_check(policy=policy)
    receipt = {
        "sandbox": network_policy_record(
            policy,
            egress_validation=check.status.value,
            egress_detail=check.reason,
        ),
        "environment": sandbox_environment_description(policy),
        "host": f"{platform.system()}/{platform.machine()}",
        "checks": [check.model_dump(mode="json")],
    }
    print(json.dumps(receipt, indent=2, default=str))

    if check.status is VerificationStatus.PASSED and receipt["sandbox"]["policy_enforced"]:
        return 0
    if check.status in (VerificationStatus.FAILED, VerificationStatus.NOT_RUN):
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
