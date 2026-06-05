from __future__ import annotations

import os

import pytest

from hai_agents import Client

DEFAULT_BASE_URL = "https://agp.staging.sandboxh.ai"


@pytest.fixture(scope="session")
def api_key() -> str:
    key = os.environ.get("HAI_API_KEY_TEST")
    if not key:
        pytest.skip("HAI_API_KEY_TEST is not set.")
    if not key.startswith("hk-"):
        pytest.skip("HAI_API_KEY_TEST does not look like an hk-* key.")
    return key


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("HAI_API_BASE_URL_TEST", DEFAULT_BASE_URL)


@pytest.fixture
def client(api_key: str, base_url: str) -> Client:
    return Client(api_key=api_key, base_url=base_url)
