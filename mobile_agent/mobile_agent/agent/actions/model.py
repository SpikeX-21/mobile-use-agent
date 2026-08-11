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

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class ActionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


NormalizedCoordinate = Annotated[int, Field(ge=0, le=1000)]


class TapAction(ActionModel):
    type: Literal["tap"] = "tap"
    x: NormalizedCoordinate
    y: NormalizedCoordinate


class SwipeAction(ActionModel):
    type: Literal["swipe"] = "swipe"
    start_x: NormalizedCoordinate
    start_y: NormalizedCoordinate
    end_x: NormalizedCoordinate
    end_y: NormalizedCoordinate
    duration_ms: int = Field(default=300, ge=1, le=10_000)


class TextInputAction(ActionModel):
    type: Literal["text_input"] = "text_input"
    text: str = Field(min_length=1)


class ClearTextAction(ActionModel):
    type: Literal["clear_text"] = "clear_text"


class HomeAction(ActionModel):
    type: Literal["home"] = "home"


class BackAction(ActionModel):
    type: Literal["back"] = "back"


class MenuAction(ActionModel):
    type: Literal["menu"] = "menu"


class LaunchAppAction(ActionModel):
    type: Literal["launch_app"] = "launch_app"
    package_name: str = Field(min_length=1)


class CloseAppAction(ActionModel):
    type: Literal["close_app"] = "close_app"
    package_name: str = Field(min_length=1)


class ListAppsAction(ActionModel):
    type: Literal["list_apps"] = "list_apps"
    ignore_system_apps: bool | None = None


class WaitAction(ActionModel):
    type: Literal["wait"] = "wait"
    duration_ms: int = Field(ge=1, le=10_000)


class FinishAction(ActionModel):
    type: Literal["finish"] = "finish"
    summary: str = Field(min_length=1)


class FailAction(ActionModel):
    type: Literal["fail"] = "fail"
    reason: str = Field(min_length=1)


CanonicalAction = Annotated[
    TapAction
    | SwipeAction
    | TextInputAction
    | ClearTextAction
    | HomeAction
    | BackAction
    | MenuAction
    | LaunchAppAction
    | CloseAppAction
    | ListAppsAction
    | WaitAction
    | FinishAction
    | FailAction,
    Field(discriminator="type"),
]
_canonical_action_adapter = TypeAdapter(CanonicalAction)


def validate_canonical_action(value: object) -> CanonicalAction:
    return _canonical_action_adapter.validate_python(value)
