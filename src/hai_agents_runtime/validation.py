"""The crossing rule: a screenshot may cross the public internet at most once.

Every step of a desktop task is the same loop — capture the screen, get it to
a model, decide, act — so the screenshot travels environment -> agent -> model
on every step. Each hop between different places crosses the public internet
once. Zero or one crossing is a working configuration; two means the same
image left, came back, and left again — always a mistake, so it is refused at
construction, naming both crossings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from hai_agents_runtime.config import Place, RuntimeConfig


def crossings(environment_host: "Place", agent_place: "Place", inference_place: "Place") -> List[str]:
    """The internet crossings one step's screenshot makes, described."""
    hops: List[str] = []
    if environment_host != agent_place:
        hops.append(f"the {environment_host} screen up to the {agent_place} agent")
    if agent_place != inference_place:
        hops.append(f"the {agent_place} agent over to the {inference_place} model")
    return hops


def validate(config: "RuntimeConfig") -> None:
    """Raise ValueError when a configuration crosses the internet twice per step."""
    hops = crossings(config.environment.host, config.agent.where, config.inference.where)
    if len(hops) >= 2:
        raise ValueError(
            "Illegal combination: the screenshot would cross the public internet "
            f"{len(hops)} times per step — crossing 1: {hops[0]}; crossing 2: {hops[1]}. "
            "Zero or one crossing is fine; move the agent next to the screen or "
            "next to the model."
        )
