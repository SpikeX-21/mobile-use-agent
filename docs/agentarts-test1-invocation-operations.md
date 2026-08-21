# AgentArts KooPhone POC Test1 调用手册

## 范围

本分支发布独立 Runtime `mobile-use-koophone-poc-test1`，公网路径为：

```text
POST https://<访问域名>/runtimes/mobile-use-koophone-poc-test1/invocations?endpoint=dev
```

请求统一使用 `inputs.operation`。除能力查询外，调用方继续传递合法的
`X-Hw-Agentarts-Session-Id`；`create_response` 和对应的 `fetch_response`
必须使用相同 Session ID。

这是固定云机的内部 POC：调用方保证任一时刻只创建一个设备任务。异步状态只保存在
当前 Runtime 进程内，不承诺跨 sandbox、进程重启或版本切换后仍可查询；查询不到时返回
`404 response_not_found`。该限制是本轮明确接受的范围，不应被描述为生产级异步队列。

## 能力查询

```json
{"inputs":{"operation":"query_capabilities"}}
```

```json
{
  "capabilities": {
    "chat_completions": true,
    "responses_api": true,
    "responses_get_fetch": true
  }
}
```

能力查询不调用 Kimi 或 KooPhone MCP。Runtime 处理函数本身不消费 Session Header，
但 AgentArts 公网 Gateway 仍要求 `X-Hw-Agentarts-Session-Id`；公网调用必须携带。

## 同步任务

```json
{
  "inputs": {
    "operation": "chat_completions",
    "query": "根据个人会议号在腾讯会议开启一个快速会议"
  }
}
```

该调用保持原有同步行为：请求阻塞到 Agent 完成或失败；成功时返回既有
`status/result/task_id/thread_id/session_id/rounds/elapsed_ms/terminal_reason`
结构，失败时沿用原有 4xx/5xx 状态映射。

## 创建异步任务

```json
{
  "inputs": {
    "operation": "create_response",
    "query": "根据个人会议号在腾讯会议开启一个快速会议"
  }
}
```

立即返回：

```json
{
  "response_id": "resp_4eb836d7-f1c5-4f5f-be80-84897b7ae61c",
  "status": "in_progress"
}
```

后台任务由 AgentArts SDK `async_task` 跟踪；任务执行期间 `/ping` 返回
`HealthyBusy`。固定云机租约仍在真正执行 Agent 时获取。

## 查询异步结果

```json
{
  "inputs": {
    "operation": "fetch_response",
    "response_id": "resp_4eb836d7-f1c5-4f5f-be80-84897b7ae61c"
  }
}
```

处理中：

```json
{"status":"in_progress"}
```

完成：

```json
{
  "status": "completed",
  "result": "任务已完成",
  "task_id": "koophone-task-4c1e6d33-a35d-4aec-9569-74588bcf8942",
  "thread_id": "koophone-thread-9ec074bb-2047-4830-9b5b-0a82215f160d",
  "session_id": "session-example",
  "rounds": 1,
  "elapsed_ms": 9971,
  "terminal_reason": "completed"
}
```

失败任务也通过 fetch 返回 HTTP 200，`status` 固定为 `failed`，并返回已有的安全
`error`、任务标识、轮次、耗时和 `terminal_reason`。不存在或不属于当前 Session 的
`response_id` 返回 HTTP 404。

状态值统一为 `in_progress`、`completed`、`failed`，不使用
`in_progeress` 或中文状态值。旧的 `{"input":"..."}` 请求体已经停用并返回
HTTP 400。

## 发布隔离

新 Runtime 使用以下独立资源：

- Runtime：`mobile-use-koophone-poc-test1`
- SWR repository：`agent_mobile-use-koophone-poc-test1`
- 本地状态目录：`mobile_agent/.agentarts/mobile-use-koophone-poc-test1/`
- 本地镜像：`mobile-use-agent-agentarts:invocation-operations`

旧 Runtime `mobile-use-koophone-poc`、其 `dev → v8` 映射和原入站 Key 不会被本次部署覆盖。

## 真实发布与验收证据

2026-08-21 已从提交 `542fb74` 构建并发布：

| 项目 | 结果 |
| --- | --- |
| Runtime | `mobile-use-koophone-poc-test1` / `ef570f2e-a525-44a8-a4c3-27e7eed69839` |
| version | `v1` |
| Endpoint | `dev` / `6dccea53-5c42-4267-9854-051b72c3bb52`，固定到 `v1` |
| Gateway | `defaultgw-grstqnldg5.cn-southwest-2.huaweicloud-agentarts.com` |
| SWR repository | `agentarts-cnso2-80c86dae-org/agent_mobile-use-koophone-poc-test1`，私有 |
| image tag | `issue25-542fb74-20260821t154214z` |
| image digest | `sha256:9551c41662ed5460ddef5a184582c6174971396603856e7a95aa96a39f6d315e` |
| image contract | `linux/arm64`、SDK `0.1.5`、非 OCI media type、只读非 root 容器测试通过 |
| 入站认证 | 独立 API Key，仅存于忽略目录；没有复用旧 Runtime Key |
| Runtime 配置 | HTTP 8080、PUBLIC 出站、文件传输关闭、session storage 关闭 |
| 可观测性 | 当前新 Runtime 的 logs/metrics/tracing 均关闭 |

公网串行验收：

- `query_capabilities`：HTTP 200，三个能力均为 `true`，没有调用模型或设备。
- `chat_completions`：真实 Kimi K2.6 + KooPhone MCP 只读应用列表，HTTP 200
  `completed`，2 轮，Agent 耗时 26,507 ms，Session Header 一致。
- `create_response`：立即返回 `resp_<UUID>` 与 `in_progress`。
- 对同一 Session 执行 `fetch_response`：处理中持续返回 HTTP 200
  `in_progress`；第 14 次查询返回 HTTP 200 `completed`，2 轮，Agent 耗时
  28,246 ms。
- 异步失败验收：只观察截图并使用 Agent 本地 `fail`，没有设备副作用；第 6 次查询
  返回 HTTP 200 `failed`，1 轮，Agent 耗时 9,377 ms，
  `terminal_reason=model_failed`，且包含完整 task/thread/session 标识。

本地全套 295 项测试通过；另行启用的 7 项真实 Docker 镜像测试全部通过。
