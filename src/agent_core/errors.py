from __future__ import annotations


class TypedAgentError(RuntimeError):
    """Base class for typed operational errors surfaced to users."""

    error_code = "INTERNAL_ERROR"
    failure_class = "internal"
    user_message = "An internal error occurred."
    http_status = 500

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


def typed_error_http_status(exc: BaseException) -> int | None:
    if isinstance(exc, TypedAgentError):
        return int(exc.http_status)
    return None


class ConfigError(TypedAgentError):
    """Configuration parsing or validation error."""

    error_code = "CONFIG_ERROR"
    failure_class = "configuration"
    user_message = "Configuration is invalid."
    http_status = 400


class IdentityError(TypedAgentError):
    """Runtime identity resolution error."""

    error_code = "IDENTITY_ERROR"
    failure_class = "identity"
    user_message = "Runtime identity resolution failed."
    http_status = 400


class MountVisibilityError(TypedAgentError):
    """Mount path is not visible to runtime daemon."""

    error_code = "MOUNT_VISIBILITY_ERROR"
    failure_class = "mount_visibility"
    user_message = "Mount path is not visible to the runtime."
    http_status = 409


class NetworkReachabilityError(TypedAgentError):
    """Required network endpoint is not reachable."""

    error_code = "NETWORK_REACHABILITY_ERROR"
    failure_class = "network"
    user_message = "Required network endpoint is not reachable."
    http_status = 502


class CredentialResolutionError(TypedAgentError):
    """Credential lookup or resolution error."""

    error_code = "CREDENTIAL_RESOLUTION_ERROR"
    failure_class = "credentials"
    user_message = "Credential resolution failed."
    http_status = 401


class RuntimeCommandError(TypedAgentError):
    """A runtime subprocess command returned a non-zero exit code."""

    error_code = "RUNTIME_COMMAND_ERROR"
    failure_class = "runtime_command"
    user_message = "Runtime command execution failed."
    http_status = 400

    def __init__(self, *, command: list[str], exit_code: int, output: str | None = None):
        self.command = [str(part) for part in command]
        self.exit_code = int(exit_code)
        self.output = str(output or "").strip()
        command_line = " ".join(self.command) if self.command else "<unknown>"
        detail = f"Command failed ({command_line}) with exit code {self.exit_code}"
        if self.output:
            detail = f"{detail}: {self.output}"
        super().__init__(detail)


class RuntimeStateError(TypedAgentError):
    """Runtime state transition or availability error."""

    error_code = "RUNTIME_STATE_ERROR"
    failure_class = "runtime_state"
    user_message = "Runtime state operation failed."
    http_status = 409


class StateStoreError(TypedAgentError):
    """Persistent hub state load/save error."""

    error_code = "STATE_STORE_ERROR"
    failure_class = "state_store"
    user_message = "Persistent state store operation failed."
    http_status = 500
