# Stream Trace Debug Guide

流式日志调试模块，用于记录和查看模型厂商原始返回与 Gateway 处理后的完整流式输出。

## 启用方式

设置环境变量 `EVOFLOW_STREAM_TRACE=1`（或 `true`、`yes`、`on`）后重启服务。

```powershell
# Windows PowerShell
$env:EVOFLOW_STREAM_TRACE="1"

# Linux/macOS
export EVOFLOW_STREAM_TRACE=1
```

## 日志存储位置

```
{base_dir}/logs/stream_trace/{thread_id}/
├── vendor_stream.jsonl   # 模型厂商原始流式响应（完整）
└── gateway_stream.jsonl  # Gateway 处理后的 SSE 输出（完整）
```

`base_dir` 默认位置：
- 开发环境：`backend/.evoflow/` 或 `~/.evoflow-dev/`
- 生产环境：`~/.evoflow/`

## 查看完整日志

```bash
cd backend
python -m evoflow.debug.analyze_stream_trace <thread_id>
```

这会完整打印两个日志文件的全部内容（JSON 格式化）。

## 查看已追踪的会话

```bash
cd backend
python -c "from evoflow.debug.stream_trace import list_trace_threads; print(list_trace_threads())"
```

## 文件格式

两个文件均为 JSONL 格式，每行一个完整的 JSON 对象：

```json
{
  "timestamp_ms": 1699999999999,
  "seq": 0,
  "source": "vendor",
  "chunk": {
    "type": "AIMessageChunk",
    "content": "好",
    "generation_info": {...}
  }
}
```

## 工作原理

### Vendor 日志点

位于 `vendor_roundtrip.py` 的 `VendorRoundtripChatMixin._astream_once()` 方法中：

1. 从 LangGraph config 获取 `thread_id`
2. 每次从模型厂商收到的 chunk 都完整记录到 `vendor_stream.jsonl`

### Gateway 日志点

位于 `langgraph_route_logger.py` 的 `LangGraphRouteLoggerMiddleware` 中：

1. 在 SSE response body 处理时记录
2. 每个 SSE chunk 都完整记录到 `gateway_stream.jsonl`

## 注意事项

1. **仅调试使用**：生产环境建议关闭
2. **磁盘空间**：长时间启用会产生大量日志，注意清理
3. **性能影响**：日志写入有轻微性能开销
