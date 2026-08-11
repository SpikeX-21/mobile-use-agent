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

export interface MessageMeta {
  finish_reason?: string;
  model?: string;
  prompt_tokens?: number;
  total_tokens?: number;
}

export interface SSEContentMessageData {
  id: string;
  task_id: string;
  role: string;
  content: string;
  response_meta?: MessageMeta;
}

export interface SSEThinkMessageData extends SSEContentMessageData {
  type: "think";
}

export interface UserInterruptMessageData extends SSEContentMessageData {
  type: "user_interrupt";
  interrupt_type: "text";
}

export interface SummaryMessageData extends SSEContentMessageData {
  type: "summary";
}

export interface SSEToolCallMessageData {
  id: string;
  task_id: string;
  tool_id: string;
  type: "tool";
  status: "start" | "stop" | "success";
  tool_type: "tool_input" | "tool_output";
  tool_name: string;
  tool_input?: string;
  tool_output?: string;
}

export type SSEMessage =
  | SSEThinkMessageData
  | UserInterruptMessageData
  | SummaryMessageData
  | SSEToolCallMessageData;

/**
 * 同构 Socket 抽象类，用于 WebClient 和 Electron 之间通信 或者 和 服务端 SSE 通信。保持 Web 端逻辑几乎不变
 */
abstract class SSELike {
  abstract connect(): Promise<void>;

  abstract onMessage(handler: (json: SSEMessage) => void): void;

  abstract close(): void;
}

export enum EVENT_KEY {
  MESSAGE = 'message',
  DONE = 'done',
}

export interface MapKey {
  [EVENT_KEY.MESSAGE]: (json: SSEMessage) => void;
  [EVENT_KEY.DONE]: () => void;
}

export default SSELike;
