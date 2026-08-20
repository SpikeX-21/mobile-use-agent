# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Run the KooPhone visual path through the production MobileUseAgent seam."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Callable

from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.agent.mobile_use_agent import MobileUseAgent
from mobile_agent.agent.run_result import AgentRunResult
from mobile_agent.koophone_task import run_koophone_task


DEFAULT_PROMPT = "请观察当前屏幕，然后返回主屏幕并确认完成。"


async def run_koophone_vision_demo(
    prompt: str,
    *,
    agent_factory: Callable[..., MobileUseAgent] = MobileUseAgent,
    outcome_sink: Callable[[str | None], None] | None = None,
) -> int:
    """Compatibility adapter over the shared structured task entry point."""

    result = await run_koophone_task(prompt, agent_factory=agent_factory)
    if outcome_sink is not None:
        outcome_sink(result.terminal_reason)
    return result.rounds


async def run_koophone_vision_task(prompt: str) -> AgentRunResult:
    """Run the shared task seam and return its authoritative business result."""

    return await run_koophone_task(prompt)


def main() -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(
        description="Run one real Kimi + KooPhone visual task through MobileUseAgent"
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    arguments = parser.parse_args()
    try:
        result = asyncio.run(
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
    if not isinstance(result, AgentRunResult):
        print(
            "KOOPHONE_VISION_DEMO=failed reason=runtime_failed",
            file=sys.stderr,
        )
        return 1
    if not result.completed:
        print(
            "KOOPHONE_VISION_DEMO=failed "
            f"reason={result.terminal_reason or 'runtime_ended'} "
            f"rounds={result.rounds}",
            file=sys.stderr,
        )
        return 2 if result.terminal_reason == "provider_configuration" else 1
    print(f"KOOPHONE_VISION_DEMO=finished rounds={result.rounds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
