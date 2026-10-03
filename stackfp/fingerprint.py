"""规范序列化与 SHA-256 指纹。"""
from __future__ import annotations

import hashlib
import struct
from typing import List

from .model import Frame, LocationKind, Node
from .parser import normalize_message, parse_trace

_LOCATION_TAG = {
    LocationKind.SOURCE: b"\x01",
    LocationKind.NATIVE: b"\x02",
    LocationKind.UNKNOWN: b"\x03",
}


def _field(out: List[bytes], data: bytes) -> None:
    """长度前缀字段：8 字节大端长度 + 内容，边界无歧义。"""
    out.append(struct.pack(">Q", len(data)))
    out.append(data)


def _text(out: List[bytes], s: str) -> None:
    _field(out, s.encode("utf-8"))


def _frame(out: List[bytes], frame: Frame) -> None:
    _text(out, frame.class_name)
    _text(out, frame.method_name)
    _field(out, _LOCATION_TAG[frame.location])


def canonical_bytes(message: str, root: Node) -> bytes:
    """把 message 与异常树序列化为边界无歧义的字节流（迭代遍历）。"""
    out: List[bytes] = []
    _text(out, normalize_message(message))
    # 显式记录树结构：子节点数量，绝不展平
    stack: List[Node] = [root]
    while stack:
        node = stack.pop()
        _text(out, node.type_name)
        _text(out, node.message)
        _field(out, struct.pack(">Q", len(node.frames)))
        for frame in node.frames:
            _frame(out, frame)
        _field(out, struct.pack(">Q", len(node.suppressed)))
        # 因果子节点先压栈，弹出顺序：抑制子节点（声明序）-> 因果子节点
        if node.cause is not None:
            out.append(b"\x01")
            stack.append(node.cause)
        else:
            out.append(b"\x00")
        for child in reversed(node.suppressed):
            stack.append(child)
    return b"".join(out)


def fingerprint(message: str, trace: str) -> str:
    """计算 (message, trace) 的 SHA-256 指纹（十六进制）。"""
    root = parse_trace(trace)
    return hashlib.sha256(canonical_bytes(message, root)).hexdigest()
