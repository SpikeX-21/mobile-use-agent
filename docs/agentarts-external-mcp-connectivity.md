# AgentArts Runtime 连接外部自研 MCP 可行性判断

> 日期：2026-08-13
> 结论对象：用 `agentarts-sdk` 为 `mobile-use-agent` 增加 `POST /invocations`，由容器内 Agent 作为 MCP Client 调用外部自研 MCP Server。这里讨论的是**出站 MCP 调用**，不是把 Agent Runtime 本身发布成 MCP 入站服务。

## 结论

**可以。** 华为云官方同时提供了两种可支持该架构的能力：

1. AgentArts Runtime 可配置公网或 VPC 私网出站，因此容器内的标准 MCP Client 可以直接访问网络可达的外部 MCP Server；
2. AgentArts MCP Gateway 可把自研或公开 MCP Server 配置成 MCP Target，支持 SSE 和 Streamable HTTP。官方明确说明，可把 Gateway URL 集成到 Agent 代码或已有 MCP Client 中。

对本项目，生产方案更推荐：

```text
调用方 -> AgentArts HTTP Runtime /invocations
       -> mobile-use-agent
       -> AgentArts MCP Gateway URL
       -> 外部自研 MCP Server
       -> 设备/业务系统
```

直接连接外部 MCP 适合先做连通性 POC；经 Gateway 更便于集中管理 Target 认证、网络、连通性测试和网关日志。

## 官方能力证据

- AgentArts 网关的 MCP Target 会把请求转发到标准 MCP Server，官方描述覆盖“自研或公开 MCP 服务”。[网关介绍](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_022.html)
- MCP Target 可配置 MCP 地址，传输支持 SSE 或 Streamable HTTP；出站认证支持 API Key、OAuth、IAM 或无认证，具体可用方式随 Target 类型由控制台展示。[创建 Target](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_025.html)
- 官方给出了把 Gateway URL 加入已有 MCP Client，并调用 `tools/list`、`tools/call`、`ping` 的示例；请求使用 JSON-RPC，可响应 JSON 或 SSE。[在智能体中使用网关](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_026.html)
- 官方高德示例证明 Gateway 可通过公网连接第三方 Streamable HTTP MCP，并用查询参数 API Key 完成 Target 出站认证。[集成高德 MCP 示例](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_023.html)
- Runtime 部署可选择公网或 VPC 私网出站；私网模式需要 VPC、子网和安全组。[通过控制台部署智能体运行时](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_031.html)
- Gateway 自身也可配置 `public` 或 `vpc` 出站网络，VPC 模式配置 VPC、子网与安全组。[Gateway SDK](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_045.html)

## 两种连接方式比较

| 方式 | 调用链 | 优点 | 风险/代价 | 建议 |
| --- | --- | --- | --- | --- |
| Runtime 直接连接 | Agent -> 自研 MCP | 改动和跳数较少；可直接复用当前 MCP Client | Target 凭据进入 Runtime；连通性、认证、日志和多个 MCP 地址由应用维护 | 用于第一轮 POC |
| 经 MCP Gateway | Agent -> Gateway -> 自研 MCP | Target 认证、网络与日志集中管理；控制台可测试/同步工具；应用只连接 Gateway | 多一层服务和认证；需验证会话、时延、错误映射 | 推荐生产方案 |

Gateway 不是强制条件。AgentArts SDK 的 Runtime wrapper 与 MCP Client 是两层独立能力：SDK 负责 `/invocations`、`/ping` 和请求上下文；MCP 调用仍由项目中的 Client 或 Gateway SDK/URL 完成。

## 当前仓库兼容性

当前代码已经具备 Streamable HTTP MCP Client 基础：

- `MOBILE_USE_MCP_URL` 提供服务地址：[`settings.py`](../mobile_agent/mobile_agent/config/settings.py)
- `Mobile.initialize()` 创建 `transport="streamable_http"` 连接：[`client.py`](../mobile_agent/mobile_agent/agent/mobile/client.py)
- `MCPHub` 使用 `MultiServerMCPClient` 建立 session、列工具和调用工具：[`mcp.py`](../mobile_agent/mobile_agent/agent/tools/mcp.py)
- `McpDeviceBackend` 已有动作执行、只读重试和副作用超时不自动重放语义：[`backend.py`](../mobile_agent/mobile_agent/agent/mobile/backend.py)

锁定依赖为 `langchain-mcp-adapters 0.1.0`、`mcp 1.10.1`。本地检查显示该组合支持 Streamable HTTP、自定义 headers，以及 MCP 协议 `2025-03-26`、`2025-06-18`。协议版本是在 `initialize` 时协商的；AgentArts 的版本策略配置位于 Gateway，而不是单个 Target。Gateway 只应允许调用方、Gateway 与 Target 共同支持的版本，并记录实际协商结果；POC 至少验证 `2025-03-26` 和 `2025-06-18`，不能只依赖“latest”。[MCP 协议版本介绍](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_074.html)

但是，**只加一层 AgentArts SDK wrapper 仍不够**：

1. `Mobile.initialize()` 固定注入 `Authorization` 和 `X-ACEP-DeviceId/ProductId/Tos*`，这是原火山 MCP 协议，不是通用 MCP 配置。
2. 当前 `/mobile-use/api/v1/agent/stream` 必须先经过 session/create，并由 `PodManager` 生成火山 ACEP token。
3. `McpDeviceBackend.verify_completion()` 当前返回 `None`，外部 MCP 路径没有 ADB 路径的独立完成判定。
4. `MCPHub.is_valid_mcp_response()` 只接受第一项 `text` content；自研 MCP 若返回 image、resource 或 structuredContent，会被判失败或丢失信息。

因此需要“小范围解耦”，而非重写 Agent：

- 新建厂商无关的 `McpConnectionConfig`：URL、transport、headers、timeout、protocol version；
- 把 ACEP device/product/TOS headers 移到火山专用适配器，自研 MCP/Gateway 使用自己的认证头；
- `/invocations` 从 AgentArts `RequestContext.session_id` 获取会话 ID，并调用独立的设备租约服务，不能依赖旧 session/create；
- Gateway 入口若采用 API Key，可把 `Authorization: Bearer ...` 配进 MCP Client headers；生产优先评估 AgentArts 工作负载身份/IAM，避免长期 API Key；
- 为自研 MCP 定义稳定的工具名称、入参、截图返回格式、错误码、幂等性与完成证据契约。

## 目标配置接口

以下变量描述完成 `McpConnectionConfig` 解耦后希望提供的配置契约，**当前代码尚未实现 `MCP_AUTH_TYPE` 和 `MCP_AUTH_TOKEN`，不能直接复制到现有部署中使用**。

### 方案 A：先直接连接验证

```text
DEVICE_PROVIDER=mcp
MOBILE_USE_MCP_URL=https://<custom-mcp-domain>/mcp
MCP_AUTH_TYPE=bearer
MCP_AUTH_TOKEN=<runtime-secret>
```

Runtime 选择能到达该域名的公网或 VPC 出站。自研 MCP 必须使用受信任 TLS 证书、支持 Streamable HTTP 初始化与 `tools/list`/`tools/call`。不要通过关闭 TLS 校验来解决证书问题。

### 方案 B：经 AgentArts Gateway

1. 创建 MCP Gateway，入站认证选 IAM、API Key 或 JWT；
2. 创建 MCP Target，选择与自研服务一致的 SSE/Streamable HTTP 和 MCP URL；
3. Gateway 出站选择公网或 VPC，并配置 Target 的 API Key/OAuth/IAM/无认证；
4. 在控制台先执行连接测试、工具同步和真实 `tools/call`；
5. 把 `MOBILE_USE_MCP_URL` 指向 Gateway URL，并给 Client 注入 Gateway 入站凭据；
6. Runtime `/invocations` 的 session ID 与 MCP session ID 建立明确映射，在同一 Agent 调用链中保持一致。

## 必须做的 POC

在判断“可上线”前，至少验证：

1. Runtime 或 Gateway 能解析并连接自研 MCP 域名；公网/VPC、安全组和对端白名单有效；
2. MCP `initialize`、`tools/list`、截图、点击、输入和读取状态全链路成功；
3. 协议版本、`Accept: application/json, text/event-stream` 和 MCP session ID 正确；
4. AgentArts Runtime 被回收或横向扩容后，不依赖进程内 MCP session；能够重连并重新 initialize；
5. 两个并发 invocation 不会控制同一设备；设备租约和互斥在外部持久化；
6. Target 超时后副作用工具不会自动重放；当前代码的 ambiguous 语义在 Gateway 错误包装后仍能正确分类；
7. Gateway/Runtime 日志不记录 API Key、设备凭据、截图敏感数据或完整授权头；
8. 自研 MCP 提供足够的只读状态或完成证据，否则只能接受“模型 finish 即完成”的弱语义。

## 文档未确认的边界

所核对的华为云页面没有明确给出 Runtime/Gateway 固定出口 IP、MCP 最大请求时长、SSE 空闲超时、单连接/单 Target 并发、请求/响应体大小、私有 CA/双向 TLS 支持，以及任意外部网络端口限制。若自研 MCP 有 IP 白名单、长任务、mTLS 或大截图响应，应通过目标区域 POC和华为云工单确认，不能仅根据“支持公网/私网出站”推断。

## 最终判断

该发布设想在 AgentArts 能力上成立。推荐把 `agentarts-sdk` 限定为标准 Runtime 入站适配层，把设备工具调用经 AgentArts MCP Gateway 转发至自研 MCP；当前仓库已有可复用的 Streamable HTTP Client 和 MCP Backend，但必须先解除 ACEP 专用 headers/session 绑定，并补齐设备租约、返回格式兼容和完成判定。完成上述改造及 POC 后，才可把结论从“平台可行”升级为“项目可上线”。
