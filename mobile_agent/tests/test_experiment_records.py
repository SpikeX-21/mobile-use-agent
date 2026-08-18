# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import stat
import tempfile
import unittest
import uuid
from pathlib import Path

from pydantic import ValidationError

from mobile_agent.agent.actions import FinishAction, TapAction, TextInputAction
from mobile_agent.agent.actions.mcp_adapter import canonical_action_to_mcp_tool_call
from mobile_agent.agent.experiments.records import (
    ExperimentRun,
    JsonlExperimentRecorder,
    RunRecord,
    redact_action_arguments,
    redact_mapping,
)
from mobile_agent.agent.llm.provider import ActionParseError
from mobile_agent.agent.mobile.result import (
    ActionResult,
    DeviceBackendError,
    DeviceErrorKind,
)
from mobile_agent.agent.mobile_use_agent import MobileUseAgent
from mobile_agent.exception.sse import SSEException


class RecordingProvider:
    name = "kimi"
    model = "kimi-k2.6"
    prompt = "test prompt"
    supports_streaming = False

    def __init__(self):
        self.actions = [TapAction(x=250, y=750), FinishAction(summary="done")]

    async def async_chat(self, messages):
        action = self.actions[0]
        return (str(uuid.uuid4()), action.type, action.type, action.type)

    def parse_action(self, action_call):
        return self.actions.pop(0)


class RecordingBackend:
    name = "adb"

    async def initialize(self, **connection):
        return None

    async def close(self):
        return None

    async def take_screenshot(self):
        return {
            "screenshot": "data:image/png;base64,must-not-be-recorded",
            "screenshot_dimensions": (1080, 2278),
        }

    def to_tool_call(self, action, screenshot_dimensions):
        return canonical_action_to_mcp_tool_call(action, screenshot_dimensions)

    async def execute(self, action, screenshot_dimensions):
        return ActionResult.success("tap dispatched")

    async def verify_completion(self, action):
        return True


class InvalidSchemaProvider(RecordingProvider):
    def __init__(self):
        self.actions = []

    async def async_chat(self, messages):
        return (str(uuid.uuid4()), "hidden model output", "invalid", "invalid")

    def parse_action(self, action_call):
        raise ActionParseError("invalid")


class OfflineBackend(RecordingBackend):
    async def execute(self, action, screenshot_dimensions):
        return ActionResult.failed("device offline", DeviceErrorKind.OFFLINE)


class ObservationFailureBackend(RecordingBackend):
    async def take_screenshot(self):
        raise DeviceBackendError(
            "invalid screenshot at https://example.test/s.png?X-Tos-Signature=secret",
            kind=DeviceErrorKind.INVALID_OBSERVATION,
        )


class PreparationFailureBackend(RecordingBackend):
    async def prepare_task(self, query):
        raise DeviceBackendError("device offline", kind=DeviceErrorKind.OFFLINE)


class ModelFailureProvider(RecordingProvider):
    async def async_chat(self, messages):
        raise RuntimeError("Authorization: Bearer private-model-token")


class CancelledModelProvider(RecordingProvider):
    async def async_chat(self, messages):
        raise asyncio.CancelledError


class CancelledPreparationBackend(RecordingBackend):
    async def prepare_task(self, query):
        raise asyncio.CancelledError


class CancelledToolBackend(RecordingBackend):
    async def execute(self, action, screenshot_dimensions):
        raise asyncio.CancelledError


class ProviderConstructionError(RuntimeError):
    pass


class ExperimentRecordTests(unittest.TestCase):
    def test_terminal_business_outcome_survives_recorder_failure(self):
        class BrokenRecorder:
            def write(self, record):
                raise OSError("disk unavailable")

        run = ExperimentRun(
            recorder=BrokenRecorder(),
            query="ensure alarm",
            provider="kimi",
            model="kimi-k2.6",
            device_provider="koophone_mcp",
        )

        recorded = run.try_record_step(
            step_number=1,
            action=FinishAction(summary="09:00 enabled"),
            model_latency_ms=1,
            device_latency_ms=None,
            action_status="success",
            schema_status="valid",
            terminal_reason="completed",
            observation_images_used=1,
        )

        self.assertFalse(recorded)
        self.assertEqual(run.terminal_reason, "completed")

    @staticmethod
    def make_record(run_id=None):
        return RunRecord(
            run_id=run_id or str(uuid.uuid4()),
            scenario_id="scenario-1234567890abcdef",
            provider="kimi",
            model="kimi-k2.6",
            step_number=1,
            action_type="tap",
            action_arguments={"x": 250, "y": 750},
            model_latency_ms=125,
            device_latency_ms=42,
            action_status="success",
            schema_status="valid",
            observation_strategy="fixed_recent",
            observation_window_size=5,
            observation_images_used=1,
            device_provider="adb",
        )

    def test_writes_comparable_jsonl_without_screenshots_or_secrets(self):
        secret_samples = {
            "api_key": "sk-secret-model-key",
            "ACEP_AK": "AKLT-secret-access-key",
            "ACEP_SK": "secret-access-secret",
            "Authorization": "Bearer secret-token",
            "adb_private_key": "-----BEGIN PRIVATE KEY-----secret",
            "screenshot": "data:image/png;base64,private-screen",
            "signed_url": "https://example.test/a.png?X-Tos-Signature=private-signature",
            "hidden_thinking": "private chain of thought",
            "model_credential": "sk-abcdefghijklmnopqrstuvwxyz123456",
            "request_context": "Bearer unlabelled-private-token",
        }
        private_text = "张三的手机号 13800138000"

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"
            recorder = JsonlExperimentRecorder(path)
            record = RunRecord(
                run_id="12345678-1234-4123-8123-123456789abc",
                scenario_id="scenario-a1b2c3d4e5f60718",
                provider="kimi",
                model="kimi-k2.6",
                step_number=1,
                action_type="text_input",
                action_arguments=redact_action_arguments(
                    TextInputAction(text=private_text)
                ),
                model_latency_ms=125,
                device_latency_ms=42,
                action_status="success",
                device_error_kind=None,
                schema_status="valid",
                terminal_reason=None,
                oracle_result=None,
                observation_strategy="fixed_recent",
                observation_window_size=5,
                observation_images_used=1,
                device_provider="adb",
                observation_policy_version=1,
            )

            recorder.write(record)

            raw_line = path.read_text(encoding="utf-8").strip()
            payload = json.loads(raw_line)
            file_mode = stat.S_IMODE(path.stat().st_mode)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(file_mode, 0o600)
        self.assertEqual(payload["run_id"], "12345678-1234-4123-8123-123456789abc")
        self.assertEqual(payload["scenario_id"], "scenario-a1b2c3d4e5f60718")
        self.assertEqual(payload["provider"], "kimi")
        self.assertEqual(payload["model"], "kimi-k2.6")
        self.assertEqual(payload["step_number"], 1)
        self.assertEqual(payload["action_type"], "text_input")
        self.assertEqual(payload["action_arguments"]["text"]["length"], len(private_text))
        self.assertRegex(payload["action_arguments"]["text"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(payload["model_latency_ms"], 125)
        self.assertEqual(payload["device_latency_ms"], 42)
        self.assertEqual(payload["action_status"], "success")
        self.assertIsNone(payload["device_error_kind"])
        self.assertEqual(payload["schema_status"], "valid")
        self.assertEqual(payload["observation_strategy"], "fixed_recent")
        self.assertEqual(payload["observation_window_size"], 5)
        self.assertEqual(payload["observation_images_used"], 1)
        self.assertNotIn(private_text, raw_line)
        redacted_samples = json.dumps(redact_mapping(secret_samples))
        for secret in secret_samples.values():
            self.assertNotIn(secret, raw_line)
            self.assertNotIn(secret, redacted_samples)

    def test_text_hash_is_stable_without_persisting_the_text(self):
        action = TextInputAction(text="上海外滩")

        first = redact_action_arguments(action)
        second = redact_action_arguments(action)

        self.assertEqual(first, second)
        self.assertEqual(
            first.model_dump(exclude_none=True),
            {
                "text": {
                    "length": 4,
                    "sha256": "97930a0a0c32d968eeed64e754e583826d1ec708535e26e41efe7df6b111eacb",
                }
            },
        )

    def test_record_schema_rejects_arbitrary_private_text_fields(self):
        common = {
            "run_id": "12345678-1234-4123-8123-123456789abc",
            "scenario_id": "scenario-a1b2c3d4e5f60718",
            "provider": "kimi",
            "model": "kimi-k2.6",
            "step_number": 1,
            "action_type": "tap",
            "model_latency_ms": 10,
            "device_latency_ms": 20,
            "action_status": "success",
            "schema_status": "valid",
            "observation_strategy": "fixed_recent",
            "observation_window_size": 5,
            "observation_images_used": 1,
            "device_provider": "adb",
            "observation_policy_version": 1,
        }

        with self.assertRaises(ValidationError):
            RunRecord(**common, action_arguments={"analysis": "private thinking"})
        with self.assertRaises(ValidationError):
            RunRecord(
                **common,
                action_arguments={"x": 1, "y": 2},
                metadata={"analysis": "private thinking"},
            )
        with self.assertRaises(ValidationError):
            RunRecord(
                **{**common, "run_id": "private thinking"},
                action_arguments={"x": 1, "y": 2},
            )
        for field_name, credential in (
            ("provider", "sk-abcdefghijklmnopqrstuvwxyz123456"),
            ("model", "ark-abcdefghijklmnopqrstuvwxyz123456"),
            ("device_provider", "AKLTABCDEFGHIJKLMNOPQRST"),
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaises(ValidationError):
                    RunRecord(
                        **{**common, field_name: credential},
                        action_arguments={"x": 1, "y": 2},
                    )
        with self.assertRaises(ValidationError):
            RunRecord(
                **{**common, "scenario_id": "Bearer private-token"},
                action_arguments={"x": 1, "y": 2},
            )

    def test_multiple_recorder_instances_append_complete_json_lines(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"

            def write_record(index):
                JsonlExperimentRecorder(path).write(
                    self.make_record(
                        run_id=f"00000000-0000-4000-8000-{index:012x}"
                    )
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(write_record, range(100)))

            payloads = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(payloads), 100)
        self.assertEqual(
            {payload["run_id"] for payload in payloads},
            {f"00000000-0000-4000-8000-{index:012x}" for index in range(100)},
        )


class AgentExperimentRecordTests(unittest.IsolatedAsyncioTestCase):
    async def run_with_records(
        self, provider, backend, path, *, sse_connection=None
    ):
        agent = MobileUseAgent(
            model_provider_name="kimi",
            device_provider_name="adb",
            model_provider_factory=lambda *args, **kwargs: provider,
            device_backend_factory=lambda name: backend,
            experiment_record_path=path,
        )
        agent.step_interval = 0
        await agent.initialize("", "", "", "", "", "")
        try:
            chunks = [
                chunk
                async for chunk in agent.run(
                    "打开高德地图",
                    is_stream=False,
                    task_id="task-experiment-record",
                    session_id="session-experiment-record",
                    thread_id=f"chat-{uuid.uuid4()}",
                    sse_connection=sse_connection or asyncio.Event(),
                    phone_width=1080,
                    phone_height=2278,
                )
            ]
        finally:
            await agent.aclose()
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        return chunks, records

    async def run_expecting_error(
        self, provider, backend, path, error_type, *, sse_connection=None
    ):
        with self.assertRaises(error_type):
            await self.run_with_records(
                provider,
                backend,
                path,
                sse_connection=sse_connection,
            )
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    async def run_with_possible_cancellation(self, provider, backend, path):
        try:
            _, records = await self.run_with_records(provider, backend, path)
            return records
        except asyncio.CancelledError:
            return [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

    async def test_agent_run_records_decision_device_and_terminal_oracle(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"
            provider = RecordingProvider()
            backend = RecordingBackend()
            chunks, records = await self.run_with_records(provider, backend, path)

        self.assertTrue(chunks)
        self.assertEqual(len(records), 2)
        first, terminal = records
        self.assertEqual(first["run_id"], terminal["run_id"])
        self.assertEqual(first["scenario_id"], terminal["scenario_id"])
        self.assertEqual(first["provider"], "kimi")
        self.assertEqual(first["model"], "kimi-k2.6")
        self.assertEqual(first["step_number"], 1)
        self.assertEqual(first["action_type"], "tap")
        self.assertEqual(first["action_arguments"], {"x": 250, "y": 750})
        self.assertEqual(first["schema_status"], "valid")
        self.assertEqual(first["action_status"], "success")
        self.assertIsInstance(first["model_latency_ms"], int)
        self.assertIsInstance(first["device_latency_ms"], int)
        self.assertEqual(first["observation_window_size"], 5)
        self.assertEqual(first["observation_images_used"], 1)
        self.assertEqual(terminal["step_number"], 2)
        self.assertEqual(terminal["action_type"], "finish")
        self.assertEqual(terminal["action_arguments"], {})
        self.assertEqual(terminal["action_status"], "success")
        self.assertEqual(terminal["terminal_reason"], "completed")
        self.assertIs(terminal["oracle_result"], True)
        self.assertEqual(terminal["observation_images_used"], 2)
        serialized = json.dumps(records, ensure_ascii=False)
        self.assertNotIn("must-not-be-recorded", serialized)
        self.assertNotIn("打开高德地图", serialized)

    async def test_schema_failures_are_recorded_without_raw_model_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"

            _, records = await self.run_with_records(
                InvalidSchemaProvider(), RecordingBackend(), path
            )

        self.assertEqual(len(records), 3)
        self.assertEqual(
            [record["schema_status"] for record in records],
            ["invalid", "invalid", "invalid"],
        )
        self.assertTrue(
            all(record["action_status"] == "not_executed" for record in records)
        )
        self.assertEqual(records[-1]["terminal_reason"], "schema_error_limit")
        self.assertNotIn("hidden model output", json.dumps(records))

    async def test_device_failure_type_and_terminal_reason_are_recorded(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"

            _, records = await self.run_with_records(
                RecordingProvider(), OfflineBackend(), path
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["action_status"], "failed")
        self.assertEqual(records[0]["device_error_kind"], "offline")
        self.assertEqual(records[0]["terminal_reason"], "device_offline")

    async def test_observation_failure_still_generates_a_redacted_record(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"

            _, records = await self.run_with_records(
                RecordingProvider(), ObservationFailureBackend(), path
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["action_type"], "observation")
        self.assertEqual(records[0]["schema_status"], "not_evaluated")
        self.assertEqual(records[0]["device_error_kind"], "invalid_observation")
        self.assertEqual(
            records[0]["terminal_reason"], "device_observation_failed"
        )
        self.assertNotIn("X-Tos-Signature", json.dumps(records))

    async def test_model_failure_still_generates_a_redacted_record(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"

            _, records = await self.run_with_records(
                ModelFailureProvider(), RecordingBackend(), path
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["action_type"], "model_call")
        self.assertEqual(records[0]["schema_status"], "not_evaluated")
        self.assertEqual(records[0]["terminal_reason"], "model_call_failed")
        self.assertNotIn("private-model-token", json.dumps(records))

    async def test_preparation_failure_still_generates_a_record(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"

            records = await self.run_expecting_error(
                RecordingProvider(),
                PreparationFailureBackend(),
                path,
                DeviceBackendError,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["action_type"], "prepare")
        self.assertEqual(records[0]["device_error_kind"], "offline")
        self.assertEqual(records[0]["terminal_reason"], "prepare_failed")
        self.assertEqual(records[0]["observation_images_used"], 0)

    async def test_model_cancellation_gets_one_terminal_record(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"
            records = await self.run_with_possible_cancellation(
                CancelledModelProvider(),
                RecordingBackend(),
                path,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["terminal_reason"], "cancelled")
        self.assertEqual(records[0]["observation_images_used"], 1)

    async def test_prepare_cancellation_gets_one_terminal_record(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"
            records = await self.run_expecting_error(
                RecordingProvider(),
                CancelledPreparationBackend(),
                path,
                asyncio.CancelledError,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["terminal_reason"], "cancelled")
        self.assertEqual(records[0]["observation_images_used"], 0)

    async def test_tool_cancellation_gets_one_terminal_record(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"
            records = await self.run_with_possible_cancellation(
                RecordingProvider(),
                CancelledToolBackend(),
                path,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["terminal_reason"], "cancelled")
        self.assertEqual(records[0]["observation_images_used"], 1)

    async def test_sse_disconnect_gets_one_terminal_record(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"
            disconnected = asyncio.Event()
            disconnected.set()
            records = await self.run_expecting_error(
                RecordingProvider(),
                RecordingBackend(),
                path,
                SSEException,
                sse_connection=disconnected,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["terminal_reason"], "client_disconnected")
        self.assertEqual(records[0]["observation_images_used"], 1)

    async def test_recording_failure_does_not_change_agent_result(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid_record_path = Path(temporary_directory)
            provider = RecordingProvider()
            backend = RecordingBackend()
            agent = MobileUseAgent(
                model_provider_name="kimi",
                device_provider_name="adb",
                model_provider_factory=lambda *args, **kwargs: provider,
                device_backend_factory=lambda name: backend,
                experiment_record_path=invalid_record_path,
            )
            agent.step_interval = 0
            await agent.initialize("", "", "", "", "", "")
            try:
                chunks = [
                    chunk
                    async for chunk in agent.run(
                        "打开高德地图",
                        is_stream=False,
                        task_id="task-record-failure",
                        session_id="session-record-failure",
                        thread_id=f"chat-{uuid.uuid4()}",
                        sse_connection=asyncio.Event(),
                        phone_width=1080,
                        phone_height=2278,
                    )
                ]
            finally:
                await agent.aclose()

        self.assertTrue(chunks)

    async def test_provider_construction_failure_gets_terminal_record(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runs.jsonl"
            agent = MobileUseAgent(
                model_provider_name="kimi",
                device_provider_name="adb",
                model_provider_factory=lambda *args, **kwargs: (_ for _ in ()).throw(
                    ProviderConstructionError("Authorization: Bearer private")
                ),
                device_backend_factory=lambda name: RecordingBackend(),
                experiment_record_path=path,
            )
            await agent.initialize("", "", "", "", "", "")
            try:
                with self.assertRaises(ProviderConstructionError):
                    _ = [
                        chunk
                        async for chunk in agent.run(
                            "打开高德地图",
                            is_stream=False,
                            task_id="task-provider-failure",
                            session_id="session-provider-failure",
                            thread_id=f"chat-{uuid.uuid4()}",
                            sse_connection=asyncio.Event(),
                            phone_width=1080,
                            phone_height=2278,
                        )
                    ]
            finally:
                await agent.aclose()

            raw = path.read_text(encoding="utf-8")
            records = [json.loads(line) for line in raw.splitlines()]

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["action_type"], "runtime")
        self.assertEqual(records[0]["terminal_reason"], "runtime_failed")
        self.assertNotIn("private", raw)


if __name__ == "__main__":
    unittest.main()
