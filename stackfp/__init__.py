"""Java 异常栈指纹与缺陷归并库。"""
from __future__ import annotations

from .fingerprint import fingerprint
from .parser import TraceParseError, parse_trace
from .store import Store

_DEFAULT_DB = "defects.sqlite3"


def ingest(project: str, message: str, trace: str, db_path: str = _DEFAULT_DB) -> tuple[int, int]:
    """写入一条缺陷记录，返回 (record_id, canonical_id)。

    同项目同指纹归到最早写入的记录；跨项目不合并。
    """
    store = Store(db_path)
    try:
        return store.ingest(project, message, trace)
    finally:
        store.close()


__all__ = ["fingerprint", "ingest", "parse_trace", "TraceParseError", "Store"]
