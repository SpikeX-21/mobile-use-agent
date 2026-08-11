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

import re
from typing import Optional
from mobile_agent.config.settings import MOBILE_USE_MCP_NAME
from mobile_agent.agent.infra.model import ToolCall
from mobile_agent.agent.utils.bbox import regular_bbox_for_ui_tars


"""
豆包的输出有讲究，需要做 ActionSpace 的映射
"""


class DoubaoActionSpaceParser:
    layout_pattern = r"Summary:(?P<summary>[\s\S]*?)Action:(?P<action>.*)"
    action_pattern = r"(?P<action>\w+)\(\s*(?P<args>.*)\)"
    args_pattern = r"""
    click: start_box=\s*[\'"]<bbox>(?P<left>\d+)\s+(?P<top>\d+)\s+(?P<bottom>\d+)\s+(?P<right>\d+)</bbox>[\'"]
    drag: start_box=\s*[\'"]<bbox>(?P<start_left>\d+)\s+(?P<start_top>\d+)\s+(?P<start_right>\d+)\s+(?P<start_bottom>\d+)</bbox>[\'"],\s+end_box=\s*[\'"]<bbox>(?P<end_left>\d+)\s+(?P<end_top>\d+)\s+(?P<end_right>\d+)\s+(?P<end_bottom>\d+)</bbox>[\'"]
    type: content=[\'"](?P<content>.*)[\'"]
    wait: t=[\'"](?P<t>\d+)[\'"]
    call_user: content=[\'"](?P<content>.*)[\'"]
    finished: content=[\'"](?P<content>.*)[\'"]
    close_app: package_name=[\'"](?P<package_name>.*)[\'"]
    launch_app: package_name=[\'"](?P<package_name>.*)[\'"]
    """

    def __init__(
        self,
        phone_width: int,
        phone_height: int,
    ):
        self.phone_width = phone_width
        self.phone_height = phone_height
        self.layout_pattern = re.compile(DoubaoActionSpaceParser.layout_pattern)
        self.action_pattern = re.compile(DoubaoActionSpaceParser.action_pattern)
        action_args_pattern = [
            line.split(":", 1)
            for line in DoubaoActionSpaceParser.args_pattern.strip().splitlines()
        ]
        self.args_pattern_map = {
            action.strip(): re.compile(pattern.strip())
            for (action, pattern) in action_args_pattern
        }

    def change_phone_dimensions(self, width: int, height: int):
        if width != 0:
            self.phone_width = width
        if height != 0:
            self.phone_height = height

    def error_action(self, action_call: Optional[str] = None):
        return {"name": "error_action", "arguments": {"content": action_call}}

    def to_mcp_tool_call(self, action_call: str) -> ToolCall:
        """将模型返回的操作转换为MCP工具调用"""
        if not action_call:
            return self.error_action("action_call is empty")

        # 解析操作类型和参数
        action_match = self.action_pattern.match(action_call)
        if not action_match:
            return self.error_action(action_call)

        action_type = action_match.group("action").lower()
        args_str = action_match.group("args").strip()
        args_pattern = self.args_pattern_map.get(action_type)

        # 根据操作类型处理参数
        if action_type == "click":
            # 解析点击坐标
            return self.__call_tap(args_pattern, args_str)
        elif action_type == "type":
            return self.__call_type(args_pattern, args_str)
        elif action_type == "drag":
            return self.__call_swipe(args_pattern, args_str)
        elif action_type == "press_back":
            # 返回操作
            return {"name": f"{MOBILE_USE_MCP_NAME}:back", "arguments": {}}
        elif action_type == "press_home":
            # 主页操作
            return {"name": f"{MOBILE_USE_MCP_NAME}:home", "arguments": {}}
        elif action_type == "close_app":
            # 关闭应用
            args_match = args_pattern.search(args_str)
            if args_match:
                package_name = args_match.group(1)
                return {
                    "name": f"{MOBILE_USE_MCP_NAME}:close_app",
                    "arguments": {"package_name": package_name},
                }
            return {
                "name": f"{MOBILE_USE_MCP_NAME}:close_app",
                "arguments": {"package_name": args_str},
            }
        elif action_type == "launch_app":
            # 启动应用
            args_match = args_pattern.search(args_str)
            if args_match:
                package_name = args_match.group(1)
                return {
                    "name": f"{MOBILE_USE_MCP_NAME}:launch_app",
                    "arguments": {"package_name": package_name},
                }
            return {
                "name": f"{MOBILE_USE_MCP_NAME}:launch_app",
                "arguments": {"package_name": args_str},
            }
        elif action_type == "list_apps":
            # 列出所有应用
            return {"name": f"{MOBILE_USE_MCP_NAME}:list_apps", "arguments": {}}
        elif action_type == "wait":
            # 等待操作
            args_match = args_pattern.search(args_str)
            if args_match:
                time = int(args_match.group(1))
                return {"name": "wait", "arguments": {"t": max(1, min(10, time))}}
            return {"name": "wait", "arguments": {"t": 1}}
        elif action_type == "call_user":
            # 呼叫用户, 后续可以增加 ux 更加好看
            args_match = args_pattern.search(args_str)
            if args_match:
                content = args_match.group(1)
                return {"name": "call_user", "arguments": {"content": content}}
            return {"name": "call_user", "arguments": {"content": args_str}}
        elif action_type == "finish" or action_type == "finished":
            # 完成操作
            args_match = args_pattern.search(args_str)
            if args_match:
                content = args_match.group(1)
                return {"name": "finished", "arguments": {"content": content}}
            return {"name": "finished", "arguments": {"content": args_str}}

        # 默认无法识别的操作
        return self.error_action(action_call)

    def __call_tap(self, args_pattern: re.Pattern, args_str: str):
        try:
            args_match = args_pattern.search(args_str)
            if args_match:
                left, top, right, bottom = [
                    int(args_match.group(i)) for i in range(1, 5)
                ]

                left, top, right, bottom = regular_bbox_for_ui_tars(
                    left,
                    top,
                    right,
                    bottom,
                    width=self.phone_width,
                    height=self.phone_height,
                )

                return {
                    "name": f"{MOBILE_USE_MCP_NAME}:tap",
                    "arguments": {
                        "x": (left + right) // 2,
                        "y": (top + bottom) // 2,
                    },
                }
        except Exception as e:
            print(f"解析点击坐标失败")

    def __call_swipe(self, args_pattern: re.Pattern, args_str: str):
        try:
            args_match = args_pattern.search(args_str)
            if args_match:
                (
                    start_left,
                    start_top,
                    start_right,
                    start_bottom,
                    end_left,
                    end_top,
                    end_right,
                    end_bottom,
                ) = [int(args_match.group(i)) for i in range(1, 9)]

                start_left, start_top, start_right, start_bottom = (
                    regular_bbox_for_ui_tars(
                        start_left,
                        start_top,
                        start_right,
                        start_bottom,
                        width=self.phone_width,
                        height=self.phone_height,
                    )
                )

                end_left, end_top, end_right, end_bottom = regular_bbox_for_ui_tars(
                    end_left,
                    end_top,
                    end_right,
                    end_bottom,
                    width=self.phone_width,
                    height=self.phone_height,
                )

                return {
                    "name": f"{MOBILE_USE_MCP_NAME}:swipe",
                    "arguments": {
                        "from_x": ((start_left + start_right) // 2),
                        "from_y": ((start_top + start_bottom) // 2),
                        "to_x": ((end_left + end_right) // 2),
                        "to_y": ((end_top + end_bottom) // 2),
                    },
                }
        except Exception as e:
            print(f"解析点击坐标失败")

    def __call_type(self, args_pattern: re.Pattern, args_str: str):
        try:
            args_match = args_pattern.search(args_str)
            if args_match:
                content = args_match.group(1)
                return {
                    "name": f"{MOBILE_USE_MCP_NAME}:text_input",
                    "arguments": {"text": content},
                }
        except Exception as e:
            print(f"解析失败")
