"""文档管理辅助函数。"""

from __future__ import annotations

import logging
import os

from flask import flash, redirect, url_for

import config
import translation.translate_runtime as translate_runtime

logger = logging.getLogger(__name__)


def guard_doc_delete(doc_id: str):
    if not doc_id:
        flash("暂无可删除的文档", "error")
        return redirect(url_for("home"))
    if translate_runtime.is_translate_running(doc_id):
        flash("该文档正在翻译中，请先停止翻译后再删除。", "error")
        return redirect(url_for("home", doc_id=doc_id))
    return None


def delete_doc_with_verification(doc_id: str) -> bool:
    doc_dir = config.get_doc_dir(doc_id)
    try:
        config.delete_doc(doc_id)
    except Exception:
        logger.exception("删除文档失败 doc_id=%s", doc_id)
        return False
    return not (doc_dir and os.path.isdir(doc_dir))
