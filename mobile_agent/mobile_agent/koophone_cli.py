# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Run the KooPhone visual path through the production MobileUseAgent seam."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Callable
import uuid

from mobile_agent.agent.provider import ProviderConfigurationError
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


async def run_koophone_vision_task(prompt: str) -> tuple[int, str | None]:
    """Return both stream activity and the Agent's authoritative terminal state."""

    outcome: list[str | None] = []
    chunk_count = await run_koophone_vision_demo(
        prompt,
        outcome_sink=outcome.append,
    )
    return chunk_count, outcome[-1] if outcome else None


def main() -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(
        description="Run one real Kimi + KooPhone visual task through MobileUseAgent"
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    arguments = parser.parse_args()
    try:
        chunk_count, terminal_reason = asyncio.run(
            run_koophone_vision_task(arguments.prompt)
        )
    except ProviderConfigurationError:
        print(
            "KOOPHONE_VISION_DEMO=failed reason=provider_configuration",
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            "KOOPHONE_VISION_DEMO=failed reason=runtime_error",
            file=sys.stderr,
        )
        return 1
    if terminal_reason != "completed":
        print(
            "KOOPHONE_VISION_DEMO=failed "
            f"reason={terminal_reason or 'runtime_ended'} chunks={chunk_count}",
            file=sys.stderr,
        )
        return 1
    print(f"KOOPHONE_VISION_DEMO=finished chunks={chunk_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
