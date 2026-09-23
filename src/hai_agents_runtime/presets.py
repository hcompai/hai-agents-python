"""The named configurations. A preset is just a RuntimeConfig — override any
toggle with `.with_()`; presets are shorthand, never a gate."""

from __future__ import annotations

from hai_agents_runtime.config import Agent, Environment, Inference, RuntimeConfig


def cloud() -> RuntimeConfig:
    """Everything in H's cloud. This is the default."""
    return RuntimeConfig(
        agent=Agent.cloud(),
        environment=Environment.browser(host="cloud"),
        inference=Inference.cloud(),
    )


def local() -> RuntimeConfig:
    """Agent and screen on the user's own machine; H's cloud model."""
    return RuntimeConfig(
        agent=Agent.user_device(),
        environment=Environment.desktop(host="user_device"),
        inference=Inference.cloud(),
    )
