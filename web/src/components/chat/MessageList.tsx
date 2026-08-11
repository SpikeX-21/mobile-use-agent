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

"use client";
import React from 'react';
import { UserMessage } from './ChatMessage';
import { Message } from '@/hooks/useCloudAgent';
import ThinkingMessageComponent from './ThinkingMessage';

interface MessageListProps {
  messages: Message[];
}

const MessageList: React.FC<MessageListProps> = ({ messages }) => {
  return (
    <div className="space-y-2">
      {messages.map((message, idx) => {
        // 如果是用户消息，直接显示
        if (message.isUser) {
          return <UserMessage key={message.id} message={message} />;
        } else {
          return <ThinkingMessageComponent key={`thinking-${message.id}`} messageId={message.id} message={message} />;
        }
      }, [])}
    </div>
  );
};

export default MessageList;
