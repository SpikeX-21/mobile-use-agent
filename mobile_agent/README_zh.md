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
