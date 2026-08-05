"""Provider routing: pick a backend by model name / policy.

The router owns a registry of named providers and an ordered list of rules.
The first rule whose predicate matches the requested model wins; if none match,
an optional default is used, otherwise :class:`RoutingError` is raised.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .providers import Provider


class RoutingError(KeyError):
    """No route (and no default) matched the requested model."""


@dataclass
class Route:
    """A single routing rule: match predicate -> provider name."""

    match: Callable[[str], bool]
    provider: str


class Router:
    """Selects a :class:`Provider` for a given model name."""

    def __init__(
        self,
        providers: dict[str, Provider],
        routes: list[Route],
        default: str | None = None,
    ) -> None:
        self._providers = providers
        self._routes = routes
        self._default = default

    def select(self, model: str) -> Provider:
        """Return the provider that should handle ``model``.

        Raises :class:`RoutingError` if nothing matches and no default is set,
        or if a matched rule names a provider absent from the registry.
        """
        for route in self._routes:
            if route.match(model):
                return self._resolve(route.provider, model)
        if self._default is not None:
            return self._resolve(self._default, model)
        raise RoutingError(f"No route for model {model!r}")

    def _resolve(self, name: str, model: str) -> Provider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise RoutingError(
                f"Route for model {model!r} points at unknown provider {name!r}"
            ) from exc


def prefix_route(prefix: str, provider: str) -> Route:
    """A convenience rule that matches models starting with ``prefix``."""
    return Route(match=lambda model, p=prefix: model.startswith(p), provider=provider)


def build_default_router(providers: dict[str, Provider]) -> Router:
    """The stock policy: ``claude*`` -> anthropic, everything else -> mock.

    Kept deliberately simple; real deployments would load rules from config.
    """
    return Router(
        providers=providers,
        routes=[
            prefix_route("claude", "anthropic"),
            prefix_route("mock", "mock"),
        ],
        default="mock",
    )
