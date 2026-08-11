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

package mobile_use_client

import (
	"context"

	"github.com/mark3labs/mcp-go/client"
	"github.com/mark3labs/mcp-go/client/transport"
	"github.com/mark3labs/mcp-go/mcp"
)

func NewMobileUseSSEClient(ctx context.Context, baseUrl string, headers map[string]string) (*client.Client, error) {
	var (
		cli *client.Client
		err error
	)
	if len(headers) > 0 {
		cli, err = client.NewSSEMCPClient(baseUrl, client.WithHeaders(headers))
	} else {
		cli, err = client.NewSSEMCPClient(baseUrl)
	}
	if err != nil {
		return nil, err
	}
	if err := cli.Start(ctx); err != nil {
		return nil, err
	}
	initReq := mcp.InitializeRequest{}
	initReq.Params.ProtocolVersion = mcp.LATEST_PROTOCOL_VERSION
	initReq.Params.ClientInfo = mcp.Implementation{
		Name:    "mobile_use_mcp_client",
		Version: "0.0.1",
	}

	_, err = cli.Initialize(ctx, initReq)
	if err != nil {
		return nil, err
	}
	return cli, nil
}

func NewMobileUseStdioClient(ctx context.Context, cmd string, env []string, args ...string) (*client.Client, error) {
	cli, err := client.NewStdioMCPClient(
		cmd,
		env,
		args...,
	)
	if err != nil {
		return nil, err
	}
	initReq := mcp.InitializeRequest{}
	initReq.Params.ProtocolVersion = mcp.LATEST_PROTOCOL_VERSION
	initReq.Params.ClientInfo = mcp.Implementation{
		Name:    "mobile_use_mcp_client",
		Version: "0.0.1",
	}

	_, err = cli.Initialize(ctx, initReq)
	if err != nil {
		return nil, err
	}
	return cli, nil
}

func NewMobileUseStreamableHTTPClient(ctx context.Context, addr string, headers map[string]string) (*client.Client, error) {
	cli, err := client.NewStreamableHttpClient(addr, transport.WithHTTPHeaders(headers))
	if err != nil {
		return nil, err
	}
	if err := cli.Start(ctx); err != nil {
		return nil, err
	}

	initReq := mcp.InitializeRequest{}
	initReq.Params.ProtocolVersion = mcp.LATEST_PROTOCOL_VERSION
	initReq.Params.ClientInfo = mcp.Implementation{
		Name:    "mobile_use_mcp_client",
		Version: "0.0.1",
	}

	_, err = cli.Initialize(ctx, initReq)
	if err != nil {
		return nil, err
	}
	return cli, nil
}
