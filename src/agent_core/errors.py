from __future__ import annotations


class TypedAgentError(RuntimeError):
    """Base class for typed operational errors surfaced to users."""

    error_code = "INTERNAL_ERROR"
    failure_class = "internal"
    user_message = "An internal error occurred."

    def metadata(self) -> dict[str, str]:
        return {
            "error_code": self.error_code,
            "failure_class": self.failure_class,
            "user_message": self.user_message,
        }

    def payload(self, *, detail: str | None = None) -> dict[str, str]:
        payload = self.metadata()
        payload["detail"] = str(self) if detail is None else str(detail)
        return payload


def typed_error_metadata(exc: BaseException) -> dict[str, str] | None:
    if isinstance(exc, TypedAgentError):
        return exc.metadata()
    return None


def typed_error_payload(exc: BaseException) -> dict[str, str] | None:
    if isinstance(exc, TypedAgentError):
        return exc.payload()
    return None


class ConfigError(TypedAgentError):
    """Configuration parsing or validation error."""

    error_code = "CONFIG_ERROR"
    failure_class = "configuration"
    user_message = "Configuration is invalid."


class IdentityError(TypedAgentError):
    """Runtime identity resolution error."""

    error_code = "IDENTITY_ERROR"
    failure_class = "identity"
    user_message = "Runtime identity resolution failed."


class MountVisibilityError(TypedAgentError):
    """Mount path is not visible to runtime daemon."""

    error_code = "MOUNT_VISIBILITY_ERROR"
    failure_class = "mount_visibility"
    user_message = "Mount path is not visible to the runtime."


class NetworkReachabilityError(TypedAgentError):
    """Required network endpoint is not reachable."""

    error_code = "NETWORK_REACHABILITY_ERROR"
    failure_class = "network"
    user_message = "Required network endpoint is not reachable."


class CredentialResolutionError(TypedAgentError):
    """Credential lookup or resolution error."""

    error_code = "CREDENTIAL_RESOLUTION_ERROR"
    failure_class = "credentials"
    user_message = "Credential resolution failed."
