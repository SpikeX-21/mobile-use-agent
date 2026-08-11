# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     https://www.volcengine.com/docs/82379/1433703
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr, ValidationError

from mobile_agent.agent.actions import TapAction
from mobile_agent.agent.llm.kimi import KimiModelProvider
from mobile_agent.agent.llm.provider import ActionParseError
from mobile_agent.config.settings import KimiConfig


class RecordingCompletions:
    def __init__(self):
        self.requests = []

    async def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(
            id="kimi-response-1",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "summary": "点击高德地图图标",
                                "action": {"type": "tap", "x": 500, "y": 420},
                            },
                            ensure_ascii=False,
                        )
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


class RecordingClient:
    def __init__(self):
        self.completions = RecordingCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class KimiModelProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_prompt_requires_observation_before_deciding_after_ambiguous_result(self):
        self.assertIn("ambiguous", KimiModelProvider.prompt)
        self.assertIn("latest screenshot", KimiModelProvider.prompt)
        self.assertIn("do not blindly repeat", KimiModelProvider.prompt)

    def test_prompt_allows_search_text_clear_and_wait_actions(self):
        self.assertIn('"type":"text_input"', KimiModelProvider.prompt)
        self.assertIn('"type":"clear_text"', KimiModelProvider.prompt)
        self.assertIn('"type":"wait"', KimiModelProvider.prompt)
        self.assertNotIn('"type":"launch_app"', KimiModelProvider.prompt)

    def test_prompt_allows_swipe_only_when_a_result_is_not_visible(self):
        self.assertIn('"type":"swipe"', KimiModelProvider.prompt)
        self.assertIn("result is not visible", KimiModelProvider.prompt)
        self.assertIn("latest screenshot", KimiModelProvider.prompt)

    def test_thinking_mode_cannot_be_enabled(self):
        with self.assertRaises(ValidationError):
            KimiConfig(api_key=SecretStr("unit-test-key"), thinking_mode="enabled")

    async def test_sends_base64_vision_request_in_non_thinking_json_mode(self):
        client = RecordingClient()
        provider = KimiModelProvider(
            thread_id="thread-1",
            config=KimiConfig(
                api_key=SecretStr("unit-test-key"),
                model="kimi-k2.6",
                base_url="https://api.moonshot.cn/v1",
                thinking_mode="disabled",
            ),
            client=client,
        )
        screenshot = "data:image/png;base64,aW1hZ2UtYnl0ZXM="
        messages = [
            SystemMessage(content="system prompt"),
            HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": screenshot}},
                    {"type": "text", "text": "打开高德地图"},
                ]
            ),
        ]

        response_id, content, summary, action_json = await provider.async_chat(
            messages
        )
        action = provider.parse_action(action_json)

        self.assertEqual(response_id, "kimi-response-1")
        self.assertEqual(summary, "点击高德地图图标")
        self.assertIn('"type": "tap"', content)
        self.assertEqual(action, TapAction(x=500, y=420))
        request = client.completions.requests[0]
        self.assertEqual(request["model"], "kimi-k2.6")
        self.assertFalse(request["stream"])
        self.assertEqual(request["temperature"], 0.6)
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(
            request["extra_body"], {"thinking": {"type": "disabled"}}
        )
        self.assertEqual(
            request["messages"][1]["content"][0]["image_url"]["url"],
            screenshot,
        )

    async def test_rejects_malformed_json_and_wrong_action_types(self):
        provider = KimiModelProvider(
            thread_id="thread-1",
            config=KimiConfig(api_key=SecretStr("unit-test-key")),
            client=RecordingClient(),
        )

        for response in (
            "not-json",
            json.dumps({"summary": "missing action"}),
            json.dumps({"action": {"type": "tap", "x": "500", "y": 420}}),
        ):
            with self.subTest(response=response):
                with self.assertRaises(ActionParseError):
                    provider.parse_action(response)


if __name__ == "__main__":
    unittest.main()
