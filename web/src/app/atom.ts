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

import { Message } from "@/hooks/useCloudAgent";
import CloudAgent from "@/lib/cloudAgent";
import { VePhoneClient } from "@/lib/vePhone";
import { SessionResponse } from "@/types";
import { atom } from "jotai";

// 从 sessionStorage 根据 threadId 读取消息列表的辅助函数
export const getMessagesFromStorage = (chatThreadId?: string): Message[] => {
  if (typeof window === 'undefined' || !chatThreadId) return [];
  try {
    const key = `mobile_use:${chatThreadId}:messages`;
    const stored = sessionStorage.getItem(key);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
};

// 保存消息列表到 sessionStorage 的辅助函数
export const saveMessagesToStorage = (messages: Message[], chatThreadId?: string): void => {
  if (typeof window === 'undefined' || !chatThreadId) return;
  try {
    const key = `mobile_use:${chatThreadId}:messages`;
    sessionStorage.setItem(key, JSON.stringify(messages));
  } catch {
    // 忽略存储错误
  }
};

// Pod ID 原子状态
export const PodIdAtom = atom<string | undefined>(undefined);
export const VePhoneAtom = atom<VePhoneClient>(
  new VePhoneClient()
);

export const cloudAgentAtom = atom<CloudAgent | null>(null);

// 消息列表原子状态 - 简单版本
export const MessageListAtom = atom<Message[]>([]);

export const initMessageStatusAtom = atom<boolean>(false)

// 用于手动初始化消息列表的 effect atom
export const initMessageListAtom = atom(
  null,
  (get, set) => {
    const cloudAgent = get(cloudAgentAtom);
    const chatThreadId = cloudAgent?.chatThreadId;

    if (chatThreadId) {
      const storedMessages = getMessagesFromStorage(chatThreadId);
      set(MessageListAtom, storedMessages);
      set(initMessageStatusAtom, true) // 设置初始化完成，用于页面组件渲染问题
    }
  }
);

// 用于保存消息到 sessionStorage 的 effect atom
export const saveMessageListAtom = atom(
  null,
  (get, set) => {
    const cloudAgent = get(cloudAgentAtom);
    const chatThreadId = cloudAgent?.chatThreadId;
    const messages = get(MessageListAtom);

    saveMessagesToStorage(messages, chatThreadId);
  }
);


export const TimeoutStateAtom = atom<'active' | 'experienceTimeout'>('active');
// 倒计时时间（秒）
export const CountdownAtom = atom<number>(30 * 60); // 30分钟
// 会话开始时间
export const StartTimeAtom = atom<number | null>(null);
// 会话数据原子状态
export const SessionDataAtom = atom<SessionResponse | null>(null);