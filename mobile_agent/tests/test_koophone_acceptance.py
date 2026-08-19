# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from mobile_agent.agent.experiments.records import RunRecord
from mobile_agent.koophone_acceptance import (
    ACCEPTANCE_SEQUENCE,
    KooPhoneAgentAcceptanceExecutor,
    KooPhoneAcceptanceExecution,
    KooPhoneAcceptanceSuite,
    _async_main,
    run_acceptance_suite,
    scan_delivery_artifacts,
    summarize_acceptance_run,
)


def make_record(
    *,
    run_id: str,
    step: int,
    action_type: str,
    action_status: str = "success",
    terminal_reason: str | None = None,
    images_used: int = 1,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        scenario_id="scenario-0123456789abcdef",
        provider="kimi",
        model="kimi-k2.6",
        step_number=step,
        action_type=action_type,
        action_arguments={},
        model_latency_ms=100,
        device_latency_ms=25 if action_type != "finish" else None,
        action_status=action_status,
        device_error_kind=None,
        schema_status="valid",
        terminal_reason=terminal_reason,
        oracle_result=None,
        observation_strategy="fixed_recent",
        observation_window_size=5,
        observation_images_used=images_used,
        device_provider="koophone_mcp",
    )


def completed_execution(*actions: str) -> KooPhoneAcceptanceExecution:
    run_id = str(uuid.uuid4())
    records = [
        make_record(
            run_id=run_id,
            step=index,
            action_type=action,
            terminal_reason="completed" if index == len(actions) else None,
        )
        for index, action in enumerate(actions, start=1)
    ]
    return KooPhoneAcceptanceExecution(records=records)


class KooPhoneAcceptanceSummaryTests(unittest.TestCase):
    def test_enable_scenario_requires_action_and_latest_visual_finish(self):
        scenario = next(
            item for item in ACCEPTANCE_SEQUENCE if item.slug == "enable_existing"
        )
        passed = summarize_acceptance_run(
            scenario,
            completed_execution("tap", "finish"),
            no_manual_intervention_attested=True,
        )
        missing_action = summarize_acceptance_run(
            scenario,
            completed_execution("finish"),
            no_manual_intervention_attested=True,
        )
        unrelated_action = summarize_acceptance_run(
            scenario,
            completed_execution("launch_app", "home", "finish"),
            no_manual_intervention_attested=True,
        )

        self.assertTrue(passed.success)
        self.assertEqual(passed.visual_evidence, "latest_screenshot_model_confirmed")
        self.assertEqual(passed.observation_images_used, (1, 1))
        self.assertFalse(missing_action.success)
        self.assertEqual(
            missing_action.failure_classification, "required_state_change_missing"
        )
        self.assertFalse(unrelated_action.success)
        self.assertEqual(
            unrelated_action.failure_classification,
            "required_state_change_missing",
        )

    def test_enabled_rerun_rejects_any_extra_device_side_effect(self):
        scenario = next(
            item for item in ACCEPTANCE_SEQUENCE if item.slug == "already_enabled"
        )
        clean = summarize_acceptance_run(
            scenario,
            completed_execution("finish"),
            no_manual_intervention_attested=True,
        )
        duplicate = summarize_acceptance_run(
            scenario,
            completed_execution("tap", "finish"),
            no_manual_intervention_attested=True,
        )

        self.assertTrue(clean.success)
        self.assertFalse(duplicate.success)
        self.assertEqual(
            duplicate.failure_classification, "unexpected_idempotent_side_effect"
        )


class KooPhoneAcceptanceSuiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_executor_uses_production_provider_seam_and_recorded_result(self):
        captured = {}

        class FakeAgent:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.record_path = kwargs["experiment_record_path"]

            async def initialize(self, *args):
                captured["initialized"] = args

            async def run(self, prompt, **kwargs):
                captured["prompt"] = prompt
                captured["run_kwargs"] = kwargs
                record = make_record(
                    run_id=str(uuid.uuid4()),
                    step=1,
                    action_type="finish",
                    terminal_reason="completed",
                )
                self.record_path.write_text(record.model_dump_json() + "\n")
                if False:
                    yield None

            async def aclose(self):
                captured["closed"] = True

        with tempfile.TemporaryDirectory() as directory:
            executor = KooPhoneAgentAcceptanceExecutor(
                Path(directory) / "records.jsonl",
                agent_factory=FakeAgent,
            )
            execution = await executor(ACCEPTANCE_SEQUENCE[2])

        self.assertEqual(captured["model_provider_name"], "kimi")
        self.assertEqual(captured["device_provider_name"], "koophone_mcp")
        self.assertEqual(captured["prompt"], ACCEPTANCE_SEQUENCE[2].prompt)
        self.assertFalse(captured["run_kwargs"]["is_stream"])
        self.assertTrue(captured["closed"])
        self.assertEqual(execution.records[-1].terminal_reason, "completed")

    async def test_suite_runs_disabled_enabled_and_two_idempotent_states(self):
        calls = []

        async def execute(scenario):
            calls.append(scenario.slug)
            if scenario.slug in {"prepare_disabled", "enable_existing"}:
                return completed_execution("tap", "finish")
            return completed_execution("finish")

        with tempfile.TemporaryDirectory() as directory:
            suite = await run_acceptance_suite(
                execute,
                output_directory=Path(directory),
                no_manual_intervention_attested=True,
            )
            markdown = (Path(directory) / "acceptance-report.md").read_text()
            json_report = (Path(directory) / "acceptance-report.json").read_text()

        self.assertEqual(calls, [scenario.slug for scenario in ACCEPTANCE_SEQUENCE])
        self.assertTrue(suite.passed)
        self.assertIn("KooPhone", markdown)
        self.assertIn("无 ADB Oracle", markdown)
        self.assertIn('"passed": true', json_report)
        self.assertNotIn("prompt", json_report)
        self.assertNotIn("data:image", json_report)

    async def test_partial_run_is_reported_failed_and_stops_following_actions(self):
        calls = []

        async def execute(scenario):
            calls.append(scenario.slug)
            if scenario.slug == "enable_existing":
                raise RuntimeError("upstream may contain secret text")
            return completed_execution("tap", "finish")

        with tempfile.TemporaryDirectory() as directory:
            suite = await run_acceptance_suite(
                execute,
                output_directory=Path(directory),
                no_manual_intervention_attested=True,
            )

        self.assertFalse(suite.passed)
        self.assertEqual(calls, ["prepare_disabled", "enable_existing"])
        self.assertEqual(
            suite.runs[-1].failure_classification, "runner_error"
        )


class KooPhoneAcceptancePrivacyTests(unittest.TestCase):
    def test_artifact_scan_rejects_screenshots_and_runtime_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            artifact = output / "report.md"
            artifact.write_text("safe report")
            scan_delivery_artifacts(output, ("runtime-secret-value",))

            artifact.write_text("data:image/png;base64,private-screen")
            with self.assertRaisesRegex(ValueError, "privacy scan"):
                scan_delivery_artifacts(output, ("runtime-secret-value",))

            artifact.write_text("runtime-secret-value")
            with self.assertRaisesRegex(ValueError, "local configuration"):
                scan_delivery_artifacts(output, ("runtime-secret-value",))

            artifact.write_text(
                "eyJhbGciOiJSUzI1NiJ9."
                "eyJzdWIiOiJpbnRlcm5hbC11c2VyIn0."
                "c2lnbmF0dXJlLXBsYWNlaG9sZGVy"
            )
            with self.assertRaisesRegex(ValueError, "privacy scan"):
                scan_delivery_artifacts(output, ())


class KooPhoneAcceptancePrivacyFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_privacy_failure_removes_success_reports_and_marks_failure(self):
        suite = KooPhoneAcceptanceSuite.from_runs(
            [
                summarize_acceptance_run(
                    scenario,
                    completed_execution(
                        *("tap", "finish")
                        if scenario.slug in {"prepare_disabled", "enable_existing"}
                        else ("finish",)
                    ),
                    no_manual_intervention_attested=True,
                )
                for scenario in ACCEPTANCE_SEQUENCE
            ]
        )

        async def write_success_then_return(*args, **kwargs):
            output = kwargs["output_directory"]
            (output / "acceptance-report.json").write_text(suite.to_json())
            (output / "acceptance-report.md").write_text(suite.to_markdown())
            (output / "experiment-runs.jsonl").write_text("unsafe artifact")
            return suite

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "acceptance"
            with (
                patch(
                    "mobile_agent.koophone_acceptance.validate_acceptance_configuration",
                    return_value=(),
                ),
                patch(
                    "mobile_agent.koophone_acceptance.run_acceptance_suite",
                    new=AsyncMock(side_effect=write_success_then_return),
                ),
                patch(
                    "mobile_agent.koophone_acceptance.scan_delivery_artifacts",
                    side_effect=ValueError("privacy scan failed"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "privacy scan failed"):
                    await _async_main(
                        output,
                        no_manual_intervention_attested=True,
                    )

            remaining = list(output.iterdir())
            self.assertEqual(
                [path.name for path in remaining], ["acceptance-failure.json"]
            )
            failure = remaining[0].read_text()
            self.assertIn('"passed": false', failure)
            self.assertIn('"failure_classification": "privacy_scan_failed"', failure)
            self.assertNotIn('"passed": true', failure)


if __name__ == "__main__":
    unittest.main()
