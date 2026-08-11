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

import { STSToken } from "@/lib/vePhone";

// 模型相关类型
export interface Model {
  id: string;
  name: string;
  icon: React.ReactNode;
  description: string;
}

// 环境配置相关类型
export interface EnvironmentConfig {
  apiKey?: string;
  serviceUrl?: string;
}

// 聊天消息相关类型
export type UIMessage = UIChatMessage | UIButtonMessage | UIThinkingMessage;

export interface UIChatMessage {
  id: string;
  isFinish: boolean;
  content: string;
  isUser: boolean;
  timestamp: number;
}

export interface UIButtonMessage {
  id: string;
  isFinish?: boolean;
  content: string;
  isUser: boolean;
  isButton: boolean;
  timestamp: number;
}

export interface UIThinkingMessage {
  id: string;
  isThinking: true;
  executionState: {
    status: 'executing' | 'completed' | 'idle';
    currentStep: string;
    completedSteps: string[];
    isExecuting: boolean;
  };
  showExecutionStatus: boolean;
  timestamp: number;
}

// 会话相关类型
export interface Conversation {
  id: string;
  title: string;
  messages: UIMessage[];
  createdAt: string;
  updatedAt: string;
}


export type AgentType = 'ui-tars' |  'doubao-vision-pro';

export type ErrorResponse = {
  error: {
    code: number
    message: string
  }
}

export type SessionBackendResponse = ErrorResponse & {
  thread_id: string
  chat_thread_id: string
  userInfo: {
    accountId: string
    userId: string
    name: string
  }
  pod: {
    product_id: string
    pod_id: string
    expired_time: number
    token: STSToken
    size: { width: number, height: number }
    account_id: string
  }
}

export type SessionResponse = {
  userInfo: {
    accountId: string
    userId: string
    name: string
  }
  pod: {
    product_id: string
    pod_id: string
    expired_time: number
    token: STSToken
    size: { width: number, height: number }
    account_id: string
  }
}