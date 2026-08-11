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

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"

echo_info "开始构建所有组件..."
echo_info "脚本目录: $SCRIPT_DIR"
echo_info "构建输出目录: $BUILD_DIR"

# 清理并创建构建目录
echo_info "清理构建目录..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/web" "$BUILD_DIR/mobile-agent" "$BUILD_DIR/mobile-use-mcp"

# 1. 构建 mobile-agent
echo_info "====== 构建 mobile-agent ======"
cd "$SCRIPT_DIR/mobile_agent"
if [ -f "build-vefaas.sh" ]; then
    chmod +x build-vefaas.sh
    ./build-vefaas.sh
    
    # 查找生成的 zip 文件（兼容 macOS）
    if [ -f "mobile-agent.zip" ]; then
        MOBILE_AGENT_ZIP="mobile-agent.zip"
    else
        # 如果没有找到 mobile-agent.zip，查找带时间戳的版本
        MOBILE_AGENT_ZIP=$(find . -name "mobile-agent-zip-*.zip" -type f | head -1)
    fi
    
    if [ -n "$MOBILE_AGENT_ZIP" ] && [ -f "$MOBILE_AGENT_ZIP" ]; then
        echo_info "找到 mobile-agent 产物: $MOBILE_AGENT_ZIP"
        cp "$MOBILE_AGENT_ZIP" "$BUILD_DIR/mobile-agent/"
        
        # 解压到目录
        cd "$BUILD_DIR/mobile-agent"
        unzip -q "$(basename "$MOBILE_AGENT_ZIP")"
        rm -rf "$(basename "$MOBILE_AGENT_ZIP")"
        echo_success "mobile-agent 构建并解压完成"
    else
        echo_error "未找到 mobile-agent 构建产物"
        echo_info "当前目录文件列表："
        ls -la
        exit 1
    fi
else
    echo_error "未找到 mobile-agent 构建脚本"
    exit 1
fi

# 2. 构建 mobile-use-mcp
echo_info "====== 构建 mobile-use-mcp ======"
cd "$SCRIPT_DIR/mobile_use_mcp"
if [ -f "build.sh" ]; then
    chmod +x build.sh
    ./build.sh
    
    if [ -f "output/mobile_use_mcp" ]; then
        echo_info "找到 mobile-use-mcp 产物"
        cp -r output/* "$BUILD_DIR/mobile-use-mcp/"
        echo_success "mobile-use-mcp 构建完成"
    else
        echo_error "未找到 mobile-use-mcp 构建产物"
        exit 1
    fi
else
    echo_error "未找到 mobile-use-mcp 构建脚本"
    exit 1
fi

# 3. 构建 web
echo_info "====== 构建 web ======"
cd "$SCRIPT_DIR/web"
if [ -f "build-vefaas.sh" ]; then
    chmod +x build-vefaas.sh
    ./build-vefaas.sh
    
    if [ -f "web.zip" ]; then
        echo_info "找到 web 产物: web.zip"
        cp "web.zip" "$BUILD_DIR/web/"
        rm -rf "web.zip"

        # 解压到目录
        cd "$BUILD_DIR/web"
        unzip -q "web.zip"
        rm -rf "web.zip"
        echo_success "web 构建并解压完成"
    else
        echo_error "未找到 web 构建产物"
        exit 1
    fi
else
    echo_error "未找到 web 构建脚本"
    exit 1
fi

# 显示构建结果
echo_info "====== 构建完成 ======"
echo_success "所有组件构建完成，产物位于:"
echo "  - Web: $BUILD_DIR/web/"
echo "  - Mobile Agent: $BUILD_DIR/mobile-agent/"
echo "  - Mobile Use MCP: $BUILD_DIR/mobile-use-mcp/"

echo_info "构建目录结构:"
tree "$BUILD_DIR" 2>/dev/null || find "$BUILD_DIR" -type f | head -20

echo_success "构建脚本执行完成！"