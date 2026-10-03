"""规范结果序列化与 SHA-256 指纹。"""

from __future__ import annotations

import hashlib
from typing import List, Tuple

from .parser import Node, normalize_text, parse_trace

_FORMAT_TAG = "stackfp/1"


def _normalize_message(message: str) -> str:
    return "\n".join(normalize_text(message))


def _serialize(message: str, root: Node) -> bytes:
    """把规范结果写成无歧界的字节串（netstring 风格），迭代实现不限深度。"""
    out = bytearray()

    def put_str(s: str) -> None:
        b = s.encode("utf-8")
        out.extend(str(len(b)).encode("ascii"))
        out.extend(b":")
        out.extend(b)

    def put_int(i: int) -> None:
        out.extend(str(i).encode("ascii"))
        out.extend(b";")

    put_str(_FORMAT_TAG)
    put_str(message)
    # 任务栈：("node", node) 序列化一个节点；("flag", bool) 写因果标记
    tasks: List[Tuple[str, object]] = [("node", root)]
    while tasks:
        kind, payload = tasks.pop()
        if kind == "flag":
            put_int(1 if payload else 0)
            continue
        node = payload  # type: Node
        put_str(node.type)
        put_str(node.message)
        put_int(len(node.frames))
        for frame in node.frames:
            put_str(frame.class_method)
            put_str(frame.position)
        put_int(len(node.suppressed))
        if node.caused_by is not None:
            tasks.append(("node", node.caused_by))
        tasks.append(("flag", node.caused_by is not None))
        for child in reversed(node.suppressed):
            tasks.append(("node", child))
    return bytes(out)


def fingerprint(message: str, trace: str) -> str:
    """对 (message, trace) 计算 SHA-256 指纹（十六进制字符串）。"""
    root = parse_trace(trace)
    canonical = _serialize(_normalize_message(message), root)
    return hashlib.sha256(canonical).hexdigest()
