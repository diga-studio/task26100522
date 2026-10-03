"""SQLite 持久化与缺陷归并。"""
from __future__ import annotations

import sqlite3

from .fingerprint import fingerprint

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    message TEXT NOT NULL,
    trace TEXT NOT NULL,
    canonical_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_project_fp
    ON records (project, fingerprint, id);
"""


class Store:
    """缺陷记录库。同项目同指纹归到最早写入的记录；跨项目不合并。"""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)

    def ingest(self, project: str, message: str, trace: str) -> tuple[int, int]:
        """写入一条记录，返回 (record_id, canonical_id)。

        栈文本无法解析时抛 TraceParseError，不产生任何记录。
        """
        fp = fingerprint(message, trace)  # 解析失败在此抛出，先于任何写入
        with self._conn:
            row = self._conn.execute(
                "SELECT MIN(id) FROM records WHERE project = ? AND fingerprint = ?",
                (project, fp),
            ).fetchone()
            canonical_id = row[0]
            if canonical_id is None:
                cur = self._conn.execute(
                    "INSERT INTO records (project, fingerprint, message, trace, canonical_id)"
                    " VALUES (?, ?, ?, ?, -1)",
                    (project, fp, message, trace),
                )
                record_id = cur.lastrowid
                self._conn.execute(
                    "UPDATE records SET canonical_id = ? WHERE id = ?",
                    (record_id, record_id),
                )
                canonical_id = record_id
            else:
                cur = self._conn.execute(
                    "INSERT INTO records (project, fingerprint, message, trace, canonical_id)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (project, fp, message, trace, canonical_id),
                )
                record_id = cur.lastrowid
        return record_id, canonical_id

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
