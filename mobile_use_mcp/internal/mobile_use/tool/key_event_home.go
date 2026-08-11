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

package tool

import (
	"context"

	"mcp_server_mobile_use/internal/mobile_use/consts"

	"github.com/mark3labs/mcp-go/mcp"
)

func NewKeyEventHomeTool() mcp.Tool {
	return mcp.NewTool("home",
		mcp.WithDescription("Go to the home screen of the cloud phone"),
	)
}

func HandleKeyEventHomeTool() func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	return func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		err := CheckAuth(ctx)
		if err != nil {
			return CallResultError(err)
		}
		mobileUseConfig, err := GetMobileUseConfig(ctx)
		if err != nil || mobileUseConfig == nil {
			return CallResultError(err)
		}
		handler, err := InitMobileUseService(ctx, mobileUseConfig)
		if err != nil {
			return CallResultError(err)
		}
		err = handler.KeyEvent(ctx, consts.AndroidKeyEventHome)
		if err != nil {
			return CallResultError(err)
		}
		return CallResultSuccess("Go home successfully")
	}
}
