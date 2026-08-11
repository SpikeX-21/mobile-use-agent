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

import httpx
from PIL import Image
from io import BytesIO


async def get_dimensions_from_url(screenshot_url: str) -> tuple[int, int]:
    """更新截图的尺寸信息"""
    try:
        # 下载图片
        async with httpx.AsyncClient() as client:
            response = await client.get(screenshot_url)
            if response.is_error:
                return (0, 0)
        # 使用 PIL 获取图片尺寸
        image = Image.open(BytesIO(response.content))
        width, height = image.size
        image.close()
        return (width, height)
    except Exception as e:
        raise e
