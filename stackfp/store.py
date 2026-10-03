"""SQLite 持久化与缺陷归并。"""

from __future__ import annotations

import sqlite3
from typing import NamedTuple

from .fingerprint import fingerprint

MAX_TRACE_BYTES = 50 * 1024


class IngestResult(NamedTuple):
    record_id: int
    canonical_id: int


class Store:
    """按 (project, fingerprint) 归并缺陷记录的 SQLite 存储。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                message TEXT NOT NULL,
                trace TEXT NOT NULL,
                canonical_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS canonicals (
                project TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                canonical_id INTEGER NOT NULL,
                PRIMARY KEY (project, fingerprint)
            );
            """
        )
        self._conn.commit()

    def ingest(self, project: str, message: str, trace: str) -> IngestResult:
        """写入一条记录并返回 (record_id, canonical_id)。"""
        if len(trace.encode("utf-8")) > MAX_TRACE_BYTES:
            raise ValueError("trace exceeds 50 KiB limit")
        fp = fingerprint(message, trace)
        with self._conn:
            row = self._conn.execute(
                "SELECT canonical_id FROM canonicals WHERE project = ? AND fingerprint = ?",
                (project, fp),
            ).fetchone()
            if row is not None:
                canonical_id = row[0]
            else:
                canonical_id = None
            cur = self._conn.execute(
                "INSERT INTO records (project, fingerprint, message, trace, canonical_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (project, fp, message, trace, canonical_id if canonical_id is not None else -1),
            )
            record_id = cur.lastrowid
            if canonical_id is None:
                canonical_id = record_id
                self._conn.execute(
                    "UPDATE records SET canonical_id = ? WHERE id = ?",
                    (canonical_id, record_id),
                )
                self._conn.execute(
                    "INSERT INTO canonicals (project, fingerprint, canonical_id)"
                    " VALUES (?, ?, ?)",
                    (project, fp, canonical_id),
                )
        return IngestResult(record_id, canonical_id)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
