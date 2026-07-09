"""Meta checks for ``hai_agents_tools``, generic over every prebuilt tool module.

Each tool module must declare ``__all__`` and have every name in it re-exported,
object for object, by the package ``__init__``. New tool modules are discovered from
the package directory automatically; adding one requires no test changes here.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import hai_agents_tools


def _tool_module_names() -> list[str]:
    """Names of the prebuilt tool modules, discovered from the package directory."""
    return sorted(module.name for module in pkgutil.iter_modules(hai_agents_tools.__path__))


def test_at_least_one_tool_module_is_discovered() -> None:
    assert "otp" in _tool_module_names()


@pytest.mark.parametrize("module_name", _tool_module_names())
def test_tool_module_declares_all(module_name: str) -> None:
    module = importlib.import_module(f"hai_agents_tools.{module_name}")
    assert getattr(module, "__all__", None), f"{module_name} must declare a non-empty __all__"


@pytest.mark.parametrize("module_name", _tool_module_names())
def test_tool_module_reexported_by_package(module_name: str) -> None:
    module = importlib.import_module(f"hai_agents_tools.{module_name}")
    for name in module.__all__:
        assert name in hai_agents_tools.__all__, f"{name} missing from hai_agents_tools __all__"
        assert getattr(hai_agents_tools, name) is getattr(module, name), (
            f"{name} re-export does not match {module_name}"
        )


def test_package_all_names_resolve() -> None:
    for name in hai_agents_tools.__all__:
        assert getattr(hai_agents_tools, name, None) is not None, f"__all__ lists unknown name {name}"
