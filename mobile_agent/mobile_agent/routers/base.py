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

"""
路由注册模块
"""

from fastapi import FastAPI
from mobile_agent.routers import session, agent


def register_routers(app: FastAPI):
    """
    注册所有路由到FastAPI应用

    Args:
        app: FastAPI应用实例
    """
    # 注册聊天相关路由
    app.include_router(session.router)

    # 注册智能代理相关路由
    app.include_router(agent.router)
