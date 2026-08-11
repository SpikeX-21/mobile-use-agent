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

import { Button } from "../ui/button"
import ClearIcon from '@/assets/icon-clear.svg'
import ClearDisabledIcon from '@/assets/icon-clear-disabled.svg'
import Image from 'next/image'
import { useMemo, useState } from 'react'
import { useCloudAgent } from '@/hooks/useCloudAgent'
import { fetchAPI } from '@/lib/fetch'
import { MessageListAtom } from "@/app/atom"
import { useAtomValue } from "jotai"
import { cn } from "@/lib/utils"
import { SessionBackendResponse } from "@/types"
import { changeAgentChatThreadId } from "@/lib/cloudAgent"



const ResetChat = (props: { className?: string }) => {
  const [isResetting, setIsResetting] = useState(false)
  const cloudAgent = useCloudAgent()
  const messages = useAtomValue(MessageListAtom)
  const disabled = useMemo(() => {
    return isResetting || !cloudAgent?.threadId || messages.length === 0
  }, [isResetting, cloudAgent?.threadId, messages?.length])

  const handleReset = async () => {
    if (!cloudAgent?.threadId || isResetting) {
      return
    }

    setIsResetting(true)

    try {
      // 调用 reset API
      await cloudAgent.cancel().catch(
        (error) => console.error('取消会话失败:', error)
      )
      const data = await fetchAPI('/api/session/reset', {
        method: 'POST',
        body: JSON.stringify({ thread_id: cloudAgent.threadId }),
      }) as SessionBackendResponse

      if (data.thread_id) {
        // 更新 cloudAgent 的 threadId
        cloudAgent.setThreadId(data.thread_id)
        changeAgentChatThreadId(data.chat_thread_id)
        console.log('会话重置成功:', data.thread_id, data.chat_thread_id)
      }
    } catch (error) {
      console.error('重置会话失败:', error)
    } finally {
      setTimeout(() => {
        setIsResetting(false)
      }, 500)
    }
  }

  return (
    <Button
      variant="outline"
      className={cn(
        "m-[20px] border-[#C9CDD4] text-[#4E5969] hover:bg-gray-50 hover:cursor-pointer rounded-[4px] disabled:text-[#C7CCD6] disabled:bg-[#F6F8FA] disabled:cursor-not-allowed",
        props.className
      )}
      onClick={handleReset}
      disabled={disabled}
    >
      {isResetting ? (
        <>
          <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin mr-1"></div>
          重置中...
        </>
      ) : (
        <>
          <Image src={disabled ? ClearDisabledIcon : ClearIcon} alt="clear icon" width={16} height={16} />
          清除上下文
        </>
      )}
    </Button>
  )
}

export default ResetChat