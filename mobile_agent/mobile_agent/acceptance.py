# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Repeatable Kimi + ADB demo acceptance and privacy-safe reporting."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Awaitable, Callable, Iterable, Sequence
import uuid

from mobile_agent.agent.experiments.records import (
    RunRecord,
    contains_sensitive_text,
)
from mobile_agent.agent.mobile.adb import AdbOracleEvidence
from mobile_agent.agent.mobile_use_agent import MobileUseAgent
from mobile_agent.config.settings import get_settings


@dataclass(frozen=True)
class AcceptanceScenario:
    slug: str
    name: str
    prompt: str
    requires_visual_tap: bool = False


ACCEPTANCE_SCENARIOS = (
    AcceptanceScenario(
        slug="open_app",
        name="从桌面视觉识别并打开高德地图",
        prompt="打开高德地图",
        requires_visual_tap=True,
    ),
    AcceptanceScenario(
        slug="search_bund",
        name="打开高德地图并搜索上海外滩",
        prompt="打开高德地图并搜索上海外滩",
    ),
    AcceptanceScenario(
        slug="open_first_result",
        name="搜索上海外滩并打开第一个搜索结果",
        prompt="打开高德地图，搜索上海外滩并打开第一个搜索结果",
    ),
)


@dataclass(frozen=True)
class AcceptanceExecution:
    records: Sequence[RunRecord]
    oracle_evidence: AdbOracleEvidence | None


@dataclass(frozen=True)
class AcceptanceRunResult:
    scenario_slug: str
    scenario_name: str
    attempt: int
    run_id: str
    success: bool
    steps: int
    model_latency_ms: int
    device_latency_ms: int
    schema_retries: int
    oracle_result: bool | None
    oracle_evidence: dict[str, bool | None]
    no_manual_intervention_attested: bool
    terminal_reason: str | None
    failure_classification: str | None
    actions: tuple[str, ...]
    provider: str
    model: str
    device_provider: str


def _failure_classification(
    scenario: AcceptanceScenario,
    records: Sequence[RunRecord],
    *,
    steps: int,
    actions: tuple[str, ...],
    oracle_result: bool | None,
    terminal_reason: str | None,
    no_manual_intervention_attested: bool,
    oracle_evidence: AdbOracleEvidence | None,
) -> str | None:
    if not no_manual_intervention_attested:
        return "manual_intervention_not_attested"
    if any(
        record.schema_status == "invalid"
        and record.action_status != "not_executed"
        for record in records
    ):
        return "unblocked_schema_error"
    if any(record.action_status == "unsupported" for record in records):
        return "unsupported_action"
    if steps > 10:
        return "step_limit_exceeded"
    if scenario.requires_visual_tap and (
        "tap" not in actions or "launch_app" in actions
    ):
        return "visual_tap_required"
    if any(record.action_status == "ambiguous" for record in records):
        return "ambiguous_action"
    if terminal_reason != "completed":
        return terminal_reason or "missing_terminal_reason"
    if oracle_result is not True:
        return "oracle_failed"
    if not _oracle_evidence_satisfies_scenario(scenario, oracle_evidence):
        return "oracle_evidence_missing"
    return None


def _oracle_evidence_satisfies_scenario(
    scenario: AcceptanceScenario,
    evidence: AdbOracleEvidence | None,
) -> bool:
    if evidence is None or evidence.foreground_package_match is not True:
        return False
    if scenario.slug == "search_bund":
        return evidence.query_text_visible is True
    if scenario.slug == "open_first_result":
        return (
            evidence.detail_title_visible is True
            and evidence.favorite_control_visible is True
        )
    return scenario.slug == "open_app"


def summarize_run(
    scenario: AcceptanceScenario,
    attempt: int,
    execution: AcceptanceExecution,
    *,
    no_manual_intervention_attested: bool,
) -> AcceptanceRunResult:
    """Summarize one Agent run from its validated experiment records."""

    records = execution.records
    if not records:
        raise ValueError("acceptance run has no experiment records")
    run_ids = {record.run_id for record in records}
    if len(run_ids) != 1:
        raise ValueError("acceptance records must belong to one run")
    steps = max(record.step_number for record in records)
    actions = tuple(record.action_type for record in records)
    oracle_results = [
        record.oracle_result
        for record in records
        if record.oracle_result is not None
    ]
    oracle_result = oracle_results[-1] if oracle_results else None
    terminal_reasons = [
        record.terminal_reason
        for record in records
        if record.terminal_reason is not None
    ]
    terminal_reason = terminal_reasons[-1] if terminal_reasons else None
    failure_classification = _failure_classification(
        scenario,
        records,
        steps=steps,
        actions=actions,
        oracle_result=oracle_result,
        terminal_reason=terminal_reason,
        no_manual_intervention_attested=no_manual_intervention_attested,
        oracle_evidence=execution.oracle_evidence,
    )
    final_record = records[-1]
    return AcceptanceRunResult(
        scenario_slug=scenario.slug,
        scenario_name=scenario.name,
        attempt=attempt,
        run_id=final_record.run_id,
        success=failure_classification is None,
        steps=steps,
        model_latency_ms=sum(record.model_latency_ms for record in records),
        device_latency_ms=sum(
            record.device_latency_ms or 0 for record in records
        ),
        schema_retries=sum(
            record.schema_status == "invalid" for record in records
        ),
        oracle_result=oracle_result,
        oracle_evidence=(
            asdict(execution.oracle_evidence)
            if execution.oracle_evidence is not None
            else {}
        ),
        no_manual_intervention_attested=no_manual_intervention_attested,
        terminal_reason=terminal_reason,
        failure_classification=failure_classification,
        actions=actions,
        provider=final_record.provider,
        model=final_record.model,
        device_provider=final_record.device_provider,
    )


@dataclass(frozen=True)
class AcceptanceSuiteResult:
    runs: tuple[AcceptanceRunResult, ...]
    passed: bool
    total_successes: int
    scenario_successes: dict[str, int]
    doubao_mcp_adapter_test: str = "not_run"
    doubao_mcp_real_regression: str = "not_run"

    @classmethod
    def from_runs(
        cls,
        runs: Iterable[AcceptanceRunResult],
        *,
        doubao_mcp_adapter_test: str = "not_run",
        doubao_mcp_real_regression: str = "not_run",
    ) -> "AcceptanceSuiteResult":
        resolved_runs = tuple(runs)
        successes = Counter(
            run.scenario_slug for run in resolved_runs if run.success
        )
        expected_slugs = {scenario.slug for scenario in ACCEPTANCE_SCENARIOS}
        counts = Counter(run.scenario_slug for run in resolved_runs)
        exact_matrix = len(resolved_runs) == 9 and all(
            counts[slug] == 3 for slug in expected_slugs
        )
        total_successes = sum(run.success for run in resolved_runs)
        scenario_successes = {
            scenario.slug: successes[scenario.slug]
            for scenario in ACCEPTANCE_SCENARIOS
        }
        passed = (
            exact_matrix
            and total_successes >= 8
            and all(value >= 2 for value in scenario_successes.values())
        )
        return cls(
            runs=resolved_runs,
            passed=passed,
            total_successes=total_successes,
            scenario_successes=scenario_successes,
            doubao_mcp_adapter_test=doubao_mcp_adapter_test,
            doubao_mcp_real_regression=doubao_mcp_real_regression,
        )

    def to_markdown(self, *, generated_at: datetime | None = None) -> str:
        timestamp = generated_at or datetime.now(timezone.utc)
        outcome = "通过" if self.passed else "未通过"
        lines = [
            "# Kimi K2.6 + ADB Demo 九轮实机验收报告",
            "",
            f"- 生成时间：{timestamp.astimezone(timezone.utc).isoformat()}",
            "- 路径：Kimi K2.6 + ADB（非思考、JSON Mode）",
            "- 设备执行：ADB；Go MCP 不参与 Kimi + ADB 动作执行",
            f"- 结论：**{outcome}**（{self.total_successes}/9）",
            "- 门槛：总成功数至少 8/9，且每个场景至少 2/3",
            "- 无人工干预声明：已逐轮显式确认",
            "",
            "## 九轮结果",
            "",
            (
                "| 场景 | 轮次 | 结果 | 步骤 | 模型耗时(ms) | 设备耗时(ms) "
                "| Schema 重试 | Oracle | 失败分类 | 动作序列 |"
            ),
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
        for run in self.runs:
            lines.append(
                "| {scenario} | {attempt} | {result} | {steps} | {model} | "
                "{device} | {schema} | {oracle} | {failure} | {actions} |".format(
                    scenario=run.scenario_name,
                    attempt=run.attempt,
                    result="成功" if run.success else "失败",
                    steps=run.steps,
                    model=run.model_latency_ms,
                    device=run.device_latency_ms,
                    schema=run.schema_retries,
                    oracle=(f"{str(run.oracle_result).lower()}; " + "; ".join(
                        f"{key}={str(value).lower()}"
                        for key, value in run.oracle_evidence.items()
                        if value is not None
                    )),
                    failure=run.failure_classification or "—",
                    actions=" → ".join(run.actions),
                )
            )
        lines.extend(
            [
                "",
                "## 场景汇总",
                "",
                *(
                    f"- `{scenario.slug}`：{self.scenario_successes[scenario.slug]}/3"
                    for scenario in ACCEPTANCE_SCENARIOS
                ),
                "",
                "## Doubao + 火山 MCP 兼容性",
                "",
                f"- Doubao/MCP 适配器单元测试：`{self.doubao_mcp_adapter_test}`",
                f"- 真实 Doubao + 火山 MCP 回归：`{self.doubao_mcp_real_regression}`",
                "- 适配器测试不启动 Go MCP，不作为真实 MCP 链路通过证据。",
                "",
                "## 判定说明",
                "",
                "- 每轮开始由 ADB Backend 强制停止高德地图并返回 Home；不执行 `pm clear`。",
                "- 每轮最多十个 Agent 步骤；执行期间脚本不接受人工点击、输入或纠正。",
                "- Schema 错误只有标记为 `not_executed` 才视为已拦截；未拦截错误直接判失败。",
                "- 未知/不支持动作、Oracle 未通过、动作回执不确定或缺少终止原因均判失败。",
                "- 报告只使用脱敏 JSONL，不包含截图、任务原文、凭证、ADB 私钥或设备临时地址。",
                "",
            ]
        )
        return "\n".join(lines)

    def to_json(self) -> str:
        payload = {
            "schema_version": 1,
            "passed": self.passed,
            "total_successes": self.total_successes,
            "total_runs": len(self.runs),
            "scenario_successes": self.scenario_successes,
            "doubao_mcp_adapter_test": self.doubao_mcp_adapter_test,
            "doubao_mcp_real_regression": self.doubao_mcp_real_regression,
            "runs": [asdict(run) for run in self.runs],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


TaskExecutor = Callable[
    [AcceptanceScenario, int], Awaitable[AcceptanceExecution]
]


def _runner_failure(
    scenario: AcceptanceScenario, attempt: int
) -> AcceptanceRunResult:
    return AcceptanceRunResult(
        scenario_slug=scenario.slug,
        scenario_name=scenario.name,
        attempt=attempt,
        run_id=str(uuid.uuid4()),
        success=False,
        steps=0,
        model_latency_ms=0,
        device_latency_ms=0,
        schema_retries=0,
        oracle_result=None,
        oracle_evidence={},
        no_manual_intervention_attested=False,
        terminal_reason="runtime_failed",
        failure_classification="runner_error",
        actions=(),
        provider="kimi",
        model="kimi-k2.6",
        device_provider="adb",
    )


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
                raise OSError("acceptance report write made no progress")
            remaining = remaining[written:]
    finally:
        os.close(descriptor)


def write_acceptance_reports(
    suite: AcceptanceSuiteResult, output_directory: Path
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_private(
        output_directory / "acceptance-report.md", suite.to_markdown()
    )
    _write_private(
        output_directory / "acceptance-report.json", suite.to_json()
    )


async def run_acceptance_suite(
    execute_task: TaskExecutor,
    *,
    output_directory: Path,
    doubao_mcp_adapter_test: str,
    no_manual_intervention_attested: bool,
    doubao_mcp_real_regression: str = "not_run",
) -> AcceptanceSuiteResult:
    """Execute the fixed three-by-three acceptance matrix without user input."""

    results: list[AcceptanceRunResult] = []
    for scenario in ACCEPTANCE_SCENARIOS:
        for attempt in range(1, 4):
            try:
                execution = await execute_task(scenario, attempt)
                result = summarize_run(
                    scenario,
                    attempt,
                    execution,
                    no_manual_intervention_attested=(
                        no_manual_intervention_attested
                    ),
                )
            except Exception:
                result = _runner_failure(scenario, attempt)
            results.append(result)
            write_acceptance_reports(
                AcceptanceSuiteResult.from_runs(
                    results,
                    doubao_mcp_adapter_test=doubao_mcp_adapter_test,
                    doubao_mcp_real_regression=doubao_mcp_real_regression,
                ),
                output_directory,
            )
    return AcceptanceSuiteResult.from_runs(
        results,
        doubao_mcp_adapter_test=doubao_mcp_adapter_test,
        doubao_mcp_real_regression=doubao_mcp_real_regression,
    )


class AgentAcceptanceExecutor:
    """Run one scenario through the real Agent boundary and return new records."""

    def __init__(
        self,
        record_path: Path,
        agent_factory: Callable[..., MobileUseAgent] = MobileUseAgent,
    ):
        self.record_path = record_path
        self._agent_factory = agent_factory

    def _offset(self) -> int:
        return self.record_path.stat().st_size if self.record_path.exists() else 0

    def _records_since(self, offset: int) -> list[RunRecord]:
        if not self.record_path.exists():
            return []
        with self.record_path.open("rb") as record_file:
            record_file.seek(offset)
            lines = record_file.read().decode("utf-8").splitlines()
        return [RunRecord.model_validate_json(line) for line in lines if line]

    async def __call__(
        self, scenario: AcceptanceScenario, attempt: int
    ) -> AcceptanceExecution:
        offset = self._offset()
        agent = self._agent_factory(
            model_provider_name="kimi",
            device_provider_name="adb",
            experiment_record_path=self.record_path,
        )
        error: Exception | None = None
        try:
            await agent.initialize("", "", "", "", "", "")
            thread_id = str(uuid.uuid4())
            async for _ in agent.run(
                scenario.prompt,
                is_stream=False,
                task_id=f"acceptance-{scenario.slug}-{attempt}",
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
        if records:
            evidence = getattr(
                agent.device_backend, "last_completion_evidence", None
            )
            return AcceptanceExecution(
                records=records,
                oracle_evidence=(
                    evidence if isinstance(evidence, AdbOracleEvidence) else None
                ),
            )
        raise RuntimeError("Agent run produced no experiment records")


def run_doubao_mcp_adapter_test() -> str:
    """Run the deterministic adapter unit test without starting Go MCP."""

    component_directory = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.test_doubao_mcp_compatibility",
        ],
        cwd=component_directory,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return "passed" if result.returncode == 0 else "failed"


def validate_acceptance_configuration() -> tuple[str, ...]:
    """Validate required local values while returning only secret values to scan."""

    settings = get_settings()
    kimi = settings.get_kimi_config()
    adb = settings.get_adb_config()
    if settings.model_provider != "kimi":
        raise ValueError("MODEL_PROVIDER must be kimi for acceptance")
    if settings.device_provider != "adb":
        raise ValueError("DEVICE_PROVIDER must be adb for acceptance")
    if kimi.model != "kimi-k2.6":
        raise ValueError("KIMI_MODEL must be kimi-k2.6 for acceptance")
    sensitive_values = [kimi.api_key.get_secret_value(), adb.serial]
    if adb.vendor_keys is not None:
        sensitive_values.append(adb.vendor_keys.get_secret_value())
    return tuple(value for value in sensitive_values if value)


def scan_acceptance_artifacts(
    output_directory: Path, sensitive_values: Sequence[str]
) -> None:
    """Fail closed if runtime artifacts retain observations or local secrets."""

    for path in output_directory.iterdir():
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        if contains_sensitive_text(content):
            raise ValueError("acceptance artifact privacy scan failed")
        if any(value in content for value in sensitive_values):
            raise ValueError("acceptance artifact contains local configuration")


def _default_output_directory() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("logs") / f"acceptance-{timestamp}"


async def _async_main(
    output_directory: Path, *, no_manual_intervention_attested: bool
) -> int:
    sensitive_values = validate_acceptance_configuration()
    output_directory.mkdir(parents=True, exist_ok=False)
    adapter_test = run_doubao_mcp_adapter_test()
    executor = AgentAcceptanceExecutor(
        output_directory / "experiment-runs.jsonl"
    )
    suite = await run_acceptance_suite(
        executor,
        output_directory=output_directory,
        doubao_mcp_adapter_test=adapter_test,
        no_manual_intervention_attested=no_manual_intervention_attested,
    )
    scan_acceptance_artifacts(output_directory, sensitive_values)
    print(
        json.dumps(
            {
                "passed": suite.passed,
                "successes": f"{suite.total_successes}/9",
                "scenario_successes": suite.scenario_successes,
                "doubao_mcp_adapter_test": adapter_test,
                "doubao_mcp_real_regression": "not_run",
                "report": str(output_directory / "acceptance-report.md"),
                "privacy_scan": "passed",
            },
            ensure_ascii=False,
        )
    )
    return 0 if suite.passed and adapter_test == "passed" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed nine-run Kimi + ADB demo acceptance"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="New directory for private JSONL and sanitized reports",
    )
    parser.add_argument(
        "--attest-no-manual-intervention",
        action="store_true",
        help=(
            "Explicitly attest that nobody will click, type, or correct the "
            "device during all nine runs"
        ),
    )
    arguments = parser.parse_args(argv)
    if not arguments.attest_no_manual_intervention:
        parser.error("--attest-no-manual-intervention is required")
    return asyncio.run(
        _async_main(
            arguments.output_dir or _default_output_directory(),
            no_manual_intervention_attested=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
