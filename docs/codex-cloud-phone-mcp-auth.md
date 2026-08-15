# Codex 接入云手机 MCP：X-Auth-Token 与 JWT

## 问题一：使用 HTTP / Streamable HTTP MCP 时，如何在 Codex 中携带 `X-Auth-Token`？

可以在 Codex 的 MCP 配置中，用环境变量映射自定义 HTTP 请求头。

编辑用户级配置 `~/.codex/config.toml`：

```toml
[mcp_servers.volc_mobile]
url = "https://<你的-mcp-域名>/mcp"
env_http_headers = { "X-Auth-Token" = "VOLC_MCP_AUTH_TOKEN" }
startup_timeout_sec = 20
tool_timeout_sec = 60
```

再让 Codex Desktop 进程能够读取环境变量。例如在 macOS 中：

```bash
launchctl setenv VOLC_MCP_AUTH_TOKEN '<你的-token>'
```

`launchctl setenv` 不会更新已经运行的 Codex Desktop 进程。设置后应完全退出并重新打开 Codex Desktop，再进入 **Settings → MCP servers** 验证连接；CLI 可运行 `codex mcp list` 和 `codex mcp get volc_mobile` 检查配置，在支持命令面板的客户端中也可输入 `/mcp` 查看连接状态。

不建议把 token 直接写入配置。仅临时调试时可使用静态 header：

```toml
[mcp_servers.volc_mobile]
url = "https://<你的-mcp-域名>/mcp"
http_headers = { "X-Auth-Token" = "<你的-token>" }
```

`env_http_headers` 会在每个 MCP HTTP 请求中，将指定环境变量的值写入对应 header；`http_headers` 则使用配置中的静态值。Codex Desktop、CLI 和 IDE 扩展共享同一套 MCP 配置。

> 当前仓库的 `mobile_use_mcp` 原始实现读取的是 `Authorization` header，而不是 `X-Auth-Token`。如要使用 `X-Auth-Token`，MCP 服务或其前置网关需要显式读取并验证该 header。

## 问题二：每次工具调用还需要获取 JWT，应该怎么做？

不要让 Codex 在每次操作前先调用一个公开的“获取 JWT”工具，再由模型把 JWT 拼到下一次请求中。Codex 的 HTTP MCP 配置支持静态 header、环境变量 header、Bearer token 和 OAuth，但不能将一个工具调用的返回值自动写进下一次 MCP HTTP 请求的 header。

推荐由 MCP 服务端管理 JWT：

```text
Codex
  └─ X-Auth-Token（客户端凭据）
       └─ MCP 网关 / MCP 服务
            ├─ 验证 X-Auth-Token
            ├─ 获取、缓存或刷新 JWT
            └─ 携带 JWT 调用云手机 API
```

服务端处理每个操作调用时应：

1. 验证 `X-Auth-Token`；
2. 按租户、账户、产品和设备查询未过期的 JWT；
3. 不存在或临近过期时刷新 JWT；
4. 使用 JWT 调用云手机 API；
5. 不将 JWT 返回给 Codex，也不接受 JWT 作为常规工具参数。

建议在 JWT 距离过期 1–5 分钟时刷新，并对同一缓存 key 的并发刷新做互斥，避免多个工具调用同时换取 token。

如果云手机服务实现的是标准 MCP OAuth，则可以使用 `codex mcp login <server-name>` 让 Codex 处理 OAuth access token 的登录与刷新；这不适用于非标准的自定义“获取 JWT”接口。

## 问题三：云手机 MCP 暴露 `get_jwt` 工具；操作工具需要 JWT。Codex Agent 能使用吗？

取决于 JWT 的传递方式：

| 云手机 MCP 协议 | Codex Agent 是否可用 | 说明 |
| --- | --- | --- |
| `get_jwt()` 返回 JWT；`tap(jwt, x, y)` 等工具把 JWT 定义为入参 | 可以 | Agent 可以依次调用两个工具，并将前一个结果作为后一个工具参数。 |
| `get_jwt()` 返回 JWT；后续 `tools/call` 必须在 HTTP header 中带 JWT | 不支持自动串联 | Codex 无法把前一个工具返回值动态注入下一次 MCP HTTP 请求头。 |

即使第一种设计技术上可用，也不宜用于生产：JWT 会进入模型上下文、工具参数以及潜在的审计记录或日志，并且模型可能使用已过期 token 或遗漏刷新。

因此，应该将 `get_jwt` 设计为 MCP 服务内部能力，而不是公开给 Codex 的工具。对 Codex 暴露不带 JWT 参数的业务工具，例如：

```text
tap(x, y)
swipe(from_x, from_y, to_x, to_y)
take_screenshot()
list_apps()
```

## 当前项目的改造建议

本项目可以直接改造为服务端管理 JWT。

### `mobile_use_mcp`

- 在 `internal/mobile_use/server/server.go` 的 `authFromRequest` 中读取和校验 `X-Auth-Token`。
- 新增内部 `JwtProvider`，负责 JWT 的申请、缓存、刷新和过期判断。
- 使用 `context.Context` 向后续工具和服务层传递已认证的身份及 JWT，避免进入工具参数或 MCP 返回内容。
- 在 `InitMobileUseService()` 或云手机 API 适配器中使用该 JWT。
- 不向 MCP 注册公开的 `get_jwt` 工具。

### `mobile_agent`

- 在 `mobile_agent/agent/mobile/client.py` 的 `Mobile.initialize()` 中加入 `X-Auth-Token` header。
- 继续以 `tap(x, y)`、`take_screenshot()` 等无 JWT 参数形式调用 MCP 工具。

### 上游协议无法修改时

如果上游云手机 MCP 已固定为“公开 `get_jwt` 工具，且操作 API 要求 JWT header”，可增加一个薄的 MCP 代理：

```text
Codex --X-Auth-Token--> 本项目 MCP 代理 --JWT header--> 上游云手机 MCP
```

代理负责 `get_jwt → 缓存/刷新 → 向上游操作请求注入 JWT header → 转发结果`。这使 Codex 仍只持有稳定的 `X-Auth-Token`，而不接触短期 JWT。

## 参考

- [OpenAI 官方：Codex MCP 配置](https://developers.openai.com/codex/mcp/)
- [OpenAI 官方：Codex 配置字段参考](https://developers.openai.com/codex/config-reference/)
