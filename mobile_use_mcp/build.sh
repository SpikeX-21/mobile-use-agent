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

set -e

mkdir -p output

## MCP Server
echo "Building MCP Server..."
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o output/mobile_use_mcp ./cmd/mobile_use_mcp/...

## Cap AOP
# echo "Building Cap AOP..."
# CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -v -o output/cap_tos ./cmd/cap_aop/...
