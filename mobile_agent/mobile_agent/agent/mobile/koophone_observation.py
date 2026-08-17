# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import base64
import binascii
import io
import json
import re
import warnings
from collections.abc import Mapping
from typing import Any

from PIL import Image, UnidentifiedImageError

from mobile_agent.agent.mobile.result import DeviceBackendError, DeviceErrorKind


MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
MAX_SCREENSHOT_PIXELS = 4_000_000
_DATA_URL_PATTERN = re.compile(r"^data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)$")


class KooPhoneScreenshotError(DeviceBackendError):
    """A redacted invalid-observation error for KooPhone screenshot responses."""

    def __init__(self, message: str):
        super().__init__(message, kind=DeviceErrorKind.INVALID_OBSERVATION)


def normalize_koophone_screenshot(response: Any) -> dict[str, object]:
    """Turn one allowed KooPhone screenshot response shape into a safe Data URL."""

    encoded = _extract_base64(response)
    raw_image = _decode_image(encoded)
    image_format, dimensions = _validate_image(raw_image)
    mime_type = "image/png" if image_format == "PNG" else "image/jpeg"
    return {
        "screenshot": f"data:{mime_type};base64,{encoded}",
        "screenshot_dimensions": dimensions,
    }


def _extract_base64(response: Any) -> str:
    if isinstance(response, str):
        return _extract_from_text(response)
    structured_content = getattr(response, "structuredContent", None)
    if structured_content is not None:
        return _extract_from_mapping(structured_content)
    content = getattr(response, "content", None)
    if isinstance(content, list):
        if len(content) != 1:
            raise KooPhoneScreenshotError("KooPhone screenshot response is ambiguous")
        text = getattr(content[0], "text", None)
        if not isinstance(text, str):
            raise KooPhoneScreenshotError("KooPhone screenshot response is invalid")
        return _extract_from_text(text)
    if isinstance(response, Mapping):
        return _extract_from_mapping(response)
    raise KooPhoneScreenshotError("KooPhone screenshot response is invalid")


def _extract_from_text(value: str) -> str:
    text = value.strip()
    if not text:
        raise KooPhoneScreenshotError("KooPhone screenshot response is empty")
    if text.startswith(("{", '"')):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            raise KooPhoneScreenshotError("KooPhone screenshot JSON is invalid") from None
        if isinstance(decoded, str):
            text = decoded.strip()
        else:
            return _extract_from_mapping(decoded)
    data_url = _DATA_URL_PATTERN.fullmatch(text)
    if data_url is not None:
        return data_url.group(2)
    return text


def _extract_from_mapping(value: Any) -> str:
    if not isinstance(value, Mapping):
        raise KooPhoneScreenshotError("KooPhone screenshot response is invalid")
    direct = value.get("screenshot")
    if isinstance(direct, str):
        return _extract_from_text(direct)
    for nested_key in ("result", "data"):
        nested = value.get(nested_key)
        if isinstance(nested, str):
            return _extract_from_text(nested)
        if isinstance(nested, Mapping):
            return _extract_from_mapping(nested)
    raise KooPhoneScreenshotError("KooPhone screenshot field is missing")


def _decode_image(encoded: str) -> bytes:
    max_base64_characters = (MAX_SCREENSHOT_BYTES * 4 // 3) + 4
    if len(encoded) > max_base64_characters:
        raise KooPhoneScreenshotError("KooPhone screenshot exceeds the size limit")
    try:
        raw_image = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise KooPhoneScreenshotError("KooPhone screenshot is not valid Base64") from None
    if not raw_image:
        raise KooPhoneScreenshotError("KooPhone screenshot is empty")
    if len(raw_image) > MAX_SCREENSHOT_BYTES:
        raise KooPhoneScreenshotError("KooPhone screenshot exceeds the size limit")
    return raw_image


def _validate_image(raw_image: bytes) -> tuple[str, tuple[int, int]]:
    if raw_image.startswith(b"\x89PNG\r\n\x1a\n"):
        expected_format = "PNG"
    elif raw_image.startswith(b"\xff\xd8\xff"):
        expected_format = "JPEG"
    else:
        raise KooPhoneScreenshotError("KooPhone screenshot is not a PNG or JPEG")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw_image)) as image:
                image.verify()
            with Image.open(io.BytesIO(raw_image)) as image:
                image_format = image.format
                dimensions = image.size
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
    ):
        raise KooPhoneScreenshotError("KooPhone screenshot image is invalid") from None
    if (
        image_format != expected_format
        or dimensions[0] <= 0
        or dimensions[1] <= 0
        or dimensions[0] * dimensions[1] > MAX_SCREENSHOT_PIXELS
    ):
        raise KooPhoneScreenshotError("KooPhone screenshot image is invalid")
    return image_format, dimensions
