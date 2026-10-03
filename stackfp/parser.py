"""Java 异常栈文本解析为异常树。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .errors import TraceParseError

# 位置类别：普通(文件:行号) / 本地方法 / 未知来源
POS_NORMAL = "normal"
POS_NATIVE = "native"
POS_UNKNOWN = "unknown"


@dataclass
class Frame:
    """一个栈帧。类与方法完整保留，位置只保留类别。"""

    class_method: str
    position: str  # POS_NORMAL / POS_NATIVE / POS_UNKNOWN


@dataclass
class Node:
    """异常树节点。frames 为展开后的有序帧。"""

    type: str
    message: str
    frames: List[Frame] = field(default_factory=list)
    suppressed: List["Node"] = field(default_factory=list)
    caused_by: Optional["Node"] = None


# 节点解析阶段：帧 -> 省略行 -> 抑制子节点 -> 因果子节点
_PHASE_FRAMES = 0
_PHASE_OMITTED = 1
_PHASE_SUPPRESSED = 2
_PHASE_CAUSED = 3

_FRAME_RE = re.compile(r"^at (\S+)\(([^()]*)\)$")
_OMITTED_RE = re.compile(r"^\.\.\. ([0-9]+) more$")
_POSITION_NORMAL_RE = re.compile(r"^.+:[0-9]+$")
_TYPE_RE = re.compile(r"^[^\s:]+$")

_SUPPRESSED_PREFIX = "Suppressed: "
_CAUSED_BY_PREFIX = "Caused by: "


class _Ctx:
    """解析期上下文：节点、树父节点、当前阶段。"""

    __slots__ = ("node", "parent", "phase")

    def __init__(self, node: Node, parent: Optional[Node]) -> None:
        self.node = node
        self.parent = parent
        self.phase = _PHASE_FRAMES


def normalize_text(text: str) -> List[str]:
    """CRLF->LF，去除行尾空格与制表符，忽略末尾空行。"""
    lines = [ln.rstrip(" \t") for ln in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _parse_header(text: str) -> Tuple[str, str]:
    if not text:
        raise TraceParseError("empty exception header")
    idx = text.find(":")
    if idx == -1:
        type_, message = text, ""
    else:
        type_ = text[:idx]
        message = text[idx + 1:]
        if message.startswith(" "):
            message = message[1:]
    if not _TYPE_RE.match(type_):
        raise TraceParseError(f"invalid exception type: {type_!r}")
    return type_, message


def _parse_frame(content: str) -> Frame:
    m = _FRAME_RE.match(content)
    if not m:
        raise TraceParseError(f"malformed frame line: {content!r}")
    class_method, position = m.group(1), m.group(2)
    if position == "Native Method":
        category = POS_NATIVE
    elif position == "Unknown Source":
        category = POS_UNKNOWN
    elif _POSITION_NORMAL_RE.match(position):
        category = POS_NORMAL
    else:
        raise TraceParseError(f"malformed frame position: {position!r}")
    return Frame(class_method, category)


def _set_current(current: Dict[int, _Ctx], level: int, ctx: _Ctx) -> None:
    for lv in [lv for lv in current if lv > level]:
        del current[lv]
    current[level] = ctx


def parse_trace(trace: str) -> Node:
    """解析规范化后的栈文本，返回根节点。解析失败抛 TraceParseError。"""
    lines = normalize_text(trace)
    if not lines:
        raise TraceParseError("empty trace")
    current: Dict[int, _Ctx] = {}
    root: Optional[Node] = None
    for lineno, line in enumerate(lines, 1):
        indent = len(line) - len(line.lstrip("\t"))
        content = line[indent:]
        if lineno == 1:
            if indent != 0:
                raise TraceParseError("root header must be at indent 0")
            if content.startswith((_SUPPRESSED_PREFIX, _CAUSED_BY_PREFIX)):
                raise TraceParseError("root header must not have a prefix")
            type_, message = _parse_header(content)
            root = Node(type_, message)
            current[0] = _Ctx(root, None)
            continue
        if content.startswith("at "):
            ctx = current.get(indent - 1) if indent >= 1 else None
            if ctx is None or ctx.phase != _PHASE_FRAMES:
                raise TraceParseError(f"frame out of place at line {lineno}")
            ctx.node.frames.append(_parse_frame(content))
        elif _OMITTED_RE.match(content):
            ctx = current.get(indent - 1) if indent >= 1 else None
            if ctx is None or ctx.phase != _PHASE_FRAMES:
                raise TraceParseError(f"omitted line out of place at line {lineno}")
            if ctx.parent is None:
                raise TraceParseError("root must not have an omitted line")
            n = int(_OMITTED_RE.match(content).group(1))  # type: ignore[union-attr]
            parent_frames = ctx.parent.frames
            if n > len(parent_frames):
                raise TraceParseError(
                    f"omitted count {n} exceeds parent stack length "
                    f"{len(parent_frames)} at line {lineno}"
                )
            if n:
                ctx.node.frames.extend(parent_frames[-n:])
            ctx.phase = _PHASE_OMITTED
        elif content.startswith(_SUPPRESSED_PREFIX):
            parent_ctx = current.get(indent - 1) if indent >= 1 else None
            if parent_ctx is None or parent_ctx.phase == _PHASE_CAUSED:
                raise TraceParseError(f"suppressed node out of place at line {lineno}")
            type_, message = _parse_header(content[len(_SUPPRESSED_PREFIX):])
            node = Node(type_, message)
            parent_ctx.node.suppressed.append(node)
            parent_ctx.phase = _PHASE_SUPPRESSED
            _set_current(current, indent, _Ctx(node, parent_ctx.node))
        elif content.startswith(_CAUSED_BY_PREFIX):
            parent_ctx = current.get(indent)
            if parent_ctx is None or parent_ctx.node.caused_by is not None:
                raise TraceParseError(f"caused-by node out of place at line {lineno}")
            type_, message = _parse_header(content[len(_CAUSED_BY_PREFIX):])
            node = Node(type_, message)
            parent_ctx.node.caused_by = node
            parent_ctx.phase = _PHASE_CAUSED
            _set_current(current, indent, _Ctx(node, parent_ctx.node))
        else:
            raise TraceParseError(f"unrecognized line {lineno}: {line!r}")
    assert root is not None
    return root
