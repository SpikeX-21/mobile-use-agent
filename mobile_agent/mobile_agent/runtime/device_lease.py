# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Replaceable device-lease boundary for local Runtime coordination."""

from __future__ import annotations

import asyncio
from typing import Protocol


class DeviceLeaseHandle(Protocol):
    async def release(self) -> None:
        """Release the lease exactly once."""


class DeviceLeaseProvider(Protocol):
    async def try_acquire(self, device_key: str) -> DeviceLeaseHandle | None:
        """Return a lease immediately, or ``None`` when the device is busy."""


class _InProcessLeaseHandle:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._lock.release()


class InProcessDeviceLease:
    """Non-queueing, one-owner lease for one process/sandbox."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    async def try_acquire(self, device_key: str) -> DeviceLeaseHandle | None:
        # ``device_key`` is intentionally accepted at this seam so a shared
        # implementation can later key leases by EID.  The local Runtime
        # passes one server-owned fixed key and never forwards request data.
        del device_key
        if self._lock.locked():
            return None
        await self._lock.acquire()
        return _InProcessLeaseHandle(self._lock)
