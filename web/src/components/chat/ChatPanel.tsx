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
import React, { useState, useEffect } from "react";
import { useAtom, useSetAtom, useAtomValue } from "jotai";
import { useCloudAgent, ChatMessage } from "@/hooks/useCloudAgent";
import { useTimeoutState } from "@/hooks/useTimeoutPhone";
import TimeoutView from "./TimeoutView";
import ChatView from "./ChatView";
import WelcomeView from "./WelcomeView";
import { MessageListAtom, SessionDataAtom, initMessageListAtom, initMessageStatusAtom, saveMessageListAtom } from "@/app/atom";
import ResetChat from "./ResetChat";

// 示例任务
const sampleTasks = [
  {
    id: 'task-2',
    title: '',
    description: '安装百度地图并从上海抖音新江湾广场导航到上海外滩',
  },
  {
    id: 'task-3',
    title: '',
    description: '安装大众点评APP，搜一下附近5km评价最好的火锅店',
  },
];

const ChatPanel: React.FC = () => {
  const [messages, setMessages] = useAtom(MessageListAtom);
  const [isCalling, setCalling] = useState(false);
  const [isCanceling, setCanceling] = useState(false);
  const [chatMode, setChatMode] = useState<'welcome' | 'chat' | 'init'>('init') // 明确的模式状态
  const cloudAgent = useCloudAgent();
  const { timeoutState } = useTimeoutState();
  const setSessionData = useSetAtom(SessionDataAtom);
  const initMessageList = useSetAtom(initMessageListAtom);
  const saveMessageList = useSetAtom(saveMessageListAtom);
  const initMessageStatus = useAtomValue(initMessageStatusAtom)

  // 在组件初始化时加载历史消息
  useEffect(() => {
    if (cloudAgent?.threadId) {
      initMessageList();
    }
  }, [cloudAgent?.threadId, initMessageList]);

  // 初始化时检查是否有历史消息，决定初始模式
  useEffect(() => {
    if (chatMode !== 'init' || initMessageStatus === false) {
      return
    }
    if (messages.length > 0) {
      setChatMode('chat');
    } else {
      setChatMode('welcome')
    }
  }, [messages, chatMode, initMessageStatus]);

  // 在消息更新时保存到 sessionStorage
  useEffect(() => {
    if (messages.length > 0 && cloudAgent?.threadId) {
      saveMessageList();
    }
  }, [messages, cloudAgent?.threadId, saveMessageList]);


  const appendUserMessage = (message: string) => {
    const newMessage: ChatMessage = {
      id: `${Date.now()}`,
      content: message,
      isUser: true,
      isFinish: true,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, newMessage]);
    // 明确切换到聊天模式
    setChatMode('chat');
  };

  const handleCancel = async () => {
    setCanceling(true);
    await cloudAgent?.cancel();
    setCanceling(false);
  };

  const handleSendMessage = async (text: string) => {
    if (text.trim() === "") return;

    appendUserMessage(text);
    setCalling(true);
    try {
      await cloudAgent?.call?.(text);
    } finally {
      setCalling(false);
    }
  };

  const handleRetry = () => {
    // 清空 threadId， 再次体验
    cloudAgent?.setThreadId("");
    // 清空会话数据
    setSessionData(null);
    window.location.reload();
  };

  // 根据状态渲染不同的视图
  if (timeoutState !== "active") {
    return <TimeoutView timeoutState={timeoutState} onRetry={handleRetry} />;
  }

  // 根据明确的模式状态来决定显示哪个视图
  if (chatMode === 'chat') {
    return (
      <>
        <ResetChat className='absolute z-10 top-0 right-0' />
        <ChatView
          messages={messages}
          handleSendMessage={handleSendMessage}
          handleCancel={handleCancel}
          isCalling={isCalling}
          isCanceling={isCanceling}
        />

      </>

    );
  }

  if (chatMode === 'welcome') {
    return (
      <WelcomeView
        handleSendMessage={handleSendMessage}
        handleCancel={handleCancel}
        isCalling={isCalling}
        isCanceling={isCanceling}
        sampleTasks={sampleTasks}
      />
    );
  }

  return <></>
};

export default ChatPanel;