"""Stable, non-sensitive error definitions for the command-line boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final


class ExitStatus(IntEnum):
    """Stable process exit statuses grouped by failure category."""

    SUCCESS = 0
    INVALID_ARGUMENTS = 2
    CONFIGURATION_ERROR = 10
    AUTHENTICATION_ERROR = 20
    NETWORK_ERROR = 30
    DATA_ERROR = 40
    STORAGE_ERROR = 50
    CONCURRENCY_ERROR = 60
    INTERNAL_ERROR = 70


class ErrorCode(StrEnum):
    """Stable machine-readable error codes."""

    INVALID_ARGUMENTS = "invalid_arguments"
    INVALID_CONFIGURATION = "invalid_configuration"
    INTERACTIVE_TERMINAL_REQUIRED = "interactive_terminal_required"
    AUTH_REQUIRED = "auth_required"
    AUTHENTICATION_FAILED = "authentication_failed"
    ACCOUNT_MISMATCH = "account_mismatch"
    NETWORK_UNAVAILABLE = "network_unavailable"
    RATE_LIMITED = "rate_limited"
    REMOTE_SERVICE_ERROR = "remote_service_error"
    INVALID_REMOTE_DATA = "invalid_remote_data"
    LOCAL_STORAGE_ERROR = "local_storage_error"
    REFRESH_IN_PROGRESS = "refresh_in_progress"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """Safe public representation and exit status for one error code."""

    exit_status: ExitStatus
    message: str


ERROR_SPECS: Final[Mapping[ErrorCode, ErrorSpec]] = MappingProxyType(
    {
        ErrorCode.INVALID_ARGUMENTS: ErrorSpec(
            ExitStatus.INVALID_ARGUMENTS, "Invalid command arguments."
        ),
        ErrorCode.INVALID_CONFIGURATION: ErrorSpec(
            ExitStatus.CONFIGURATION_ERROR, "The backend configuration is invalid."
        ),
        ErrorCode.INTERACTIVE_TERMINAL_REQUIRED: ErrorSpec(
            ExitStatus.CONFIGURATION_ERROR,
            "Garmin login requires a visible interactive terminal.",
        ),
        ErrorCode.AUTH_REQUIRED: ErrorSpec(
            ExitStatus.AUTHENTICATION_ERROR, "Garmin authentication is required."
        ),
        ErrorCode.AUTHENTICATION_FAILED: ErrorSpec(
            ExitStatus.AUTHENTICATION_ERROR, "Garmin authentication failed."
        ),
        ErrorCode.ACCOUNT_MISMATCH: ErrorSpec(
            ExitStatus.AUTHENTICATION_ERROR,
            "The Garmin account does not match the local data scope.",
        ),
        ErrorCode.NETWORK_UNAVAILABLE: ErrorSpec(
            ExitStatus.NETWORK_ERROR, "Garmin Connect is unavailable."
        ),
        ErrorCode.RATE_LIMITED: ErrorSpec(
            ExitStatus.NETWORK_ERROR, "Garmin Connect rate limit reached."
        ),
        ErrorCode.REMOTE_SERVICE_ERROR: ErrorSpec(
            ExitStatus.NETWORK_ERROR, "Garmin Connect request failed."
        ),
        ErrorCode.INVALID_REMOTE_DATA: ErrorSpec(
            ExitStatus.DATA_ERROR, "Garmin Connect returned invalid activity data."
        ),
        ErrorCode.LOCAL_STORAGE_ERROR: ErrorSpec(
            ExitStatus.STORAGE_ERROR, "Local Garmin activity storage failed."
        ),
        ErrorCode.REFRESH_IN_PROGRESS: ErrorSpec(
            ExitStatus.CONCURRENCY_ERROR, "An activity refresh is already in progress."
        ),
        ErrorCode.INTERNAL_ERROR: ErrorSpec(
            ExitStatus.INTERNAL_ERROR, "The backend encountered an internal error."
        ),
    }
)


class CommandError(RuntimeError):
    """Carry a reviewed public error code to the process boundary."""

    def __init__(self, code: ErrorCode) -> None:
        """Initialize the error from a catalogued public code."""
        self.code = code
        super().__init__(ERROR_SPECS[code].message)
