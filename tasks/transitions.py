"""Task status transition rules (workflow-aware)."""

from __future__ import annotations

from .workflow import can_transition, validate_transition

__all__ = ["can_transition", "validate_transition"]
