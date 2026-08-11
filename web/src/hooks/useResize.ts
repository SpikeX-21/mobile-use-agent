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

import { useEffect, useState } from 'react';

export const usePanelResize = () => {
  const [leftPanelMinSize, setLeftPanelMinSize] = useState(30);
  const [rightPanelMinSize, setRightPanelMinSize] = useState(20);

  // 面板默认尺寸

  // 响应式布局设置
  useEffect(() => {
    const handleResize = () => {
      setRightPanelMinSize(Math.floor((400 / window.innerWidth) * 100));
      setLeftPanelMinSize(Math.floor((600 / window.innerWidth) * 100));
    };

    // 初始化时执行一次
    handleResize();

    // 监听窗口大小变化
    window.addEventListener('resize', handleResize);

    // 清理函数
    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  return {
    leftPanelMinSize,
    rightPanelMinSize,
  };
};
