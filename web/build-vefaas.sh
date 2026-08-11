#!/bin/bash
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at 
#     https://www.volcengine.com/docs/82379/1433703
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -ex
cd `dirname $0`
# check dependencies
npm install
# output: 'standalone'
npm run build

# https://nextjs.org/docs/pages/api-reference/config/next-config-js/output#automatically-copying-traced-files
cp -r public .next/standalone/ && cp -r .next/static .next/standalone/.next/

zip -FSr web.zip . -x "node_modules/*"