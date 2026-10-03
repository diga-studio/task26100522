# stackfp：Java 异常栈指纹与缺陷归并库

纯 Python + SQLite 实现，无第三方依赖。

## 用法

```python
from stackfp import fingerprint, Store, TraceParseError

# 计算指纹（解析失败抛 TraceParseError）
fp = fingerprint(message, trace)

# 写入并按 (project, fingerprint) 归并
with Store("defects.db") as store:
    result = store.ingest(project, message, trace)
    # result.record_id    新记录 ID
    # result.canonical_id 归并目标（同项目同指纹的最早记录）
```

## 规则要点

- 支持根 / `Suppressed: ` / `Caused by: ` 三类节点头部，制表符缩进表达树结构。
- 帧位置分三类（`文件:行号` / `Native Method` / `Unknown Source`），文件名与行号忽略，类别不可混同。
- `... N more` 把直接父异常已展开栈的最后 N 帧接到本节点显式帧之后；根不允许省略，N 越界拒绝。
- 规范化：CRLF->LF、去行尾空格与制表符、忽略末尾空行，其余内容原样保留。
- 规范结果含独立 message、每节点类型与消息、展开后有序帧、有序抑制与因果关系，
  以 netstring 风格无歧界序列化后取 SHA-256。
- 无法解析的栈抛 `TraceParseError`，不写入任何记录；trace 超过 50 KiB 抛 `ValueError`。

## 测试

```sh
python3 -m unittest discover -s tests -v
```
