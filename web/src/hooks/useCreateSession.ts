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

import { SessionBackendResponse } from "@/types";
import { useCloudAgent } from "./useCloudAgent";
import { fetchAPI } from '@/lib/fetch';
import { SessionDataAtom } from "@/app/atom";
import { useSetAtom } from "jotai";
import { changeAgentChatThreadId } from '@/lib/cloudAgent';

const useCreateSessionAPI = () => {
  const cloudAgent = useCloudAgent();
  const setSessionData = useSetAtom(SessionDataAtom);

  const createSession = async (
    productId?: string,
    podId?: string,
  ) => {
    if (!cloudAgent) {
      return null;
    }

    const _productId = productId || cloudAgent.productId;
    const _podId = podId || cloudAgent.podId;

    if (!_productId || !_podId) {
      return null;
    }

    const data = (await fetchAPI('/api/session/create', {
      method: 'POST',
      body: JSON.stringify({ thread_id: cloudAgent.threadId, product_id: _productId, pod_id: _podId }),
    })) as SessionBackendResponse;

    if (data) {
      // 将会话数据存储到全局状态
      cloudAgent.setThreadId(data.thread_id);
      cloudAgent.setProductPodId(data.pod.product_id, data.pod.pod_id);
      setSessionData(data);
      changeAgentChatThreadId(data.chat_thread_id);

      return data;
    }

    return null;
  };

  return { createSession };
};

export default useCreateSessionAPI;