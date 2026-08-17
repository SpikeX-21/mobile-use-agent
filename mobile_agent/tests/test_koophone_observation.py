# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import base64
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from mobile_agent.agent.mobile.koophone_observation import (
    KooPhoneScreenshotError,
    normalize_koophone_screenshot,
)


def image_base64(image_format: str, width: int = 48, height: int = 32) -> str:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format=image_format)
    return base64.b64encode(output.getvalue()).decode("ascii")


class KooPhoneObservationTests(unittest.TestCase):
    def test_normalizes_bare_png_base64_into_a_data_url_with_dimensions(self):
        encoded = image_base64("PNG")

        observation = normalize_koophone_screenshot(encoded)

        self.assertEqual(observation["screenshot_dimensions"], (48, 32))
        self.assertEqual(
            observation["screenshot"], f"data:image/png;base64,{encoded}"
        )

    def test_normalizes_json_text_and_structured_content_jpeg(self):
        encoded = image_base64("JPEG", width=64, height=40)

        json_observation = normalize_koophone_screenshot(
            json.dumps({"result": {"screenshot": encoded}})
        )
        structured_observation = normalize_koophone_screenshot(
            SimpleNamespace(structuredContent={"screenshot": encoded})
        )

        self.assertEqual(json_observation["screenshot_dimensions"], (64, 40))
        self.assertEqual(structured_observation["screenshot_dimensions"], (64, 40))
        self.assertTrue(json_observation["screenshot"].startswith("data:image/jpeg"))
        self.assertEqual(json_observation, structured_observation)

    def test_normalizes_data_field_from_json_and_structured_content(self):
        encoded = image_base64("PNG")

        json_observation = normalize_koophone_screenshot(json.dumps({"data": encoded}))
        structured_observation = normalize_koophone_screenshot(
            SimpleNamespace(structuredContent={"data": encoded})
        )

        self.assertEqual(json_observation["screenshot_dimensions"], (48, 32))
        self.assertEqual(json_observation, structured_observation)

    def test_normalizes_json_encoded_data_url_returned_by_the_live_mcp(self):
        encoded = image_base64("PNG")

        observation = normalize_koophone_screenshot(
            json.dumps(f"data:image/png;base64,{encoded}")
        )

        self.assertEqual(
            observation["screenshot"], f"data:image/png;base64,{encoded}"
        )

    def test_rejects_invalid_base64_and_mcp_multi_content_ambiguity_without_echoing_data(self):
        secret_like_data = "not-valid-base64-private-observation"

        with self.assertRaises(KooPhoneScreenshotError) as invalid:
            normalize_koophone_screenshot(secret_like_data)
        with self.assertRaises(KooPhoneScreenshotError) as ambiguous:
            normalize_koophone_screenshot(
                SimpleNamespace(
                    content=[
                        SimpleNamespace(text=image_base64("PNG")),
                        SimpleNamespace(text=image_base64("PNG")),
                    ]
                )
            )

        self.assertNotIn(secret_like_data, str(invalid.exception))
        self.assertIn("ambiguous", str(ambiguous.exception).lower())

    def test_rejects_empty_corrupt_and_oversized_images(self):
        corrupt_png = base64.b64encode(b"\x89PNG\r\n\x1a\nnot-a-real-image").decode("ascii")

        with self.assertRaisesRegex(KooPhoneScreenshotError, "empty"):
            normalize_koophone_screenshot("")
        with self.assertRaisesRegex(KooPhoneScreenshotError, "invalid"):
            normalize_koophone_screenshot(corrupt_png)
        with patch(
            "mobile_agent.agent.mobile.koophone_observation.MAX_SCREENSHOT_BYTES", 8
        ):
            with self.assertRaisesRegex(KooPhoneScreenshotError, "size limit"):
                normalize_koophone_screenshot(base64.b64encode(b"x" * 9).decode())

    def test_rejects_image_with_excessive_pixel_count(self):
        output = io.BytesIO()
        Image.new("RGB", (2001, 2000), "white").save(output, format="PNG")

        with self.assertRaisesRegex(KooPhoneScreenshotError, "image is invalid"):
            normalize_koophone_screenshot(base64.b64encode(output.getvalue()).decode())


if __name__ == "__main__":
    unittest.main()
