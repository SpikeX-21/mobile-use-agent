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

TRAIN_WIDTH = 1000  # FOR UI_TARS
TRAIN_HEIGHT = 1000  # FOR UI_TARS


def regular_bbox_for_ui_tars(x1, y1, x2, y2, width, height):
    x1_reg = int((x1 * width) / TRAIN_WIDTH)
    y1_reg = int((y1 * height) / TRAIN_HEIGHT)
    x2_reg = int((x2 * width) / TRAIN_WIDTH)
    y2_reg = int((y2 * height) / TRAIN_HEIGHT)
    return [x1_reg, y1_reg, x2_reg, y2_reg]


def bbox_to_point(bbox):
    x1 = bbox[0]
    y1 = bbox[1]
    x2 = bbox[2]
    y2 = bbox[3]
    return [(x1 + x2) / 2, (y1 + y2) / 2]
