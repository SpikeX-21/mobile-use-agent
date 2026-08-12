# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path

from mobile_agent.acceptance import (
    ACCEPTANCE_SCENARIOS,
    AcceptanceExecution,
    AcceptanceSuiteResult,
    AgentAcceptanceExecutor,
    run_acceptance_suite,
    scan_acceptance_artifacts,
    summarize_run,
)
from mobile_agent.agent.experiments.records import RunRecord
from mobile_agent.agent.mobile.adb import AdbOracleEvidence


def make_record(
    *,
    run_id: str,
    step: int,
    action_type: str,
    action_status: str = "success",
    schema_status: str = "valid",
    model_latency_ms: int = 100,
    device_latency_ms: int | None = 20,
    terminal_reason: str | None = None,
    oracle_result: bool | None = None,
) -> RunRecord:
    action_arguments = {"x": 500, "y": 500} if action_type == "tap" else {}
    return RunRecord(
        run_id=run_id,
        scenario_id="scenario-a1b2c3d4e5f60718",
        provider="kimi",
        model="kimi-k2.6",
        step_number=step,
        action_type=action_type,
        action_arguments=action_arguments,
        model_latency_ms=model_latency_ms,
        device_latency_ms=device_latency_ms,
        action_status=action_status,
        schema_status=schema_status,
        terminal_reason=terminal_reason,
        oracle_result=oracle_result,
        observation_strategy="fixed_recent",
        observation_window_size=5,
        observation_images_used=min(step, 5),
        device_provider="adb",
    )


def make_execution(records, scenario_slug="open_app"):
    evidence = {
        "open_app": AdbOracleEvidence(foreground_package_match=True),
        "search_bund": AdbOracleEvidence(
            foreground_package_match=True,
            query_text_visible=True,
        ),
        "open_first_result": AdbOracleEvidence(
            foreground_package_match=True,
            detail_title_visible=True,
            favorite_control_visible=True,
        ),
    }[scenario_slug]
    return AcceptanceExecution(records=records, oracle_evidence=evidence)


class AcceptanceRunSummaryTests(unittest.TestCase):
    def test_successful_visual_open_records_metrics_and_oracle_evidence(self):
        run_id = str(uuid.uuid4())
        records = [
            make_record(
                run_id=run_id,
                step=1,
                action_type="invalid_action",
                action_status="not_executed",
                schema_status="invalid",
                model_latency_ms=90,
                device_latency_ms=None,
            ),
            make_record(
                run_id=run_id,
                step=2,
                action_type="tap",
                model_latency_ms=110,
                device_latency_ms=35,
            ),
            make_record(
                run_id=run_id,
                step=3,
                action_type="finish",
                model_latency_ms=120,
                device_latency_ms=25,
                terminal_reason="completed",
                oracle_result=True,
            ),
        ]

        result = summarize_run(
            ACCEPTANCE_SCENARIOS[0],
            1,
            make_execution(records),
            no_manual_intervention_attested=True,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.steps, 3)
        self.assertEqual(result.model_latency_ms, 320)
        self.assertEqual(result.device_latency_ms, 60)
        self.assertEqual(result.schema_retries, 1)
        self.assertEqual(result.actions, ("invalid_action", "tap", "finish"))
        self.assertEqual(result.oracle_result, True)
        self.assertEqual(
            result.oracle_evidence,
            {
                "foreground_package_match": True,
                "query_text_visible": None,
                "detail_title_visible": None,
                "favorite_control_visible": None,
            },
        )
        self.assertIsNone(result.failure_classification)

    def test_unblocked_schema_error_is_always_a_failure(self):
        run_id = str(uuid.uuid4())
        records = [
            make_record(
                run_id=run_id,
                step=1,
                action_type="tap",
                action_status="success",
                schema_status="invalid",
            ),
            make_record(
                run_id=run_id,
                step=2,
                action_type="finish",
                terminal_reason="completed",
                oracle_result=True,
            ),
        ]

        result = summarize_run(
            ACCEPTANCE_SCENARIOS[0],
            1,
            make_execution(records),
            no_manual_intervention_attested=True,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_classification, "unblocked_schema_error")

    def test_open_app_requires_visual_tap_and_rejects_launch_app(self):
        run_id = str(uuid.uuid4())
        records = [
            make_record(run_id=run_id, step=1, action_type="launch_app"),
            make_record(
                run_id=run_id,
                step=2,
                action_type="finish",
                terminal_reason="completed",
                oracle_result=True,
            ),
        ]

        result = summarize_run(
            ACCEPTANCE_SCENARIOS[0],
            1,
            make_execution(records),
            no_manual_intervention_attested=True,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_classification, "visual_tap_required")

    def test_missing_no_manual_intervention_attestation_is_a_failure(self):
        run_id = str(uuid.uuid4())
        records = [
            make_record(run_id=run_id, step=1, action_type="tap"),
            make_record(
                run_id=run_id,
                step=2,
                action_type="finish",
                terminal_reason="completed",
                oracle_result=True,
            ),
        ]

        result = summarize_run(
            ACCEPTANCE_SCENARIOS[0],
            1,
            make_execution(records),
            no_manual_intervention_attested=False,
        )

        self.assertFalse(result.success)
        self.assertEqual(
            result.failure_classification,
            "manual_intervention_not_attested",
        )

    def test_missing_actual_oracle_evidence_is_a_failure(self):
        run_id = str(uuid.uuid4())
        records = [
            make_record(run_id=run_id, step=1, action_type="tap"),
            make_record(
                run_id=run_id,
                step=2,
                action_type="finish",
                terminal_reason="completed",
                oracle_result=True,
            ),
        ]

        result = summarize_run(
            ACCEPTANCE_SCENARIOS[0],
            1,
            AcceptanceExecution(records=records, oracle_evidence=None),
            no_manual_intervention_attested=True,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_classification, "oracle_evidence_missing")

    def test_search_requires_actual_query_text_evidence(self):
        run_id = str(uuid.uuid4())
        records = [
            make_record(run_id=run_id, step=1, action_type="tap"),
            make_record(
                run_id=run_id,
                step=2,
                action_type="finish",
                terminal_reason="completed",
                oracle_result=True,
            ),
        ]

        result = summarize_run(
            ACCEPTANCE_SCENARIOS[1],
            1,
            AcceptanceExecution(
                records=records,
                oracle_evidence=AdbOracleEvidence(
                    foreground_package_match=True
                ),
            ),
            no_manual_intervention_attested=True,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_classification, "oracle_evidence_missing")

    def test_detail_requires_title_and_favorite_evidence(self):
        run_id = str(uuid.uuid4())
        records = [
            make_record(run_id=run_id, step=1, action_type="tap"),
            make_record(
                run_id=run_id,
                step=2,
                action_type="finish",
                terminal_reason="completed",
                oracle_result=True,
            ),
        ]

        result = summarize_run(
            ACCEPTANCE_SCENARIOS[2],
            1,
            AcceptanceExecution(
                records=records,
                oracle_evidence=AdbOracleEvidence(
                    foreground_package_match=True,
                    detail_title_visible=True,
                ),
            ),
            no_manual_intervention_attested=True,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_classification, "oracle_evidence_missing")


class AcceptanceSuiteResultTests(unittest.TestCase):
    def test_nine_runs_pass_at_eight_successes_with_each_scenario_at_least_two(self):
        run_id = str(uuid.uuid4())
        successful_records = [
            make_record(run_id=run_id, step=1, action_type="tap"),
            make_record(
                run_id=run_id,
                step=2,
                action_type="finish",
                terminal_reason="completed",
                oracle_result=True,
            ),
        ]
        failed_records = [
            make_record(
                run_id=str(uuid.uuid4()),
                step=1,
                action_type="fail",
                action_status="failed",
                terminal_reason="model_failed",
                oracle_result=False,
            )
        ]
        runs = []
        for scenario in ACCEPTANCE_SCENARIOS:
            for attempt in range(1, 4):
                records = (
                    failed_records
                    if scenario.slug == "open_first_result" and attempt == 3
                    else successful_records
                )
                runs.append(
                    summarize_run(
                        scenario,
                        attempt,
                        make_execution(records, scenario.slug),
                        no_manual_intervention_attested=True,
                    )
                )

        suite = AcceptanceSuiteResult.from_runs(runs)

        self.assertTrue(suite.passed)
        self.assertEqual(suite.total_successes, 8)
        self.assertEqual(
            suite.scenario_successes,
            {"open_app": 3, "search_bund": 3, "open_first_result": 2},
        )
        markdown = suite.to_markdown()
        self.assertIn("8/9", markdown)
        self.assertIn("Kimi K2.6 + ADB", markdown)
        self.assertIn("Go MCP 不参与", markdown)
        self.assertNotIn("203.0.113.10:10001", markdown)
        self.assertNotIn("sk-private", markdown)


class AcceptanceSuiteRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_executes_each_scenario_three_times_and_writes_reports(self):
        calls = []

        async def execute_task(scenario, attempt):
            calls.append((scenario.slug, attempt))
            run_id = str(uuid.uuid4())
            return make_execution(
                [
                    make_record(run_id=run_id, step=1, action_type="tap"),
                    make_record(
                        run_id=run_id,
                        step=2,
                        action_type="finish",
                        terminal_reason="completed",
                        oracle_result=True,
                    ),
                ],
                scenario.slug,
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            suite = await run_acceptance_suite(
                execute_task,
                output_directory=Path(temporary_directory),
                doubao_mcp_adapter_test="passed",
                no_manual_intervention_attested=True,
            )
            markdown = (Path(temporary_directory) / "acceptance-report.md").read_text(
                encoding="utf-8"
            )
            json_report = (Path(temporary_directory) / "acceptance-report.json").read_text(
                encoding="utf-8"
            )

        self.assertEqual(
            calls,
            [
                (scenario.slug, attempt)
                for scenario in ACCEPTANCE_SCENARIOS
                for attempt in range(1, 4)
            ],
        )
        self.assertTrue(suite.passed)
        self.assertIn("9/9", markdown)
        self.assertIn('"passed": true', json_report)
        self.assertNotIn('"prompt"', json_report)

    async def test_completed_records_followed_by_agent_error_fail_the_run(self):
        run_id = str(uuid.uuid4())
        record = make_record(
            run_id=run_id,
            step=1,
            action_type="finish",
            terminal_reason="completed",
            oracle_result=True,
        )

        class FakeBackend:
            last_completion_evidence = AdbOracleEvidence(
                foreground_package_match=True
            )

        class FailingAgent:
            device_backend = FakeBackend()

            def __init__(self, record_path):
                self.record_path = Path(record_path)

            async def initialize(self, *args):
                return self

            async def run(self, *args, **kwargs):
                self.record_path.write_text(
                    record.model_dump_json() + "\n", encoding="utf-8"
                )
                if False:
                    yield None
                raise RuntimeError("post-record failure")

            async def aclose(self):
                return None

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"
            executor = AgentAcceptanceExecutor(
                path,
                agent_factory=lambda **kwargs: FailingAgent(
                    kwargs["experiment_record_path"]
                ),
            )
            with self.assertRaisesRegex(RuntimeError, "post-record failure"):
                await executor(ACCEPTANCE_SCENARIOS[0], 1)


class AcceptancePrivacyTests(unittest.TestCase):
    def test_scan_rejects_alternate_secret_and_signed_url_forms(self):
        unsafe_values = (
            "authorization: Basic abc",
            "https://example.test/object?x-amz-signature=abc",
            "-----BEGIN RSA PRIVATE KEY-----",
            "sk-abcdefghijklmnopqrstuvwxyz1234",
        )
        for unsafe in unsafe_values:
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as directory:
                Path(directory, "report.md").write_text(unsafe, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "privacy scan failed"):
                    scan_acceptance_artifacts(Path(directory), ())


if __name__ == "__main__":
    unittest.main()
