# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Run the KooPhone 09:00 alarm demo through the production Agent loop."""

from __future__ import annotations

import argparse
import asyncio
from typing import Callable

from mobile_agent.agent.mobile_use_agent import MobileUseAgent
from mobile_agent.koophone_cli import run_koophone_vision_demo


ALARM_PROMPT = """请确保云手机中存在一个已启用的 09:00 闹钟。

使用用户已明确提供的时钟应用包名 com.android.deskclock 启动闹钟应用，然后只根据每一轮最新截图操作和判断：
1. 若清晰显示已有启用的 09:00 闹钟，直接 finish，绝不创建重复闹钟。
2. 若清晰显示已有但禁用的 09:00 闹钟，只点击其开关启用，然后重新观察确认。
3. 若没有 09:00 闹钟，使用应用界面创建一个 09:00 闹钟，保持系统默认的重复、铃声和标签设置，然后重新观察确认。

只能使用截图可见的界面，不要使用 UI 树、ADB、安装、Shell 或任何未列动作。动作回执失败、超时或结果不确定时，必须先重新观察；不要盲目重试有副作用的动作。只有最新截图清晰显示 09:00 且为已启用状态时才返回 finish。"""


async def run_koophone_alarm_demo(
    *,
    agent_factory: Callable[..., MobileUseAgent] = MobileUseAgent,
) -> int:
    """Run the idempotent 09:00 alarm task via the production Kimi adapter."""

    return await run_koophone_vision_demo(ALARM_PROMPT, agent_factory=agent_factory)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the real Kimi + KooPhone 09:00 alarm acceptance task"
    )
    parser.parse_args()
    chunk_count = asyncio.run(run_koophone_alarm_demo())
    print(f"KOOPHONE_ALARM_DEMO=finished chunks={chunk_count}")


if __name__ == "__main__":
    main()
