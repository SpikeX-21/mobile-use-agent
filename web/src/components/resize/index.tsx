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

import { cn } from "@/lib/utils";
import { PanelResizeHandle } from "react-resizable-panels";

// 自定义拖拽手柄组件
function ResizeHandle({ className = "" }: { className?: string }) {
  return (
    <PanelResizeHandle className={cn(
      "PanelResizeHandle w-2 mx-1 group relative cursor-col-resize",
      className
    )}>
      <div className="absolute top-0 bottom-0 left-0 right-0 flex items-center justify-center">
        <div className="w-1 h-10 bg-gray-300 rounded transition-colors group-hover:bg-blue-400 group-active:bg-blue-500" />
      </div>
    </PanelResizeHandle>
  );
}

export default ResizeHandle;