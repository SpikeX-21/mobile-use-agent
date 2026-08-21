# AgentArts ARM64 Runtime 镜像（Issue #24）

这份说明对应 `mobile_agent/Dockerfile.agentarts-koophone`。它构建的是一个
只提供官方 AgentArts Runtime 路由的同步 JSON 内部 POC 镜像：入口为
`POST /invocations` 和 `GET /ping`，不会启动闹钟验收、固定任务或一次性 CLI。

## 认证边界

本地 `docker build`、`docker image inspect`、`docker run` 和 `/ping` 验收不需要
华为云账号，也不会调用华为云 API。华为官方的“制作Agent镜像”文档给出的本地
构建命令就是 `docker build`，随后才是将镜像上传到 SWR 的单独步骤：
[制作Agent镜像](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_079.html)。

只有以下云端操作需要华为云身份或控制台权限：

- 登录 SWR 并执行临时登录命令、`docker push`；需要目标区域、SWR 组织/仓库和
  对应的镜像仓库权限。
- 使用 `agentarts launch` 或 SDK/CLI 调用华为云控制面；按照官方快速开始配置
  `HUAWEICLOUD_SDK_AK` 和 `HUAWEICLOUD_SDK_SK`。这两个值不能写入 Dockerfile、
  镜像层、脚本或 Git。

华为高码开发要求使用 Linux ARM64 制作镜像，并说明 SWR 基础版不支持 OCI 镜像
格式；Docker 27+ 可设置 `BUILDKIT_USE_OCI_MEDIA_TYPES=0`（或关闭 BuildKit）。
本项目保留 BuildKit 是因为 Dockerfile 使用 `COPY --chmod`，构建脚本显式设置前者：
[快速开始](https://support.huaweicloud.com/highcode-agentarts/agentarts_10_040.html)。

## 构建与检查

在仓库的 `mobile_agent/` 目录执行。脚本会检查本地 `jwt.jks` 存在、构建平台为
`linux/arm64`，并在镜像中验证锁定的 `agentarts-sdk==0.1.5`。`jwt.jks` 是当前
内部 POC 的短期制品，文件被 Git 忽略；不要将由它构建的镜像发布到公共仓库。
Issue 描述中提到的 `0.1.4` 是早期审计基线；当前代码已经使用并锁定仓库中已验证
的 `0.1.5`，构建脚本和测试会拒绝未锁定或意外升级的版本。

```bash
cd mobile_agent
IMAGE_REPOSITORY=mobile-use-agent-agentarts \
IMAGE_TAG=issue24 \
./scripts/build-agentarts-runtime.sh

./scripts/check-agentarts-image.sh mobile-use-agent-agentarts:issue24
```

脚本输出只包含镜像引用、`linux/arm64`、SDK 版本和非 OCI 结论，不打印环境变量、
镜像层、JKS、Token、API Key 或配置内容。检查脚本对本地镜像读取 Docker Engine
的 image descriptor media type；如果 Docker 27+ 的 classic image store 不提供该
字段，则回退到 Docker archive exporter 并标为 `non-oci-export`。对仓库镜像使用
`docker manifest inspect --verbose`；发现任一 `application/vnd.oci.*` 媒体类型，或
远程 manifest 没有 `linux/arm64` descriptor，就失败，避免把 unsupported OCI
manifest 当成 SWR 基础版制品。

如果要上传到 SWR，先在华为云 SWR 控制台选择与 AgentArts 相同的区域，使用控制台
生成的临时登录命令，再自行替换区域、域名、组织和仓库：

```bash
docker tag mobile-use-agent-agentarts:issue24 \
  swr.<region>.<domain>/<organization>/mobile-use-agent-agentarts:issue24
docker push swr.<region>.<domain>/<organization>/mobile-use-agent-agentarts:issue24
```

登录命令和 AK/SK 只在本地进程环境或华为云控制面使用；不要把命令回显、凭据或
私钥粘贴到 Issue、文档或终端记录中。

## 只读本地运行

运行脚本需要一个本地、Git 忽略的 `.env`。它不会把 `.env` 复制进镜像，而是以
Docker 的 `--env-file` 在启动时注入；脚本固定覆盖镜像内配置路径和 JKS 路径，使用
非 root 用户、只读根文件系统以及仅用于实验记录和 Python 临时文件的 `/tmp` tmpfs。

```bash
cd mobile_agent
IMAGE_REF=mobile-use-agent-agentarts:issue24 \
ENV_FILE="$PWD/.env" \
HOST_PORT=8080 \
./scripts/run-agentarts-runtime.sh
```

启动后先做无外部 I/O 的健康检查：

```bash
curl -sS http://127.0.0.1:8080/ping
```

再使用 SDK 会话头调用同步接口：

```bash
curl -sS http://127.0.0.1:8080/invocations \
  -H 'Content-Type: application/json' \
  -H 'x-hw-agentarts-session-id: local-demo-1' \
  -d '{"input":"根据个人会议号在腾讯会议开启一个快速会议"}'
```

请求只接受 `{"input":"..."}`。成功返回 `200` 和 `status=completed`；模型、
KooPhone MCP、任务 deadline 或配置错误分别返回稳定的非 2xx JSON 错误。真实 Kimi
Key、KooPhone 双 Token、固定实例 ID 和 JKS 密码都必须通过启动环境提供，缺少时
启动或调用失败，不会回显其值。

## 容器验收与安全限制

- `/ping` 必须在一秒内返回 `Healthy`、`HealthyBusy` 或 `Unhealthy`，不访问模型、
  IAM、MCP 或云手机。
- 通过 `RUN_DOCKER_CONTRACT=1 AGENTARTS_TEST_IMAGE=...` 可启用 Docker 合同测试；
  测试通过临时 fake `run_koophone_task` 做依赖注入，仅验证真实容器的同步成功/失败
  HTTP 形状，不会在默认镜像中加入 debug 路由或 fake upstream。
- Runtime 的 busy、deadline、客户端取消/清理以及“业务结果不依赖 JSONL 记录器”
  由同一 `/invocations` ASGI 边界的 `test_agentarts_runtime.py` 和
  `test_koophone_task.py` 聚焦测试覆盖；容器合同测试只增加真实镜像/只读根文件系统
  这一层，不重复伪造 MCP 网络。
- 构建上下文是闭合 allowlist：只允许依赖锁、配置、Python 源码和明确批准的根
  `jwt.jks`；`.env`、密码、API Key、EID、Token、日志、JSONL、截图、缓存、venv
  和嵌套私钥不会进入上下文或镜像。
- 镜像标签和文档明确标记 `secret-bearing internal-poc`。短期验证结束后删除本地
  镜像和临时 SWR 标签，并按内部密钥轮换流程处理 JKS/双 Token；生产应改用平台
  Secret 或只读密钥挂载，不能继续把私钥烘焙进镜像。

```bash
docker image rm mobile-use-agent-agentarts:issue24
```
