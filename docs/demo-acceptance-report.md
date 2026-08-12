# Kimi K2.6 + ADB Demo 九轮实机验收报告

- 验收时间：2026-08-12
- 路径：Kimi K2.6 + ADB（非思考、JSON Mode）
- 设备执行：ADB；Go MCP 不参与 Kimi + ADB 动作执行
- 结论：**通过（9/9）**
- 门槛：总成功数至少 8/9，且每个场景至少 2/3
- 无人工干预声明：已逐轮显式确认
- 运行时隐私扫描：通过

## 九轮结果

| 场景 | 轮次 | 结果 | 步骤 | 模型耗时(ms) | 设备耗时(ms) | Schema 重试 | Oracle | 失败分类 | 动作序列 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 从桌面视觉识别并打开高德地图 | 1 | 成功 | 2 | 11004 | 370 | 0 | true; `foreground_package_match=true` | — | tap → finish |
| 从桌面视觉识别并打开高德地图 | 2 | 成功 | 2 | 9797 | 222 | 0 | true; `foreground_package_match=true` | — | tap → finish |
| 从桌面视觉识别并打开高德地图 | 3 | 成功 | 2 | 9196 | 225 | 0 | true; `foreground_package_match=true` | — | tap → finish |
| 打开高德地图并搜索上海外滩 | 1 | 成功 | 5 | 29022 | 5428 | 0 | true; `foreground_package_match=true`; `query_text_visible=true` | — | tap → tap → tap → wait → finish |
| 打开高德地图并搜索上海外滩 | 2 | 成功 | 5 | 33767 | 4787 | 0 | true; `foreground_package_match=true`; `query_text_visible=true` | — | tap → tap → tap → wait → finish |
| 打开高德地图并搜索上海外滩 | 3 | 成功 | 4 | 21989 | 2588 | 0 | true; `foreground_package_match=true`; `query_text_visible=true` | — | tap → tap → tap → finish |
| 搜索上海外滩并打开第一个搜索结果 | 1 | 成功 | 5 | 28918 | 3107 | 0 | true; 前台包、详情标题及收藏控件匹配 | — | tap → tap → text_input → tap → finish |
| 搜索上海外滩并打开第一个搜索结果 | 2 | 成功 | 6 | 43091 | 4806 | 0 | true; 前台包、详情标题及收藏控件匹配 | — | tap → tap → tap → wait → tap → finish |
| 搜索上海外滩并打开第一个搜索结果 | 3 | 成功 | 6 | 38641 | 3395 | 0 | true; 前台包、详情标题及收藏控件匹配 | — | tap → tap → clear_text → text_input → tap → finish |

## 场景汇总

- `open_app`：3/3
- `search_bund`：3/3
- `open_first_result`：3/3

## Doubao + 火山 MCP 兼容性

- Doubao/MCP 适配器单元测试：`passed`
- 真实 Doubao + 火山 MCP 回归：`not_run`
- 适配器测试不启动 Go MCP，不作为真实 MCP 链路通过证据。

## 判定说明

- 每轮开始由 ADB Backend 强制停止高德地图并返回 Home；不执行 `pm clear`。
- 每轮最多十个 Agent 步骤；执行者已显式声明期间未人工点击、输入或纠正。
- 场景一三轮均由截图识别产生 `tap`，没有使用 `launch_app`。
- Schema 错误只有标记为 `not_executed` 才视为已拦截；未拦截错误直接判失败。
- 未知或不支持动作、Oracle 未通过、动作回执不确定或缺少终止原因均判失败。
- 九轮 Schema 重试均为 0，失败分类均为空；Oracle 证据为每轮 ADB 的实际结构化观测，不是预设文案。
- 原始 JSONL 与机器可读报告仅保存在本机被 Git 忽略的 `logs/` 目录，权限为 `0600`。
- 已扫描运行产物，未发现截图、任务原文、API Key、Authorization、ADB 私钥或设备临时地址。
