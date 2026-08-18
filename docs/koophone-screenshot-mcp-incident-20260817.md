# KooPhone MCP `get_screenshot` 响应异常报告

时间：2026-08-17（Asia/Shanghai）

## 结论

`get_screenshot` 当前返回的 MCP content 块不符合 MCP `TextContent` 架构。Python MCP 客户端在解析 `CallToolResult` 时失败，因此 Agent、Kimi 和任何后续点击动作都不会开始执行。

本报告不包含截图 Base64、JWT、IAM Token、密码或私钥。截图内容本身不应通过工单传输；请在服务端日志中按请求时间定位原始载荷。

## 本次重试结果

初始化、认证、MCP initialize 和 tools/list 均成功。调用 `get_screenshot` 时客户端直接收到的可见 content 输入为：

```json
{
  "content": [
    {
      "type": "text"
    }
  ]
}
```

完整客户端校验错误：

```text
12 validation errors for CallToolResult
content.0.TextContent.text
  Field required [type=missing, input_value={'type': 'text'}, input_type=dict]
content.0.ImageContent.type
  Input should be 'image' [type=literal_error, input_value='text', input_type=str]
content.0.ImageContent.data
  Field required [type=missing, input_value={'type': 'text'}, input_type=dict]
content.0.ImageContent.mimeType
  Field required [type=missing, input_value={'type': 'text'}, input_type=dict]
content.0.AudioContent.type
  Input should be 'audio' [type=literal_error, input_value='text', input_type=str]
content.0.AudioContent.data
  Field required [type=missing, input_value={'type': 'text'}, input_type=dict]
content.0.AudioContent.mimeType
  Field required [type=missing, input_value={'type': 'text'}, input_type=dict]
content.0.ResourceLink.name
  Field required [type=missing, input_value={'type': 'text'}, input_type=dict]
content.0.ResourceLink.uri
  Field required [type=missing, input_value={'type': 'text'}, input_type=dict]
content.0.ResourceLink.type
  Input should be 'resource_link' [type=literal_error, input_value='text', input_type=str]
content.0.EmbeddedResource.type
  Input should be 'resource' [type=literal_error, input_value={'type': 'text'}, input_type=dict]
content.0.EmbeddedResource.resource
  Field required [type=missing, input_value={'type': 'text'}, input_type=dict]
```

## 此前成功形态

此前 KooPhone 实例曾成功返回单个 MCP `TextContent`。该 `text` 字段是一个 JSON 编码的 data URL 字符串，语义如下：

```json
{
  "content": [
    {
      "type": "text",
      "text": "\"data:image/png;base64,<PNG_BASE64>\""
    }
  ]
}
```

客户端当时成功严格解码为 PNG，得到尺寸 `304 x 540`，随后 Kimi 根据截图执行了真实 `send_key(HOME)`，并在下一轮截图后完成任务。

原始成功截图 Base64 没有保留在运行记录或日志中，这是客户端的既定脱敏设计；因此无法提供或恢复完整原始图片消息。

## 服务端修复要求

请确保 `get_screenshot` 的 `CallToolResult` 总是返回合法的 MCP content。二选一：

```json
{"content":[{"type":"text","text":"\"data:image/png;base64,<PNG_BASE64>\""}]}
```

或：

```json
{"content":[{"type":"image","data":"<PNG_BASE64>","mimeType":"image/png"}]}
```

禁止返回只有 `{"type":"text"}` 的 content 块。若截图生成失败，请返回一个完整的文本错误字段，或 MCP JSON-RPC error；不要返回半成品 content。

## 影响

- 09:00 闹钟 Agent 无法进入 Kimi 推理阶段。
- 不会发出点击、输入、启动应用等副作用操作。
- 本地 CLI 安全终止并报告失败，不会误报任务完成。

## 2026-08-18 恢复验证

上游已恢复为合法 `TextContent`，其中 Base64 PNG 的实际尺寸为
`1080 x 1920`，与云手机原生输入坐标空间一致。

恢复后使用同一生产 Agent 链路完成真实验收：

1. Kimi K2.6（非思考、JSON mode）从最新截图识别到 09:00 闹钟未启用；
2. Agent 依次执行 `start_app` 和归一化 `tap(888, 710)`；
3. KooPhone 后端将点击映射为原生像素 `tap(959, 1363)`；
4. 最新 MCP 截图显示 09:00 开关已启用；
5. Agent 返回 `finish`，终止原因记录为 `completed`。

本次恢复验证证明此前故障位于 KooPhone MCP 上游响应/设备命令链路；同时也确认
Agent 不应把缩略截图尺寸当作 `tap` 的设备像素空间。当前实现要求通过
`KOOPHONE_INPUT_WIDTH` / `KOOPHONE_INPUT_HEIGHT` 显式配置输入坐标尺寸。
