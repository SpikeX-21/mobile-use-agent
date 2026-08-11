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

'use client';
import { useEffect, useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import Image from 'next/image';
import Phone from '@/components/phone';
import ChatPanel from '@/components/chat/ChatPanel';
import { useCloudAgentInit, useUpdateCloudAgentPodId } from '@/hooks/useCloudAgent';
import { STSToken } from '@/lib/vePhone';
import useTimeoutPhone, { useTimeoutState } from '@/hooks/useTimeoutPhone';
import { Panel, PanelGroup } from 'react-resizable-panels';
import { usePanelResize } from '@/hooks/useResize';
import ResizeHandle from '@/components/resize';
import { formatCountdown } from '@/lib/time/format';
import { VePhoneAtom, PodIdAtom, SessionDataAtom } from '../atom';
import cloudTaskIcon from '@/assets/cloud-task-icon.svg';
import backgroundImage from '@/assets/background.png';
import { SessionResponse } from '@/types';
import useCreateSessionAPI from '@/hooks/useCreateSession';
import { buildUrlWithToken } from '@/lib/utils';

function ChatPageContent() {
  useCloudAgentInit();
  const router = useRouter();
  const searchParams = useSearchParams();
  const initCountdown = useTimeoutPhone();
  const { updatePod: updatePodAgent, cloudAgent } = useUpdateCloudAgentPodId();
  const [vePhone] = useAtom(VePhoneAtom);
  const { timeoutState, countdownTime } = useTimeoutState();
  const setPodId = useSetAtom(PodIdAtom);
  const { leftPanelMinSize, rightPanelMinSize } = usePanelResize();
  const [isLoading, setIsLoading] = useState(true);
  const sessionData = useAtomValue(SessionDataAtom);
  const { createSession } = useCreateSessionAPI();

  const initWebVePhone = ({
    podId,
    productId,
    podSize,
    stsToken,
    accountId
  }: {
    podId: string;
    productId: string;
    podSize: {
      width: number;
      height: number;
    };
    stsToken: STSToken;
    accountId: string;
  }) => {
    vePhone.setPodInitInfo({
      podId,
      productId,
      podSize,
      stsToken,
      accountId
    });
    setPodId(podId);
  };

  const initMobileUse = (_sessionData: SessionResponse) => {
    console.log('使用缓存的会话数据');
    updatePodAgent({
      productId: _sessionData?.pod?.product_id,
      podId: _sessionData?.pod?.pod_id,
    });

    initWebVePhone({
      podId: _sessionData?.pod?.pod_id,
      productId: _sessionData?.pod?.product_id,
      podSize: _sessionData?.pod?.size,
      stsToken: _sessionData?.pod?.token,
      accountId: _sessionData?.pod?.account_id,
    });

    initCountdown(_sessionData?.pod?.expired_time);
  }

  useEffect(() => {
    // 检查身份验证和设置
    const setupSession = async () => {
      setIsLoading(true);

      // 鉴权逻辑：如果没有 threadId，重定向到首页
      if (!cloudAgent) {
        return;
      }
      if (!cloudAgent.threadId) {
        router.replace(buildUrlWithToken('/', searchParams));
        return;
      }

      try {
        // 优先使用全局状态中的会话数据
        if (sessionData) {
          initMobileUse(sessionData)
        } else {
          // 如果没有会话数据，但有 threadid 则请求一下会话看看
          const checkThreadId = async () => {
            if (cloudAgent?.threadId) {
              try {
                // 获取会话数据并存储到全局状态
                const data = await createSession();
                if (!data) {
                  router.replace(buildUrlWithToken('/', searchParams));
                  return;
                }
              } catch (error) {
                console.error('获取会话数据失败', error);
                router.replace(buildUrlWithToken('/', searchParams));
              }
            }
          };
          checkThreadId()
          return;
        }
      } catch (error) {
        console.error('初始化会话失败', error);
        router.replace(buildUrlWithToken('/', searchParams));
      } finally {
        setIsLoading(false);
      }
    };

    setupSession();
  }, [cloudAgent, router, sessionData, searchParams]);

  // 加载状态下显示更友好的加载指示器
  if (isLoading) {
    return (
      <div className="h-screen w-screen flex items-center justify-center"
        style={{
          backgroundColor: 'rgba(255, 255, 255, 0.2)',
          backgroundImage: `linear-gradient(rgba(255, 255, 255, 0.6), rgba(255, 255, 255, 0.6)), url(${backgroundImage.src})`,
          backgroundSize: '20px 20px',
        }}>
        <div className="flex flex-col items-center">
          <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
          <p className="text-gray-600">正在初始化云手机...</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="h-screen w-screen max-w-screen max-h-screen min-w-[1000px] overflow-auto bg-center bg-repeat"
      style={{
        backgroundColor: 'rgba(255, 255, 255, 0.2)',
        backgroundImage: `linear-gradient(rgba(255, 255, 255, 0.6), rgba(255, 255, 255, 0.6)), url(${backgroundImage.src})`,
        backgroundSize: '20px 20px',
      }}
    >
      <div className="flex flex-1 overflow-hidden h-screen w-full">
        {timeoutState === 'active' ? (
          <PanelGroup direction="horizontal" className="w-full h-full">
            <Panel minSize={leftPanelMinSize}>
              <div className="h-full overflow-hidden p-5 pr-[8px] relative pt-[80px]  flex flex-col items-stretch">
                <ChatPanel />
              </div>
            </Panel>
            <ResizeHandle />
            <Panel defaultSize={rightPanelMinSize} minSize={rightPanelMinSize}>
              <div className="p-5 pl-[8px] h-full w-full">
                <div className="bg-white rounded-xl shadow-sm w-full h-full flex flex-col overflow-hidden">
                  <div className="flex items-center gap-2 p-3 border-b border-gray-100">
                    <div className="w-5 h-5 flex-shrink-0 flex items-center justify-center">
                      <Image src={cloudTaskIcon} alt="Cloud Task Icon" width={20} height={20} />
                    </div>
                    <span className="font-medium text-sm text-gray-900">云手机任务执行过程</span>
                  </div>
                  <div className="p-6 flex flex-col items-center justify-center flex-auto overflow-hidden">
                    <Phone />
                    <p className="max-w-[360px] text-xs text-gray-500 text-center mt-4 flex-0 whitespace-nowrap">
                      因安全合规原因，体验页面已禁止与云手机实例点击交互
                      <br />
                      请知悉由于Demo应用白名单限制，部分应用会安装失败
                    </p>
                  </div>
                </div>
              </div>
            </Panel>
          </PanelGroup>
        ) : (
          <div className="w-full h-full overflow-hidden">
            <ChatPanel />
          </div>
        )}
      </div>
    </div>
  );
}

// 创建一个加载组件
function ChatPageFallback() {
  return (
    <div className="h-screen w-screen flex items-center justify-center"
      style={{
        backgroundColor: 'rgba(255, 255, 255, 0.2)',
        backgroundImage: `linear-gradient(rgba(255, 255, 255, 0.6), rgba(255, 255, 255, 0.6)), url(${backgroundImage.src})`,
        backgroundSize: '20px 20px',
      }}>
      <div className="flex flex-col items-center">
        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
        <p className="text-gray-600">正在加载...</p>
      </div>
    </div>
  );
}

// 主组件用 Suspense 包装
function ChatPage() {
  return (
    <Suspense fallback={<ChatPageFallback />}>
      <ChatPageContent />
    </Suspense>
  );
}

export default ChatPage;
