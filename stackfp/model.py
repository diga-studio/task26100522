"""数据模型：异常树与帧。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class LocationKind(Enum):
    SOURCE = "source"          # 文件:行号
    NATIVE = "native"          # Native Method
    UNKNOWN = "unknown"        # Unknown Source


@dataclass(frozen=True)
class Frame:
    class_name: str
    method_name: str
    location: LocationKind


@dataclass
class Node:
    type_name: str
    message: str
    frames: List[Frame] = field(default_factory=list)  # 展开后的有序帧
    suppressed: List["Node"] = field(default_factory=list)
    cause: Optional["Node"] = None
