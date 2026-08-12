# Kimi K2.6 + ADB Demo 本地启动与验收

本文面向内部技术验证。所有密钥、ADB 私钥和云手机临时地址只保存在本机
`mobile_agent/.env`，不得写入仓库、验收报告或命令历史。

## 1. 本地前置条件

- macOS 或 Linux。
- Conda 与 Python 3.11。
- Android Platform Tools，终端可执行 `adb`。
- Node.js 20（仅交互式 Web Demo 需要）。
- Go 1.23（仅 Doubao + 火山 MCP 兼容路径需要；Kimi + ADB 不需要）。
- 已开通并可调用 Kimi K2.6 的 API Key。
- 已启用 ADB 的火山云手机，以及与该业务匹配的 ADB 私钥。

从仓库根目录创建环境：

```bash
conda create -n mobile-use-agent python=3.11 -y
conda activate mobile-use-agent
cd mobile_agent
python -m pip install -e .
```

## 2. 本地配置模板

复制 `mobile_agent/.env.example` 为 `mobile_agent/.env`，只在本机填写占位项：

```dotenv
MODEL_PROVIDER=kimi
KIMI_API_KEY=<local-secret>
KIMI_MODEL=kimi-k2.6
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_THINKING_MODE=disabled

DEVICE_PROVIDER=adb
ADB_SERIAL=<host:port-or-device-serial>
ADB_VENDOR_KEYS=<path-to-local-adb-private-key>
ADB_COMMAND_TIMEOUT=10
ADB_ORACLE_PACKAGE=com.autonavi.minimap

EXPERIMENT_RECORD_PATH=logs/experiment-runs.jsonl
```

模板不得填写真实示例值。若 ADB Server 已经加载密钥，可以不设置
`ADB_VENDOR_KEYS`。

## 3. ADB 连接检查

先完成云手机控制台的 ADB 开启与本地认证，再检查设备状态：

```bash
adb connect "$ADB_SERIAL"
adb -s "$ADB_SERIAL" get-state
```

第二条命令必须输出 `device`。验收脚本不会输出或保存 `ADB_SERIAL`。

## 4. 服务启动顺序

### Kimi + ADB 交互式 Demo

Kimi + ADB 的动作链路不经过 Go MCP。启动顺序为：

1. 确认 ADB 为 `device`。
2. 启动 Python Agent。
3. 如需网页交互，再启动 Next.js Web。

```bash
# 终端 1
conda activate mobile-use-agent
cd mobile_agent
python main.py

# 终端 2（可选）
cd web
npm install
npm run dev
```

Web 的 `CLOUD_AGENT_BASE_URL` 指向本机 Agent。浏览器访问
`http://localhost:8080/chat?token=<local-demo-token>`，可输入任务进行交互式体验。
交互体验不计入九轮无人干预验收。

### Doubao + 火山 MCP 兼容路径

该路径与 Kimi + ADB 分开：先启动 Go MCP，再以 `MODEL_PROVIDER=doubao`、
`DEVICE_PROVIDER=mcp` 启动 Agent，最后启动 Web。Go MCP 只服务旧兼容路径，
不参与 Kimi + ADB 的截图、点击、输入或 Oracle。

## 5. 九轮无人干预验收

在 `mobile_agent` 目录执行：

```bash
conda activate mobile-use-agent
python -m mobile_agent.acceptance \
  --attest-no-manual-intervention \
  --output-dir logs/acceptance-run
```

`--output-dir` 必须是尚不存在的新目录。命令会固定执行：

1. 从桌面视觉识别并打开高德地图，三次。
2. 打开高德地图并搜索“上海外滩”，三次。
3. 搜索“上海外滩”并打开第一个搜索结果，三次。

每轮都通过现有 `prepare_task` 强制停止高德地图并返回 Home，不执行
`pm clear`；最多十个 Agent 步骤，执行期间不接受人工点击、输入或纠正。
场景一必须包含视觉 `tap`，使用 `launch_app` 会判失败。
`--attest-no-manual-intervention` 是验收执行者对九轮无人操作的显式声明；缺少
该声明时命令拒绝启动，声明缺失也会使逐轮结果判失败。

退出码 `0` 表示九轮总成功数至少 8/9、每个场景至少 2/3，且 Doubao/MCP
适配器兼容单元测试通过；否则退出码为 `1`。该单元测试不启动 Go MCP，真实
Doubao + 火山 MCP 回归在报告中单独标记为 `not_run`，不冒充实机链路证据。

## 6. 交付物与判定

运行目录包含：

- `experiment-runs.jsonl`：逐步脱敏实验记录，文件权限 `0600`。
- `acceptance-report.json`：机器可读的九轮汇总。
- `acceptance-report.md`：每轮结果、步骤数、模型/设备耗时、Schema 重试、
  Oracle 证据、动作序列和失败分类。

报告生成后会扫描实际 Kimi API Key、ADB 私钥路径、设备地址、截图 Base64、
Authorization 和签名 URL；发现任一敏感值时命令失败。

最终内部验收报告见 [Demo 九轮实机验收报告](demo-acceptance-report.md)。原始
JSONL 和本地配置保持在被 Git 忽略的 `logs/` 与 `.env` 中，不提交仓库。
