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

export * from './safeJSONParse';
export * from './time';
export * from './delay';
export * from './css';

import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * 构建带 token 的 URL 的辅助函数
 * 用于在页面跳转时保留 URL 中的 token 参数
 * @param path 目标路径
 * @param searchParams 可选的 URLSearchParams 对象，如果不提供则从当前页面读取
 * @returns 带 token 的完整路径
 */
export function buildUrlWithToken(path: string, searchParams?: URLSearchParams): string {
  let urlParams: URLSearchParams;
  
  if (searchParams) {
    urlParams = searchParams;
  } else if (typeof window !== 'undefined') {
    urlParams = new URLSearchParams(window.location.search);
  } else {
    return path;
  }
  
  const token = urlParams.get('token');
  if (token) {
    const url = new URL(path, typeof window !== 'undefined' ? window.location.origin : 'http://localhost');
    url.searchParams.set('token', token);
    return url.pathname + url.search;
  }
  return path;
}

/**
 * 获取当前页面 URL 中的 token 参数
 * @returns token 字符串或 null
 */
export function getCurrentToken(): string | null {
  if (typeof window !== 'undefined') {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('token');
  }
  return null;
}
