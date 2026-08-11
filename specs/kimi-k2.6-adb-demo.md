# Kimi K2.6 + ADB Mobile Use Demo 实施规格

状态：Ready for agent

目标读者：内部研发与验证人员

交付类型：本地技术验证 Demo
涉及服务：`mobile_agent`（主要改造）；`mobile_use_mcp` 与 `web` 保持现状

## Problem Statement

现有 Mobile Use 项目的 Agent 层与豆包模型输出格式、火山云手机 MCP 工具和 TOS 截图 URL 紧密耦合。当前已验证模型可以从截图中识别“打开高德地图”的意图并生成正确点击坐标，但火山云手机旧命令链路 `RunSyncCommand` 会在动作已经生效后返回 gRPC `DeadlineExceeded`，导致 Agent 将成功动作判断为失败并停止后续推理。

本项目需要交付一个最小本地 Demo，用 Kimi K2.6 替换模型决策能力，并通过已连通的 ADB 直接控制火山云手机，以隔离旧 MCP 命令回执故障。Demo 的目标不是完成生产部署，而是回答一个明确问题：Kimi K2.6 在非思考模式和 JSON Mode 下，能否稳定理解用户意图、识别 Android 截图并连续选择正确动作。

同时，设计必须为将来接入其他云手机厂商 MCP 保留清晰边界，但本期不实现该厂商的真实连接。

## Solution

在 Python Agent 内建立两层适配边界：模型适配层负责把不同模型响应归一为内部动作；设备适配层负责把内部动作执行到 ADB 或未来的厂商 MCP。LangGraph 的观察—决策—执行循环继续保留，Web 页面、现有 SSE 协议和火山云手机画面展示链路不改造。

本期运行路径为：

```text
用户指令
  -> 现有 Agent/SSE 入口
  -> LangGraph 循环
  -> ADB 截图（Base64/二进制）
  -> Kimi K2.6 Vision（非思考、非流式、JSON Mode）
  -> CanonicalAction 校验
  -> ADB 动作执行
  -> 新截图验证
  -> 继续、完成或失败
```

保留豆包路径用于对照验证。运行时通过服务端环境变量选择模型和设备后端，不向 Web 增加供应商选择功能。

## User Stories

1. 作为内部研发人员，我可以设置 `MODEL_PROVIDER=kimi` 和 `DEVICE_PROVIDER=adb` 启动 Agent，使请求走 Kimi K2.6 与 ADB，而无需修改源码。

2. 作为内部研发人员，我可以继续设置 `MODEL_PROVIDER=doubao` 使用现有豆包实现，以便对比模型行为并降低改造回归风险。

3. 作为验证人员，我输入“打开高德地图”后，Agent 必须先观察桌面截图，再通过视觉定位产生 `tap`，不能用 `launch_app` 绕过视觉识别。

4. 作为验证人员，我输入“打开高德地图并搜索上海外滩”后，Agent 可以连续执行打开应用、定位搜索框、输入中文、提交搜索等动作。

5. 作为验证人员，我要求 Agent 打开第一个搜索结果时，Agent 可以在必要时滑动列表、点击正确结果并判断目标页面是否出现。

6. 作为维护人员，我可以从统一的 `CanonicalAction` 结构理解模型选择的动作，而不必解析 Kimi 或豆包各自的输出文本。

7. 作为维护人员，我可以在不修改 LangGraph 核心循环的情况下增加新的模型 Provider，Provider 只需负责构造请求和返回规范动作。

8. 作为维护人员，我可以在不修改模型 Provider 的情况下增加厂商 MCP 设备后端，后端只需实现统一的设备操作协议。

9. 作为验证人员，当 ADB 动作超时或返回结果不明确时，Agent 不会盲目重复点击或输入，而是获取新截图确认设备实际状态。

10. 作为验证人员，每个场景开始前设备会回到一致的基线：强制停止高德地图并返回桌面，但不会清除应用数据。

11. 作为维护人员，我可以查看脱敏 JSONL 运行记录，比较每一步的动作、耗时、结果和终止原因，同时日志不包含 API Key、ADB 私钥、截图 Base64、完整隐私文本或模型思维链。

12. 作为研发人员，我可以独立运行单元测试和模拟后端测试，不依赖真实云手机或真实 Kimi API；只有端到端验收需要实际 ADB 设备和模型凭证。

## Implementation Decisions

### 1. 保留 Agent 编排，拆除供应商硬编码

- 保留现有 LangGraph 状态机、任务入口、SSE 输出和最多步数控制。
- 将节点中硬编码的 `DoubaoLLM`、豆包 Prompt、豆包动作解析器和 MCP 工具集合替换为由工厂创建的模型 Provider 与设备 Backend。
- Agent 核心只依赖规范化的观察结果、动作和执行结果，不直接依赖 Kimi、Ark、ADB 或 MCP 参数。
- Kimi 路径使用独立 Prompt；豆包 Prompt 原样保留，避免一个 Prompt 同时迁就两种模型。

### 2. 模型适配协议

模型 Provider 接收以下逻辑输入：用户目标、最近的对话/动作摘要、最近五张截图、当前步数和允许动作 Schema；返回经过结构校验的 `CanonicalAction` 以及可选的简短可展示摘要。

Kimi Provider 的固定约束：

- 模型：`kimi-k2.6`。
- 模式：非思考模式。
- 调用方式：OpenAI 兼容 Chat Completions，Agent 内部非流式调用。
- 输出：JSON Mode；不依赖原生 function calling。
- 图片：以 Base64 data URL 或接口要求的等价 Base64 形式传入，不依赖公网图片 URL。
- 温度：按 Kimi 非思考模式约束使用 `0.6`，不复用当前豆包的 `0` 配置。
- 上下文图片：基线固定保留最近五张。动态保留一至两张仅作为后续 A/B 扩展点。
- 不记录或展示隐藏思维链，只允许输出可审计的简短动作理由。

### 3. CanonicalAction

所有模型输出必须先解析为单个 JSON 对象，再通过严格 Schema 校验。动作类型如下：

| 动作 | 关键参数 | 语义 |
| --- | --- | --- |
| `tap` | `x`, `y` | 点击归一化坐标 |
| `swipe` | `start_x`, `start_y`, `end_x`, `end_y`, `duration_ms` | 执行滑动 |
| `text_input` | `text` | 输入文本 |
| `clear_text` | 无 | 清空当前输入框 |
| `home` | 无 | 返回主屏幕 |
| `back` | 无 | 返回上一页 |
| `menu` | 无 | 打开菜单键 |
| `launch_app` | `package_name` | 按包名启动应用 |
| `close_app` | `package_name` | 按包名停止应用 |
| `list_apps` | 可选过滤条件 | 获取已安装应用 |
| `wait` | `duration_ms` | 等待界面稳定 |
| `finish` | `summary` | 明确声明任务成功 |
| `fail` | `reason` | 明确声明无法完成 |

坐标统一为 0–1000 的整数。设备后端根据实际截图宽高转换为像素坐标，并对边界进行裁剪和校验。`take_screenshot` 是每轮自动执行的观察能力，不暴露为模型动作。`autoinstall_app` 不属于本期能力。

JSON 之外的前后缀、未知字段、未知动作、类型错误和越界坐标都视为 Schema 错误，不允许下发到设备。Schema 错误可把简短校验反馈交回模型重新生成，但计入总步数。

### 4. 设备适配协议

设备 Backend 提供：截图、点击、滑动、文本输入、清空文本、Home、Back、Menu、启动应用、关闭应用和列出应用。输入输出使用项目内部类型，不暴露 `instanceId` 等供应商字段。

ADB Backend 的实现约束：

- 通过 `asyncio.create_subprocess_exec` 调用系统 ADB CLI，不使用 shell 字符串拼接，避免注入和转义问题。
- 所有命令显式指定 `ADB_SERIAL`，并应用统一超时。
- 截图使用 `exec-out screencap -p` 读取二进制数据，解析真实宽高并转换为模型需要的 Base64。
- 点击、滑动、按键、应用启动/停止和应用列表使用对应 ADB 命令。
- 中文文本优先复用设备已有的字节输入广播能力；普通 `adb shell input text` 仅作为对安全字符集的降级路径。
- `clear_text` 复用设备已有清空广播能力，并在执行后截图确认。
- 命令返回码、标准错误、超时和设备离线必须归一为结构化 `ActionResult`。

未来的 Vendor MCP Backend 实现同一协议，在内部负责注入厂商的 `instanceId`、参数命名与截图格式。本期只保留接口和可测试的占位工厂分支，不连接真实厂商 MCP。

### 5. 动作结果与重试语义

- 读取类操作（截图、应用列表）可在瞬时网络或进程错误时进行有界重试。
- 有副作用的操作（点击、滑动、输入、按键、启动/停止应用）不得因超时直接原样重试。
- 副作用操作发生超时或结果不明确时，状态标记为 `ambiguous`，下一步必须重新截图，让模型或确定性验证逻辑判断动作是否已经生效。
- 工具执行失败时 SSE 必须只发出失败状态，不能随后再发同一动作成功状态。
- Agent 达到十步、连续 Schema 错误、设备离线或模型不可恢复错误时应以明确失败原因结束，而不是无限循环。

### 6. 配置

新增或规范以下服务端环境变量；示例文件只写占位符，不写真实凭证：

```dotenv
MODEL_PROVIDER=kimi
KIMI_API_KEY=<secret>
KIMI_MODEL=kimi-k2.6
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_THINKING_MODE=disabled

DEVICE_PROVIDER=adb
ADB_SERIAL=<host:port>
ADB_VENDOR_KEYS=<path-to-private-key>
ADB_COMMAND_TIMEOUT=10
```

服务启动时应校验当前 Provider 所需变量，并给出缺失字段名称；不得把变量值写入错误信息。豆包和现有 MCP 配置继续保留，仅在对应 Provider 被选中时要求存在。

### 7. 运行记录

每次场景运行生成一条或多条 JSONL 记录，至少包含：运行 ID、场景 ID、Provider 名称、模型名、步骤号、动作类型、脱敏参数、模型耗时、设备耗时、动作状态、Schema 状态、终止原因和最终 Oracle 结果。

以下内容禁止记录：API Key、AK/SK、ADB 私钥、Authorization Header、截图 Base64、截图 URL 中的临时签名、完整用户隐私文本和模型隐藏思维链。文本输入参数默认只记录长度和稳定哈希；确需调试时使用显式的本地开关，并仍过滤凭证形态。

### 8. 与现有三个服务的边界

- `mobile_agent`：完成本期全部核心改造，包括 Provider、Backend、规范动作、循环语义、日志和测试。
- `mobile_use_mcp`：不修改。它保留为豆包/火山旧链路的兼容实现和历史对照，但 Kimi + ADB 路径不依赖它执行设备动作。
- `web`：不修改。继续使用现有页面、SSE 展示和火山 WebSDK 画面；不增加 Provider 开关或新的设备配置 UI。

## Testing Decisions

### 主要测试缝

最高价值测试缝是 Agent 的任务执行入口：在不启动 Web 的情况下，向 Agent 提交任务，通过可替换的 Model Provider 和 Device Backend 驱动完整 LangGraph 循环，并断言动作序列、SSE 状态与最终结果。该测试缝既覆盖真实端到端路径，又允许使用确定性截图夹具和假后端快速回归。

### 自动化测试

1. CanonicalAction Schema 测试：覆盖所有动作、缺失字段、额外字段、错误类型、越界坐标和非 JSON 输出。
2. 坐标换算测试：覆盖横竖屏、不同分辨率、边界值和裁剪行为。
3. Kimi Provider 测试：用录制响应验证 JSON 解析、非思考配置、Base64 图片消息、Schema 修复和错误分类，不调用真实 API。
4. ADB Backend 测试：注入假子进程结果，验证命令参数、超时、离线、中文输入、截图解析及敏感数据不进入日志。
5. Agent 循环测试：用脚本化 Provider 与假 Backend 验证正常多步流程、Schema 重试、副作用动作歧义后先截图、十步终止和 SSE 失败状态唯一性。
6. 豆包回归测试：确认 `MODEL_PROVIDER=doubao` 仍能创建原有 Provider，并将旧文本动作转换为 CanonicalAction。

### 真实设备验收

每次运行前执行统一基线：强制停止高德地图，然后返回 Home；不执行 `pm clear`。每个任务最多十个 Agent 步骤，不允许人工点击。

验收场景：

1. 从桌面视觉识别并打开高德地图；必须由截图生成 `tap`。
2. 打开高德地图并搜索“上海外滩”。
3. 打开第一个搜索结果；结果不在可视区时允许滑动。

每个场景独立运行三次，共九次。通过标准为：总成功次数至少 8/9，且每个场景至少 2/3 成功；任何 Schema 错误未被拦截、未知工具实际执行或人工干预均判为失败。

最终成功由独立 ADB Test Oracle 判断，不能只采信模型的 `finish`：

- 场景 1：前台包名为高德地图。
- 场景 2：前台包名正确，且 UI 层级或可见文本包含目标查询/结果特征。
- 场景 3：前台包名正确，且 UI 层级出现详情页稳定特征；若 UI 层级不可用，可用预先定义的截图特征作为补充证据。

记录每次运行的成功与否、步骤数、模型耗时、设备耗时、Schema 重试次数和失败分类，作为后续固定五图与动态一至两图 A/B Test 的基线。

## Delivery Plan

1. 定义内部类型、配置校验和 Provider/Backend 协议，先用假实现跑通 Agent 测试缝。
2. 实现 CanonicalAction Schema、Kimi JSON Mode Provider 和 Kimi 专用 Prompt。
3. 实现 ADB Backend、截图尺寸解析、中文输入与结构化结果。
4. 把 LangGraph 节点切换到工厂和统一协议，修正失败状态与歧义动作语义。
5. 加入脱敏 JSONL 记录和独立 ADB Test Oracle。
6. 执行自动化测试、豆包回归和九轮真实设备验收，输出 Demo 验证报告。

## Definition of Done

- Kimi K2.6 非思考 JSON Mode 可通过环境变量启用，真实密钥不进入仓库。
- Kimi + ADB 路径不依赖 Go MCP 执行动作，Web 无需修改即可继续展示现有页面。
- 所有模型动作经过 CanonicalAction 严格校验；副作用动作没有盲重试。
- 固定最近五张截图的策略生效，截图以 Base64 传给 Kimi。
- 自动化测试覆盖模型适配、设备适配、Schema 和 Agent 主循环的关键失败分支。
- 三个真实场景满足 8/9 且单场景至少 2/3 的验收门槛。
- 运行记录完成脱敏，安全扫描确认没有凭证、私钥和截图数据被提交或记录。
- 提供本地启动说明、环境变量模板、验收命令和结果报告。

## Out of Scope

- 真实接入其他云手机厂商 MCP。
- `autoinstall_app` 或任何自动安装能力。
- 修改 Web 前端、增加供应商选择 UI 或重做画面展示。
- AgentArts、云函数、容器或其他生产部署。
- 多租户、权限系统、生产级密钥托管、计费与高可用。
- 同时控制多台设备，或校验 Web 画面对应的 Pod 与 ADB 目标是否一致。
- 动态截图窗口策略；本期只保留扩展点和 A/B Test 数据结构。
- 解决火山云手机旧 `RunSyncCommand` 的服务端 `DeadlineExceeded`。

## Further Notes

- 当前代码受火山方舟原型应用软件自用许可约束。本 Demo 定位为内部技术验证；在对外分发、商用或改变使用范围前必须重新核对许可。
- 已有实机证据表明“打开高德地图”的视觉识别和坐标选择正确，失败发生在旧云手机命令的回执链路。ADB 路径用于绕过该故障并验证模型适配，不代表服务端故障已经修复。
- Kimi API Key、火山 AK/SK、ADB 私钥和云手机临时地址均属于本地秘密；仓库文档只允许使用占位符。
- 未来接入厂商 MCP 时，应优先新增 Backend 实现，不应把 `instanceId` 或厂商工具名重新渗透到 Agent 状态、Prompt 或 Web。
