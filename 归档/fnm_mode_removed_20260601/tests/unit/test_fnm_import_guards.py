#!/usr/bin/env python3
"""导入守卫：主仓运行代码与现行测试禁止静态导入 legacy 链路。

legacy 链路当前指仓库根 `legacy/`（已 gitignore，仅本地保留）下的旧 FNM 实现。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _is_executable_python_file(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    rel_path = path.relative_to(REPO_ROOT)
    if any(part.startswith(".") for part in rel_path.parts):
        return False
    if "__pycache__" in path.parts:
        return False
    if _is_under_legacy_archive(path):
        return False
    return True


def _is_under_legacy_archive(path: Path) -> bool:
    rel_path = path.relative_to(REPO_ROOT)
    if not rel_path.parts:
        return False
    return rel_path.parts[0] in {"legacy", "归档"}


_LEGACY_MODULE_PREFIXES = ("fnm", "legacy")


def _is_legacy_module(module: str) -> bool:
    if not module:
        return False
    head = module.split(".", 1)[0]
    return head in _LEGACY_MODULE_PREFIXES


def _find_legacy_import_violations(path: Path) -> list[tuple[int, str]]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_legacy_module(alias.name):
                    lineno = int(node.lineno or 0)
                    stmt = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else f"import {alias.name}"
                    violations.append((lineno, stmt))
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            if node.level == 0 and _is_legacy_module(module):
                lineno = int(node.lineno or 0)
                stmt = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else f"from {module} import ..."
                violations.append((lineno, stmt))

    return violations


class FnmImportGuardTest(unittest.TestCase):
    def test_executable_python_files_must_respect_legacy_archive_boundary(self):
        scanned_files = 0
        violations: list[str] = []

        for path in sorted(REPO_ROOT.rglob("*.py")):
            if not _is_executable_python_file(path):
                continue
            scanned_files += 1
            for lineno, statement in _find_legacy_import_violations(path):
                rel_path = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_path}:{lineno}: {statement}")

        self.assertGreater(scanned_files, 0, msg="未扫描到可执行 .py 文件，请检查导入守卫测试范围。")
        self.assertFalse(
            violations,
            msg=(
                "检测到 legacy 归档边界违规（主仓禁止静态导入 fnm.* 或 legacy.*）：\n"
                + "\n".join(f"- {entry}" for entry in violations)
            ),
        )


if __name__ == "__main__":
    unittest.main()
