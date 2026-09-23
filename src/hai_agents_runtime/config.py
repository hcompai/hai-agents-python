"""Choose where each part of an agent task runs — the three-toggle switch layer.

Every agent task has three parts, and each can run in one of three places:

    user_device   installed on the user's own machine
    self_hosted   the customer's own server / VM (BYO), inside their perimeter
    cloud         H's infrastructure

    toggle       what it is             positions
    agent        the reasoning loop     user_device | self_hosted | cloud
    environment  what it drives         user_device | self_hosted | cloud
    inference    the model              self_hosted | cloud

Pick each toggle, or use a preset:

    from hai_agents_runtime import RuntimeConfig, Agent, Environment, Inference

    config = RuntimeConfig.cloud()            # everything in H's cloud (the default)
    config = RuntimeConfig.local()            # agent + screen on this machine, cloud model
    client = config.client()                  # an ordinary hai_agents Client

Presets are shorthand, never a gate — override any toggle with `.with_()`:

    RuntimeConfig.local().with_(inference=Inference.self_hosted("https://gpu.internal/v1"))

EXPERIMENTAL — a hand-written sibling package (not inside `hai_agents`, which
codegen regenerates), so it is regen-proof and free to graduate to
`hai_agents.runtime` via a codegen overlay once the external API is settled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Literal

Place = Literal["user_device", "self_hosted", "cloud"]

DEFAULT_MODEL = "Hcompany/Holo-3.1-35B-A3B"
DEFAULT_AGENT_PORT = 18795

# External contract spelling (theirs, not ours): despite the name, this env var
# is the INFERENCE endpoint the agent runtime calls out to — not the runtime's
# own address. The cloud API key is never handed to a self-hosted model endpoint.
INFERENCE_BASE_URL_ENV = "HAI_AGENT_RUNTIME_BASE_URL"
INFERENCE_MODEL_ENV = "HAI_AGENT_RUNTIME_MODEL"
CLOUD_API_KEY_ENV = "HAI_API_KEY"


# ---- the agent toggle ------------------------------------------------------


@dataclass(frozen=True)
class UserDeviceAgent:
    """The reasoning loop runs on the user's own machine (a local agent runtime)."""

    port: int = DEFAULT_AGENT_PORT
    where: Literal["user_device"] = field(default="user_device", init=False)


@dataclass(frozen=True)
class SelfHostedAgent:
    """The reasoning loop runs on the customer's own server (BYO)."""

    url: str  # required: the customer's agent-runtime address — no default to guess at
    where: Literal["self_hosted"] = field(default="self_hosted", init=False)


@dataclass(frozen=True)
class CloudAgent:
    """The reasoning loop runs on H's infrastructure."""

    region: str = "eu"
    where: Literal["cloud"] = field(default="cloud", init=False)


AgentChoice = UserDeviceAgent | SelfHostedAgent | CloudAgent


class Agent:
    """Constructors for the agent toggle. Each place is its own small type, so an
    agent object only carries the fields that mean something for it."""

    @staticmethod
    def user_device(port: int = DEFAULT_AGENT_PORT) -> UserDeviceAgent:
        return UserDeviceAgent(port=port)

    @staticmethod
    def self_hosted(url: str) -> SelfHostedAgent:
        return SelfHostedAgent(url=url)

    @staticmethod
    def cloud(region: str = "eu") -> CloudAgent:
        return CloudAgent(region=region)


# ---- the environment toggle ------------------------------------------------


@dataclass(frozen=True)
class Environment:
    """Where the thing being driven (desktop, browser) lives."""

    kind: Literal["desktop", "browser"]
    host: Place

    @classmethod
    def desktop(cls, host: Place = "user_device") -> "Environment":
        return cls(kind="desktop", host=host)

    @classmethod
    def browser(cls, host: Place = "cloud") -> "Environment":
        return cls(kind="browser", host=host)


# ---- the inference toggle --------------------------------------------------
# Two choices only: H's cloud model, or a model you host yourself by URL (a
# localhost URL is fine — there is no special local/loopback handling here).


@dataclass(frozen=True)
class SelfHostedInference:
    """A model server you host yourself. Any URL, localhost included."""

    base_url: str  # required — no default to guess at
    model: str = DEFAULT_MODEL
    where: Literal["self_hosted"] = field(default="self_hosted", init=False)


@dataclass(frozen=True)
class CloudInference:
    """H's cloud model. Carries no endpoint and no model name — the platform
    resolves the model server-side."""

    where: Literal["cloud"] = field(default="cloud", init=False)


InferenceChoice = SelfHostedInference | CloudInference


class Inference:
    """Constructors for the inference toggle: our cloud, or your own URL."""

    @staticmethod
    def self_hosted(base_url: str, model: str = DEFAULT_MODEL) -> SelfHostedInference:
        return SelfHostedInference(base_url=base_url, model=model)

    @staticmethod
    def cloud() -> CloudInference:
        return CloudInference()


# ---- the config ------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeConfig:
    """One object, three toggles. Instantiate it; presets are ordinary shorthand."""

    agent: AgentChoice
    environment: Environment
    inference: InferenceChoice

    def __post_init__(self) -> None:
        from hai_agents_runtime.validation import validate

        validate(self)
        if isinstance(self.agent, UserDeviceAgent):
            _require_local_agent_runtime()

    @classmethod
    def cloud(cls) -> "RuntimeConfig":
        from hai_agents_runtime.presets import cloud

        return cloud()

    @classmethod
    def local(cls) -> "RuntimeConfig":
        from hai_agents_runtime.presets import local

        return local()

    def with_(self, **toggles) -> "RuntimeConfig":
        """A copy with some toggles replaced: local().with_(inference=Inference.cloud())."""
        return replace(self, **toggles)

    def client(self):
        """An ordinary hai_agents Client, wired for this configuration.

        Cloud agent: the plain SDK client, unchanged from today. User-device
        agent: Client.local() (PR #185) spawns or attaches to the agent runtime
        on loopback; a self-hosted inference endpoint is handed to it at spawn
        time, without the cloud API key.
        """
        from hai_agents.client import Client

        if isinstance(self.agent, CloudAgent):
            return Client()  # env-configured; nothing about this path changes

        if isinstance(self.agent, SelfHostedAgent):
            raise NotImplementedError(
                "self_hosted agent (a customer's own server) is not wired yet — the "
                "contract is identical to user_device; only the address changes."
            )

        if self.environment.kind != "desktop" or self.environment.host != "user_device":
            raise NotImplementedError(
                "A user_device agent currently drives the user's own desktop only."
            )

        if isinstance(self.inference, CloudInference):
            # The runtime inherits the environment and calls H's model gateway
            # exactly as it does today.
            return Client.local(port=self.agent.port)

        # self_hosted inference: point the runtime at the chosen endpoint, and
        # keep the cloud key out of a model server we do not own. (Final spawn
        # environment handling tracks agent_platform#1452's spawn_env hook.)
        spawn_env = {k: v for k, v in os.environ.items() if k != CLOUD_API_KEY_ENV}
        spawn_env[INFERENCE_BASE_URL_ENV] = self.inference.base_url
        spawn_env[INFERENCE_MODEL_ENV] = self.inference.model
        return Client.local(port=self.agent.port, spawn_env=spawn_env)


def _require_local_agent_runtime() -> None:
    """A user_device agent needs the local agent runtime, shipped as an opt-in extra.

    Fail here, at construction, with a plain message naming the extra — never a
    cryptic import error later. The compiled binary itself is fetched on first
    use by LocalRuntime; this checks the local-mode support is installed at all.
    """
    from importlib.util import find_spec

    if find_spec("hai_agents.local") is None:
        raise RuntimeError(
            "A user_device agent needs the local agent runtime, which is an opt-in extra. "
            'Install it with:  pip install "hai-agents[local-agent]"  (compiled binary, public)  '
            'or  pip install "hai-agents[local-agent-src]"  (source, internal only).'
        )
