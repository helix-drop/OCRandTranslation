"""开发者模式：从现有 doc 的 raw_pages.json 导入并初始化阶段记录。

不触发 OCR，不改动现有 FNM 产物表；只为 `fnm_phase_runs` 写入 6 条 idle 记录。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class ImportResult:
    ok: bool
    doc_id: str
    raw_pages_path: str
    page_count: int
    phase_runs: list[dict]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "doc_id": self.doc_id,
            "raw_pages_path": self.raw_pages_path,
            "page_count": self.page_count,
            "phase_runs": self.phase_runs,
            "error": self.error,
        }


def _fail(doc_id: str, raw_path: str, message: str) -> ImportResult:
    return ImportResult(
        ok=False,
        doc_id=doc_id,
        raw_pages_path=raw_path,
        page_count=0,
        phase_runs=[],
        error=message,
    )


def import_doc_for_dev(
    doc_id: str,
    *,
    repo,
    get_doc_dir,
    load_pages_from_disk=None,
) -> ImportResult:
    """幂等导入。

    流程：
      1. 校验 doc_id 非空
      2. 检查 doc 目录存在
      3. 检查 raw_pages.json 存在且可读
      4. 校验 page_count > 0（可选：通过 load_pages_from_disk 读一遍）
      5. `repo.init_phase_runs(doc_id)` 写入 6 条 idle 行（幂等）
      6. 返回所有 phase_runs
    """
    doc_id = (doc_id or "").strip()
    raw_path = ""
    if not doc_id:
        return _fail("", "", "doc_id 不能为空")

    try:
        doc_dir = get_doc_dir(doc_id)
    except Exception as exc:  # noqa: BLE001
        return _fail(doc_id, "", f"无法解析文档目录: {exc}")

    if not doc_dir or not os.path.isdir(doc_dir):
        return _fail(doc_id, "", f"文档目录不存在: {doc_dir}")

    raw_path = os.path.join(doc_dir, "raw_pages.json")
    if not os.path.isfile(raw_path):
        return _fail(doc_id, raw_path, "raw_pages.json 不存在，请先完成 OCR 上传流程")

    page_count = 0
    if load_pages_from_disk is not None:
        try:
            pages, _name = load_pages_from_disk(doc_id)
            page_count = len(pages or [])
        except Exception as exc:  # noqa: BLE001
            return _fail(doc_id, raw_path, f"raw_pages.json 解析失败: {exc}")
        if page_count <= 0:
            return _fail(doc_id, raw_path, "raw_pages.json 页数为 0")
    else:
        # 仅校验文件大小
        try:
            if os.path.getsize(raw_path) <= 2:
                return _fail(doc_id, raw_path, "raw_pages.json 为空")
        except OSError as exc:
            return _fail(doc_id, raw_path, f"raw_pages.json 读取失败: {exc}")

    try:
        phase_runs = repo.init_phase_runs(doc_id)
    except Exception as exc:  # noqa: BLE001
        return _fail(doc_id, raw_path, f"初始化 fnm_phase_runs 失败: {exc}")

    return ImportResult(
        ok=True,
        doc_id=doc_id,
        raw_pages_path=raw_path,
        page_count=page_count,
        phase_runs=phase_runs,
        error=None,
    )
