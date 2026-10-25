"""Time and identity helpers shared by the contract models."""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_run_id() -> str:
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(8))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"run_{stamp}_{suffix}"
