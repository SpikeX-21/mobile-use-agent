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
import Image from 'next/image';
import { useRouter, useSearchParams } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { useCloudAgent, useCloudAgentInit } from '@/hooks/useCloudAgent';
import backgroundImage from '@/assets/background.png';
import mobileUseIcon from '@/assets/mobile-use-icon.png';
import useCreateSessionAPI from '@/hooks/useCreateSession';
import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { buildUrlWithToken } from '@/lib/utils';
import { MOBILE_USE_POD_ID_KEY, MOBILE_USE_PRODUCT_ID_KEY } from '@/lib/cloudAgent';

// 表单验证 schema
const formSchema = z.object({
  podId: z.string()
    .min(1, { message: 'Pod ID 不能为空' })
    .max(50, { message: 'Pod ID 长度不能超过50' })
    .regex(/^\d+$/, { message: 'Pod ID 必须是数字' }),
  productId: z.string()
    .min(1, { message: 'Product ID 不能为空' })
    .max(50, { message: 'Product ID 长度不能超过50' })
    .regex(/^\d+$/, { message: 'Product ID 必须是数字' })
});

type FormValues = z.infer<typeof formSchema>;

function WelcomePageFallback() {
  return (
    <div
      className="h-screen w-screen flex flex-col items-center justify-center"
      style={{
        backgroundColor: 'rgba(255, 255, 255, 0.2)',
        backgroundImage: `linear-gradient(rgba(255, 255, 255, 0.6), rgba(255, 255, 255, 0.6)), url(${backgroundImage.src})`,
        backgroundSize: '20px 20px',
      }}
    >
      <div className="flex flex-col items-center">
        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
        <p className="text-gray-600">正在加载...</p>
      </div>
    </div>
  );
}

function WelcomePageContent() {
  useCloudAgentInit();
  const router = useRouter();
  const searchParams = useSearchParams();
  const cloudAgent = useCloudAgent();
  const [isNavigating, setIsNavigating] = useState(false);
  const { createSession } = useCreateSessionAPI();

  // 初始化表单
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      podId: '',
      productId: ''
    }
  });

  useEffect(() => {
    form.reset({
      productId: localStorage.getItem(MOBILE_USE_PRODUCT_ID_KEY) || '',
      podId: localStorage.getItem(MOBILE_USE_POD_ID_KEY) || ''
    });
  }, []);

  useEffect(() => {
    // 如果已经有 threadId，直接进入聊天页面
    const checkThreadId = async () => {
      if (cloudAgent?.threadId && !isNavigating) {
        setIsNavigating(true);
        try {
          // 获取会话数据并存储到全局状态
          const data = await createSession();
          if (!data) {
            return;
          }
          // 跳转时保留 token 参数
          router.replace(buildUrlWithToken('/chat', searchParams));
        } catch (error) {
          console.error('获取会话数据失败', error);
        } finally {
          setIsNavigating(false);
        }
      }
    };
    checkThreadId();
  }, [cloudAgent, router, searchParams]);

  const onSubmit = async (values: FormValues) => {
    if (!cloudAgent || isNavigating) {
      return;
    }

    setIsNavigating(true);

    try {
      const data = await createSession(values.productId, values.podId);
      if (!data) {
        return;
      }
      // 重定向到聊天页面时保留 token 参数
      router.replace(buildUrlWithToken('/chat', searchParams));
    } catch (error) {
      console.error('创建会话失败', error);
    } finally {
      setIsNavigating(false);
    }
  };

  return (
    <div
      className="h-screen w-screen flex flex-col items-center justify-center"
      style={{
        backgroundColor: 'rgba(255, 255, 255, 0.2)',
        backgroundImage: `linear-gradient(rgba(255, 255, 255, 0.6), rgba(255, 255, 255, 0.6)), url(${backgroundImage.src})`,
        backgroundSize: '20px 20px',
      }}
    >
      <div className="max-w-[400px] w-full text-center mb-10 px-4">
        <Image
          src={mobileUseIcon}
          alt="Mobile Use Icon"
          width={64}
          height={64}
          className="mx-auto mb-6 bg-blue-100 rounded-xl flex items-center justify-center"
        />
        <h1 className="leading-[32px] text-[24px] font-bold mb-6">Hi, 我是 Mobile Use Agent</h1>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="productId"
              render={({ field }) => (
                <FormItem>
                  <FormControl>
                    <Input
                      placeholder="云手机 业务ID"
                      {...field}
                      disabled={isNavigating}
                    />
                  </FormControl>
                  {/* <FormDescription>
                    请输入数字，长度不超过50
                  </FormDescription> */}
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="podId"
              render={({ field }) => (
                <FormItem>
                  <FormControl>
                    <Input
                      placeholder="云手机 PodID"
                      {...field}
                      disabled={isNavigating}
                    />
                  </FormControl>
                  {/* <FormDescription>
                    请输入数字，长度不超过50
                  </FormDescription> */}
                  <FormMessage />
                </FormItem>
              )}
            />



            {isNavigating ? (
              <Button
                type="button"
                disabled
                className="w-full py-3 bg-gradient-to-r from-blue-500 to-purple-500 text-white rounded-lg font-medium shadow-lg opacity-70 cursor-not-allowed"
              >
                <div className="flex gap-1 items-center justify-center ">
                  <div className="flex items-center justify-center ">
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></div>
                  </div>
                  Mobile Use 启动中
                </div>
              </Button>
            ) : (
              <Button
                type="submit"
                className="w-full py-3 bg-gradient-to-r from-blue-500 to-purple-500 text-white rounded-lg font-medium shadow-lg transition-all hover:from-blue-600 hover:to-purple-600 hover:shadow-xl"
              >
                创建会话
              </Button>
            )}
          </form>
        </Form>
      </div>
    </div>
  );
}

// 主组件，用 Suspense 包装
function WelcomePage() {
  return (
    <Suspense fallback={<WelcomePageFallback />}>
      <WelcomePageContent />
    </Suspense>
  );
}

export default WelcomePage;
