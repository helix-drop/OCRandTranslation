"""FNM_RE 模块化协议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class GateReport:
    module: str
    hard: dict[str, bool] = field(default_factory=dict)
    soft: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    overrides_used: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ModuleResult(Generic[T]):
    data: T
    gate_report: GateReport
    evidence: dict[str, Any] = field(default_factory=dict)
    overrides_used: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

