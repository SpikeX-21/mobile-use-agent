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

'use client';

import { VePhoneStatic } from "./type";

declare global {
  interface Window {
    vePhoneSDK: VePhoneStatic; // VePhone SDK 构造函数
  }
}

class UMDLoader {
  private static instance: UMDLoader;
  private loadPromise: Promise<VePhoneStatic> | null = null;
  private isLoaded = false;

  static getInstance(): UMDLoader {
    if (!UMDLoader.instance) {
      UMDLoader.instance = new UMDLoader();
    }
    return UMDLoader.instance;
  }

  async loadVePhoneSDK(): Promise<VePhoneStatic> {
    // 如果已经加载，直接返回
    if (this.isLoaded && window.vePhoneSDK) {
      return window.vePhoneSDK;
    }

    // 如果正在加载，返回同一个 Promise
    if (this.loadPromise) {
      return this.loadPromise;
    }

    // 确保在客户端环境
    if (typeof window === 'undefined') {
      throw new Error('VePhone SDK can only be loaded in client environment');
    }

    this.loadPromise = new Promise((resolve, reject) => {
      // 检查是否已经有脚本标签
      const existingScript = document.querySelector('script[src="/vephone-sdk.js"]');
      if (existingScript && window.vePhoneSDK) {
        this.isLoaded = true;
        resolve(window.vePhoneSDK);
        return;
      }

      const script = document.createElement('script');
      script.src = '/vephone-sdk.js';
      script.async = true;

      script.onload = () => {
        if (window.vePhoneSDK) {
          this.isLoaded = true;
          console.log('VePhone SDK loaded successfully');
          resolve(window.vePhoneSDK);
        } else {
          reject(new Error('VePhone SDK not found on window object'));
        }
      };

      script.onerror = () => {
        reject(new Error('Failed to load VePhone SDK'));
      };

      // 避免重复添加脚本
      if (!existingScript) {
        document.head.appendChild(script);
      }
    });

    return this.loadPromise;
  }

  isSDKLoaded(): boolean {
    return this.isLoaded && !!window.vePhoneSDK;
  }
}

export default UMDLoader; 