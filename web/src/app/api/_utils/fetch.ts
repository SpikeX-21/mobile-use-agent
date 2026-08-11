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

import { handleVEFaaSError } from "@/app/api/_utils/vefaas";
import { NextResponse } from "next/server";
import { APIError } from "../../../lib/exception/apiError";
import { MiddlewareResult } from "./middleware";
// 函数重载定义


export async function fetchServer(
  target: string,
  middlewareResult: MiddlewareResult,
  body: Record<string, any>,
  method: string,
  options: { withUserInfo: boolean } = { withUserInfo: false }
): Promise<NextResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Account-Id': middlewareResult.accountId,
    'x-faas-instance-name': middlewareResult.faasInstanceName || '',
    'Authorization': `Bearer ${middlewareResult.authToken}`
  }

  const response = await fetch(target, {
    method,
    body: JSON.stringify(body),
    headers,
  });

  if (!response.ok) {
    const errorText = await response.text();
    let errorData;
    try {
      errorData = JSON.parse(errorText);
    } catch (e) {
      // JSON解析失败，直接使用文本
      errorData = { message: errorText };
    }

    await handleVEFaaSError(errorData, response.status);
    throw new Error(`请求失败: errorData.message: ${errorData.message}  errorData.status: ${response.status}`);
  }

  if (response.headers.get('Content-Type') === 'text/event-stream') {
    return new NextResponse(response.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'x-request-target': target,
        'x-agent-faas-instance-name': response.headers.get('x-faas-instance-name') || '',
      },
    });
  }

  const json = await response.json();
  if (json?.error && json?.error?.code !== 0) {
    throw new APIError(json.error.code, json.error.message);
  }

  if (options.withUserInfo) {
    return NextResponse.json({
      userInfo: {
        accountId: middlewareResult.accountId,
        userId: middlewareResult.userId,
        name: middlewareResult.name,
      },
      ...json
    }, {
      status: 200, headers: {
        'Content-Type': 'application/json',
        'x-agent-faas-instance-name': response.headers.get('x-faas-instance-name') || '',
      }
    });
  }

  return NextResponse.json(
    options.withUserInfo ? {
      userInfo: {
        accountId: middlewareResult.accountId,
        userId: middlewareResult.userId,
        name: middlewareResult.name,
      },
      ...json
    } : json, {
    status: 200, headers: {
      'Content-Type': 'application/json',
      'x-agent-faas-instance-name': response.headers.get('x-faas-instance-name') || '',
    }
  });
}