# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

import httpx


class ActionResultStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"


class DeviceErrorKind(str, Enum):
    TIMEOUT = "timeout"
    OFFLINE = "offline"
    COMMAND_FAILED = "command_failed"
    INVALID_OBSERVATION = "invalid_observation"


class DeviceBackendError(RuntimeError):
    """A classified device failure that callers can handle deterministically."""

    def __init__(self, message: str, *, kind: DeviceErrorKind):
        super().__init__(message)
        self.kind = kind


def classify_device_error(error: BaseException | str) -> DeviceErrorKind:
    if isinstance(error, DeviceBackendError):
        return error.kind
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return DeviceErrorKind.TIMEOUT

    raw_message = str(error)
    message = raw_message.lower()
    structured_code = ""
    try:
        payload = json.loads(raw_message)
        if isinstance(payload, dict):
            structured_code = str(payload.get("code", "")).lower()
    except (json.JSONDecodeError, TypeError):
        pass
    if structured_code == "acep_command_outcome_unknown":
        return DeviceErrorKind.TIMEOUT
    if any(
        marker in message
        for marker in (
            "acep_command_outcome_unknown",
            "deadlineexceeded",
            "deadline exceeded",
            "timed out",
            "timeout",
            "outcome unknown",
            "outcome is unknown",
        )
    ):
        return DeviceErrorKind.TIMEOUT
    if any(
        marker in message
        for marker in ("offline", "no devices", "device not found")
    ):
        return DeviceErrorKind.OFFLINE
    return DeviceErrorKind.COMMAND_FAILED


@dataclass(frozen=True)
class ActionResult:
    status: ActionResultStatus
    message: str
    error_kind: DeviceErrorKind | None = None

    @classmethod
    def success(cls, message: str) -> "ActionResult":
        return cls(status=ActionResultStatus.SUCCESS, message=message)

    @classmethod
    def failed(
        cls, message: str, error_kind: DeviceErrorKind
    ) -> "ActionResult":
        return cls(
            status=ActionResultStatus.FAILED,
            message=message,
            error_kind=error_kind,
        )

    @classmethod
    def ambiguous(
        cls, message: str, error_kind: DeviceErrorKind
    ) -> "ActionResult":
        return cls(
            status=ActionResultStatus.AMBIGUOUS,
            message=message,
            error_kind=error_kind,
        )
