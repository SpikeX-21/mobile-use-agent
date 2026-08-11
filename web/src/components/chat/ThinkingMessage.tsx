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

import React, { useState } from 'react';
import Image from 'next/image';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { atomDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { cn } from '@/lib/utils/css';
import { ChevronDown } from 'lucide-react';
import mobileUseIcon from '@/assets/mobile-use-icon.png';
import userInterruptIcon from '@/assets/user-interrupt.svg';
import toolLoadingIcon from '@/assets/tool-loading.png';
import stopIcon from '@/assets/tool-stop.png';
import { ThinkingMessage, TaskStep } from '@/hooks/useCloudAgent';

// 添加旋转动画的 CSS 类
const spinAnimation = 'animate-spin';

// 状态文本常量
const STATUS_TEXT = {
  start: '正在执行命令',
  success: '执行完成',
  stop: '执行失败',
};

// 状态图标常量
const STATUS_ICON = {
  start: (
    <Image
      src={toolLoadingIcon}
      alt="loading"
      width={12}
      height={12}
      className={cn('w-3 h-3', spinAnimation)}
      style={{ transformOrigin: 'center' }}
    />
  ),
  success: <Image src="/checked.svg" alt="completed" width={12} height={12} className="w-3 h-3" />,
  stop: <Image src={stopIcon.src} alt="completed" width={12} height={12} className="w-3 h-3" />,
  interrupt: <Image src={userInterruptIcon.src} alt="interrupted" width={12} height={12} className="w-3 h-3" />,
};

// 执行状态卡片组件
interface ProgressCardProps {
  className?: string;
  content?: React.ReactNode;
  contentClass?: string;
  toolName?: string;
  icon?: React.ReactNode;
}

const ProgressCard: React.FC<ProgressCardProps> = ({ className, content, contentClass, toolName, icon }) => {
  return (
    <div className={cn('rounded-lg border p-2 flex items-center gap-2 max-w-[50%] min-w-[200px]', className)}>
      <div className="w-5 h-5 rounded-full flex items-center justify-center text-green-600">{icon}</div>
      <div className="text-[13px]">
        {content && <span className={cn('mr-2', contentClass)}>{content}</span>}
        {toolName && <span className={cn('text-[#75798D] text-[12px]')}>{toolName}</span>}
      </div>
    </div>
  );
};

export interface ThinkingMessageProps {
  messageId: string;
  message: ThinkingMessage;
}

const ThinkingMessageComponent: React.FC<ThinkingMessageProps> = ({ messageId, message }) => {
  const [showExecutionStatus, setShowExecutionStatus] = useState(true);

  // 渲染单个步骤的函数
  const renderStep = (step: TaskStep) => {
    switch (step.type) {
      case 'think':
        return (
          <>
            <div className="text-[#42464E] text-[13px]">{step.content || ''}</div>
            {step.toolCall && (
              <ProgressCard
                className="bg-white border-[#E6E3DE]"
                icon={STATUS_ICON[step.toolCall.status || 'success']}
                content={STATUS_TEXT[step.toolCall.status || 'success']}
                toolName={step.toolCall.toolName}
              />
            )}
          </>
        );
      case 'user_interrupt':
        return (
          <ProgressCard className="bg-white border-[#E6E3DE]" icon={STATUS_ICON.interrupt} content={step.content} />
        );
      default:
        return null;
    }
  };

  return (
    <div key={`thinking-${messageId}`} className="max-w-[85%]">
      <div className="flex items-center gap-2 mb-2">
        <div
          className={cn('flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center')}
          style={{ borderRadius: '50%', overflow: 'hidden' }}
        >
          <Image
            style={{ transform: 'scale(1.1)' }}
            src={mobileUseIcon}
            alt="Mobile Use Agent"
            width={32}
            height={32}
          />
        </div>
        <span className="text-sm font-bold text-gray-600">Mobile Use Agent</span>
      </div>
      <div className="flex-1">
        <div className="bg-white rounded-lg p-4 space-y-4">
          <div className="flex flex-row items-center">
            <div className="flex items-center">
              <Image src="/thinking-dot.svg" alt="thinking dot" width={20} height={20} className="mr-1" />
              <span style={{ fontWeight: 500, fontSize: '13px' }}>执行过程</span>
            </div>
            <ChevronDown
              onClick={() => setShowExecutionStatus(!showExecutionStatus)}
              style={{
                width: '14px',
                height: '14px',
                cursor: 'pointer',
                marginLeft: '4px',
                color: 'rgba(115, 122, 135, 1)',
              }}
              className={cn('transition-transform', !showExecutionStatus && 'rotate-180')}
            />
          </div>
          {showExecutionStatus && (
            <div className="space-y-2 mt-4">
              {message.steps.map(step => (
                <div className="relative mb-4 py-2" key={`${step.id}-${step.type}`}>
                  <div className="absolute left-[10px] w-[1px] h-full bg-[#4D6B9933] -mt-2" />
                  <div className="space-y-2 ml-8">{renderStep(step)}</div>
                </div>
              ))}
              {message.steps.length === 0 && <div className="space-y-2 ml-8"></div>}
            </div>
          )}

          <ReactMarkdown
            rehypePlugins={[rehypeRaw]}
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0 text-[14px] text-[#0C0D0E]">{children}</p>,
              code: ({ node, inline, className, children, ...props }: any) => {
                const match = /language-(\w+)/.exec(className || '');
                return !inline && match ? (
                  <div className="rounded-md my-2 overflow-hidden">
                    <SyntaxHighlighter language={match[1]} style={atomDark} PreTag="div">
                      {String(children).replace(/\n$/, '')}
                    </SyntaxHighlighter>
                  </div>
                ) : (
                  <code {...props} className={cn('px-1 py-0.5 rounded-sm font-mono text-sm', className)}>
                    {children}
                  </code>
                );
              },
              ul: ({ children }) => <ul className="mb-2 text-[14px] text-[#0C0D0E]">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal mb-2 text-[14px] text-[#0C0D0E]">{children}</ol>,
              li: ({ children }) => (
                <li className="mb-1 flex items-center pl-2">
                  <span className="mr-2 h-[4px] w-[4px] rounded-full bg-[#0C0D0E] shrink-0"></span>
                  <span className="flex-grow">{children}</span>
                </li>
              ),
              a: ({ href, children }) => (
                <a href={href} className="text-blue-500 hover:underline" target="_blank" rel="noopener noreferrer">
                  {children}
                </a>
              ),
              h1: ({ children }) => <h1 className="text-xl font-bold mb-2">{children}</h1>,
              h2: ({ children }) => <h2 className="text-lg font-bold mb-2">{children}</h2>,
              h3: ({ children }) => <h3 className="text-md font-bold mb-2">{children}</h3>,
              blockquote: ({ children }) => (
                <blockquote className={cn('border-l-4 pl-3 py-1 my-2')}>{children}</blockquote>
              ),
            }}
          >
            {message.summary?.content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
};

export default ThinkingMessageComponent;
