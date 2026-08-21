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

能力查询不调用 Kimi 或 KooPhone MCP，也不要求 Session Header。

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
