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

import { safeJSONParse } from '@/lib/utils';
import { EVENT_KEY, MapKey, SSEMessage } from '@/lib/socket/abc';
import { fetchAPI, fetchSSE } from './fetch';
import { getDefaultStore } from 'jotai';
import { cloudAgentAtom, MessageListAtom, saveMessageListAtom } from '@/app/atom';

const MOBILE_USE_THREAD_ID_KEY = 'mobile_use:thread_id'
const MOBILE_USE_CHAT_THREAD_ID_KEY = 'mobile_use:chat_thread_id'
export const MOBILE_USE_PRODUCT_ID_KEY = 'mobile_use:product_id'
export const MOBILE_USE_POD_ID_KEY = 'mobile_use:pod_id'

class CloudAgent {
  private _ready: boolean;
  private handler: Map<keyof MapKey, MapKey[keyof MapKey]> = new Map();
  private _threadId: string | undefined;
  private _chatThreadId: string | undefined;
  private _abortController?: AbortController;
  private _podId?: string;
  private _productId?: string;

  constructor() {
    this._ready = false;
    this._threadId = sessionStorage.getItem(MOBILE_USE_THREAD_ID_KEY) || undefined;
    this._chatThreadId = sessionStorage.getItem(MOBILE_USE_CHAT_THREAD_ID_KEY) || undefined
    this._podId = localStorage.getItem(MOBILE_USE_POD_ID_KEY) || undefined;
    this._productId = localStorage.getItem(MOBILE_USE_PRODUCT_ID_KEY) || undefined;
    this.handler.set(EVENT_KEY.MESSAGE, () => { });
    this.handler.set(EVENT_KEY.DONE, () => { });
  }

  get ready() {
    return this._ready;
  }

  get threadId() {
    return this._threadId;
  }

  get chatThreadId() {
    return this._chatThreadId
  }

  get podId() {
    return this._podId;
  }

  get productId() {
    return this._productId;
  }

  setProductPodId(productId: string, podId: string) {
    this._productId = productId;
    this._podId = podId;
    localStorage.setItem(MOBILE_USE_PRODUCT_ID_KEY, productId);
    localStorage.setItem(MOBILE_USE_POD_ID_KEY, podId);
  }

  setThreadId(threadId: string) {
    if (this._threadId === threadId) {
      return;
    }
    this._threadId = threadId;
    sessionStorage.setItem(MOBILE_USE_THREAD_ID_KEY, threadId);
  }

  setChatThreadId(chatThreadId: string) {
    if (this._chatThreadId === chatThreadId) {
      return;
    }
    this._chatThreadId = chatThreadId
    sessionStorage.setItem(MOBILE_USE_CHAT_THREAD_ID_KEY, chatThreadId)
  }

  closeConnection() {
    if (this._abortController) {
      this._abortController.abort();
      this._abortController = undefined;
    }
  }

  async call(message: string) {
    if (!this._podId) {
      throw new Error('podId is required');
    }

    this.closeConnection();

    this._abortController = new AbortController();
    try {
      await this._call(message);
    } catch (error) {
      // 如果是中止错误，则不需要抛出
      if (error instanceof DOMException && error.name === 'AbortError') {
        console.log('SSE连接已主动关闭');
        return;
      }
      throw error;
    } finally {
      this._abortController = undefined;
    }
  }

  private async _call(message: string) {
    const readable = await fetchSSE(`/api/agent/stream`, {
      method: 'POST',
      body: JSON.stringify({
        thread_id: this._threadId,
        message,
        pod_id: this._podId,
      }),
      signal: this._abortController?.signal,
    });

    const reader = readable.getReader();
    const decoder = new TextDecoder();

    let buffer = '';

    // 处理流数据
    try {
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          (this.handler.get(EVENT_KEY.DONE) as MapKey[typeof EVENT_KEY.DONE])?.();
          break;
        }

        // 将二进制数据转换为文本
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.trim() === '') {
            continue;
          }

          try {
            if (typeof line === 'string' && line.startsWith('data: ')) {
              this._onMessage(line as `data: ${string}`);
            }
          } catch (error) {
            console.error('解析消息失败:', error, line);
          }
        }
      }
    } catch (error) {
      // 处理SSE流读取过程中的错误
      console.log('SSE连接断开:', error);
      // 触发DONE事件，通知前端SSE连接已断开
      throw error;
    } finally {
      (this.handler.get(EVENT_KEY.DONE) as MapKey[typeof EVENT_KEY.DONE])?.();
    }
  }

  async cancel() {
    if (!this._threadId) {
      throw new Error('threadId is required');
    }
    this.closeConnection()
    await fetchAPI(`/api/agent/cancel`, {
      method: 'POST',
      body: JSON.stringify({
        thread_id: this._threadId,
      }),
    });
  }

  private _onMessage(data: `data: ${string}`) {
    const jsonStr = data.split('data: ')[1];
    if (jsonStr === '[DONE]') {
      (this.handler.get(EVENT_KEY.DONE) as MapKey[typeof EVENT_KEY.DONE])?.();
      return;
    }
    const json: SSEMessage = safeJSONParse(jsonStr);
    if (!json) {
      return;
    }
    this.handler.get(EVENT_KEY.MESSAGE)?.(json);
  }

  onMessageDone(handler: () => void) {
    this.handler.set(EVENT_KEY.DONE, handler);
  }

  onMessage(handler: (json: SSEMessage) => void) {
    this.handler.set(EVENT_KEY.MESSAGE, handler);
  }

  offMessageDone() {
    this.handler.set(EVENT_KEY.DONE, () => { });
  }

  offMessage() {
    this.handler.set(EVENT_KEY.MESSAGE, () => { });
  }
}

export const changeAgentChatThreadId = (chatThreadId: string) => {
  const store = getDefaultStore()
  const cloudAgent = store.get(cloudAgentAtom)
  if (cloudAgent) {
    if (cloudAgent.chatThreadId === chatThreadId) { return }
    store.set(MessageListAtom, [])
    cloudAgent.setChatThreadId(chatThreadId)
  }
}

export default CloudAgent;
