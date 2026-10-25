"""Verification: real checks with honest receipts."""

from repomate_core.verification.runner import run_verification
from repomate_core.verification.sandbox import (
    ProcessSandbox,
    SandboxLimits,
    SandboxResult,
    ToolchainCommand,
    detect_test_command,
    run_test_suite_check,
)

__all__ = [
    "ProcessSandbox",
    "SandboxLimits",
    "SandboxResult",
    "ToolchainCommand",
    "detect_test_command",
    "run_test_suite_check",
    "run_verification",
]
