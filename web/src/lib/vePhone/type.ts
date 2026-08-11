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

export interface STSToken {
  AccessKeyID: string;
  SecretAccessKey: string;
  SessionToken: string;
  CurrentTime: string;
  ExpiredTime: string;
}

export interface StartConfig {
  productId: string;
  podId: string;
  token: STSToken;
  rotation?: 'portrait';
  isScreenLock?: boolean; // !isPc
  mute?: boolean;
  audioAutoPlay?: boolean;
  remoteWindowSize?: {
    // 填死, agent 识别规约
    width: 1080;
    height: 1920;
  };
}

export interface VePhoneConstructorParams {
  userId: string;
  accountId: string;
  phoneHost?: string;
  isPC: boolean;
  domId: string;
  isDebug: boolean;
  enableLocalKeyboard: boolean;
  enableSyncClipboard: boolean;
  enableLocalMouseScroll: boolean;
  enableLocationService?: boolean;
  disableInteraction?: boolean;
}

export interface VePhoneStatic {
  new(params: VePhoneConstructorParams): VePhone;
  isRtcSupported: () => boolean;
}

export const enum KeyCode {
  Home = 3,
  Back = 4,
  Menu = 82,
  APP_SWITCH = 187,
}

export const enum ButtonAction {
  DOWN = 0,
  UP = 1,
  MOVE = 2,
}

export const enum TouchAction {
  TOUCH_START = 0,
  TOUCH_END = 1,
  TOUCH_MOVE = 2,
}

export const enum PCKeyAction {
  PC_TOUCH_UP = 0,
  PC_TOUCH_DOWN = 1,
  PC_TOUCH_MOVE = 2,
  WHEEL = 8,
}

export const enum MouseButton {
  LEFT = 0,
  CENTER = 1,
  RIGHT = 2,
}

export interface VePhone {
  on: (
    event: string,
    callback: (data: unknown) => void | Promise<void>,
  ) => void;
  setAutoRecycleTime: (time: number) => void;
  setIdleTime: (time: number) => void;
  start: (config: StartConfig) => void;
  stop: () => void;
  destroy: () => void;
  getVersion: () => string;
  getConnectionState: () => string;
  screenShot: (isSavedOnPod: boolean) => Promise<{
    /**
     * 截图结果:
     * 0：截图成功
     * -1：存储空间不足，截图失败
     * -2：未知原因，截图失败
     */
    result: number;
    /** 在云手机实例中保存截图文件的路径，例如：/sdcard/Pictures/Screenshots/20220721_164937.jpg */
    savePath: string;
    /** 错误码，正常情况为 0 */
    errorCode?: number;
    /** 错误信息，正常情况为空 */
    message: string;
    /** 截图成功时返回截图文件的下载链接，链接有效期1小时 */
    downloadUrl?: string;
  }>;
  launchApp: (appId: string) => Promise<{ result: number; message: string }>;
  sendTouchMessage: (params: {
    action: TouchAction;
    pointerId: number;
    x: number;
    y: number;
  }) => Promise<void>;
  getRemoteBackgroundAppList: () => Promise<string[]>;
  sendClipBoardMessage: (text: string) => Promise<void>;
  sendKeycodeMessage: (params: {
    keycode?: number;
    action?: ButtonAction;
  }) => Promise<void>;
  sendMouseMessage: (mouseMessage: {
    button?: MouseButton;
    action: PCKeyAction;
    wheel?: number;
    x: number;
    y: number;
  }) => void;
  startVideoStream: () => Promise<{
    success: boolean;
    code: number;
    message: string;
  }>;
  startSendAudioStream: () => Promise<{
    success: boolean;
    code: number;
    message: string;
  }>;
  stopVideoStream: () => Promise<{
    success: boolean;
    code: number;
    message: string;
  }>;
  stopSendAudioStream: () => Promise<{
    success: boolean;
    code: number;
    message: string;
  }>;
}
