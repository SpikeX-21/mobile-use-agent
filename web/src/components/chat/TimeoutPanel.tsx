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

import React from 'react';
import { Button } from '@/components/ui/button';
import Image from 'next/image';

interface TimeoutPanelProps {
  type: 'experienceTimeout';
  onRetry: () => void;
}

const TimeoutPanel: React.FC<TimeoutPanelProps> = ({ type, onRetry }) => {
  const content = {
    experienceTimeout: {
      icon: '/30-min-icon.svg',
      text: '30分钟体验已结束，若您有兴趣了解更多请联系您的火山对接人员，或通过方案咨询留下您的联系方式',
    },
  };

  const onConsult = () => {
    window.open('https://www.volcengine.com/contact/product-acep', '_blank');
  };

  return (
    <div className="flex flex-col items-center justify-center">
      <Image src={content[type].icon} alt="timeout icon" width={64} height={64} className="mb-6" />
      <p className="text-center text-[14px] text-[#86909C] mb-6 max-w-[400px] px-4">{content[type].text}</p>
      <div className="flex gap-3">
        <Button
          onClick={onConsult}
          className="relative cursor-pointer h-10 px-4 text-white rounded-[10px] overflow-hidden"
          style={{
            background: 'linear-gradient(77.86deg, #3B91FF -3.23%, #0D5EFF 51.11%, #C069FF 98.65%)',
            border: 'none',
          }}
        >
          方案咨询
        </Button>
        <Button
          onClick={() => {
            window.open('https://bytedance.larkoffice.com/share/base/form/shrcn0fT1SGEG19AI0ONIIHf3oh', '_blank');
          }}
          variant="outline"
          className="relative cursor-pointer h-10 px-4 rounded-[10px] overflow-hidden"
          style={{
            border: 'none',
            background: 'linear-gradient(77.86deg, #3B91FF -3.23%, #0D5EFF 51.11%, #C069FF 98.65%)',
            padding: '2px',
          }}
        >
          <div className="w-full h-full bg-white rounded-[8px] flex items-center justify-center text-[#42464E] px-[14px] py-[2px]">
            问卷反馈
          </div>
        </Button>
        <Button
          onClick={onRetry}
          variant="outline"
          className="relative cursor-pointer h-10 px-4 rounded-[10px] overflow-hidden"
          style={{
            border: 'none',
            background: 'linear-gradient(77.86deg, #3B91FF -3.23%, #0D5EFF 51.11%, #C069FF 98.65%)',
            padding: '2px',
          }}
        >
          <div className="w-full h-full bg-white rounded-[8px] flex items-center justify-center text-[#42464E] px-[14px] py-[2px]">
            再次体验
          </div>
        </Button>
      </div>
    </div>
  );
};

export default TimeoutPanel;
