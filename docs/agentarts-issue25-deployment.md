# AgentArts KooPhone Runtime 发布记录与运行手册（Issue #25）

## 当前结论

2026-08-21 已完成私有 SWR、AgentArts Runtime、固定 `dev` Endpoint、API Key
入站认证、LTS 实例日志和真实只读调用。账号充值后，原计费阻塞已解除；日志出口修复版
真实返回 `200 completed`，LTS 查询命中同一调用的结构化审计事件，受控低超时版本也已
产生真实 `504 task_timeout`。当前 `dev` 固定到显式恢复 900 秒任务超时的 `v8`，不再引用
临时低超时配置。随后 KooPhone 截图上游再次出现间歇性 `502 device_observation_failed`，
这是设备上游健康问题，不是 Gateway 认证、LTS 或超时恢复失败。8 路历史真实并发探测全部
进入不同的可执行 sandbox 并返回
`200 completed`，证明现有 `InProcessDeviceLease` 不提供跨 sandbox 互斥。内部 POC 已明确
接受这一限制，并约束调用方同一时间最多发送一个请求；这不是并发安全保证。若未来允许
多调用方或并发流量，必须先引入共享外部租约。

## 脱敏发布证据

| 项目 | 已验证结果 |
| --- | --- |
| Region | `cn-southwest-2` |
| Runtime | `mobile-use-koophone-poc` / `b783ad38-0fbe-4c5c-b23e-50498266e659` |
| Runtime version | 最新 `v8`（日志开启、正常超时） |
| named Endpoint | `dev` / `bd6db606-8d72-497a-aea9-9e20802b9a9f`，当前固定到 `v8` |
| 入站网关 | 默认网关 `4e85c7b8-7874-4e63-b51b-d5948a7155b1` |
| 访问域名 | `defaultgw-grstqnldg5.cn-southwest-2.huaweicloud-agentarts.com` |
| SWR | `agentarts-cnso2-80c86dae-org/agent_mobile-use-koophone-poc`，私有 |
| image tag | `issue25-249296d-20260821t091117z`，未使用 `latest` |
| tag digest | `sha256:950a93841c57c4151d9962b3fbe5aa61cbea11b5c73b97ca0556a58cc54d465c` |
| version → artifact | `v5` 至 `v8` 均引用上述同一私有 tag；SWR 实时查询为上述 digest |
| 镜像平台/格式 | Linux ARM64；SWR Basic 兼容的 Docker media type |
| 容器协议 | HTTP / `8080` / `ACCURATE_MATCH` |
| 入站认证 | AgentArts `API_KEY`；真实值只保存在本地忽略目录 |
| 出站网络 | `PUBLIC` |
| 存储/文件接口 | 无 session storage；file transfer 关闭 |
| 可观测性 | `v8` LTS logs 已开启；metrics、tracing 关闭；真实查询已命中 `runtime_invocation` |
| LTS project/group/stream | `58195b7cbcf44a25ab37cbcab40947ca` / `d06ea872-174e-4273-aa0d-133e93e8122a` / `4a884d25-2d3c-48f2-a6c9-1314f092d8cd` |
| LTS 费用归属 | 当前华为云账号的按需计费；充值后控制面切换已恢复 |
| probe | 平台默认 probe；未放宽超时，未对外暴露 `/ping` |
| 执行委托 | `DefaultAgentArtsRuntimeAgency` |
| 委托信任主体 | `service.WorkloadSandboxMetadata` |
| 委托策略 | `AgentArtsCoreRunRuntimeIdentityAgencyPolicy`、`AgentArtsCoreRunRuntimeOpsAgencyPolicy`；未发现 KMS/CSMS/SFS 策略 |
| 发布者有效权限 | 已真实创建私有 SWR 仓库、Runtime、版本和 Endpoint，并成功把运行委托传给 Runtime；这证明本次发布身份在执行时具备所需 AgentArts/SWR 写权限及 PassRole 等效权限 |

镜像由本地 #24 构建链重建并加入运行时审计 stdout 修复；AgentArts `v8` 的来源 URL 使用上述唯一 tag，
而不是未被目标区域证明支持的 `@sha256:` URL。SWR 查询明确返回 `is_public=false`，
Runtime 成功拉取并启动进一步证明执行委托具备私有拉取能力。

`v2` 仅调整控制面环境：入站 Bearer Key 不再重复注入工作负载环境，Gateway 仍使用原
`identity_config` 鉴权。旧 `v1` 不再由 `dev` 指向；POC 销毁时应连同旧版本和 Key 一并
清理/轮换。

## 真实验收结果

Gateway 认证边界：

- 缺失 `Authorization`：`401`。
- 错误 Bearer Key：`401`。
- 缺失 `X-Hw-Agentarts-Session-Id`：`400`。
- 非法 Session Header：`400 invalid_request`。
- 正确 API Key 与合法 Session：`200`，响应 Session Header 与请求一致。

首次发布 `v1` 后，真实无副作用任务为“只读取当前云手机已安装应用列表，不执行启动、
点击、输入、滑动或修改”。它通过同一 Runtime 调用 Kimi K2.6、Huawei IAM 和
KooPhone MCP，结果为：

- `status=completed`
- `terminal_reason=completed`
- 2 轮
- Agent 内部耗时 25,724 ms；网关端到端约 26.0 秒

这同时证明 `PUBLIC` 出站可访问 Kimi、Huawei IAM 和 KooPhone MCP。没有使用 fake
Kimi、fake MCP、ADB 或自定义 debug path。

切换到 `v2` 后，用同一只读任务串行调用两次，均在第 1 轮约 32–34 秒返回真实 Gateway
`502`，稳定 body 为 `status=failed`、`terminal_reason=device_observation_failed`。随后从
本地使用同一 IAM/JWT/MCP 配置直接调用 `get_screenshot`，同样连续失败为
`DeviceErrorKind.COMMAND_FAILED`。因此当时的异常定位到 KooPhone MCP 截图上游；Gateway
鉴权已通过，且没有执行点击、输入、滑动或应用启停。控制面虽然报告 Runtime `READY`，
但在下述恢复调用完成前不能单独作为端到端健康证据。

上游恢复后再次通过 `dev → v2` 串行执行同一无副作用任务，结果为：

- `HTTP 200`、`status=completed`、`terminal_reason=completed`；
- 2 轮；Agent 24,172 ms，Gateway 端到端 25,184 ms；
- 响应 Session Header 与请求一致；
- 只读取应用列表，没有执行设备副作用。

随后发送“只观察、禁止设备动作、使用本地 fail 结束”的验收探针，真实 Gateway 返回：

- `HTTP 422`、`error=task_failed`、`terminal_reason=model_failed`；
- 1 轮；Agent 8,459 ms，Gateway 端到端 8,803 ms；
- 没有向 KooPhone 下发点击、输入、滑动、应用启停或按键动作。

并发已知限制：预热后同时发送 8 条不同合法 Session 的同一只读任务，8 条均返回
`200 completed`，端到端耗时约 18.2–39.9 秒；没有 `409`。该结果不能证明单 owner，
反而实证多 sandbox 可同时持有各自的进程内锁。POC 的运行约束是由调用方串行化，任何
压测、重试器、多个操作者或并发会话都会超出当前支持范围。

账号充值后，日志出口修复版 `v5` 使用同一真实只读任务返回：

- `HTTP 200`、`status=completed`、`terminal_reason=completed`；
- 2 轮；Agent 21,566 ms，Gateway 端到端 22,218 ms；
- LTS `ListLogs` 查询命中同一 Session 的 1 条 `runtime_invocation`，字段与响应一致。

随后创建临时 `AGENT_TASK_TIMEOUT_SECONDS=0.1` 版本。由于 named Endpoint 的沙箱路由存在
短暂传播延迟，首次请求仍落到旧正常沙箱并完成，紧随其后的请求落到低超时沙箱，真实返回
`HTTP 504`、`error=task_timeout`、`terminal_reason=timeout`、0 轮；LTS 查询到两条对应的
超时审计事件，耗时分别约 416 ms 和 432 ms。发现 AgentArts 版本更新会继承被省略的可选
环境变量后，发布器已改为始终显式提交正常默认值 900 秒，并创建 `v8`、把 `dev` 固定到
`v8`。后续请求不再走超时分支，而是因 KooPhone 截图上游波动返回真实
`502 device_observation_failed`。

400、422、502 和 504 已由真实 Gateway 验证。409 在跨 sandbox 场景不会稳定产生，内部
POC 已接受且不把它列作单请求验收门槛。

## 本地秘密位置

以下文件全部被 Git 忽略且权限为 owner-only；不得粘贴到 Issue、日志或文档：

- Huawei 发布 AK/SK：`mobile_agent/credentials.csv`
- Kimi/KooPhone Runtime 变量：`mobile_agent/.env`
- 入站 Bearer Key：`mobile_agent/.agentarts/inbound-api-key`
- 脱敏控制状态：`mobile_agent/.agentarts/deployment-state.json`
- 未完成发布意图：`mobile_agent/.agentarts/deployment-pending.json`（仅中断时存在）
- 当前内部 POC JKS：`mobile_agent/jwt.jks`（已烘焙进私有镜像）

入站 Bearer Key 只提交给 AgentArts Gateway 的 `identity_config`，不注入工作负载环境。

`app:app` 是 `agentarts config` 向导中的 SDK 源码入口字段。本次使用 #24 已构建镜像并
直接调用控制面 API，云端 CreateCoreRuntime 不接收该字段；容器实际入口仍是经过测试的
`python -m mobile_agent.agentarts_runtime`。不要把仓库原有 Web API 的 `app.py` 当成
AgentArts Runtime 入口。

## 发布与版本切换

在 `mobile_agent/` 目录执行：

```bash
.venv/bin/python -m mobile_agent.agentarts_deploy_cli deploy
```

命令会：

1. 检查 CSV、`.env`、本地 Linux ARM64 镜像和默认运行委托；
2. 按 AgentArts SDK 默认规则选择 SWR 组织和 `agent_<Agent名>` 仓库；
3. 精确校验运行委托唯一信任主体和两条最小策略，额外主体或策略均失败；
4. 拒绝公开仓库、`latest`、已有 tag 和非 Docker media type；
5. 通过自动销毁的独立 `DOCKER_CONFIG` 登录和推送，Git/Docker 子进程不会继承华为 AK/SK；
6. 生成唯一 tag，推送后查询 digest；
7. 首次创建 Runtime，后续只允许更新本地状态所拥有的同一 Runtime；
8. 入站 Key 指纹必须与本地 owner-only 状态一致；Key 丢失或被替换时发布会在上传前失败，不会伪装成已轮换；
9. 将 `dev` 更新到本次明确版本，不调用 `Latest`；
10. 只把脱敏标识写入 owner-only 状态文件，并在退出时恢复调用者原有 SDK 环境变量。

当本地状态记录 `logs=true` 时，后续发布会要求 project/group/stream 三个 LTS 标识完整，
并把同一日志配置保留到新版本；不会因为 CLI 更新而静默关闭日志。

若未来再次在控制台只开启日志并生成一个尚未固定到 `dev` 的 successor，不要直接运行
普通 `deploy` 来代替该版本的严格核对。使用：

```bash
.venv/bin/python -m mobile_agent.agentarts_deploy_cli promote-logs-version
```

该命令只接受一个已经 `READY` 的 latest successor，并逐项验证 Runtime ID、原 SWR
repository/tag、环境变量键集合、执行委托、PUBLIC 网络、HTTP 8080、严格路由、无 SFS、
metrics/tracing 关闭以及完整 LTS project/group/stream；任何差异都会失败关闭。验证通过后
才把 `dev` 固定到目标版本，并原子更新本地 last-known-good 状态。它不会创建额外版本，
也不会自动认领其他镜像或 Runtime。

查看脱敏状态：

```bash
.venv/bin/python -m mobile_agent.agentarts_deploy_cli show
```

发布器先把新制品的脱敏意图写到独立的 `deployment-pending.json`，只有 Runtime `READY`、
`dev` 已固定到新版本且所有安全标识完整后，才原子替换 `deployment-state.json`。因此失败
不会把 `show` 的最后一个可用映射伪装成新版本。若控制面已经创建资源但客户端超时，
下一次发布会以 `unfinished deployment requires manual reconciliation` 失败关闭，禁止自动
认领同名 Runtime。

### 中断发布的人工恢复

1. 保留 pending 文件，先读取其中的脱敏 tag、digest 和 `expected_runtime_id`；不得手工写入
   Runtime ID 或删除当前 `deployment-state.json` 来绕过所有权检查。
2. 在 AgentArts 控制台查询同名 Runtime，并在 SWR 查询 pending tag。若没有生成 Runtime/
   version，确认无云端变更后删除该唯一 tag（如存在）和 pending 文件，再重试。
3. 若 `expected_runtime_id` 为空但出现同名 Runtime，逐项核对 agent 名称、私有 SWR
   repository、pending tag/digest、执行委托、PUBLIC 网络、HTTP 8080 和 API_KEY 认证。
   只有全部匹配且能确认是本次中断创建的孤儿资源，才先删除其 Endpoint、Runtime 和唯一
   tag，再删除 pending 文件；不自动 adopt。任何一项不确定时停止并联系账号管理员。
4. 若 `expected_runtime_id` 非空，先保持 `dev` 在 `deployment-state.json` 记录的上一版本；
   核对 Runtime 最新版本是否使用 pending tag/digest。未完成版本保留待定位或在控制台
   明确删除后，再删除 pending 文件并重新发布。

上述删除会改变云端资源，必须由操作者逐项复核资源 ID 后执行；发布脚本不会自动删除。

内部 POC 外部同步 JSON 调用模板如下；调用方必须保证任一时刻最多一个在途请求：

```bash
curl --fail-with-body --request POST \
  'https://<gateway-domain>/runtimes/mobile-use-koophone-poc/invocations?endpoint=dev' \
  --header 'Authorization: Bearer <INBOUND_API_KEY>' \
  --header 'X-Hw-Agentarts-Session-Id: <UNIQUE_SESSION_ID>' \
  --header 'Content-Type: application/json' \
  --data '{"input":"<TASK>"}'
```

升级会创建唯一镜像 tag 和新 Runtime version，再把 `dev` 固定到新版本。回滚时在
AgentArts Runtime 的“访问方式”中把 `dev` 改回上一个明确版本；禁止把验证流量改到
`Latest`。每次切换使用新的 Session ID。

## 后续并发扩展：共享租约

当前单请求 POC 不实现共享租约。若后续取消调用方串行约束，需要一个所有 AgentArts
sandbox 都能访问、支持原子
`acquire-if-absent + TTL + owner-token compare-and-release/renew` 的共享存储。推荐提供
Redis-compatible 服务，并给出：

- TLS 连接地址与端口；
- 用户名（如需要）和密码/Token；
- 是否允许 `SET key value NX PX <ttl>` 与 Lua compare-and-delete/renew；
- PUBLIC 出站白名单要求；
- 用于 POC 的 key prefix；
- 凭据应写入哪个本地忽略文件或由 AgentArts 环境变量注入。

拿到这些信息后，应先实现 fail-closed 分布式租约，再发布新版本并重跑至少 8 路并发：
预期只能有一条进入设备操作，其余稳定返回 `409 device_busy`；之后再验证 422/502/504
透传与版本回滚。

单请求 POC 的发布、LTS 和 504 验收已完成。当前已知运行约束仍是调用方串行化，以及
KooPhone 截图上游的间歇性 `502`；设备上游恢复后可直接在 `dev → v8` 重跑只读探针，
无需再次创建 Runtime 版本。

## 销毁

POC 结束时按顺序执行：

1. 删除 `dev`（`Latest` 是平台默认方式，不能删除）。
2. 删除 Runtime `mobile-use-koophone-poc`。
3. 删除 SWR 中所有 `issue25-*` tag；仓库无其他制品时再删除仓库/组织。
4. 删除本地远端 tag、导出的 tar 和 Docker build cache 中的 secret-bearing 镜像。
5. 删除/轮换入站 API Key；按 KooPhone 流程吊销或轮换 JKS 对应密钥。
6. 删除本地 `.agentarts/` 状态与 Key 文件。

销毁是破坏性操作，不由发布脚本自动执行，必须显式复核资源 ID 后再操作。

## 官方依据

- [高代码开发 SDK 部署](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_028.html)
- [CreateCoreRuntime](https://support.huaweicloud.com/api-agentarts/CreateCoreRuntime.html)
- [CreateCoreRuntimeEndpoint](https://support.huaweicloud.com/api-agentarts/CreateCoreRuntimeEndpoint.html)
- [创建智能体运行时访问方式](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_048.html)
- [LTS 查询日志 ListLogs](https://support.huaweicloud.com/api-lts/ListLogs.html)
