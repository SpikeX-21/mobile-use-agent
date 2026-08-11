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

from typing import Literal
from mobile_agent.config.settings import get_agent_config
import logging


class CostCalculator:
    def __init__(self, agentName: Literal["mobile_use"]):
        agent_config = get_agent_config(agentName)
        self.logger = logging.getLogger(__name__)
        self.pricing = {
            "input_price_per_1k": agent_config.input_price_per_1k,
            "output_price_per_1k": agent_config.output_price_per_1k,
        }
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_rmb = 0
        self.step = 0

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算本次调用的费用（元）"""
        input_cost = (input_tokens / 1000) * self.pricing["input_price_per_1k"]
        output_cost = (output_tokens / 1000) * self.pricing["output_price_per_1k"]
        total_cost = input_cost + output_cost
        return round(total_cost, 6)  # 保留6位小数

    def update_step(self, step: int):
        self.step = step

    def record_cost(self, input_tokens: int, output_tokens: int):
        """记录本次调用的成本并累积总成本"""
        current_cost = self.calculate_cost(
            input_tokens=input_tokens, output_tokens=output_tokens
        )

        # 更新累积数据
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_rmb += current_cost

        # 记录本次调用的详细信息
        self.logger.info(
            f"Step {self.step}: input_tokens={input_tokens}, output_tokens={output_tokens}, "
            f"current_cost={current_cost:.6f}¥, total_cost={self.cost_rmb:.6f}¥"
        )

        return current_cost

    def print_cost(self):
        """打印总的成本统计信息"""
        self.logger.info(
            f"Final Cost Summary - Total Steps: {self.step}, "
            f"Total Cost: {self.cost_rmb:.6f}¥, "
            f"Total Input Tokens: {self.input_tokens}, "
            f"Total Output Tokens: {self.output_tokens}"
        )

    def get_cost_summary(self) -> dict:
        """获取成本摘要信息"""
        return {
            "total_steps": self.step,
            "total_cost_rmb": round(self.cost_rmb, 6),
            "total_input_tokens": self.input_tokens,
            "total_output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "pricing": self.pricing,
        }
