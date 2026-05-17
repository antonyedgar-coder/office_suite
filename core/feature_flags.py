"""Environment-driven feature flags."""

from __future__ import annotations

import os


def env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def task_module_enabled() -> bool:
    return env_flag("ENABLE_TASK_MODULE", default=False)
