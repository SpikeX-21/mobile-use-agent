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

import { useEffect } from 'react';
import { useAtomValue, useSetAtom } from 'jotai';
import { SSEMessage } from '@/lib/socket/abc';
import CloudAgent from '@/lib/cloudAgent';
import { MessageListAtom, cloudAgentAtom, saveMessageListAtom } from '@/app/atom';

interface BaseMessage {
  id: string;
  isUser?: boolean;
  isFinish: boolean;
  timestamp: number;
}

export interface ChatMessage extends BaseMessage {
  content: string;
  isUser: true;
}

export interface ThinkingMessage extends BaseMessage {
  isUser: false;
  steps: TaskStep[];
  taskId: string;
  summary?: Summary;
}

// 定义四种TaskStep类型
interface BaseStep {
  id: string;
  taskId: string;
}

export interface ToolCall {
  toolId: string;
  status: 'start' | 'stop' | 'success';
  toolType: 'tool_input' | 'tool_output';
  toolName: string;
  toolInput?: any;
  toolOutput?: any;
}

export interface UserInterruptStep extends BaseStep {
  type: 'user_interrupt';
  interruptType: 'text';
  content: string;
}

export interface Summary extends BaseStep {
  type: 'summary';
  content: string;
}

export interface ThinkStep extends BaseStep {
  type: 'think';
  content: string;
  toolCall?: ToolCall;
}

export type TaskStep = UserInterruptStep | ThinkStep;

export type Message = ChatMessage | ThinkingMessage;

export const useCloudAgentInit = () => {
  const setCloudAgent = useSetAtom(cloudAgentAtom);
  const setMessageList = useSetAtom(MessageListAtom);
  const saveMessageList = useSetAtom(saveMessageListAtom);

  useEffect(() => {
    // 将消息处理逻辑移到 hook 内部
    const handleSSEMessage = (json: SSEMessage) => {
      setMessageList((pre: Message[]) => {
        // 查找是否有相同task_id的消息
        let thinkingMessage = pre.find(message => 'taskId' in message && message.taskId === json.task_id) as
          | ThinkingMessage
          | undefined;

        if (!thinkingMessage) {
          // 创建新的ThinkingMessage
          thinkingMessage = {
            id: json.task_id,
            isFinish: false,
            timestamp: Date.now(),
            isUser: false,
            steps: [],
            taskId: json.task_id,
          };
          pre.push(thinkingMessage);
        }

        if (!('type' in json)) {
          return [...pre];
        }

        switch (json.type) {
          case 'think':
            // 查找或创建ThinkStep
            let thinkStep = thinkingMessage.steps.find(step => step.type === 'think' && step.id === json.id) as
              | ThinkStep
              | undefined;

            if (!thinkStep) {
              // 不存在相同id的ThinkStep，创建新的
              thinkStep = {
                id: json.id,
                taskId: json.task_id,
                type: 'think',
                content: '',
              };

              thinkingMessage.steps.push(thinkStep);
            }

            thinkStep.content = `${thinkStep.content}${json.content}`.replaceAll('\\n', '\n');
            break;
          case 'user_interrupt':
            const newUserInterruptStep: UserInterruptStep = {
              id: json.id,
              taskId: json.task_id,
              type: 'user_interrupt',
              interruptType: json.interrupt_type,
              content: json.content,
            };

            thinkingMessage.steps.push(newUserInterruptStep);
            break;
          case 'tool':
            // 查找与当前工具调用相同ID的ThinkStep
            let thinkStepForTool = thinkingMessage.steps.find(step => step.type === 'think' && step.id === json.id) as
              | ThinkStep
              | undefined;

            if (!thinkStepForTool) {
              // 如果不存在相同ID的ThinkStep，创建新的
              thinkStepForTool = {
                id: json.id,
                taskId: json.task_id,
                type: 'think',
                content: '',
                toolCall: {
                  toolId: json.tool_id,
                  status: json.status,
                  toolType: json.tool_type,
                  toolName: json.tool_name,
                  toolInput: json.tool_input,
                  toolOutput: json.tool_output,
                },
              };
              thinkingMessage.steps.push(thinkStepForTool);
            } else {
              // 如果存在相同ID的ThinkStep，更新或添加toolCall
              thinkStepForTool.toolCall = {
                ...(thinkStepForTool.toolCall || {}),
                toolId: json.tool_id,
                status: json.status,
                toolType: json.tool_type,
                toolName: json.tool_name,
                toolInput: json.tool_input,
                toolOutput: json.tool_output,
              };
            }
            break;
          case 'summary':
            // 更新summary内容
            if (!thinkingMessage.summary) {
              // 如果summary不存在，创建新的
              const newSummary: Summary = {
                id: json.id,
                taskId: json.task_id,
                type: 'summary',
                content: '',
              };
              thinkingMessage.summary = newSummary;
            }
            thinkingMessage.summary.content = `${thinkingMessage.summary.content}${json.content}`.replaceAll(
              '\\n',
              '\n',
            );
            break;
          default:
            break;
        }

        const updatedMessages = [...pre];
        // 触发保存到 sessionStorage
        setTimeout(() => saveMessageList(), 0);
        return updatedMessages;
      });
    };

    const handleSSEDone = () => {
      console.log('handleSSEDone');
      setMessageList((pre: Message[]) => {
        console.log('done');
        // 找到最后一条未完成的消息，将其标记为已完成
        const lastUnfinishedIndex = pre.findLastIndex(msg => !msg.isFinish);
        if (lastUnfinishedIndex >= 0) {
          const updatedMessages = [...pre];
          updatedMessages[lastUnfinishedIndex] = {
            ...updatedMessages[lastUnfinishedIndex],
            isFinish: true,
          };
          // 触发保存到 sessionStorage
          setTimeout(() => saveMessageList(), 0);
          return updatedMessages;
        }
        return pre;
      });
    };

    const agent = new CloudAgent();
    agent.onMessage(handleSSEMessage);
    agent.onMessageDone(handleSSEDone);
    setCloudAgent(agent);

    // 清理函数
    return () => {
      // 清理事件监听器
      agent.offMessage();
      agent.offMessageDone();
    };
  }, [setCloudAgent, setMessageList, saveMessageList]);
};

export const useCloudAgent = () => {
  const cloudAgent = useAtomValue(cloudAgentAtom);
  return cloudAgent;
};

export const useUpdateCloudAgentPodId = () => {
  const cloudAgent = useAtomValue(cloudAgentAtom);

  const updatePod = ({ productId, podId }: { productId: string, podId: string }) => {
    if (cloudAgent) {
      cloudAgent.setProductPodId(productId, podId);
    }
  };

  return { cloudAgent, updatePod };
};
