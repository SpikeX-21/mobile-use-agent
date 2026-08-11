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

import unittest

from pydantic import ValidationError

from mobile_agent.agent.actions import TapAction, validate_canonical_action


class CanonicalActionTests(unittest.TestCase):
    def test_validates_a_normalized_tap(self):
        action = validate_canonical_action({"type": "tap", "x": 250, "y": 750})

        self.assertEqual(action, TapAction(x=250, y=750))

    def test_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            validate_canonical_action(
                {"type": "tap", "x": 250, "y": 750, "unexpected": True}
            )

    def test_rejects_coordinates_outside_the_normalized_screen(self):
        with self.assertRaises(ValidationError):
            validate_canonical_action({"type": "tap", "x": 1001, "y": 750})

    def test_rejects_coercible_but_incorrect_parameter_types(self):
        invalid_actions = [
            {"type": "tap", "x": "250", "y": 750},
            {"type": "wait", "duration_ms": "1000"},
            {"type": "list_apps", "ignore_system_apps": 1},
        ]

        for action in invalid_actions:
            with self.subTest(action=action):
                with self.assertRaises(ValidationError):
                    validate_canonical_action(action)

    def test_rejects_unknown_actions(self):
        with self.assertRaises(ValidationError):
            validate_canonical_action({"type": "install_app", "package_name": "x"})

    def test_supports_the_complete_action_vocabulary(self):
        examples = [
            {"type": "tap", "x": 1, "y": 2},
            {
                "type": "swipe",
                "start_x": 100,
                "start_y": 800,
                "end_x": 100,
                "end_y": 200,
                "duration_ms": 300,
            },
            {"type": "text_input", "text": "上海外滩"},
            {"type": "clear_text"},
            {"type": "home"},
            {"type": "back"},
            {"type": "menu"},
            {"type": "launch_app", "package_name": "com.autonavi.minimap"},
            {"type": "close_app", "package_name": "com.autonavi.minimap"},
            {"type": "list_apps", "ignore_system_apps": True},
            {"type": "wait", "duration_ms": 1000},
            {"type": "finish", "summary": "任务完成"},
            {"type": "fail", "reason": "需要用户登录"},
        ]

        self.assertEqual(
            [validate_canonical_action(example).type for example in examples],
            [example["type"] for example in examples],
        )

    def test_rejects_observation_and_excluded_install_actions(self):
        for action_type in ("take_screenshot", "autoinstall_app"):
            with self.subTest(action_type=action_type):
                with self.assertRaises(ValidationError):
                    validate_canonical_action({"type": action_type})

    def test_rejects_missing_action_parameters(self):
        invalid_actions = [
            {"type": "swipe", "start_x": 1, "start_y": 2},
            {"type": "text_input"},
            {"type": "launch_app"},
            {"type": "finish"},
            {"type": "fail"},
        ]

        for action in invalid_actions:
            with self.subTest(action=action):
                with self.assertRaises(ValidationError):
                    validate_canonical_action(action)


if __name__ == "__main__":
    unittest.main()
