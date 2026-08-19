# Mobile Agent - AI移动设备自动化代理核心

[English](README.md) | 简体中文


## 🏗️ 架构设计

```
mobile_agent/
├── mobile_agent/
│   ├── agent/              # 核心代理逻辑
│   │   ├── mobile_use_agent.py    # 主代理类
│   │   ├── graph/          # LangGraph工作流
│   │   ├── tools/          # 工具管理
│   │   ├── prompt/         # 提示词模板
│   │   ├── memory/         # 记忆管理
│   │   ├── mobile/         # 移动设备交互
│   │   ├── llm/           # 大语言模型接口
│   │   ├── cost/          # 成本计算
│   │   ├── infra/         # 基础设施
│   │   └── utils/         # 工具函数
│   ├── config/            # 配置管理
│   ├── routers/           # API路由
│   ├── service/           # 业务服务
│   ├── middleware/        # 中间件
│   └── exception/         # 异常处理
├── config.toml           # 配置文件
├── requirements.txt      # 依赖管理
├── pyproject.toml       # 项目配置
└── main.py             # 应用入口
```

## 🚀 快速开始

### 环境要求

- **Python** >= 3.11
- **uv** (推荐的Python包管理器)
- 豆包模型API密钥
- 云手机服务访问权限

### 安装步骤

1. **安装依赖**
```bash
cd mobile_agent
uv sync
```

2. **配置环境**
```bash
# 编辑配置文件，填入你的API密钥和服务端点
cp .env.example .env
```

3. **启动服务**
```bash
# 开发模式
uv run main.py
```

该 HTTP 服务仅预期在本机使用。`main.py` 会始终监听 `127.0.0.1`，
即使配置了其他 `UVICORN_SERVER_HOST` 也不会对外网卡暴露。

### 配置说明

```bash
MOBILE_USE_MCP_URL= # MCP_SSE 服务地址 http://xxxx.com/sse

TOS_BUCKET= # 火山引擎对象存储桶
TOS_REGION= # 火山引擎对象存储区域
TOS_ENDPOINT= # 火山引擎对象存储终端

ARK_API_KEY= # 火山引擎API密钥
ARK_MODEL_ID= # 火山引擎模型ID

ACEP_AK= # 火山引擎 AK
ACEP_SK= # 火山引擎 SK
ACEP_ACCOUNT_ID= # 火山引擎 账号ID
```

### Kimi K2.6 + ADB 视觉点击 Demo

Issue #6 的多步 Demo 不依赖 Go MCP 执行动作。先确保 `adb devices` 中目标设备状态为
`device`，再在 `.env` 中配置：

```dotenv
MODEL_PROVIDER=kimi
KIMI_API_KEY=<仅保存在本机的密钥>
KIMI_MODEL=kimi-k2.6
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_THINKING_MODE=disabled

DEVICE_PROVIDER=adb
ADB_SERIAL=<设备地址或序列号>
ADB_VENDOR_KEYS=<ADB 私钥路径，可在 adb server 已加载密钥时留空>
ADB_COMMAND_TIMEOUT=10
ADB_ORACLE_PACKAGE=com.autonavi.minimap
EXPERIMENT_RECORD_PATH=logs/experiment-runs.jsonl
```

也兼容用 `OPENAI_BASE_URL` 提供接口地址；若同时设置，`KIMI_BASE_URL` 优先。
启动方式不变：

```bash
conda activate mobile-use-agent
python main.py
```

该 Demo 每轮通过 `adb exec-out screencap -p` 获取截图，以 Base64 发送给 Kimi。
ADB Backend 支持 `tap`、`swipe`、`text_input`、`clear_text`、`home`、`back`、
`menu`、`launch_app`、`close_app`、`list_apps` 和 `wait`。截图始终由 Agent 自动
观察，不是模型动作；`autoinstall_app` 不属于 Demo 的原子能力。
坐标采用 0–1000 归一化格式，执行前会按截图尺寸转换为像素。安全 ASCII 文本使用
`adb shell input text`；中文和特殊字符使用 Android UTF-8 剪贴板及
`KEYCODE_PASTE`，避免依赖已废弃的云手机私有广播。清空文本使用 Ctrl+A 后删除。
应用包名必须符合 Android application ID 格式。`list_apps` 可通过
`ignore_system_apps=true` 只列出第三方应用，并会过滤无效命令输出。

每个任务开始前会强制停止高德地图并返回桌面，但不会执行 `pm clear`。任务完成由
独立 Oracle 验证：`adb shell dumpsys window` 必须确认前台包为
`com.autonavi.minimap`，搜索“上海外滩”场景还会读取 UI hierarchy，要求目标文本
真实可见。打开首个搜索结果场景使用压缩 UI hierarchy，要求详情页同时出现精确的
语义标题节点与收藏按钮；搜索框文字或结果列表不能被误判为详情页。压缩读取可避免
复杂详情页的非压缩 hierarchy 被设备系统杀死。完整任务最多执行十步，并且不需要
人工点击。

动作执行结果统一分为 `success`、`failed` 和 `ambiguous`。点击、滑动、输入、
按键及应用生命周期操作发生超时时不会自动重放，而是标记为 `ambiguous`，
下一轮先获取新截图，再由 Agent 判断动作是否已经生效。截图和应用列表读取最多
尝试两次；设备离线、连续三次动作 Schema 错误或达到十步上限时会给出明确原因并
终止。每个工具调用只会产生一个最终 SSE 状态，不会在 `stop` 后再次发送
`success`。

每次 Agent 运行还会向 `EXPERIMENT_RECORD_PATH` 追加脱敏 JSONL。每行代表一个
模型决策步骤，包含运行/场景 ID、Provider、模型、步骤和动作、模型/设备耗时、
动作与 Schema 状态、失败类型、终止原因及 Oracle 结果。场景 ID 由规范化任务文本
生成稳定哈希，原始任务文本不会保存；`text_input` 参数只保存字符长度与 SHA-256。
API Key、AK/SK、Authorization、ADB 私钥、截图 Base64、签名 URL 和隐藏思维均会
在写入前移除。当前截图实验策略记录为 `fixed_recent`、窗口大小 `5`，只保存策略和
实际使用数量，不保存截图；相同字段也可用于未来 `dynamic_recent` 一至两张策略的
A/B Test，本期不启用动态策略。默认输出位于已被 Git 忽略的 `logs/` 目录。

### 九轮实机验收与 Demo 交付

完整的 Conda 环境、配置占位符、ADB 检查、服务启动顺序和九轮验收说明见
[Kimi K2.6 + ADB Demo 本地启动与验收](../docs/demo-delivery.md)。在
`mobile_agent` 目录执行以下命令，会无人干预地运行三个场景各三次，并生成脱敏的
Markdown/JSON 报告：

```bash
python -m mobile_agent.acceptance \
  --attest-no-manual-intervention \
  --output-dir logs/acceptance-run
```

Kimi + ADB 路径不启动也不调用 Go MCP；Doubao + 火山 MCP 兼容回归单独标识。

### KooPhone secret-bearing 内部 POC 容器

`Dockerfile.koophone-poc` 只打包 Python Agent 和闹钟 CLI，不包含 Web、Go MCP 或
AgentArts SDK。该镜像会把本机、受 Git 忽略的 `jwt.jks` 复制进镜像，因此它是
**包含私钥材料的内部临时产物**：不得推送公共镜像仓库、不得用于生产，也不要导出或
作为普通镜像共享。完成联调后应删除本地镜像。后续可通过同一个
`KeyMaterialProvider` 接口改用 AgentArts/Kubernetes Secret、只读挂载文件或外部
密钥服务，无需修改 JWT 签发逻辑。

构建前确保 `mobile_agent/jwt.jks` 存在；`.dockerignore` 采用默认拒绝策略，只允许
Python 包、锁文件、README 和该 JKS 进入构建上下文，`.env`、日志、实验记录、截图、
缓存和虚拟环境均不会进入镜像：

```bash
cd mobile_agent
test -s jwt.jks
docker build \
  --file Dockerfile.koophone-poc \
  --tag mobile-use-koophone-poc:local-secret-bearing \
  .
```

所有密码、API Key、实例标识、端点和 TLS 配置只能在启动时从受 Git 忽略的 `.env`
注入。容器内 JKS 固定为 `/opt/mobile-agent/secrets/koophone.jks`，所以需要在
`--env-file` 之后显式覆盖本地 `.env` 中可能存在的宿主机路径。当前内部自签证书联调
可设置 `ENV=poc` 与 `KOOPHONE_TLS_VERIFY=false`；任何非 POC 环境都会拒绝该组合。
若改用可信自定义 CA，则设置 `KOOPHONE_TLS_VERIFY=true` 和
`KOOPHONE_CA_BUNDLE=<容器内 CA 路径>`，并将 CA 只读挂载进容器。

```bash
docker run --rm \
  --env-file .env \
  --env KOOPHONE_JKS_PATH=/opt/mobile-agent/secrets/koophone.jks \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  mobile-use-koophone-poc:local-secret-bearing
```

镜像以 UID/GID `10001:10001` 运行，JKS 权限为 `0400`，实验记录默认写入临时目录
`/tmp/mobile-agent/experiment-runs.jsonl`。入口会先校验 JKS 权限和必需配置；随后沿用
现有 `MobileUseAgent.initialize()` 刷新 IAM Token 与 JWT，并执行 MCP initialize 和
`tools/list` 能力探测。任一步失败都会在调用 Kimi 前以非零状态退出；成功后才运行
真实的“确保存在已启用 09:00 闹钟”任务。

确认镜像身份和密钥权限：

```bash
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --entrypoint /bin/sh mobile-use-koophone-poc:local-secret-bearing \
  -c 'id && stat -c "mode=%a uid=%u gid=%g" /opt/mobile-agent/secrets/koophone.jks'
```

联调完成后删除本地 secret-bearing 镜像：

```bash
docker image rm mobile-use-koophone-poc:local-secret-bearing
```

若要执行 Issue #18 的完整实机交付矩阵（准备禁用状态、启用、已启用识别、幂等重复），
请按 [Kimi K2.6 + KooPhone 容器 Demo 交付与验收](../docs/koophone-container-demo-delivery.md)
构建镜像，并在容器入口后增加：

```bash
acceptance --output-dir /output --attest-no-manual-intervention
```

该命令只以最新真实截图作为完成证据；任一阶段失败都会非零退出，且输出会经过凭据、
截图和实例信息检查。

## 🛠️ 核心组件

通过 Mobile Use MCP 支持的移动设备操作：

| 工具名称 | 功能描述 | 参数 |
|---------|---------|------|
| `mobile:screenshot` | 截取设备屏幕 | - |
| `mobile:tap` | 点击屏幕坐标 | `x, y` |
| `mobile:swipe` | 滑动手势 | `from_x, from_y, to_x, to_y` |
| `mobile:type` | 文本输入 | `text` |
| `mobile:home` | 返回主屏幕 | - |
| `mobile:back` | 返回上一级 | - |
| `mobile:close_app` | 关闭应用 | `package_name` |
| `mobile:launch_app` | 启动应用 | `package_name` |
| `mobile:list_apps` | 列出已安装应用 | - |

强烈推荐：如果你需要在生产环境、业务集成场景，或对服务稳定性与任务成功率有更高要求的场景中使用 Mobile Use Agent，建议优先通过火山引擎控制台使用 [Mobile Use Open API](https://www.volcengine.com/docs/6394/1583515)。相比自行维护完整的本地部署链路，控制台提供的 Open API 能带来更稳定的托管服务体验，是将 Mobile Use Agent 接入真实业务流程时更推荐的使用方式。
