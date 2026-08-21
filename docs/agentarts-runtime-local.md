# 本地 AgentArts Runtime（Issue #21）

当前分支提供一个只支持同步 JSON 的本地 AgentArts Runtime 适配层。协议路由由
官方 `agentarts-sdk==0.1.5` 提供，业务入口复用现有的
`run_koophone_task`，不会复制 MobileUseAgent 图或 KooPhone MCP 工具逻辑。

## 启动

在 `mobile_agent/` 目录安装依赖并启动：

```bash
python -m pip install -r requirements.txt \
  --index-url https://repo.huaweicloud.com/repository/pypi/simple
AGENT_RUN_PORT=8080 python -m mobile_agent.agentarts_runtime
```

服务绑定 `0.0.0.0`；`AGENT_RUN_PORT` 未设置时使用 `8080`。SDK 应用只提供
`POST /invocations` 和 `GET /ping` 这两个本地 HTTP 入口。带
`/runtimes/{runtime_name}/invocations` 的完整 Gateway 路径属于后续
AgentArts Gateway/OpenAPI 集成，不由本地应用重复实现。

## 调用

每个请求都必须携带 SDK 的会话头，并且 JSON body 必须只有一个非空的
`input` 字段：

```bash
curl -sS http://127.0.0.1:8080/invocations \
  -H 'Content-Type: application/json' \
  -H 'x-hw-agentarts-session-id: local-demo-1' \
  -d '{"input":"根据个人会议号在腾讯会议开启一个快速会议"}'
```

返回是同步 JSON。成功时 `status` 为 `completed`，同时包含安全的任务 ID、线程
ID、会话 ID、轮次、耗时和终止原因。`400` 表示请求格式错误，`422` 表示任务
执行失败，`502` 表示 KooPhone/MCP 设备上游失败，`500` 表示 Runtime 配置或
运行时失败，`409` 表示固定设备槽已被占用，`504` 表示整体任务 deadline；错误
响应只包含稳定错误码和安全结构化字段，不回显异常、截图或模型内部思考。

每个任务受 `AGENT_TASK_TIMEOUT_SECONDS` 约束，默认 `900` 秒。超时会取消当前
Agent，等待 KooPhone MCP/Agent 上下文关闭后返回 `504 {"error":"task_timeout"}`；
客户端主动断连时无法再返回 HTTP body，但同一清理路径仍会释放设备槽。

`GET /ping` 使用 SDK 的 `PingStatus` wire format。空闲且就绪时返回
`{"status":"Healthy", ...}`；通过进程内 readiness 状态标记为不可用时返回
`Unhealthy`，不会访问 Kimi、IAM、MCP 或云手机。

## 约束与后续扩展点

- Runtime 每次请求都会创建新的 task/thread；即使复用同一个会话头，也不会继承
  上一次的 prompt、消息、截图或 checkpoint。
- 当前为同步 JSON POC，不提供 SSE/流式响应，也不在本地实现 Gateway 外层 URL。
- 模型和设备 provider 在 `run_koophone_task` 内固定为 Kimi + KooPhone MCP。
- 同一进程内固定设备槽不排队：占用期间新请求立即返回 `409
  {"error":"device_busy"}`，不会创建 Agent 或访问任何上游；任务执行期间 `/ping`
  返回 `HealthyBusy`。
- 跨 sandbox 的固定设备租约、TTL/失主恢复以及 Gateway 入站 Header 规则由后续
  Issue 继续实现；本地总超时和取消清理已在当前 Runtime 边界生效。

进程内设备槽只覆盖一个 Runtime sandbox/进程，不是跨 sandbox 的单设备所有权证明。
多副本部署前必须增加共享外部租约、TTL 和失主恢复，不能用低 QPS 或人工串行替代。

## Docker POC 边界

`mobile_agent/Dockerfile.agentarts-koophone` 延续当前内部 POC 决策，会把被 Git
忽略的本地 `jwt.jks` 复制进镜像，并在运行时以只读权限使用。该镜像只能在受控
内部环境短期验证，禁止推送到公共仓库、共享给外部人员或用于生产；生产扩展点是
改为 AgentArts/容器平台提供的运行时 Secret 或密钥挂载，避免密钥进入镜像层。
