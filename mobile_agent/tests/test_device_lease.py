# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase

from mobile_agent.runtime.device_lease import InProcessDeviceLease


class InProcessDeviceLeaseTests(IsolatedAsyncioTestCase):
    async def test_second_owner_is_rejected_without_waiting(self):
        lease_provider = InProcessDeviceLease()
        first = await lease_provider.try_acquire("server-fixed-device")
        self.assertIsNotNone(first)

        second = await asyncio.wait_for(
            lease_provider.try_acquire("another-request-value"),
            timeout=0.05,
        )

        self.assertIsNone(second)
        await first.release()

    async def test_release_is_idempotent_and_allows_next_owner(self):
        lease_provider = InProcessDeviceLease()
        first = await lease_provider.try_acquire("server-fixed-device")
        self.assertIsNotNone(first)

        await first.release()
        await first.release()

        second = await lease_provider.try_acquire("server-fixed-device")
        self.assertIsNotNone(second)
        await second.release()
