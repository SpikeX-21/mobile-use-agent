# Kimi K2.6 + KooPhone 容器 Demo 交付与验收

## 交付范围

本交付用于内部 POC，验证同一条生产 Agent 主链路可以在 ARM64 容器中使用 Kimi
K2.6 非思考 JSON Mode、双 Token 认证和 KooPhone MCP 完成视觉闹钟任务。它不包含
Web、Go MCP、ADB Oracle、Android UI Tree 或 AgentArts Runtime 包装层。

验收命令固定运行四个连续阶段：

1. 通过视觉 Agent 准备“存在但关闭的 09:00 闹钟”；
2. 启用该闹钟，要求发生设备副作用并由后续截图确认；
3. 再次运行，要求识别已启用状态且不产生设备副作用；
4. 再运行一次，要求仍不创建重复闹钟或切换开关。

每轮都使用 `MobileUseAgent(model_provider_name="kimi",
device_provider_name="koophone_mcp")`。完成判定来自该轮最新真实截图；不调用独立
Oracle、ADB、Shell、UI Tree 或 Agent 未获准的 MCP 工具。任一运行失败、超时、回执
不确定、缺少最新截图、Provider 契约不符或只完成部分阶段，整个验收均以非零状态退出。

## 配置

在受 Git 忽略的 `mobile_agent/.env` 中配置以下变量，值不得写入文档、Git、Dockerfile
或镜像标签：

```dotenv
ENV=poc
MODEL_PROVIDER=kimi
KIMI_API_KEY=<运行时注入>
KIMI_MODEL=kimi-k2.6
KIMI_BASE_URL=<运行时注入>
KIMI_THINKING_MODE=disabled

DEVICE_PROVIDER=koophone_mcp
KOOPHONE_MCP_URL=<运行时注入>
KOOPHONE_INSTANCE_ID=<运行时注入>
KOOPHONE_IAM_AUTH_URL=<运行时注入>
KOOPHONE_IAM_DOMAIN=<运行时注入>
KOOPHONE_IAM_USERNAME=<运行时注入>
KOOPHONE_IAM_PASSWORD=<运行时注入>
KOOPHONE_IAM_PROJECT=<运行时注入>
KOOPHONE_JKS_STORE_PASSWORD=<运行时注入>
KOOPHONE_JKS_KEY_PASSWORD=<运行时注入>
KOOPHONE_TLS_VERIFY=false
```

仅内部自签证书 POC 允许 `ENV=poc` 与 `KOOPHONE_TLS_VERIFY=false`。生产必须启用 TLS
校验，并使用可信系统 CA 或只读挂载的 `KOOPHONE_CA_BUNDLE`。

当前镜像按已批准的临时方案包含 `mobile_agent/jwt.jks`，因此属于 secret-bearing
产物：不得推送公共或共享仓库，不得导出给无关人员，联调结束后必须删除。`.env`、
截图、日志、JSONL、缓存和虚拟环境不进入构建上下文。

## 构建与运行

```bash
cd mobile_agent
test -s jwt.jks
docker build \
  --file Dockerfile.koophone-poc \
  --tag mobile-use-koophone-poc:issue18 \
  .

mkdir -p logs/koophone-acceptance
chmod 700 logs/koophone-acceptance
docker run --rm \
  --env-file .env \
  --env MODEL_PROVIDER=kimi \
  --env DEVICE_PROVIDER=koophone_mcp \
  --env KOOPHONE_JKS_PATH=/opt/mobile-agent/secrets/koophone.jks \
  --env EXPERIMENT_RECORD_PATH=/output/experiment-runs.jsonl \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --mount type=bind,src="$(pwd)/logs/koophone-acceptance",dst=/output \
  mobile-use-koophone-poc:issue18 \
  acceptance \
  --output-dir /output \
  --attest-no-manual-intervention
```

输出目录必须为空。运行过程中不得人工点击、输入或补充模型信息。成功时标准输出包含
`"passed": true`、四轮运行和 `"privacy_scan": "passed"`；失败时返回非零，不把
部分完成报告成成功。

## 2026-08-19 实机结果

在 Docker Desktop ARM64、Python 3.11.13、`mobile-agent 0.1.0` 环境中，重建镜像后
完成了一次无人干预的真实运行：

| 阶段 | 动作 | 图片数/模型轮 | 模型耗时 | 设备耗时 | 终态 |
| --- | --- | --- | ---: | ---: | --- |
| 准备禁用状态 | `tap → finish` | `1,2` | 8108 ms | 126 ms | `completed` |
| 启用现有闹钟 | `tap → finish` | `1,2` | 8391 ms | 126 ms | `completed` |
| 识别已启用 | `finish` | `1` | 4131 ms | 0 ms | `completed` |
| 幂等重复运行 | `finish` | `1` | 4482 ms | 0 ms | `completed` |

后两轮没有设备副作用，满足“不创建重复闹钟”的验收条件。每轮的 `finish` 都基于最新
真实截图，未使用 ADB Oracle 或 UI Tree。原始报告保存在受 Git 忽略且权限为 `0600`
的本地 `logs/` 目录，不随源码交付；报告只记录 Provider、模型、环境版本、动作、步骤、
耗时、实际图片数和终止原因，不保存截图、任务原文、Token、密码、端点或实例标识。

同一最终镜像与本次输出还通过了独立交付扫描：源码/暂存差异未包含真实凭据、JKS 或
截图；Builder 中待打包的 Python 源码目录只含 `.py`；Docker 构建上下文采用闭合
allowlist；最终镜像元数据和完整历史、容器运行日志及三份验收文件均未命中当前运行的
IAM 密码、API Key、Token 配置、JKS 密码、实例标识或通用私钥/截图模式。扫描只输出
通过状态或泄漏字段名，不输出敏感值本身。

## 常见失败与处理

- `KooPhone JKS key material is not available`：确认 `jwt.jks` 在构建前存在且容器内为
  `/opt/mobile-agent/secrets/koophone.jks`、权限 `0400`。
- 配置错误或 Token 刷新失败：核对 `.env` 的变量名、IAM 账号范围和系统时间；不要把值
  粘贴进工单或日志。
- TLS 失败：生产修复证书链；仅内部 POC 可显式关闭校验。
- MCP 初始化、截图或动作失败：保留脱敏报告中的失败分类和终止原因，不重复发送不确定
  的副作用动作。
- 输出目录非空：创建新的空目录，避免旧记录与本次运行混合。
- 隐私扫描失败：隔离并删除该次输出，检查是否出现截图、凭据或本地配置值，不得发布。

## 安全清理与后续扩展

验收完成后删除本地 secret-bearing 镜像和不再需要的本地验收记录：

```bash
docker image rm mobile-use-koophone-poc:issue18
```

后续扩展点仅记录、不在本 Issue 实现：

- 增加 AgentArts SDK 的 `POST /invocations` 与 `GET /ping` 薄包装层；
- 构建并上传 Linux ARM64 镜像至受控 SWR；
- 评估通过 AgentArts MCP Gateway 连接 KooPhone MCP；
- 生产环境强制 TLS 校验，并用运行时 Secret/只读挂载或外部密钥服务替代镜像内 JKS。
