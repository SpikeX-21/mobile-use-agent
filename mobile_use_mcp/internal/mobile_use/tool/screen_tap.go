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
	"fmt"

	"github.com/mark3labs/mcp-go/mcp"
)

func NewScreenTapTool() mcp.Tool {
	return mcp.NewTool("tap",
		mcp.WithDescription("Tap at specified coordinates on the cloud phone screen"),
		mcp.WithNumber("x",
			mcp.Description("The x coordinate of the tap point"),
			mcp.Required(),
		),
		mcp.WithNumber("y",
			mcp.Description("The y coordinate of the tap point"),
			mcp.Required(),
		),
	)
}

func HandleScreenTap() func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error) {
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
		args, err := CheckArgs(req.Params.Arguments)
		if err != nil {
			return CallResultError(err)
		}
		x, err := GetInt64Param(args, "x")
		if err != nil {
			return CallResultError(fmt.Errorf("x is required"))
		}
		y, err := GetInt64Param(args, "y")
		if err != nil {
			return CallResultError(fmt.Errorf("y is required"))
		}
		err = handler.ScreenTap(ctx, int(x), int(y))
		if err != nil {
			return CallResultError(err)
		}
		return CallResultSuccess("Tap the screen successfully")
	}
}
