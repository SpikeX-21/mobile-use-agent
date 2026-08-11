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
from mobile_agent.agent.tools.tool.abc import Tool


class WaitTool(Tool):
    def __init__(self):
        super().__init__(
            name="wait",
            description="Sleep for t seconds number, wait for change,  t is lower than 10, higher than 0.",
            parameters={
                "t": {
                    "type": "number",
                    "description": "The time to wait in seconds",
                }
            },
        )

    async def handler(self, args: dict):
        await asyncio.sleep(args.get("t"))
        return f"已等待{args.get('t')}s"
