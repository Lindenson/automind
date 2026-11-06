"""The application's reference data at run time: built by the composition root (delivery.bootstrap), read by
the areas. Holding a factory here keeps the shared kernel free of imports from the areas."""

from __future__ import annotations

from collections.abc import Callable

from automind.shared.contracts.config import Reference

_FACTORY: Callable[[dict[str, str]], Reference] | None = None


def install(factory: Callable[[dict[str, str]], Reference]) -> None:
    """Called once by `delivery.bootstrap.configure_domain()`."""
    global _FACTORY
    _FACTORY = factory


def reference(prompts: dict[str, str]) -> Reference:
    """The reference data with these prompts."""
    if _FACTORY is None:
        raise RuntimeError("delivery.bootstrap.configure_domain() was not called: no Reference factory installed")
    return _FACTORY(prompts)
