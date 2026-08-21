# 本地 AgentArts Runtime（Issue #23）

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

本地 POC 仍要求 KooPhone 配置完整，并在启动前通过本地校验：provider 必须是
`kimi`/`koophone_mcp`，JKS 必须是非空普通文件、权限 `0400` 且当前用户可读，
自定义 CA（如果配置）也必须是非空、可读且可解析的 PEM；配置或 TLS policy 不满足时进程以退出码 `2`
停止，不会先监听端口。仓库中的 `jwt.jks` 被 Git 忽略，若仅用于本地 POC，先
执行 `chmod 0400 mobile_agent/jwt.jks`，再设置 `KOOPHONE_JKS_PATH` 及其密码环境
变量。启动校验不发起网络请求。

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

请求体只允许自然语言目标：`{"input":"..."}`。实例/EID、模型、provider、
工具、endpoint、Token 或 JSON 中额外的 header 字段不属于本地 schema；带这些字段的请求会
在 SDK entrypoint 前返回 `400 invalid_request`。Session header 只用于安全关联，
不能选择实例、授权、恢复 checkpoint 或延续上一次任务。

`GET /ping` 使用 SDK 的 `PingStatus` wire format。空闲且就绪时返回
`{"status":"Healthy", ...}`；通过进程内 readiness 状态标记为不可用时返回
`Unhealthy`，不会访问 Kimi、IAM、MCP 或云手机。

每次 invocation 会先在任务边界内构造 Kimi provider，并初始化 KooPhone MCP 会话；
初始化会刷新/复用 IAM Token 与 JWT、完成 MCP initialize/tool 白名单探测，随后才
进入模型动作循环。Kimi 的实际请求也只发生在 invocation 内，绝不由 `/ping` 触发。

## 约束与后续扩展点

- Runtime 每次请求都会创建新的 task/thread；即使复用同一个会话头，也不会继承
  上一次的 prompt、消息、截图或 checkpoint。
- 当前为同步 JSON POC，不提供 SSE/流式响应，也不在本地实现 Gateway 外层 URL。
- 模型和设备 provider 在 `run_koophone_task` 内固定为 Kimi (`kimi-k2.6`、非思考
  JSON 模式) + KooPhone MCP；固定 EID 只来自服务端环境配置，不进入请求、响应、
  模型工具参数或普通日志。
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

## 入站认证、日志与秘密边界

- AgentArts Gateway 的入站 API Key（通常由网关以
  `Authorization: Bearer <API_KEY>` 校验）是调用方身份凭据。它由 Gateway/入口
  配置管理，不是 `KIMI_API_KEY`、Huawei IAM 密码/Token、KooPhone JWT 或 JKS
  密码；应用不会读取、转发或写入上游请求。
- Runtime 控制台里的环境变量按普通 literal key/value 处理，不把它们称为
  Secret Manager。应限制控制面查看权限，按审计要求更新、轮换和删除；真实值
  不得写入 `.env`、`.agentarts_config.yaml`、Issue、runbook、镜像说明或日志。
- stdout/LTS 只输出 allowlist 事件：安全 task/thread/session ID、固定 provider/
  model/device 标识、轮次、耗时、状态、终止原因和稳定错误码。prompt、截图、
  Base64/Data URL、坐标、动作参数、完整轨迹、异常文本、路径、Token、EID 和
  隐藏推理不会进入响应或普通日志；启用 LTS 前应对代表性秘密、控制字符和图片
  内容做扫描。
- `EXPERIMENT_RECORD_PATH` 产生的本地 JSONL 是 sandbox 内的易失辅助遥测，不是
  云上权威结果。遥测写入失败不会改变 HTTP 业务状态，也不能被调用方用来推断
  未返回的数据。

## POC TLS 风险

在内部联调中可以使用 `ENV=poc` + `KOOPHONE_TLS_VERIFY=false`，但该开关由
Huawei IAM 和 KooPhone MCP 共用：关闭它会同时降低 IAM Token 请求和 MCP 请求的
证书校验，可能暴露双 Token、截图和控制指令。生产必须启用 TLS 校验并提供可信
CA；后续生产改造应拆分 IAM/MCP 策略，并始终让 IAM 校验证书。内置 `jwt.jks` 的
镜像同样只限短期、受控、私有 POC，禁止公开分发或用于生产。
