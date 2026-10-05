"""Inference placement for a local agent runtime, independent of environment placement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlsplit


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
            env["HAI_AGENT_RUNTIME_BASE_URL"] = self.base_url
        else:
            env.pop("HAI_AGENT_RUNTIME_BASE_URL", None)
        if self.model is not None:
            env["HAI_AGENT_RUNTIME_MODEL"] = self.model
        return env
