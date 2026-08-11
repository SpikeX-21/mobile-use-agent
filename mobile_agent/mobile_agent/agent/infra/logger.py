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

import logging
from typing import Optional


# 创建自定义Logger类
class AgentLogger:
    def __init__(self, logger_name):
        self.logger = logging.getLogger(logger_name)
        self.thread_id = None
        self.pod_id = None
        self.chat_thread_id = None

    def set_context(
        self,
        thread_id: Optional[str] = None,
        chat_thread_id: Optional[str] = None,
        pod_id: Optional[str] = None,
    ):
        """设置日志上下文"""
        if chat_thread_id:
            self.chat_thread_id = chat_thread_id
        if thread_id:
            self.thread_id = thread_id
        if pod_id:
            self.pod_id = pod_id

    def _format_message(self, msg):
        """添加上下文信息到日志消息"""
        context = []
        if self.chat_thread_id:
            context.append(f"chat_thread_id={self.chat_thread_id}")
        if self.thread_id:
            context.append(f"thread_id={self.thread_id}")
        if self.pod_id:
            context.append(f"pod_id={self.pod_id}")

        if context:
            return f"[{' '.join(context)}] {msg}"
        return msg

    def debug(self, msg, *args, **kwargs):
        self.logger.debug(self._format_message(msg), *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.logger.info(self._format_message(msg), *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(self._format_message(msg), *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.logger.error(self._format_message(msg), *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.logger.critical(self._format_message(msg), *args, **kwargs)
