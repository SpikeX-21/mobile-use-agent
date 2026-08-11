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

import { StartConfig, STSToken, VePhoneConstructorParams } from '../type';
import { VE_PHONE_CONFIG, DOM_ID } from './config';
import { EventEmitter } from 'eventemitter3';
import { VePhoneError } from './error';
import { PhoneTool } from './tool';
import { Camera } from './camera';
import logger from '@/lib/vePhone/log';
import UMDLoader from '../loader';
// import VePhoneSDK from '@volcengine/vephone'

type InstanceOptions = Partial<
  Pick<
    VePhoneConstructorParams,
    | 'userId'
    | 'isPC'
    | 'isDebug'
    | 'enableLocalKeyboard'
    | 'enableSyncClipboard'
    | 'enableLocalMouseScroll'
    | 'enableLocationService'
    | 'disableInteraction'
  >
>;

class VePhoneClient extends EventEmitter {
  private vePhone: any | null = null;
  private podId: string | undefined;
  private productId: string | undefined;
  private podSize:
    | {
      width: number;
      height: number;
    }
    | undefined;
  private stsToken: STSToken | undefined;
  private vePhoneSDK: any | null = null;
  private accountId: string | undefined;
  static VePhoneEvent = {
    Starting: 'starting',
    StartSuccess: 'start-success',
    Stop: 'stop',
    Destroy: 'destroy',
    StartError: 'start-error',
  };
  tool!: PhoneTool;
  camera!: Camera;

  constructor() {
    super();
  }

  reset() {
    this.stop();
    this.destroy();
    this.vePhone = null;
    this.podId = undefined;
    this.productId = undefined;
    this.podSize = undefined;
    this.stsToken = undefined;
    this.accountId = undefined;
  }

  setPodInitInfo({
    podId,
    stsToken,
    podSize,
    productId,
    accountId,
  }: {
    podId: string;
    productId: string;
    podSize: {
      width: number;
      height: number;
    };
    stsToken: STSToken;
    accountId: string;
  }) {
    this.podId = podId;
    this.accountId = accountId;
    this.productId = productId;
    this.podSize = podSize;
    this.stsToken = stsToken;
  }

  async init(options?: InstanceOptions) {
    // 确保在客户端环境
    if (typeof window === 'undefined') {
      throw new Error('VePhoneClient init can only be called in client-side environment');
    }

    // 确保已经加载了 SDK
    if (!this.vePhoneSDK) {
      try {
        const loader = UMDLoader.getInstance();
        this.vePhoneSDK = await loader.loadVePhoneSDK();
        logger.info('VePhone SDK loaded successfully');
      } catch (error) {
        console.error('Failed to load vePhoneSDK:', error);
        throw new Error('Failed to load vePhoneSDK');
      }
    }

    // this.vePhoneSDK = VePhoneSDK;

    const params = Object.assign(
      {
        isPC: true,
        isDebug: false,
        enableLocalKeyboard: false, // 开启云端键盘
        enableLocationService: true, // 开启定位服务
        // 禁用交互， 禁用后， 无法进行交互
        // disableInteraction: true, // 禁用交互， 禁用后， 无法进行交互
        // enableSyncClipboard: false, // 禁用同步剪贴板
        // enableLocalMouseScroll: false, // 禁用本地鼠标滚动
      },
      options,
    );
    const sdkInitConfig = {
      ...VE_PHONE_CONFIG,
      domId: DOM_ID,
      accountId: this.accountId,
      ...params,
    };

    this.vePhone = new this.vePhoneSDK(sdkInitConfig);

    // this.vePhone._localKeyboardHandler.destroy();
    // this.vePhone._keyboardDisableHandler.setEnabled(false);
    this.tool = new PhoneTool(this.vePhone);
    this.camera = new Camera(this.vePhone);
    logger.info('vePhoneSDK version', this.vePhone.getVersion());
    logger.info('sdkInitConfig', sdkInitConfig);
    this.bindEvent();
  }

  bindEvent() {
    if (!this.vePhone) {
      return;
    }
    (this.vePhone as any).on('message-received', (params: unknown) => {
      const { msg } = params as { msg: { command: number } };
      const { command } = msg;
      if (command === 8) {
        logger.info('timeout exit');
      }
    });

    (this.vePhone as any).on('on-screen-rotation', (params: unknown) => {
      this.emit('on-screen-rotation', params);
    });

    window.addEventListener('beforeunload', () => {
      if (!this.vePhone?.getConnectionState) {
        return;
      }
      const connectionState = this.vePhone?.getConnectionState?.();
      if (connectionState === 'CONNECTED') {
        this.vePhone?.stop();
        this.vePhone.destroy();
      }
    });

    window.addEventListener('error', event => {
      const { errorCode, errorMessage } = event as unknown as {
        errorCode: number;
        errorMessage: string;
      };
      logger.info('error', event, errorCode, errorMessage);
    });
  }

  async start(
    config?: Partial<Pick<StartConfig, 'rotation' | 'isScreenLock' | 'mute' | 'audioAutoPlay'>> &
      Pick<StartConfig, 'podId'>,
    instanceOptions?: InstanceOptions,
  ) {
    console.log('podid', config);
    if (config?.podId) {
      this.podId = config?.podId;
    }
    if (!this.podId) {
      throw Error('pod id is required');
    }

    if (!this.vePhone) {
      await this.init({ userId: `mobileuse-${this.podId}`, ...instanceOptions });
    }

    //  从后端拿的状态，通过分配pod的时候接口获得
    const sessionConfig = {
      productId: this.productId,
      remoteWindowSize: {
        width: this.podSize?.width,
        height: this.podSize?.height,
      },
      token: {
        AccessKeyID: this.stsToken?.AccessKeyID,
        SecretAccessKey: this.stsToken?.SecretAccessKey,
        SessionToken: this.stsToken?.SessionToken,
        CurrentTime: this.stsToken?.CurrentTime,
        ExpiredTime: this.stsToken?.ExpiredTime,
      },
    };

    const phoneConfig = Object.assign(
      {
        // rotation: 'auto',
        isScreenLock: false,
        mute: false,
        audioAutoPlay: true,
      },
      config,
    );

    const params = {
      ...sessionConfig,
      ...phoneConfig,
    };
    this.emit(VePhoneClient.VePhoneEvent.Starting);
    try {
      if (!this.vePhone) {
        return;
      }
      const result = await this.vePhone.start(params);
      this.emit(VePhoneClient.VePhoneEvent.StartSuccess);
      logger.info('start result', result);
      /** 无操作回收时长2h */
      this.vePhone.setAutoRecycleTime(120 * 60);
      /** 客户端退房后pod端 延迟30s 退房 */
      this.vePhone.setIdleTime(60);
      return result;
    } catch (error) {
      logger.error('start error', error);
      this.emit(VePhoneClient.VePhoneEvent.StartError, new VePhoneError(error as VePhoneError));
    }
  }

  async changePodId(podId: string) {
    if (this.podId) {
      const connectionState = this.vePhone?.getConnectionState?.();
      if (connectionState === 'CONNECTED') {
        await this.stop();
      }
    }
    this.podId = podId;
    const result = await this.start({ podId });
    logger.info('changePodId result', result);
    return result;
  }

  async refresh() {
    if (!this.podId) {
      return;
    }
    const connectionState = this.vePhone?.getConnectionState?.();
    if (connectionState === 'CONNECTED') {
      await this.stop();
    }
    const result = await this.start({ podId: this.podId });
    logger.info('refresh result', result);
    return result;
  }

  async stop() {
    try {
      if (!this.vePhone) {
        return;
      }
      const result = await this.vePhone.stop();
      logger.info('stop result', result);
      this.emit(VePhoneClient.VePhoneEvent.Stop);
    } catch (error) {
      logger.error('stop error', error);
    }
  }

  async destroy() {
    try {
      if (!this.vePhone) {
        return;
      }
      const result = await this.vePhone.destroy();
      logger.info('destroy result', result);
      this.emit(VePhoneClient.VePhoneEvent.Destroy);
    } catch (error) {
      logger.error('destroy error', error);
    }
  }

  onWithDisposer(event: string, callback: (params: unknown) => void): void | (() => void) {
    this.on(event, callback);

    return () => {
      this.off(event, callback);
    };
  }

  onceWithDisposer(event: string, callback: (params: unknown) => void): void | (() => void) {
    this.once(event, callback);

    return () => {
      this.off(event, callback);
    };
  }
}

export { VePhoneClient };
