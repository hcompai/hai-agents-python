"""Inference placement for a local agent runtime, independent of environment placement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Mapping, Optional
from urllib.parse import urlsplit

URL_ENV = "HAI_AGENT_RUNTIME_BASE_URL"
MODEL_ENV = "HAI_AGENT_RUNTIME_MODEL"
HOSTED = "hosted"


@dataclass(frozen=True)
class Inference:
    base_url: Optional[str] = None
    model: Optional[str] = None

    @classmethod
    def cloud(cls) -> "Inference":
        return cls()

    @classmethod
    def self_hosted(cls, base_url: str, *, model: str) -> "Inference":
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or not model:
            raise ValueError("self-hosted inference requires an HTTP(S) endpoint and model")
        return cls(base_url=base_url, model=model)

    def runtime_env(self, overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        env = {**os.environ, **(overrides or {})}
        if self.base_url is not None:
            # Never forward a hosted inference credential to a user-selected endpoint.
            env.pop("HAI_API_KEY", None)
            env[URL_ENV] = self.base_url
        else:
            env.pop(URL_ENV, None)
        if self.model is not None:
            env[MODEL_ENV] = self.model
        return env


def served_inference(env: Mapping[str, str]) -> str:
    """What a runtime started with ``env`` infers against: ``hosted`` or a server URL, then any default model."""
    url = env.get(URL_ENV, "").strip()
    model = env.get(MODEL_ENV, "").strip()
    return " ".join(part for part in (url or HOSTED, model) if part)
