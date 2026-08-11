// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// Licensed under the 【火山方舟】原型应用软件自用许可协议
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at 
//     https://www.volcengine.com/docs/82379/1433703
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { KeyCode, ButtonAction, TouchAction } from '../type';
import { catchLog } from './decorator';
// 删除直接导入
// import vePhoneSDK from '@volcengine/vephone';

export class PhoneTool {
  cursorId = 0;
  vePhone: any;

  constructor(vePhoneInstance?: any) {
    // 如果提供了实例，使用它；否则在客户端环境中动态导入
    this.vePhone = vePhoneInstance;
  }


  // home 键
  @catchLog()
  async home() {
    await this.vePhone.sendKeycodeMessage({
      keycode: KeyCode.Home,
      action: ButtonAction.DOWN,
    });
    await this.vePhone.sendKeycodeMessage({
      keycode: KeyCode.Home,
      action: ButtonAction.UP,
    });
  }

  // 返回键
  @catchLog()
  async back() {
    await this.vePhone.sendKeycodeMessage({
      keycode: KeyCode.Back,
      action: ButtonAction.DOWN,
    });
    await this.vePhone.sendKeycodeMessage({
      keycode: KeyCode.Back,
      action: ButtonAction.UP,
    });
  }

  // 切换应用
  @catchLog()
  async appSwitch() {
    await this.vePhone.sendKeycodeMessage({
      keycode: KeyCode.APP_SWITCH,
      action: ButtonAction.DOWN,
    });
    await this.vePhone.sendKeycodeMessage({
      keycode: KeyCode.APP_SWITCH,
      action: ButtonAction.UP,
    });
  }

  // 点击
  @catchLog()
  async touch(x: number, y: number) {
    await this.vePhone.sendTouchMessage({
      action: TouchAction.TOUCH_START,
      pointerId: this.cursorId,
      x,
      y,
    });
    await this.vePhone.sendTouchMessage({
      action: TouchAction.TOUCH_END,
      pointerId: this.cursorId,
      x,
      y,
    });
  }

  // 截图
  @catchLog()
  async screenShot() {
    const result = await this.vePhone.screenShot(false);
    return result;
  }

  // 滚动
  @catchLog()
  async scroll(y1: number, y2: number) {
    await this.swipe(0.5, y1, 0.5, y2);
  }

  // 滑动
  @catchLog()
  async swipe(x1: number, y1: number, x2: number, y2: number) {
    await this.vePhone.sendTouchMessage({
      action: TouchAction.TOUCH_START,
      pointerId: this.cursorId,
      x: x1,
      y: y1,
    });
    await this.vePhone.sendTouchMessage({
      action: TouchAction.TOUCH_MOVE,
      pointerId: this.cursorId,
      x: x2,
      y: y2,
    });
    return new Promise(resolve => {
      setTimeout(() => {
        this.vePhone.sendTouchMessage({
          action: TouchAction.TOUCH_END,
          pointerId: this.cursorId,
          x: x2,
          y: y2,
        });
        resolve(true);
      }, 0);
    });
  }
}
