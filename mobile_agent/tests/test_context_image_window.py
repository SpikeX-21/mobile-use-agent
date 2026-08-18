# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

import unittest

from mobile_agent.agent.memory.context_manager import ContextManager


class ContextImageWindowTests(unittest.TestCase):
    def test_initial_screenshot_includes_resolution_and_high_detail(self):
        manager = ContextManager(messages=[])

        manager.add_user_initial_message(
            message="启用九点闹钟",
            screenshot_url="data:image/png;base64,image",
            screenshot_dimensions=(304, 540),
        )

        content = manager.get_messages()[0].content
        self.assertEqual(content[0]["image_url"]["detail"], "high")
        self.assertIn("304x540", content[1]["text"])

    def test_keeps_exactly_the_last_five_screenshots(self):
        manager = ContextManager(messages=[])
        for index in range(7):
            manager.add_user_initial_message(
                message=f"step {index}",
                screenshot_url=f"data:image/png;base64,image-{index}",
            )

        manager.keep_last_n_images_in_messages(5)

        images = [
            part["image_url"]["url"]
            for message in manager.get_messages()
            if isinstance(message.content, list)
            for part in message.content
            if part.get("type") == "image_url"
        ]
        self.assertEqual(
            images,
            [f"data:image/png;base64,image-{index}" for index in range(2, 7)],
        )


if __name__ == "__main__":
    unittest.main()
