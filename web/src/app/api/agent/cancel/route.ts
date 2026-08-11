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

import * as url from "url"
import { ApiHandler, withMiddleware } from "../../_utils/middleware";
import { fetchServer } from "@/app/api/_utils/fetch";


const target = url.resolve(process.env.CLOUD_AGENT_BASE_URL || "", 'api/v1/agent/cancel')

const _post: ApiHandler = async (request: Request, middlewareResult) => {
  const { thread_id } = await request.json();
  const response = await fetchServer(target, middlewareResult, { thread_id }, 'POST');
  return response;
}

export const POST = withMiddleware(_post);
