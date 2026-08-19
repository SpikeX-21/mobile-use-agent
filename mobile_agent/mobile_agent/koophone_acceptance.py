# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Container-native KooPhone demo acceptance and privacy-safe reporting."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import sys
from typing import Awaitable, Callable, Iterable, Sequence
import uuid

from mobile_agent.agent.experiments.records import (
    RunRecord,
    contains_sensitive_text,
)
from mobile_agent.agent.mobile_use_agent import MobileUseAgent
from mobile_agent.config.settings import get_settings
from mobile_agent.koophone_alarm_cli import ALARM_PROMPT


PREPARE_DISABLED_PROMPT = """请只根据最新截图，把系统闹钟准备为以下状态：存在一个 09:00 闹钟，但它当前处于关闭状态。

使用用户明确提供的时钟包名 com.android.deskclock。若 09:00 已启用，只关闭它；若不存在，使用系统默认设置创建 09:00 后再关闭。不要删除其他闹钟，不使用 UI 树、ADB、Shell 或安装能力。只有最新截图清晰显示 09:00 且开关关闭时才 finish。动作失败、超时或回执不确定时先重新观察，不盲目重试副作用。"""


@dataclass(frozen=True)
class KooPhoneAcceptanceScenario:
    slug: str
    name: str
    phase: str
    prompt: str
    requires_state_change: bool = False
    forbids_side_effects: bool = False


ACCEPTANCE_SEQUENCE = (
    KooPhoneAcceptanceScenario(
        slug="prepare_disabled",
        name="准备已存在但禁用的 09:00 闹钟",
        phase="state_setup",
        prompt=PREPARE_DISABLED_PROMPT,
    ),
    KooPhoneAcceptanceScenario(
        slug="enable_existing",
        name="启用已存在但禁用的 09:00 闹钟",
        phase="acceptance",
        prompt=ALARM_PROMPT,
        requires_state_change=True,
    ),
    KooPhoneAcceptanceScenario(
        slug="already_enabled",
        name="识别已启用的 09:00 闹钟",
        phase="acceptance",
        prompt=ALARM_PROMPT,
        forbids_side_effects=True,
    ),
    KooPhoneAcceptanceScenario(
        slug="idempotent_repeat",
        name="再次运行且不制造重复闹钟",
        phase="acceptance",
        prompt=ALARM_PROMPT,
        forbids_side_effects=True,
    ),
)

_DEVICE_SIDE_EFFECTS = frozenset(
    {
        "tap",
        "swipe",
        "text_input",
        "clear_text",
        "home",
        "back",
        "menu",
        "launch_app",
        "close_app",
    }
)
_ALARM_STATE_MUTATIONS = frozenset({"tap"})


@dataclass(frozen=True)
class KooPhoneAcceptanceExecution:
    records: Sequence[RunRecord]


@dataclass(frozen=True)
class KooPhoneAcceptanceRun:
    scenario_slug: str
    scenario_name: str
    phase: str
    run_id: str
    success: bool
    steps: int
    model_latency_ms: int
    device_latency_ms: int
    schema_retries: int
    terminal_reason: str | None
    failure_classification: str | None
    actions: tuple[str, ...]
    observation_images_used: tuple[int, ...]
    visual_evidence: str | None
    no_manual_intervention_attested: bool
    provider: str
    model: str
    device_provider: str


def _failure_classification(
    scenario: KooPhoneAcceptanceScenario,
    records: Sequence[RunRecord],
    *,
    terminal_record: RunRecord | None,
    actions: tuple[str, ...],
    no_manual_intervention_attested: bool,
) -> str | None:
    if not no_manual_intervention_attested:
        return "manual_intervention_not_attested"
    if not records:
        return "missing_experiment_records"
    if any(
        record.provider != "kimi"
        or record.model != "kimi-k2.6"
        or record.device_provider != "koophone_mcp"
        for record in records
    ):
        return "provider_contract_mismatch"
    if any(
        record.action_status in {"failed", "ambiguous", "rejected", "unsupported"}
        for record in records
    ):
        return "unsafe_or_failed_action"
    if terminal_record is None or terminal_record.terminal_reason != "completed":
        return "missing_completed_terminal"
    if (
        terminal_record.action_type != "finish"
        or terminal_record.observation_images_used < 1
    ):
        return "latest_visual_finish_missing"
    side_effects = tuple(action for action in actions if action in _DEVICE_SIDE_EFFECTS)
    alarm_mutations = tuple(
        action for action in actions if action in _ALARM_STATE_MUTATIONS
    )
    if scenario.requires_state_change and not alarm_mutations:
        return "required_state_change_missing"
    if scenario.forbids_side_effects and side_effects:
        return "unexpected_idempotent_side_effect"
    return None


def summarize_acceptance_run(
    scenario: KooPhoneAcceptanceScenario,
    execution: KooPhoneAcceptanceExecution,
    *,
    no_manual_intervention_attested: bool,
) -> KooPhoneAcceptanceRun:
    records = tuple(execution.records)
    if not records:
        raise ValueError("acceptance run has no experiment records")
    run_ids = {record.run_id for record in records}
    if len(run_ids) != 1:
        raise ValueError("acceptance records must belong to one run")
    actions = tuple(record.action_type for record in records)
    terminal_records = [
        record for record in records if record.terminal_reason is not None
    ]
    terminal_record = terminal_records[-1] if terminal_records else None
    failure = _failure_classification(
        scenario,
        records,
        terminal_record=terminal_record,
        actions=actions,
        no_manual_intervention_attested=no_manual_intervention_attested,
    )
    final_record = records[-1]
    return KooPhoneAcceptanceRun(
        scenario_slug=scenario.slug,
        scenario_name=scenario.name,
        phase=scenario.phase,
        run_id=final_record.run_id,
        success=failure is None,
        steps=max(record.step_number for record in records),
        model_latency_ms=sum(record.model_latency_ms for record in records),
        device_latency_ms=sum(record.device_latency_ms or 0 for record in records),
        schema_retries=sum(record.schema_status == "invalid" for record in records),
        terminal_reason=(terminal_record.terminal_reason if terminal_record else None),
        failure_classification=failure,
        actions=actions,
        observation_images_used=tuple(
            record.observation_images_used for record in records
        ),
        visual_evidence=(
            "latest_screenshot_model_confirmed" if failure is None else None
        ),
        no_manual_intervention_attested=no_manual_intervention_attested,
        provider=final_record.provider,
        model=final_record.model,
        device_provider=final_record.device_provider,
    )


@dataclass(frozen=True)
class KooPhoneAcceptanceSuite:
    runs: tuple[KooPhoneAcceptanceRun, ...]
    passed: bool

    @classmethod
    def from_runs(
        cls, runs: Iterable[KooPhoneAcceptanceRun]
    ) -> "KooPhoneAcceptanceSuite":
        resolved = tuple(runs)
        expected = tuple(scenario.slug for scenario in ACCEPTANCE_SEQUENCE)
        passed = (
            tuple(run.scenario_slug for run in resolved) == expected
            and all(run.success for run in resolved)
        )
        return cls(runs=resolved, passed=passed)

    def _environment(self) -> dict[str, str]:
        final = self.runs[-1] if self.runs else None
        return {
            "python": platform.python_version(),
            "architecture": platform.machine(),
            "mobile_agent": version("mobile-agent"),
            "provider": final.provider if final else "kimi",
            "model": final.model if final else "kimi-k2.6",
            "device_provider": (
                final.device_provider if final else "koophone_mcp"
            ),
            "thinking_mode": "disabled",
            "response_format": "json_object",
            "runtime": "secret-bearing-read-only-non-root-poc-container",
        }

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "passed": self.passed,
                "environment": self._environment(),
                "oracle": "none; latest screenshot judged by model",
                "runs": [asdict(run) for run in self.runs],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

    def to_markdown(self, *, generated_at: datetime | None = None) -> str:
        timestamp = generated_at or datetime.now(timezone.utc)
        environment = self._environment()
        lines = [
            "# Kimi K2.6 + KooPhone 容器 Demo 实机验收报告",
            "",
            f"- 生成时间：{timestamp.astimezone(timezone.utc).isoformat()}",
            f"- 结论：**{'通过' if self.passed else '未通过'}**",
            "- 判断路径：真实截图 → Kimi K2.6 非思考 JSON Mode → CanonicalAction",
            "- 完成证据：每轮最新截图由模型确认 09:00 状态",
            "- Oracle：无 ADB Oracle、无 UI 树、无未授权 MCP 工具",
            "- 人工干预：无点击、输入或模型补充信息",
            "",
            "## 环境",
            "",
            *(f"- `{key}`：`{value}`" for key, value in environment.items()),
            "",
            "## 运行结果",
            "",
            "| 阶段 | 场景 | 结果 | 步骤 | 模型耗时(ms) | 设备耗时(ms) | 图片数/轮 | 终止原因 | 动作 | 失败分类 |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
        for run in self.runs:
            lines.append(
                "| {phase} | {scenario} | {result} | {steps} | {model_ms} | "
                "{device_ms} | {images} | {terminal} | {actions} | {failure} |".format(
                    phase=run.phase,
                    scenario=run.scenario_name,
                    result="成功" if run.success else "失败",
                    steps=run.steps,
                    model_ms=run.model_latency_ms,
                    device_ms=run.device_latency_ms,
                    images=",".join(map(str, run.observation_images_used)),
                    terminal=run.terminal_reason or "—",
                    actions=" → ".join(run.actions) or "—",
                    failure=run.failure_classification or "—",
                )
            )
        lines.extend(
            [
                "",
                "## 判定",
                "",
                "- `prepare_disabled` 仅准备可复核的禁用初始状态。",
                "- `enable_existing` 必须执行状态改变，并由新截图确认启用。",
                "- 后两轮不得产生设备副作用，以证明重复运行不会创建或切换闹钟。",
                "- 任一失败、超时、不确定回执、缺少最新截图或部分完成都判失败并停止。",
                "- 报告不保存截图、任务原文、Token、密码、私钥、端点或实例标识。",
                "",
            ]
        )
        return "\n".join(lines)


def _write_private(path: Path, content: str) -> None:
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_CLOEXEC,
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(content.encode("utf-8"))
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("acceptance artifact write made no progress")
            remaining = remaining[written:]
    finally:
        os.close(descriptor)


def write_acceptance_reports(
    suite: KooPhoneAcceptanceSuite, output_directory: Path
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_private(output_directory / "acceptance-report.json", suite.to_json())
    _write_private(
        output_directory / "acceptance-report.md", suite.to_markdown()
    )


TaskExecutor = Callable[
    [KooPhoneAcceptanceScenario], Awaitable[KooPhoneAcceptanceExecution]
]


def _runner_failure(
    scenario: KooPhoneAcceptanceScenario,
) -> KooPhoneAcceptanceRun:
    return KooPhoneAcceptanceRun(
        scenario_slug=scenario.slug,
        scenario_name=scenario.name,
        phase=scenario.phase,
        run_id=str(uuid.uuid4()),
        success=False,
        steps=0,
        model_latency_ms=0,
        device_latency_ms=0,
        schema_retries=0,
        terminal_reason="runtime_failed",
        failure_classification="runner_error",
        actions=(),
        observation_images_used=(),
        visual_evidence=None,
        no_manual_intervention_attested=True,
        provider="kimi",
        model="kimi-k2.6",
        device_provider="koophone_mcp",
    )


async def run_acceptance_suite(
    execute_task: TaskExecutor,
    *,
    output_directory: Path,
    no_manual_intervention_attested: bool,
) -> KooPhoneAcceptanceSuite:
    """Run the state setup and acceptance matrix without interactive input."""

    results: list[KooPhoneAcceptanceRun] = []
    for scenario in ACCEPTANCE_SEQUENCE:
        try:
            execution = await execute_task(scenario)
            result = summarize_acceptance_run(
                scenario,
                execution,
                no_manual_intervention_attested=no_manual_intervention_attested,
            )
        except Exception:
            result = _runner_failure(scenario)
        results.append(result)
        suite = KooPhoneAcceptanceSuite.from_runs(results)
        write_acceptance_reports(suite, output_directory)
        if not result.success:
            break
    return KooPhoneAcceptanceSuite.from_runs(results)


class KooPhoneAgentAcceptanceExecutor:
    """Execute one phase through the production MobileUseAgent boundary."""

    def __init__(
        self,
        record_path: Path,
        agent_factory: Callable[..., MobileUseAgent] = MobileUseAgent,
    ) -> None:
        self.record_path = record_path
        self._agent_factory = agent_factory

    def _offset(self) -> int:
        return self.record_path.stat().st_size if self.record_path.exists() else 0

    def _records_since(self, offset: int) -> tuple[RunRecord, ...]:
        if not self.record_path.exists():
            return ()
        with self.record_path.open("rb") as record_file:
            record_file.seek(offset)
            lines = record_file.read().decode("utf-8").splitlines()
        return tuple(RunRecord.model_validate_json(line) for line in lines if line)

    async def __call__(
        self, scenario: KooPhoneAcceptanceScenario
    ) -> KooPhoneAcceptanceExecution:
        offset = self._offset()
        agent = self._agent_factory(
            model_provider_name="kimi",
            device_provider_name="koophone_mcp",
            experiment_record_path=self.record_path,
        )
        error: Exception | None = None
        try:
            await agent.initialize("", "", "", "", "", "")
            thread_id = str(uuid.uuid4())
            async for _ in agent.run(
                scenario.prompt,
                is_stream=False,
                task_id=f"koophone-acceptance-{scenario.slug}-{uuid.uuid4()}",
                session_id=thread_id,
                thread_id=thread_id,
                sse_connection=asyncio.Event(),
                phone_width=0,
                phone_height=0,
            ):
                pass
        except Exception as exc:
            error = exc
        finally:
            await agent.aclose()
        records = self._records_since(offset)
        if error is not None:
            raise error
        if not records:
            raise RuntimeError("Agent run produced no experiment records")
        return KooPhoneAcceptanceExecution(records=records)


def validate_acceptance_configuration() -> tuple[str, ...]:
    settings = get_settings()
    kimi = settings.get_kimi_config()
    koophone = settings.get_koophone_config()
    if kimi.model != "kimi-k2.6" or kimi.thinking_mode != "disabled":
        raise ValueError("Kimi K2.6 non-thinking mode is required")
    sensitive_values = (
        kimi.api_key.get_secret_value(),
        koophone.instance_id,
        koophone.mcp_url,
        koophone.iam_auth_url,
        koophone.iam_domain,
        koophone.iam_username,
        koophone.iam_password.get_secret_value(),
        koophone.jks_store_password.get_secret_value(),
        koophone.jks_key_password.get_secret_value(),
    )
    return tuple(value for value in sensitive_values if value)


def scan_delivery_artifacts(
    output_directory: Path, sensitive_values: Sequence[str]
) -> None:
    """Fail closed if reports or records contain private runtime material."""

    for path in output_directory.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("acceptance artifact privacy scan failed")
        content = path.read_text(encoding="utf-8")
        if contains_sensitive_text(content):
            raise ValueError("acceptance artifact privacy scan failed")
        if any(value in content for value in sensitive_values):
            raise ValueError("acceptance artifact contains local configuration")


def _replace_with_privacy_failure(output_directory: Path) -> None:
    """Remove unsafe candidate artifacts and leave one redacted failure marker."""

    for path in output_directory.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink()
    _write_private(
        output_directory / "acceptance-failure.json",
        json.dumps(
            {
                "passed": False,
                "failure_classification": "privacy_scan_failed",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


async def _async_main(
    output_directory: Path, *, no_manual_intervention_attested: bool
) -> int:
    sensitive_values = validate_acceptance_configuration()
    output_directory.mkdir(parents=True, exist_ok=True)
    if any(output_directory.iterdir()):
        raise ValueError("acceptance output directory must be empty")
    executor = KooPhoneAgentAcceptanceExecutor(
        output_directory / "experiment-runs.jsonl"
    )
    suite = await run_acceptance_suite(
        executor,
        output_directory=output_directory,
        no_manual_intervention_attested=no_manual_intervention_attested,
    )
    try:
        scan_delivery_artifacts(output_directory, sensitive_values)
    except Exception:
        _replace_with_privacy_failure(output_directory)
        raise
    print(
        json.dumps(
            {
                "passed": suite.passed,
                "runs": len(suite.runs),
                "privacy_scan": "passed",
                "report": str(output_directory / "acceptance-report.md"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if suite.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the real Kimi + KooPhone container demo acceptance"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--attest-no-manual-intervention",
        action="store_true",
        help="Attest that nobody will click, type, or add model input",
    )
    arguments = parser.parse_args(argv)
    if not arguments.attest_no_manual_intervention:
        parser.error("--attest-no-manual-intervention is required")
    try:
        return asyncio.run(
            _async_main(
                arguments.output_dir,
                no_manual_intervention_attested=True,
            )
        )
    except Exception:
        print(
            "KOOPHONE_ACCEPTANCE=failed reason=runtime_error",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
