"""Errors raised by the OSZT broker.

Every refusal is one of these. Nothing in the broker ever fails silently.
"""

from __future__ import annotations


class OSZTError(Exception):
    """Base class for all OSZT errors."""


class UnknownCapability(OSZTError):
    """No capability with the requested name is registered."""


class PolicyViolation(OSZTError):
    """The capability or one of its arguments is not permitted by the policy."""


class QuotaExceeded(OSZTError):
    """The call is permitted but exceeds a configured rate limit."""


class CapabilityFailed(OSZTError):
    """The capability was allowed and attempted, but the underlying command failed."""
