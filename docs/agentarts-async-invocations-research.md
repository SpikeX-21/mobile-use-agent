# AgentArts 高代码 Runtime 异步 Invocation 状态与路由研究

更新时间：2026-08-21

## 结论

AgentArts 智能体运行时会依据业务流量自动扩缩容，并明确运行在分布式弹性伸缩集群中；
安全 sandbox 可能被水平扩容、空闲回收或因健康检查失败而删除。因此，同一个 named
Endpoint 不是“固定访问某一个容器/进程”的承诺，连续请求可能由不同 sandbox 处理。
[运行时介绍](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_029.html)
明确说明自动弹性伸缩，并明确禁止依赖普通本地文件系统，因为 sandbox 可能随时销毁或
水平扩容，本地磁盘数据会丢失。

所以，拟新增的 `create_response -> fetch_response` 可以实现，但不能只把任务状态、
`response_id` 索引和结果保存在 Python 进程内字典、普通本地文件或 SQLite 中。可选设计为：

1. 内部单请求 POC：启用 AgentArts **会话存储**，要求创建和查询请求始终携带同一个
   `X-Hw-Agentarts-Session-Id`、同一个 named Endpoint/版本；使用 Runtime SDK 的后台任务
   追踪，并把状态与结果原子写入会话存储。
2. 需要跨 session、跨 sandbox、重启恢复或多请求排队时：使用所有 sandbox 可访问的共享
   状态库和任务队列。状态库可选 DCS Redis/数据库；队列可选 DMS RabbitMQ/Kafka 等。
   SFS Turbo 也能共享持久化结果文件，但它本身不是消息队列，不能单独提供可靠消费、重试、
   可见性超时或任务所有权。

第二种方案是更可靠的生产方向。第一种方案符合当前“固定云机、一次只执行一个请求”的
内部 POC 范围，但必须把这个限制写入 `query_capabilities` 或接入说明，且不能宣称具备
多实例异步调度能力。

## 证据分级

本文按以下三类表述，避免把推断写成平台保证：

- **文档事实**：华为云/AgentArts 官方页面明确写明。
- **本项目实测推断**：来自已完成的真实 8 路并发探测，只证明当前账号、区域、Runtime
  和当时平台行为。
- **文档未承诺**：官方页面没有给出可依赖的路由、超时或一致性保证。

## 1. named Endpoint、自动扩缩容与 sandbox 路由

### 1.1 文档事实

- AgentArts Runtime 支持基于业务流量、QPS 和并发数的自动扩缩容，并以安全 sandbox
  提供隔离执行环境。[高代码开发概述](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_001.html)
  和[智能体运行时介绍](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_029.html)
  都明确描述了自动弹性伸缩和高并发承载。
- named Endpoint（官方页面称“访问方式”）用于选择运行时版本，或按灰度比例把流量分配到
  主要/次要版本。它没有声明会绑定到一个固定 sandbox。
  [创建智能体运行时访问方式](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_048.html)
- 外部调用必须携带 `X-Hw-Agentarts-Session-Id`。该字段是每个会话的唯一标识，最大 64 字符；
  `endpoint` 查询参数选择访问方式/版本。
  [ExecuteRuntime API](https://support.huaweicloud.com/api-agentarts/InvokeRuntime1.html)
- 未配置会话存储时，新请求按指定 Endpoint 路由；同一 Session ID 甚至可以在不同版本中
  单独使用。配置会话存储后，如果已存在同 Session ID 的活动 sandbox，且 Endpoint 版本
  相同，新请求会调用同一个 sandbox；如果版本不一致，请求会超时。
  [控制台部署文档的 Session 路由约束](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_031.html)

这意味着 AgentArts 有一种**有条件的 session affinity**：只有启用会话存储、同 Session ID、
同 Endpoint 版本、且对应 sandbox 仍处于活动状态时，文档才明确承诺复用同一 sandbox。
官方没有承诺“只要 Session Header 相同，无论是否配置会话存储都固定路由到同一实例”。

### 1.2 本项目实测推断

既有验收曾预热后并发发送 8 条不同合法 Session 的只读任务；8 条均进入不同的可执行
sandbox 并返回 `200 completed`，且没有触发进程内设备锁的 `409`。详细记录见
[Issue #25 发布记录](./agentarts-issue25-deployment.md)。

该证据支持以下项目级推断：

- 当前 `cn-southwest-2` 的这个 Runtime/Endpoint 确实可能同时使用多个 sandbox；
- Python 进程锁或单进程字典只能约束一个 sandbox，不能保护固定 KooPhone 实例；
- `fetch_response` 不能假定会回到创建任务的进程。

它不证明所有账号、所有区域、所有时段必定按“一请求一 sandbox”运行，也不证明配置会话
存储后的同 Session 路由行为。后两者仍应以官方路由约束和专项验收为准。

## 2. sandbox 生命周期、回收和重启语义

### 2.1 文档事实

HTTP 入栈协议要求容器暴露 `/ping`，并定义以下状态：

- `Healthy`：服务健康且没有后台异步任务；连续空闲超过空闲超时时间（文档示例为 15 分钟）
  应发起删除 sandbox；
- `HealthyBusy`：服务健康且存在后台异步任务，用于支持运行时间超过空闲超时的长任务；
- 不健康：多次健康检查失败会发起删除 sandbox。

来源：[HTTP 入栈协议的 `/ping` 生命周期](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_070.html)。

Runtime SDK 提供 `@app.async_task`，官方说明被装饰的异步后台任务会被自动追踪，并给出
`asyncio.create_task(background_job(payload))` 后立即返回 `accepted` 的示例；SDK 同时提供
`app.has_running_tasks()` 和 `HEALTHY_BUSY` 状态。
[Runtime SDK](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_041.html)

### 2.2 对异步接口的含义

- `create_response` 启动任务后，Runtime 应在任务结束前正确呈现 `HealthyBusy`，否则空闲回收
  可能把仍在执行任务的 sandbox 当作 Idle。
- `HealthyBusy` 只降低“正常空闲回收”中断任务的风险，并不等于任务队列、持久执行或容灾。
  进程崩溃、sandbox 不健康、版本切换和平台故障仍可能终止后台协程。
- 任务状态应在状态变化时持续写入持久化存储；不能只在协程完成后一次性落盘。
- 对中断后仍为 `in_progress` 的记录，应设计租约/心跳、超时转失败和可选重试。AgentArts
  文档没有为自定义后台任务提供内置“自动恢复执行”保证。

## 3. 本地内存和本地磁盘能否保存异步状态

### 3.1 文档事实

官方明确要求高代码 Runtime 无状态，并说明它部署在分布式弹性伸缩集群中：sandbox 空闲
触发伸缩时本地磁盘数据全部丢失；禁止依赖 SQLite、本地日志文件或本地缓存等普通本地
文件系统。sandbox 可能随时被销毁或水平扩容。
[运行时的无状态与本地磁盘约束](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_029.html)

### 3.2 设计判断

| 状态位置 | `create_response -> fetch_response` 是否安全 | 原因 |
| --- | --- | --- |
| Python 进程内 `dict` | 否 | fetch 可能落到另一个 sandbox；进程退出即丢失 |
| 普通本地 JSON/SQLite | 否 | 官方明确本地磁盘会随回收或扩容丢失 |
| AgentArts 会话存储 | POC 可用 | 同 Session 独立持久目录；需同 Header、同 Endpoint 版本 |
| SFS Turbo | 可用作共享结果/状态文件 | 多 sandbox/版本可共享，但需自行实现并发控制和任务队列 |
| 外部 Redis/数据库 + 消息队列 | 推荐 | 路由与 sandbox 生命周期无关，可实现原子状态、TTL、租约、排队和恢复 |

## 4. AgentArts 官方持久化与外部队列能力

### 4.1 平台直接提供的持久化

1. **会话存储**

   控制台文档称它为“会话级别的存储持久化”，用于保存会话上下文、中间结果和用户偏好；
   每个会话在持久化存储中拥有独立子目录，并把该目录挂载到指定路径。会话存储只允许配置
   一个。[控制台存储配置](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_031.html)
   CreateCoreRuntime API 也公开 `storage_config.session_storage.mount_path`，并明确一旦配置后
   不可关闭。[CreateCoreRuntime 存储结构](https://support.huaweicloud.com/api-agentarts/CreateCoreRuntime.html)

2. **SFS Turbo**

   Runtime 最多可挂载 5 个 SFS Turbo 存储卷。它是可由多云主机、容器同时挂载的持久化
   共享文件存储，只能在 Runtime 私网访问模式下配置；同一 Runtime 多个版本挂载同一目录时
   会自动共享。[控制台存储配置](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_031.html)

3. **Memory 记忆库**

   AgentArts Memory 支持短期记忆和长期持久化记忆，但它面向语义记忆、用户偏好、会话摘要
   等对话场景。官方还说明长期记忆抽取有延迟，建议短期记忆写入 3–5 分钟后再查询长期记忆。
   因此它不适合作为要求立即、精确读取 `in_progress/completed/failed` 的任务状态数据库。
   [记忆库概述](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_015.html)

### 4.2 队列能力的边界

AgentArts 高代码 Runtime 文档和 CreateCoreRuntime 存储结构没有公开内置的通用任务队列，
`@app.async_task` 是当前 sandbox 内后台任务跟踪机制，不是跨 sandbox 的持久队列。

如果需要可靠排队和恢复，可由应用连接外部华为云服务：

- DCS Redis 支持 Key-Value、Hash、List、Stream，以及事件发布/订阅和高速队列等场景，适合
  保存 response 状态、TTL、幂等键或实现轻量任务队列。
  [DCS 产品介绍](https://support.huaweicloud.com/intl/zh-cn/productdesc-dcs/dcs-pd-200713001.html)
- DMS RabbitMQ 提供普通消息、死信、延迟消息、灵活路由和高可用仲裁队列，更适合需要可靠
  消费、失败重试和任务解耦的执行队列。
  [DMS RabbitMQ 产品介绍](https://support.huaweicloud.com/productdesc-rabbitmq/rabbitmq-pd-190828001.html)

Runtime 支持 `PUBLIC` 或 `VPC` 出网，因此能否连接上述服务取决于相应网络、安全组、凭据和
委托配置；这不是部署 Runtime 后自动附带的队列。
[CreateCoreRuntime 网络配置](https://support.huaweicloud.com/api-agentarts/CreateCoreRuntime.html)

## 5. 同步 `/invocations` 的超时与并发

### 5.1 文档事实

- 容器内 HTTP 路由为 `POST /invocations`；公网 Gateway 路由为
  `POST /runtimes/{runtime_name}/invocations`。HTTP 协议支持完整 JSON 响应，也支持 SSE
  增量响应；官方把 JSON 描述为适合快速处理，把 SSE 描述为适合长期计算和实时更新。
  [HTTP 入栈协议](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_070.html)
- 官方 CLI 的 `agentarts invoke --timeout` 默认值是 900 秒。这是 SDK/CLI 请求超时参数，
  不能自动解释为 Gateway 对所有调用承诺的服务端最大处理时长。
  [AgentArts CLI](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_039.html)
- Runtime 会依据 QPS/并发量自动扩缩容，但官方没有公开单个 named Endpoint 的固定 sandbox
  数量、单 sandbox 并发度或稳定的最大并发值。
  [高代码开发概述](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_001.html)

### 5.2 文档未承诺

当前 ExecuteRuntime API 页面只列出 `200/401/404/500`，没有给出公网 Gateway 的固定超时
秒数、`504` 触发条件、`429` 并发阈值、请求排队方式或断开后是否取消容器任务。
[ExecuteRuntime API](https://support.huaweicloud.com/api-agentarts/InvokeRuntime1.html)

因此：

- 不能把 CLI 默认 900 秒写成公网 Gateway SLA；
- 同步 `chat_completions` 应继续保留应用级 deadline、明确超时响应和幂等设计；
- 预计会超过调用链实际超时的任务应使用异步 `create_response/fetch_response`，或按官方 HTTP
  协议使用 SSE；
- 8 路并发成功只属于本项目实测，不是平台配额承诺。

## 6. 对四个 operation 的具体建议

### 6.1 `query_capabilities`

该操作应完全无状态、无外部设备动作，直接返回：

```json
{
  "capabilities": {
    "chat_completions": true,
    "responses_api": true,
    "responses_get_fetch": true
  }
}
```

只有在异步状态使用持久化存储、并完成真实 create/fetch 验收后，才应把后两项置为 `true`。

### 6.2 `chat_completions`

保持当前同步执行和响应体不变，只把输入改为 `inputs.operation/query`。它仍会占用一个同步
Gateway 请求直到完成，受客户端 deadline 和未公开的 Gateway 实际超时边界约束。

### 6.3 `create_response`

建议流程：

1. 校验 `query` 非空；生成不可预测的 UUID `response_id`；
2. 在持久化状态库原子写入 `in_progress`，并绑定调用者身份、Session ID、Endpoint 版本；
3. 将任务提交给持久队列，或在 POC 中以 `@app.async_task` 启动并立即返回；
4. 后台任务按阶段更新心跳/状态，最终写入 `completed` 或 `failed` 及结构化结果；
5. 固定 KooPhone 实例最多只允许一个活动设备任务；额外请求应排队或明确拒绝，不能让
   Runtime 的自动扩容把同一云机并发控制起来。

### 6.4 `fetch_response`

建议要求调用方复用创建任务时的 `X-Hw-Agentarts-Session-Id`。即使状态放在全局共享库，也应
把 `response_id` 与 Session/User 绑定并校验，防止仅凭 response ID 越权读取其他任务。

不要依赖请求体中的 `response_id` 完成平台路由：官方 Gateway 的路由身份仍是 Header 和
Endpoint。若使用会话存储，create/fetch 必须携带相同 Session Header 和相同 Endpoint 版本；
如果 named Endpoint 在任务期间切换版本，官方说明已激活旧 Session sandbox 与新版本不一致
时会调用超时。POC 应在任务生命周期内固定 Endpoint 版本。

状态值建议统一为：

- `in_progress`
- `completed`
- `failed`

不要输出示例中的 `in_progeress`。进行中时 `result` 应为空或省略；失败时增加稳定的
`error/code/message`，完成时返回现有同步结果字段。`response_id` 应始终出现在 fetch 响应中，
便于调用方关联。

## 7. 推荐的 POC 落地边界

当前固定 KooPhone EID、调用方保证同一时刻只有一个任务时，可以先采用：

- AgentArts 会话存储；
- `@app.async_task` + `HealthyBusy`；
- `response_id` 对应的原子 JSON 状态文件；
- create/fetch 使用同一 Session Header、同一固定 named Endpoint/版本；
- 进程启动时扫描遗留 `in_progress`，无有效心跳则转为 `failed/interrupted`；
- 禁止并发 `create_response`，或在已有活动任务时返回明确的 busy 状态。

上线多调用方或允许并发前，应迁移为共享状态库 + 持久队列 + 固定云机分布式租约。原因不是
异步协议本身不可行，而是 Runtime 自动扩缩容后，任意 fetch sandbox 都必须看见一致状态，
且多个执行 sandbox 不能同时控制同一台固定云机。

## 8. 尚需真实验收、官方未替代回答的项目

1. 启用会话存储后，同 Session + 同 `dev` Endpoint 的 create/fetch 是否稳定复用活动 sandbox；
2. 后台任务运行超过 15 分钟时，LTS 是否持续显示 `HealthyBusy` 且 sandbox 不被空闲回收；
3. sandbox 被人为终止后，会话存储中的状态文件是否由新 sandbox 正确重新挂载；
4. named Endpoint 切换版本时，活动 Session 是否按文档返回超时；
5. 当前区域真实 Gateway 的同步超时、断连传播和并发限流行为；
6. 固定云机 busy/排队/幂等策略，以及进程崩溃后的任务租约回收。

这些验收只能确认当前环境行为，不能把未公开的平台配额或 SLA 反推为官方长期保证。
