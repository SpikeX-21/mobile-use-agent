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

import asyncio
import json
import logging
from mobile_agent.config.settings import MOBILE_USE_MCP_NAME, get_settings
from mobile_agent.agent.utils.image import get_dimensions_from_url
from mobile_agent.agent.tools.mcp import MCPHub

"""
负责对手机MCP的连接管理，工具调用的管理
"""

logger = logging.getLogger(__name__)


class Mobile:
    def __init__(self, mcp_hub: MCPHub):
        self.phone_width: int | None = None
        self.phone_height: int | None = None
        self.mcp_hub = mcp_hub

    async def initialize(
        self,
        pod_id: str,
        product_id: str,
        tos_bucket: str,
        tos_region: str,
        tos_endpoint: str,
        auth_token: str,
    ):
        """mobile use mcp 单独处理"""
        self.mcp_hub.add_mcp_json(
            MOBILE_USE_MCP_NAME,
            {
                "url": get_settings().mobile_use_mcp.url,
                "transport": "streamable_http",
                "headers": {
                    "Authorization": auth_token,
                    "X-ACEP-DeviceId": pod_id,
                    "X-ACEP-ProductId": product_id,
                    "X-ACEP-TosBucket": tos_bucket,
                    "X-ACEP-TosRegion": tos_region,
                    "X-ACEP-TosEndpoint": tos_endpoint,
                },
            },
        )
        await self.mcp_hub.session(MOBILE_USE_MCP_NAME)

    async def _take_screenshot(self) -> dict:
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                result = await self.mcp_hub.call_tool(
                    mcp_server_name=MOBILE_USE_MCP_NAME,
                    name="take_screenshot",
                    arguments={},
                )

                text = result.content[0].text
                try:
                    parsed_data = json.loads(text)
                    screenshot_url = parsed_data["result"]["screenshot_url"]
                    width = int(parsed_data["result"]["width"])
                    height = int(parsed_data["result"]["height"])
                except (json.JSONDecodeError, KeyError, TypeError):
                    logger.warning("主动解析截屏长宽")
                    screenshot_url = text
                    (
                        width,
                        height,
                    ) = await get_dimensions_from_url(screenshot_url)

                logger.info(
                    f"截图成功，重试次数: {retry_count}, 截图尺寸: {width}x{height}"
                )

                return {
                    "screenshot": screenshot_url,
                    "screenshot_dimensions": (width, height),
                }

            except Exception as e:
                retry_count += 1
                logger.error(f"截图异常，重试第 {retry_count} 次。错误: {e}")

                if retry_count >= max_retries:
                    raise ValueError(
                        f"截图失败，已重试 {max_retries} 次。最后错误: {e}"
                    )

                await asyncio.sleep(1)  # 等待1秒后重试

        # 如果所有重试都失败
        raise ValueError(f"截图失败，已重试 {max_retries} 次")

    def change_phone_dimensions(self, width: int, height: int):
        if width != 0:
            self.phone_width = width
        if height != 0:
            self.phone_height = height

    async def take_screenshot(self) -> tuple[int, int]:
        screenshot_state = await self._take_screenshot()
        # 处理横竖屏切换逻辑
        self.change_phone_dimensions(
            screenshot_state.get("screenshot_dimensions")[0],
            screenshot_state.get("screenshot_dimensions")[1],
        )
        return screenshot_state
