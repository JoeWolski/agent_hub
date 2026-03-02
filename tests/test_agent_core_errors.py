from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_core.errors import (
    ConfigError,
    CredentialResolutionError,
    IdentityError,
    MountVisibilityError,
    NetworkReachabilityError,
    typed_error_metadata,
    typed_error_payload,
)
from agent_hub import server as hub_server


@pytest.mark.parametrize(
    ("error", "error_code", "failure_class", "user_message"),
    [
        (ConfigError("config bad"), "CONFIG_ERROR", "configuration", "Configuration is invalid."),
        (IdentityError("identity bad"), "IDENTITY_ERROR", "identity", "Runtime identity resolution failed."),
        (
            MountVisibilityError("mount bad"),
            "MOUNT_VISIBILITY_ERROR",
            "mount_visibility",
            "Mount path is not visible to the runtime.",
        ),
        (
            NetworkReachabilityError("network bad"),
            "NETWORK_REACHABILITY_ERROR",
            "network",
            "Required network endpoint is not reachable.",
        ),
        (
            CredentialResolutionError("credential bad"),
            "CREDENTIAL_RESOLUTION_ERROR",
            "credentials",
            "Credential resolution failed.",
        ),
    ],
)
def test_typed_errors_expose_deterministic_metadata_and_payload(
    error: Exception,
    error_code: str,
    failure_class: str,
    user_message: str,
) -> None:
    metadata = typed_error_metadata(error)
    assert metadata == {
        "error_code": error_code,
        "failure_class": failure_class,
        "user_message": user_message,
    }
    payload = typed_error_payload(error)
    assert payload == {
        "error_code": error_code,
        "failure_class": failure_class,
        "user_message": user_message,
        "detail": str(error),
    }


def test_typed_error_helpers_return_none_for_untyped_exceptions() -> None:
    exc = RuntimeError("boom")
    assert typed_error_metadata(exc) is None
    assert typed_error_payload(exc) is None


def test_hub_core_error_payload_maps_typed_error_with_metadata() -> None:
    status, payload = hub_server._core_error_payload(NetworkReachabilityError("target down"))
    assert status == 502
    assert payload["error_code"] == "NETWORK_REACHABILITY_ERROR"
    assert payload["failure_class"] == "network"
    assert payload["user_message"] == "Required network endpoint is not reachable."
    assert payload["detail"] == "target down"


def test_hub_core_error_payload_falls_back_for_untyped_error() -> None:
    status, payload = hub_server._core_error_payload(RuntimeError("boom"))
    assert status == 500
    assert payload == {"error_code": "INTERNAL_ERROR", "detail": "boom"}
