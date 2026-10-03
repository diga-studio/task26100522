# stackfp — Java 异常栈指纹与缺陷归并库

对 Java 异常栈（含 `Caused by:` 因果链、`Suppressed:` 抑制子节点、`... N more`
省略行）做规范化解析，生成 SHA-256 指纹，并用 SQLite 做同项目缺陷归并。

## API

```python
import stackfp

fp = stackfp.fingerprint(message, trace)          # -> 64 位十六进制字符串
record_id, canonical_id = stackfp.ingest(          # 持久化并归并
    project, message, trace, db_path="defects.sqlite3")

# 或使用长连接
with stackfp.Store("defects.sqlite3") as store:
    record_id, canonical_id = store.ingest(project, message, trace)
```

- 同项目、同指纹的记录归到最早写入的记录（`canonical_id` 为其记录 ID）；
  跨项目不合并；重开库后归并关系仍然有效。
- 无法解析的栈抛 `stackfp.TraceParseError`，且不产生任何缺陷记录。

## 规范要点

- 文本先统一 CRLF 为 LF、去行尾空格/制表符、忽略末尾空行，其余内容原样保留。
- 帧位置只区分三类（`文件:行号` / `Native Method` / `Unknown Source`），
  文件名与行号被忽略，类别不可混同；类名与方法名完整保留。
- 省略行 `... N more` 展开为树父节点已展开栈的最后 N 帧；根不允许省略，
  N 超过父栈长度即拒绝。
- 指纹覆盖：独立 message、每个节点的类型与消息、展开后的有序帧、
  有序抑制与因果关系；序列化使用长度前缀，字段边界无歧义。

## 运行测试

```bash
python3 -m unittest discover -s tests -v
```
