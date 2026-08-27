"""The backend's exception hierarchy.

One root so callers can catch everything ours and nothing else, and enough
distinct subclasses that the CLI can turn a failure into an exit code and a
sentence a human can act on.
"""

from __future__ import annotations


class HblError(Exception):
    """Base class for every error this backend raises deliberately."""


class ConfigError(HblError):
    """Configuration is missing, malformed, or forbidden by a hard constraint."""


class ProviderError(HblError):
    """Something went wrong with a model provider."""


class ProviderNotFound(ProviderError):
    """The configured provider name is not in the registry."""


class ProviderUnavailable(ProviderError):
    """The provider exists but cannot run here — missing deps, or the service is down."""


class ProviderNotImplemented(ProviderError):
    """The provider is declared in the registry but its implementation phase hasn't run yet."""


class IndexMismatch(HblError):
    """The index was built by a different embedder than the one now configured.

    Raised rather than warned about, because the failure it prevents is silent:
    vectors from two models share a collection happily and produce rankings
    that look ordinary and mean nothing.
    """
