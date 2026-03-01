from __future__ import annotations


class ConfigError(RuntimeError):
    """Configuration parsing or validation error."""


class IdentityError(RuntimeError):
    """Runtime identity resolution error."""


class MountVisibilityError(RuntimeError):
    """Mount path is not visible to runtime daemon."""


class NetworkReachabilityError(RuntimeError):
    """Required network endpoint is not reachable."""


class CredentialResolutionError(RuntimeError):
    """Credential lookup or resolution error."""
