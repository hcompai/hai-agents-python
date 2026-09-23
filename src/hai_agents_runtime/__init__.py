"""Choose where each part of an agent task runs: agent, environment, inference.

EXPERIMENTAL — the interface may change while the three toggles are pre-release.
Deliberately a hand-written sibling package (not inside `hai_agents`, which
codegen regenerates): regen-proof, not re-exported from the main package, and
free to graduate to `hai_agents.runtime` via a codegen overlay once the external
API is settled.
"""

from hai_agents_runtime.config import (
    Agent,
    AgentChoice,
    CloudAgent,
    CloudInference,
    Environment,
    Inference,
    InferenceChoice,
    Place,
    RuntimeConfig,
    SelfHostedAgent,
    SelfHostedInference,
    UserDeviceAgent,
)
from hai_agents_runtime.presets import cloud, local

__all__ = [
    "Agent",
    "AgentChoice",
    "CloudAgent",
    "CloudInference",
    "Environment",
    "Inference",
    "InferenceChoice",
    "Place",
    "RuntimeConfig",
    "SelfHostedAgent",
    "SelfHostedInference",
    "UserDeviceAgent",
    "cloud",
    "local",
]
