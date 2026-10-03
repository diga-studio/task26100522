"""把 Java 异常栈文本解析为异常树。"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .model import Frame, LocationKind, Node


class TraceParseError(ValueError):
    """栈文本不符合规范格式。"""


_HEADER_RE = re.compile(r"^([^\s:]+)(?:: (.*))?$")
_FRAME_RE = re.compile(r"^at (.+)\.([^.]+)\(([^()]*)\)$")
_OMITTED_RE = re.compile(r"^\.\.\. (\d+) more$")
_SOURCE_LOCATION_RE = re.compile(r"^.+:\d+$")

# 节点内容阶段：帧 -> 省略行 -> 抑制子节点 -> 因果子节点
_FRAMES, _OMITTED, _SUPPRESSED, _CAUSED = range(4)


def normalize_text(text: str) -> List[str]:
    """CRLF 归一为 LF，去行尾空格/制表符，去掉末尾空行。"""
    text = text.replace("\r\n", "\n")
    lines = [line.rstrip(" \t") for line in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def normalize_message(message: str) -> str:
    return "\n".join(normalize_text(message))


def _parse_header(content: str) -> Tuple[str, str]:
    m = _HEADER_RE.match(content)
    if not m:
        raise TraceParseError(f"非法异常头: {content!r}")
    return m.group(1), (m.group(2) or "")


def _parse_frame(content: str) -> Frame:
    m = _FRAME_RE.match(content)
    if not m:
        raise TraceParseError(f"非法帧行: {content!r}")
    class_name, method_name, location = m.groups()
    if location == "Native Method":
        kind = LocationKind.NATIVE
    elif location == "Unknown Source":
        kind = LocationKind.UNKNOWN
    elif _SOURCE_LOCATION_RE.match(location):
        kind = LocationKind.SOURCE
    else:
        raise TraceParseError(f"非法帧位置: {location!r}")
    return Frame(class_name, method_name, kind)


def parse_trace(trace: str) -> Node:
    """解析整条栈文本，返回根节点（帧已展开）。格式非法时抛 TraceParseError。"""
    lines = normalize_text(trace)
    if not lines:
        raise TraceParseError("空栈")

    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip("\t"))

    if indent_of(lines[0]) != 0 or lines[0].startswith(("at ", "Suppressed: ", "Caused by: ")):
        raise TraceParseError("首行必须是根异常头")
    type_name, message = _parse_header(lines[0])
    root = Node(type_name, message)

    # stack[level] = 该层级当前打开的节点；phase 记录每个节点的内容阶段
    stack: List[Node] = [root]
    phase: Dict[int, int] = {id(root): _FRAMES}
    omitted: Dict[int, int] = {}       # id(node) -> N

    for line in lines[1:]:
        indent = indent_of(line)
        content = line[indent:]

        if content.startswith("at "):
            if indent < 1 or indent > len(stack):
                raise TraceParseError(f"帧缩进非法: {line!r}")
            node = stack[indent - 1]
            if phase[id(node)] != _FRAMES:
                raise TraceParseError(f"帧出现在非法位置: {line!r}")
            node.frames.append(_parse_frame(content))
            del stack[indent:]
        elif _OMITTED_RE.match(content):
            if indent < 1 or indent > len(stack):
                raise TraceParseError(f"省略行缩进非法: {line!r}")
            node = stack[indent - 1]
            if node is root:
                raise TraceParseError("根异常不允许省略行")
            if phase[id(node)] != _FRAMES:
                raise TraceParseError(f"省略行出现在非法位置: {line!r}")
            omitted[id(node)] = int(_OMITTED_RE.match(content).group(1))
            phase[id(node)] = _OMITTED
            del stack[indent:]
        elif content.startswith("Suppressed: "):
            if indent < 1 or indent > len(stack):
                raise TraceParseError(f"抑制子节点缩进非法: {line!r}")
            parent = stack[indent - 1]
            if phase[id(parent)] > _SUPPRESSED:
                raise TraceParseError(f"抑制子节点出现在非法位置: {line!r}")
            type_name, message = _parse_header(content[len("Suppressed: "):])
            child = Node(type_name, message)
            parent.suppressed.append(child)
            phase[id(parent)] = _SUPPRESSED
            phase[id(child)] = _FRAMES
            del stack[indent:]
            stack.append(child)
        elif content.startswith("Caused by: "):
            if indent > len(stack) - 1:
                raise TraceParseError(f"因果子节点缩进非法: {line!r}")
            parent = stack[indent]
            if phase[id(parent)] > _SUPPRESSED:
                raise TraceParseError(f"因果子节点出现在非法位置: {line!r}")
            type_name, message = _parse_header(content[len("Caused by: "):])
            child = Node(type_name, message)
            parent.cause = child
            phase[id(parent)] = _CAUSED
            phase[id(child)] = _FRAMES
            del stack[indent:]
            stack.append(child)
        else:
            raise TraceParseError(f"无法识别的行: {line!r}")

    _expand_omitted(root, omitted)
    return root


def _expand_omitted(root: Node, omitted: Dict[int, int]) -> None:
    """把每个节点的省略行展开：接上树父节点已展开栈的最后 N 帧。"""
    # 迭代 DFS：弹出节点时其父节点的 frames 已展开完毕
    todo: List[Tuple[Node, Optional[Node]]] = [(root, None)]
    while todo:
        node, parent = todo.pop()
        n = omitted.get(id(node))
        if n is not None:
            assert parent is not None  # 根不允许省略，解析时已拒绝
            if n > len(parent.frames):
                raise TraceParseError(f"省略行 N={n} 超过父栈长度 {len(parent.frames)}")
            node.frames = node.frames + parent.frames[len(parent.frames) - n:]
        for child in reversed(node.suppressed):
            todo.append((child, node))
        if node.cause is not None:
            todo.append((node.cause, node))
