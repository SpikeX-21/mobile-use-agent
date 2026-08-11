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
import InputArea from './InputArea';
import mobileUseIcon from '@/assets/mobile-use-icon.png';
import starIcon from '@/assets/star.svg';

interface SampleTask {
  id: string;
  title: string;
  description: string;
}

interface WelcomeViewProps {
  handleSendMessage: (text: string) => void;
  handleCancel: () => void;
  isCalling: boolean;
  isCanceling: boolean;
  sampleTasks: SampleTask[];
}

const WelcomeView: React.FC<WelcomeViewProps> = ({
  handleSendMessage,
  handleCancel,
  isCalling,
  isCanceling,
  sampleTasks,
}) => {
  // 添加输入框状态管理
  const [inputText, setInputText] = useState('');

  // 处理快速任务点击
  const handleSampleTaskClick = (task: SampleTask) => {
    // 设置输入文本
    setInputText(task.description);
  };

  // 处理发送消息
  const handleSend = (text: string) => {
    handleSendMessage(text);
    // 清空输入框
    setInputText('');
  };

  return (
    <div className="flex flex-col justify-center items-center h-full">
      <div className="max-w-[900px] flex flex-col items-center">
        {/* 欢迎消息区域 */}
        <div className="mb-6 flex h-[42px] items-start gap-3 mb-4">
          <Image
            src={mobileUseIcon}
            alt="Mobile Use Icon"
            width={36}
            height={36}
            className="mt-[3px] flex items-center justify-center"
            onError={e => {
              e.currentTarget.src = 'https://portal.volccdn.com/obj/volcfe/cloud-universal-doc/mobile_use.svg';
            }}
          />
          <div className="leading-[42px] text-[22px]">
            Hi，我是 Mobile Use Agent，你需要我帮你做什么？
          </div>
        </div>

        {/* 输入框区域 */}
        <div className="mb-8 w-full">
          <InputArea
            handleSendMessage={handleSend}
            handleCancel={handleCancel}
            isCalling={isCalling}
            isCanceling={isCanceling}
            inputValue={inputText}
            onTextChange={setInputText}
          />
        </div>

        {/* 快速任务区域 */}
        <div>
          <div className="flex items-center justify-center gap-2 mb-6">
            <span className="text-gray-400 text-[15px] flex items-center gap-1">
              <Image src={starIcon} alt="star" width={16} height={16} /> 快速体验以下任务场景
              <Image src={starIcon} alt="star" width={16} height={16} />
            </span>
          </div>
          <div className="grid grid-cols-2 gap-6">
            {sampleTasks.map(task => (
              <div
                key={task.id}
                onClick={() => handleSampleTaskClick(task)}
                className="bg-white py-[20px] px-4 rounded-[12px] cursor-pointer transition-all min-h-[94px] shadow-sm hover:shadow-md"
              >
                {task.title && <h3 className="mb-2 text-[#0C0D0E]">{task.title}</h3>}
                <p className="text-[#42464E] text-[14px]">{task.description}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default WelcomeView;
