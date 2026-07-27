"""OSZT - an AI-operated computer where the agent acts only through a broker.

Assembly lives here so callers never wire a broker without a policy and ledger.
"""

from __future__ import annotations

from pathlib import Path

from oszt.audit import AuditLog
from oszt.broker import Broker
from oszt.capabilities import BUILTIN_CAPABILITIES
from oszt.policy import Policy
from oszt.runner import Runner

__version__ = "0.1.0"


def build_broker(
    policy: Policy, audit_path: Path | str, runner: Runner | None = None
) -> Broker:
    """Create a broker with every built-in capability registered.

    Registration is not permission: :class:`Policy` still decides what is
    callable and what appears in ``tool_list()``.
    """
    broker = Broker(policy=policy, audit=AuditLog(audit_path), runner=runner)
    broker.register_all(BUILTIN_CAPABILITIES.items())
    return broker


__all__ = ["Broker", "Policy", "AuditLog", "build_broker", "__version__"]
