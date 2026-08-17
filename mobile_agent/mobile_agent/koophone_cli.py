# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Run the KooPhone visual path through the production MobileUseAgent seam."""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Callable
import uuid

from mobile_agent.agent.mobile_use_agent import MobileUseAgent


DEFAULT_PROMPT = "请观察当前屏幕，然后返回主屏幕并确认完成。"


async def run_koophone_vision_demo(
    prompt: str,
    *,
    agent_factory: Callable[..., MobileUseAgent] = MobileUseAgent,
    outcome_sink: Callable[[str | None], None] | None = None,
) -> int:
    """Run one Kimi + KooPhone task without introducing a second agent loop."""

    agent = agent_factory(
        model_provider_name="kimi",
        device_provider_name="koophone_mcp",
    )
    try:
        await agent.initialize("", "", "", "", "", "")
        chunk_count = 0
        async for _ in agent.run(
            prompt,
            is_stream=False,
            task_id=f"koophone-vision-{uuid.uuid4()}",
            session_id="koophone-cli",
            thread_id=f"koophone-cli-{uuid.uuid4()}",
            sse_connection=asyncio.Event(),
            phone_width=0,
            phone_height=0,
        ):
            chunk_count += 1
        if outcome_sink is not None:
            outcome_sink(getattr(agent, "last_terminal_reason", None))
        return chunk_count
    finally:
        await agent.aclose()


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(
        description="Run one real Kimi + KooPhone visual task through MobileUseAgent"
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    arguments = parser.parse_args()
    chunk_count = asyncio.run(run_koophone_vision_demo(arguments.prompt))
    print(f"KOOPHONE_VISION_DEMO=finished chunks={chunk_count}")


if __name__ == "__main__":
    main()
