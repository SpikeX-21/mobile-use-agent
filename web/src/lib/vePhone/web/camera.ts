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

import logger from '@/lib/vePhone/log';
import UMDLoader from '../loader';
const VIDEO_CODE_MSG_MAP = {
  GET_VIDEO_TRACK_FAILED: '请授权网站获取摄像头权限', // 当申请摄像头权限被用户禁止时，code 为 'GET_VIDEO_TRACK_FAILED'
  PUBLISH_FAIL: '视频流发布失败，请重试或联系客服', // 当发布视频流失败时，code 为 'PUBLISH_FAIL' ，此时可能是用户网络问题或服务异常，可以重新 start 或告知用户有异常稍后再试
} as const;

// 这里映射的 MSG 仅作为告诉开发者报错 CODE 的含义
const AUDIO_CODE_MSG_MAP = {
  GET_AUDIO_TRACK_FAILED: '请授权网站获取麦克风权限', // 当申请麦克风权限被用户禁止时，code 为 'GET_AUDIO_TRACK_FAILED'
  PUBLISH_FAIL: '音频流发布失败，请重试或联系客服', // 当发布音频流失败时，code 为 'PUBLISH_FAIL' ，此时可能是用户网络问题或服务异常，可以重新 start 或告知用户有异常稍后再试
} as const;

class Camera {
  constructor(private vePhone: any) {
    this.bindEvent();
  }

  // 确保在客户端环境中动态加载vePhone SDK
  static async create(vePhoneInstance?: any) {
    // 检查是否在客户端环境
    if (typeof window === 'undefined') {
      throw new Error('Camera can only be initialized in client-side environment');
    }

    if (!vePhoneInstance) {
      const loader = UMDLoader.getInstance();
      const VePhoneSDK = await loader.loadVePhoneSDK();
      vePhoneInstance = VePhoneSDK;
    }

    return new Camera(vePhoneInstance);
  }

  bindEvent() {
    (this.vePhone as any).on('remote-stream-start-request', async (data: any) => {
      const { isAudio, isVideo } = data as {
        isAudio: boolean;
        isVideo: boolean;
      };
      logger.info('remote-stream-start-request', data);
      if (isVideo) {
        await this.startVideoStream();
      }
      if (isAudio) {
        await this.startSendAudioStream();
      }
    });
    (this.vePhone as any).on('remote-stream-stop-request', async (data: any) => {
      const { isAudio, isVideo } = data as {
        isAudio: boolean;
        isVideo: boolean;
      };
      logger.info('remote-stream-stop-request', data);
      if (isVideo) {
        await this.vePhone.stopVideoStream();
      }
      if (isAudio) {
        await this.vePhone.stopSendAudioStream();
      }
    });
  }

  async startVideoStream() {
    const { success, code, message } = await this.vePhone.startVideoStream();

    if (!success) {
      const msg =
        VIDEO_CODE_MSG_MAP[code as unknown as keyof typeof VIDEO_CODE_MSG_MAP] ||
        `本地摄像头注入失败，失败 Code：${code}，错误消息：${message}`;
      logger.info(msg);
    }
  }

  async startSendAudioStream() {
    const { success, code, message } =
      await this.vePhone.startSendAudioStream();
    if (!success) {
      const msg =
        AUDIO_CODE_MSG_MAP[code as unknown as keyof typeof AUDIO_CODE_MSG_MAP] ||
        `本地麦克风注入失败，失败 Code：${code}，错误消息：${message}`;
      logger.info(msg);
    }
  }
}

export { Camera };
