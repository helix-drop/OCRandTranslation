"""FNM_RE 第七阶段：doc/repo-aware 主线接线层。"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from FNM_RE.app.mainline_repo import (
    _normalize_unit_id,
    _paragraph_record_from_payload,
    _repo_body_anchor_record,
    _repo_chapter_note_mode_record,
    _repo_chapter_record,
    _repo_note_item_record,
    _repo_note_link_record,
    _repo_note_region_record,
    _repo_section_head_record,
    _repo_structure_review_record,
    _segment_record_from_payload,
    _serialize_structure_reviews,
    _serialize_units_for_repo,
)
from FNM_RE.app.pipeline import build_module_pipeline_snapshot
from FNM_RE.constants import is_valid_pipeline_state
from FNM_RE.shared.review_overrides import group_review_overrides as _group_review_overrides
from FNM_RE.models import (
    BodyAnchorRecord,
    ChapterNoteModeRecord,
    ChapterRecord,
    ExportBundleRecord,
    ExportChapterRecord,
    NoteItemRecord,
    NoteLinkRecord,
    NoteRegionRecord,
    Phase4Structure,
    Phase5Structure,
    Phase6Structure,
    Phase6Summary,
    SectionHeadRecord,
    StructureReviewRecord,
    StructureStatusRecord,
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)
from persistence.fnm_export_bundle import (
    clear_fnm_export_bundle,
    load_fnm_export_bundle,
    save_fnm_export_bundle,
)
from FNM_RE.app.persist_helpers import (
    _safe_list,
    load_fnm_visual_toc_bundle as _load_fnm_visual_toc_bundle,
    load_fnm_toc_items as _load_fnm_toc_items,
    normalize_marker as _normalize_marker,
    serialize_chapter_note_modes_for_repo as _serialize_chapter_note_modes_for_repo,
    serialize_heading_candidates_for_repo as _serialize_heading_candidates_for_repo,
    serialize_note_items_for_repo as _serialize_note_items_for_repo,
    serialize_note_regions_for_repo as _serialize_note_regions_for_repo,
    serialize_pages_for_repo as _serialize_pages_for_repo,
    serialize_section_heads_for_repo as _serialize_section_heads_for_repo,
    to_plain as _to_plain,
)
from FNM_RE.stages.diagnostics import build_diagnostic_projection
from FNM_RE.stages.export import build_export_zip
from FNM_RE.stages.export_audit import audit_phase6_export
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import get_pdf_path, get_translate_args
from persistence.storage_toc import load_toc_visual_manual_inputs

_EMPTY_ROLE_SUMMARY = {
    "container": 0,
    "chapter": 0,
    "section": 0,
    "post_body": 0,
    "back_matter": 0,
    "front_matter": 0,
}
_EXPORT_VALIDATION_LOG_PATH = "logs/fnm_export_validation_issues.log"
_EXPORT_STAGE_REASON_PREFIXES = ("merge_", "export_")
_EXPORT_STAGE_REASON_EXACT = {"local_note_contract_broken"}
_MISSING_PERSISTED_EXPORT_BUNDLE_MESSAGE = "FNM 导出包不存在，请先执行最终校验。"


def _safe_dict(callable_obj: Any, *args) -> dict[str, Any]:
    if not callable(callable_obj):
        return {}
    value = callable_obj(*args)
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _safe_json_loads(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _resolve_manual_toc_state(doc_id: str) -> tuple[bool, dict[str, Any]]:
    inputs = load_toc_visual_manual_inputs(doc_id) if doc_id else {}
    mode = str((inputs or {}).get("mode") or "").strip().lower()
    pdf_path = str((inputs or {}).get("pdf_path") or "").strip()
    image_paths = [
        str(path or "").strip()
        for path in (inputs or {}).get("image_paths") or []
        if str(path or "").strip()
    ]
    page_count = int((inputs or {}).get("page_count") or 0)
    if page_count <= 0:
        if mode == "manual_pdf" and pdf_path:
            page_count = 1
        elif mode == "manual_images":
            page_count = len(image_paths)
    source_name = str((inputs or {}).get("source_name") or "").strip()
    manual_toc_ready = False
    if mode == "manual_pdf":
        manual_toc_ready = bool(pdf_path and page_count > 0)
    elif mode == "manual_images":
        manual_toc_ready = bool(image_paths)
    summary = {
        "mode": mode,
        "page_count": int(max(0, page_count)),
        "file_count": 1 if mode == "manual_pdf" and pdf_path else len(image_paths),
        "image_count": len(image_paths),
        "source_name": source_name,
    }
    return manual_toc_ready, summary


def _summarize_book_audit(
    *,
    slug: str,
    doc_id: str,
    zip_path: str,
    structure_state: str,
    blocking_reasons: list[str],
    manual_toc_summary: dict[str, Any],
    toc_role_summary: dict[str, Any],
    chapter_titles: list[str],
    file_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    now = int(time.time())
    blocking_files = [row for row in file_reports if str(row.get("severity") or "") == "blocking"]
    major_files = [row for row in file_reports if str(row.get("severity") or "") == "major"]
    issue_counts: dict[str, int] = {}
    for row in file_reports:
        for code in list(row.get("issue_codes") or []):
            token = str(code or "").strip()
            if not token:
                continue
            issue_counts[token] = issue_counts.get(token, 0) + 1
    recommended_followups = [
        {"issue_code": code, "count": count}
        for code, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]
    return {
        "slug": str(slug or "").strip(),
        "doc_id": str(doc_id or "").strip(),
        "zip_path": str(zip_path or "").strip(),
        "audit_started_at": now,
        "audit_finished_at": now,
        "structure_state": str(structure_state or "").strip(),
        "blocking_reasons": [str(item).strip() for item in (blocking_reasons or []) if str(item).strip()],
        "manual_toc_summary": dict(manual_toc_summary or {}),
        "toc_role_summary": dict(toc_role_summary or {}),
        "chapter_titles": list(chapter_titles or []),
        "files": file_reports,
        "blocking_issue_count": len(blocking_files),
        "major_issue_count": len(major_files),
        "can_ship": len(blocking_files) == 0,
        "must_fix_before_next_book": [
            {
                "path": str(row.get("path") or ""),
                "issue_codes": list(row.get("issue_codes") or []),
            }
            for row in blocking_files
        ],
        "recommended_followups": recommended_followups,
    }


def _infer_max_body_chars(model_key: str) -> int:
    lowered = str(model_key or "").strip().lower()
    if lowered.startswith("qwen-"):
        return 24000
    if lowered.startswith("deepseek-"):
        return 18000
    return 12000


def _effective_max_body_chars(explicit_value: int | None) -> int:
    if explicit_value is not None:
        return max(2000, int(explicit_value))
    model_key = str(get_translate_args().get("model_key") or "")
    return _infer_max_body_chars(model_key)


def _is_export_stage_reason(reason_code: str) -> bool:
    token = str(reason_code or "").strip()
    if not token:
        return False
    if token in _EXPORT_STAGE_REASON_EXACT:
        return True
    return token.startswith(_EXPORT_STAGE_REASON_PREFIXES)


def _format_issue_page_span(page_span: list[int]) -> str:
    pages = [int(page_no) for page_no in list(page_span or []) if int(page_no) > 0]
    if not pages:
        return "-"
    if len(pages) == 1:
        return f"p.{pages[0]}"
    start = int(pages[0])
    end = int(pages[1])
    if end <= 0:
        end = start
    if start == end:
        return f"p.{start}"
    return f"p.{start}-{end}"


def _tail_translation_issue_payloads(
    doc_id: str,
    *,
    repo: SQLiteRepository | None = None,
    snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from FNM_RE.page_translate import build_retry_summary

    summary = build_retry_summary(doc_id, repo=repo, snapshot=snapshot)
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, str]] = set()
    for row in list(summary.get("manual_required_locations") or []) + list(summary.get("failed_locations") or []):
        if not isinstance(row, dict):
            continue
        unit_id = str(row.get("unit_id") or "").strip()
        page_no = int(row.get("page_no") or 0)
        para_idx = int(row.get("para_idx") or 0)
        status = str(row.get("status") or "").strip() or "failed"
        key = (unit_id, page_no, para_idx, status)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            {
                "unit_id": unit_id,
                "section_title": str(row.get("section_title") or "").strip(),
                "page_no": page_no,
                "para_idx": para_idx,
                "paragraph_label": para_idx + 1 if para_idx >= 0 else 0,
                "status": status,
                "error": str(row.get("error") or "").strip(),
            }
        )
    return issues


def _tail_blocking_summary(
    *,
    translation_blockers: list[dict[str, Any]],
    export_blocking_reasons: list[str],
) -> list[str]:
    summary: list[str] = []
    for row in translation_blockers:
        page_no = int(row.get("page_no") or 0)
        para_label = int(row.get("paragraph_label") or 0)
        status = str(row.get("status") or "failed").strip() or "failed"
        unit_id = str(row.get("unit_id") or "").strip()
        if page_no > 0 and para_label > 0:
            summary.append(f"{status}:p.{page_no} ¶{para_label} ({unit_id or 'unit'})")
        elif page_no > 0:
            summary.append(f"{status}:p.{page_no} ({unit_id or 'unit'})")
        else:
            summary.append(f"{status}:{unit_id or 'unknown_unit'}")
    for reason in export_blocking_reasons:
        token = str(reason or "").strip()
        if token:
            summary.append(token)
    return summary[:16]


def _build_export_validation_log(
    *,
    doc_id: str,
    phase6: Phase6Structure | None = None,
    run: dict[str, Any] | None = None,
) -> str:
    run = dict(run or {})
    if not run:
        repo = SQLiteRepository()
        run = _safe_dict(getattr(repo, "get_latest_fnm_run", None), doc_id)
    run_validation = _safe_json_loads(run.get("validation_json"))
    post_translate_export_check = dict(run_validation.get("post_translate_export_check") or {})
    translation_blockers = [
        dict(item or {})
        for item in list(post_translate_export_check.get("translation_blockers") or [])
        if isinstance(item, dict)
    ]
    translation_attempt_history = [
        dict(item or {})
        for item in list(post_translate_export_check.get("translation_attempt_history") or [])
        if isinstance(item, dict)
    ]
    if phase6 is not None:
        status = phase6.status or StructureStatusRecord(structure_state="idle")
        structure_state = str(status.structure_state or "").strip()
        export_stage_reasons = [
            str(reason).strip()
            for reason in list(status.blocking_reasons or [])
            if _is_export_stage_reason(str(reason))
        ]
        audit_files = [
            _phase6_file_issue_payload(row)
            for row in list((phase6.export_audit.files if phase6.export_audit else []) or [])
            if list(getattr(row, "issue_codes", []) or [])
            and str(getattr(row, "severity", "") or "").strip().lower() in {"blocking", "major"}
        ]
    else:
        structure_state = str(run.get("structure_state") or "").strip()
        export_stage_reasons = [
            str(reason).strip()
            for reason in list(run_validation.get("blocking_reasons") or [])
            if _is_export_stage_reason(str(reason))
        ]
        audit_files = [
            dict(row or {})
            for row in list(post_translate_export_check.get("final_blocking_files") or [])
            if isinstance(row, dict)
            and list(row.get("issue_codes") or [])
            and str(row.get("severity") or "").strip().lower() in {"blocking", "major"}
        ]
    if not export_stage_reasons and not audit_files and not translation_blockers:
        return ""

    lines = [
        "FNM 导出校验问题日志",
        f"doc_id: {str(doc_id or '').strip()}",
        f"structure_state: {structure_state}",
        "",
    ]
    if export_stage_reasons:
        lines.append("阻塞原因（导出阶段）:")
        for reason in export_stage_reasons:
            lines.append(f"- {reason}")
        lines.append("")

    if translation_blockers:
        lines.append("翻译补救后仍未解决:")
        for row in translation_blockers:
            page_no = int(row.get("page_no") or 0)
            para_label = int(row.get("paragraph_label") or 0)
            status = str(row.get("status") or "failed").strip() or "failed"
            unit_id = str(row.get("unit_id") or "").strip() or "-"
            section_title = str(row.get("section_title") or "").strip() or "-"
            lines.append(
                f"- 页面: {'p.' + str(page_no) if page_no > 0 else '-'} | 段落: {para_label if para_label > 0 else '-'} | unit_id: {unit_id} | 状态: {status} | 章节: {section_title}"
            )
            error = str(row.get("error") or "").strip()
            if error:
                lines.append(f"  原因: {error}")
        lines.append("")

    if translation_attempt_history:
        lines.append("翻译模型尝试记录:")
        for row in translation_attempt_history:
            round_no = int(row.get("round") or 0)
            unit_id = str(row.get("unit_id") or "").strip() or "-"
            model_label = str(row.get("model_label") or row.get("model_id") or row.get("model_key") or "-").strip()
            provider = str(row.get("provider") or "").strip() or "-"
            result = str(row.get("result") or "").strip() or "-"
            page_start = int(row.get("page_start") or 0)
            page_end = int(row.get("page_end") or page_start or 0)
            page_text = _format_issue_page_span([page_start, page_end]) if page_start > 0 else "-"
            lines.append(
                f"- 第 {round_no} 轮 | 页面: {page_text} | unit_id: {unit_id} | 模型: {model_label} | provider: {provider} | 结果: {result}"
            )
            error = str(row.get("error") or "").strip()
            if error:
                lines.append(f"  原因: {error}")
        lines.append("")

    if audit_files:
        lines.append("校验失败明细:")
        for row in audit_files:
            path = str(row.get("path") or "").strip()
            title = str(row.get("title") or "").strip()
            severity = str(row.get("severity") or "").strip().lower() or "unknown"
            issue_codes = [str(code).strip() for code in list(row.get("issue_codes") or []) if str(code).strip()]
            issue_summary = [str(item).strip() for item in list(row.get("issue_summary") or []) if str(item).strip()]
            issue_details = [
                dict(item or {})
                for item in list(row.get("issue_details") or [])
                if isinstance(item, dict)
            ]
            lines.append(
                f"- 路径: {path or '-'} | 标题: {title or '-'} | 页码: {_format_issue_page_span(list(row.get('page_span') or []))} | 级别: {severity}"
            )
            if issue_codes:
                lines.append(f"  原因代码: {', '.join(issue_codes)}")
            for summary in issue_summary:
                lines.append(f"  详情: {summary}")
            for detail in issue_details[:6]:
                code = str(detail.get("code") or "").strip() or "-"
                paragraph_index = int(detail.get("paragraph_index") or 0)
                paragraph_label = str(paragraph_index) if paragraph_index > 0 else "-"
                detail_text = str(detail.get("detail") or "").strip() or code
                lines.append(f"  定位: code={code} | 段落={paragraph_label} | {detail_text}")
                excerpt = str(detail.get("excerpt") or "").strip()
                if excerpt:
                    lines.append(f"  片段: {excerpt}")
        lines.append("")

    repair_rounds = [
        dict(item or {})
        for item in list(post_translate_export_check.get("repair_rounds") or [])
        if isinstance(item, dict)
    ]
    if repair_rounds:
        lines.append("自动修补记录:")
        for row in repair_rounds:
            round_no = int(row.get("round") or 0)
            error = str(row.get("error") or "").strip()
            if error:
                lines.append(f"- 第 {round_no} 轮: 调用失败 | error={error}")
                continue
            auto_applied_count = int(row.get("auto_applied_count") or 0)
            suggestion_count = int(row.get("suggestion_count") or 0)
            can_ship = bool(row.get("post_round_can_ship"))
            lines.append(
                f"- 第 {round_no} 轮: suggestion={suggestion_count} | auto_applied={auto_applied_count} | 结果={'通过' if can_ship else '仍阻塞'}"
            )
            auto_action_counts = {
                str(key): int(value)
                for key, value in dict(row.get("auto_action_counts") or {}).items()
                if str(key).strip()
            }
            model_attempts = [
                dict(item or {})
                for item in list(row.get("model_attempts") or [])
                if isinstance(item, dict)
            ]
            for attempt in model_attempts:
                lines.append(
                    "  模型尝试: "
                    + f"{str(attempt.get('model_label') or attempt.get('model_id') or '-').strip()} "
                    + f"| provider={str(attempt.get('provider') or '-').strip()} "
                    + f"| result={str(attempt.get('result') or '-').strip()}"
                )
                attempt_error = str(attempt.get("error") or "").strip()
                if attempt_error:
                    lines.append(f"    error: {attempt_error}")
            if auto_action_counts:
                action_summary = ", ".join(
                    f"{key}={value}"
                    for key, value in sorted(auto_action_counts.items(), key=lambda item: item[0])
                )
                lines.append(f"  自动应用: {action_summary}")
            blocking_reasons_after = [
                str(reason).strip()
                for reason in list(row.get("post_round_blocking_reasons") or [])
                if str(reason).strip()
            ]
            if blocking_reasons_after and not can_ship:
                lines.append(f"  仍阻塞: {', '.join(blocking_reasons_after[:8])}")
        lines.append("")

    return "\n".join(lines).strip()


def _bundle_with_export_validation_log(
    bundle: ExportBundleRecord,
    *,
    phase6: Phase6Structure | None = None,
    doc_id: str,
    run: dict[str, Any] | None = None,
) -> ExportBundleRecord:
    log_text = _build_export_validation_log(doc_id=doc_id, phase6=phase6, run=run)
    if not log_text:
        return bundle
    files = dict(bundle.files or {})
    files[_EXPORT_VALIDATION_LOG_PATH] = log_text
    return replace(bundle, files=files)


def _phase6_file_issue_payload(row: Any) -> dict[str, Any]:
    return {
        "path": str(getattr(row, "path", "") or ""),
        "title": str(getattr(row, "title", "") or ""),
        "page_span": [int(page_no) for page_no in list(getattr(row, "page_span", []) or []) if int(page_no) > 0],
        "issue_codes": [str(code).strip() for code in list(getattr(row, "issue_codes", []) or []) if str(code).strip()],
        "issue_summary": [str(item).strip() for item in list(getattr(row, "issue_summary", []) or []) if str(item).strip()],
        "issue_details": [
            dict(item or {})
            for item in list(getattr(row, "issue_details", []) or [])
            if isinstance(item, dict)
        ],
        "severity": str(getattr(row, "severity", "") or ""),
    }


def _phase6_blocking_file_payloads(phase6: Phase6Structure) -> list[dict[str, Any]]:
    return [
        _phase6_file_issue_payload(row)
        for row in list((phase6.export_audit.files if phase6.export_audit else []) or [])
        if str(getattr(row, "severity", "") or "").strip().lower() == "blocking"
    ]


def _update_latest_fnm_run_from_phase6(
    doc_id: str,
    phase6: Phase6Structure,
    *,
    repo: SQLiteRepository,
    validation_extra: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    status_payload = _status_payload(
        status=phase6.status,
        summary=phase6.summary,
        run_validation=None,
    )
    latest_run = _safe_dict(getattr(repo, "get_latest_fnm_run", None), doc_id)
    validation_payload = _safe_json_loads(latest_run.get("validation_json"))
    validation_payload.update(_build_validation_payload(status_payload))
    if validation_extra:
        validation_payload.update(dict(validation_extra))

    run_id = int(latest_run.get("id") or 0)
    page_count = len(list(phase6.pages or []))
    section_count = len(list(phase6.chapters or []))
    note_count = len(list(phase6.note_items or []))
    unit_count = len(list(phase6.translation_units or []))
    if run_id <= 0:
        run_id = int(
            getattr(repo, "create_fnm_run")(
                doc_id,
                status="done",
                page_count=page_count,
                section_count=section_count,
                note_count=note_count,
                unit_count=unit_count,
                structure_state=str(status_payload.get("structure_state") or "ready"),
                review_counts=dict(status_payload.get("review_counts") or {}),
                blocking_reasons=list(status_payload.get("blocking_reasons") or []),
                link_summary=dict(status_payload.get("link_summary") or {}),
                page_partition_summary=dict(status_payload.get("page_partition_summary") or {}),
                chapter_mode_summary=dict(status_payload.get("chapter_mode_summary") or {}),
            )
        )

    repo.update_fnm_run(
        doc_id,
        run_id,
        status="done",
        error_msg="",
        page_count=page_count,
        section_count=section_count,
        note_count=note_count,
        unit_count=unit_count,
        validation_json=json.dumps(validation_payload, ensure_ascii=False),
        structure_state=str(status_payload.get("structure_state") or "ready"),
        review_counts=dict(status_payload.get("review_counts") or {}),
        blocking_reasons=list(status_payload.get("blocking_reasons") or []),
        link_summary=dict(status_payload.get("link_summary") or {}),
        page_partition_summary=dict(status_payload.get("page_partition_summary") or {}),
        chapter_mode_summary=dict(status_payload.get("chapter_mode_summary") or {}),
    )
    return run_id, status_payload, validation_payload


def _phase_state_from_run(run: dict[str, Any]) -> str:
    if not run:
        return "idle"
    status = str(run.get("status") or "").strip().lower()
    if status in {"pending", "running"}:
        return "running"
    if status == "error":
        return "error"
    return "done"



def _export_bundle_payload(phase6: Phase6Structure) -> dict[str, Any]:
    bundle = phase6.export_bundle
    return {
        "index_path": str(bundle.index_path or "index.md"),
        "chapters_dir": str(bundle.chapters_dir or "chapters"),
        "chapters": [
            {
                "order": int(chapter.order or 0),
                "section_id": str(chapter.section_id or ""),
                "title": str(chapter.title or ""),
                "path": str(chapter.path or ""),
            }
            for chapter in bundle.chapters
        ],
        "chapter_files": dict(bundle.chapter_files or {}),
        "files": dict(bundle.files or {}),
        "export_semantic_contract_ok": bool(bundle.export_semantic_contract_ok),
        "front_matter_leak_detected": bool(bundle.front_matter_leak_detected),
        "toc_residue_detected": bool(bundle.toc_residue_detected),
        "mid_paragraph_heading_detected": bool(bundle.mid_paragraph_heading_detected),
        "duplicate_paragraph_detected": bool(bundle.duplicate_paragraph_detected),
    }


def _export_bundle_record_from_payload(payload: dict[str, Any]) -> ExportBundleRecord:
    chapter_files = {
        str(path): str(content or "")
        for path, content in dict(payload.get("chapter_files") or {}).items()
        if str(path).strip()
    }
    files = {
        str(path): str(content or "")
        for path, content in dict(payload.get("files") or {}).items()
        if str(path).strip()
    }
    chapters: list[ExportChapterRecord] = []
    for raw_row in list(payload.get("chapters") or []):
        if not isinstance(raw_row, dict):
            continue
        path = str(raw_row.get("path") or "").strip()
        if not path:
            continue
        chapters.append(
            ExportChapterRecord(
                order=int(raw_row.get("order") or 0),
                section_id=str(raw_row.get("section_id") or ""),
                title=str(raw_row.get("title") or ""),
                path=path,
                content=chapter_files.get(path, ""),
            )
        )
    return ExportBundleRecord(
        index_path=str(payload.get("index_path") or "index.md"),
        chapters_dir=str(payload.get("chapters_dir") or "chapters"),
        chapters=chapters,
        chapter_files=chapter_files,
        files=files,
        export_semantic_contract_ok=bool(payload.get("export_semantic_contract_ok", True)),
        front_matter_leak_detected=bool(payload.get("front_matter_leak_detected")),
        toc_residue_detected=bool(payload.get("toc_residue_detected")),
        mid_paragraph_heading_detected=bool(payload.get("mid_paragraph_heading_detected")),
        duplicate_paragraph_detected=bool(payload.get("duplicate_paragraph_detected")),
    )


def _load_persisted_export_bundle_payload_or_raise(doc_id: str) -> dict[str, Any]:
    payload = load_fnm_export_bundle(doc_id)
    if not isinstance(payload, dict):
        raise FileNotFoundError(_MISSING_PERSISTED_EXPORT_BUNDLE_MESSAGE)
    files = dict(payload.get("files") or {})
    if not files:
        raise FileNotFoundError(_MISSING_PERSISTED_EXPORT_BUNDLE_MESSAGE)
    return payload


def _status_payload(
    *,
    status: StructureStatusRecord,
    summary: Phase6Summary,
    run_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_validation = dict(run_validation or {})
    summary_payload = dict(run_validation.get("summary") or {})
    toc_export_coverage_summary = dict(
        summary_payload.get("toc_export_coverage_summary")
        or run_validation.get("toc_export_coverage_summary")
        or {}
    )
    if toc_export_coverage_summary:
        toc_export_coverage_summary = {
            "resolved_body_items": int(toc_export_coverage_summary.get("resolved_body_items") or 0),
            "exported_body_items": int(toc_export_coverage_summary.get("exported_body_items") or 0),
            "missing_body_items_preview": list(toc_export_coverage_summary.get("missing_body_items_preview") or [])[:8],
        }

    return {
        "structure_state": str(status.structure_state or "idle"),
        "review_counts": dict(status.review_counts or {}),
        "blocking_reasons": list(status.blocking_reasons or []),
        "link_summary": dict(status.link_summary or {}),
        "page_partition_summary": dict(status.page_partition_summary or {}),
        "chapter_mode_summary": dict(status.chapter_mode_summary or {}),
        "heading_review_summary": dict(status.heading_review_summary or {}),
        "heading_graph_summary": dict(status.heading_graph_summary or {}),
        "chapter_source_summary": dict(status.chapter_source_summary or {}),
        "visual_toc_conflict_count": int(status.visual_toc_conflict_count or 0),
        "toc_export_coverage_summary": toc_export_coverage_summary,
        "toc_alignment_summary": dict(status.toc_alignment_summary or {}),
        "toc_semantic_summary": dict(status.toc_semantic_summary or {}),
        "toc_role_summary": dict(status.toc_role_summary or _EMPTY_ROLE_SUMMARY),
        "container_titles": list(status.container_titles or []),
        "post_body_titles": list(status.post_body_titles or []),
        "back_matter_titles": list(status.back_matter_titles or []),
        "toc_semantic_contract_ok": bool(status.toc_semantic_contract_ok),
        "toc_semantic_blocking_reasons": list(status.toc_semantic_blocking_reasons or []),
        "chapter_title_alignment_ok": bool(status.chapter_title_alignment_ok),
        "chapter_section_alignment_ok": bool(status.chapter_section_alignment_ok),
        "chapter_endnote_region_alignment_ok": bool(status.chapter_endnote_region_alignment_ok),
        "chapter_endnote_region_alignment_summary": dict(status.chapter_endnote_region_alignment_summary or {}),
        "export_drift_summary": dict(status.export_drift_summary or {}),
        "chapter_local_endnote_contract_ok": bool(status.chapter_local_endnote_contract_ok),
        "export_semantic_contract_ok": bool(status.export_semantic_contract_ok),
        "front_matter_leak_detected": bool(status.front_matter_leak_detected),
        "toc_residue_detected": bool(status.toc_residue_detected),
        "mid_paragraph_heading_detected": bool(status.mid_paragraph_heading_detected),
        "duplicate_paragraph_detected": bool(status.duplicate_paragraph_detected),
        "manual_toc_required": bool(status.manual_toc_required),
        "manual_toc_ready": bool(status.manual_toc_ready),
        "manual_toc_summary": dict(status.manual_toc_summary or {}),
        "chapter_progress_summary": dict(status.chapter_progress_summary or {}),
        "note_region_progress_summary": dict(status.note_region_progress_summary or {}),
        "chapter_binding_summary": dict(status.chapter_binding_summary or {}),
        "note_capture_summary": dict(status.note_capture_summary or {}),
        "footnote_synthesis_summary": dict(status.footnote_synthesis_summary or {}),
        "chapter_link_contract_summary": dict(status.chapter_link_contract_summary or {}),
        "book_endnote_stream_summary": dict(status.book_endnote_stream_summary or {}),
        "freeze_note_unit_summary": dict(status.freeze_note_unit_summary or {}),
        "chapter_issue_counts": dict(status.chapter_issue_counts or {}),
        "chapter_issue_summary": [dict(row or {}) for row in list(status.chapter_issue_summary or [])][:24],
        "page_count": int(status.page_count or 0),
        "chapter_count": int(status.chapter_count or 0),
        "section_head_count": int(status.section_head_count or 0),
        "review_count": int(status.review_count or 0),
        "export_ready_test": bool(status.export_ready_test),
        "export_ready_real": bool(status.export_ready_real),
        "summary": {
            "heading_review_summary": dict(summary.heading_review_summary or {}),
            "heading_graph_summary": dict(summary.heading_graph_summary or {}),
            "chapter_source_summary": dict(summary.chapter_source_summary or {}),
            "toc_alignment_summary": dict(summary.toc_alignment_summary or {}),
            "toc_semantic_summary": dict(summary.toc_semantic_summary or {}),
            "toc_role_summary": dict(summary.toc_role_summary or {}),
            "container_titles": list(summary.container_titles or []),
            "post_body_titles": list(summary.post_body_titles or []),
            "back_matter_titles": list(summary.back_matter_titles or []),
            "toc_semantic_contract_ok": bool(summary.toc_semantic_contract_ok),
            "toc_semantic_blocking_reasons": list(summary.toc_semantic_blocking_reasons or []),
            "chapter_title_alignment_ok": bool(summary.chapter_title_alignment_ok),
            "chapter_section_alignment_ok": bool(summary.chapter_section_alignment_ok),
            "export_bundle_summary": dict(summary.export_bundle_summary or {}),
            "export_audit_summary": dict(summary.export_audit_summary or {}),
            "chapter_progress_summary": dict(status.chapter_progress_summary or {}),
            "note_region_progress_summary": dict(status.note_region_progress_summary or {}),
            "chapter_binding_summary": dict(status.chapter_binding_summary or {}),
            "note_capture_summary": dict(status.note_capture_summary or {}),
            "footnote_synthesis_summary": dict(status.footnote_synthesis_summary or {}),
            "chapter_link_contract_summary": dict(status.chapter_link_contract_summary or {}),
            "book_endnote_stream_summary": dict(status.book_endnote_stream_summary or {}),
            "freeze_note_unit_summary": dict(status.freeze_note_unit_summary or {}),
            "chapter_issue_counts": dict(status.chapter_issue_counts or {}),
            "chapter_issue_summary": [dict(row or {}) for row in list(status.chapter_issue_summary or [])][:24],
            "export_drift_summary": dict(status.export_drift_summary or {}),
            "chapter_local_endnote_contract_ok": bool(status.chapter_local_endnote_contract_ok),
            "export_semantic_contract_ok": bool(status.export_semantic_contract_ok),
            "front_matter_leak_detected": bool(status.front_matter_leak_detected),
            "toc_residue_detected": bool(status.toc_residue_detected),
            "mid_paragraph_heading_detected": bool(status.mid_paragraph_heading_detected),
            "duplicate_paragraph_detected": bool(status.duplicate_paragraph_detected),
        },
    }


def _build_validation_payload(status_payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(status_payload.get("summary") or {})
    return {
        "needs_human_review": str(status_payload.get("structure_state") or "") != "ready",
        "review_counts": dict(status_payload.get("review_counts") or {}),
        "blocking_reasons": list(status_payload.get("blocking_reasons") or []),
        "link_summary": dict(status_payload.get("link_summary") or {}),
        "summary": summary,
        "manual_toc_required": bool(status_payload.get("manual_toc_required")),
        "manual_toc_ready": bool(status_payload.get("manual_toc_ready")),
        "manual_toc_summary": dict(status_payload.get("manual_toc_summary") or {}),
        "toc_export_coverage_summary": dict(status_payload.get("toc_export_coverage_summary") or {}),
    }


def _load_module_snapshot_for_doc(
    doc_id: str,
    *,
    repo: SQLiteRepository,
    pages: list[dict],
    max_body_chars: int | None = None,
    pipeline_state_override: str | None = None,
    overlay_repo_units: bool = True,
    include_diagnostic_entries: bool = False,
    slug: str = "",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Any, str]:
    run = _safe_dict(getattr(repo, "get_latest_fnm_run", None), doc_id)
    pipeline_state = str(pipeline_state_override or _phase_state_from_run(run)).strip().lower()
    if not is_valid_pipeline_state(pipeline_state):
        pipeline_state = "done"

    toc_items, toc_offset = _load_fnm_toc_items(doc_id, repo)
    visual_toc_bundle = _load_fnm_visual_toc_bundle(doc_id)
    overrides = _group_review_overrides(
        _safe_list(getattr(repo, "list_fnm_review_overrides", None), doc_id)
    )
    manual_toc_ready, manual_toc_summary = _resolve_manual_toc_state(doc_id)
    repo_units = (
        _safe_list(getattr(repo, "list_fnm_translation_units", None), doc_id)
        if overlay_repo_units
        else None
    )
    snapshot = build_module_pipeline_snapshot(
        pages,
        toc_items=toc_items or None,
        toc_offset=int(toc_offset or 0),
        review_overrides=overrides,
        pdf_path=get_pdf_path(doc_id),
        manual_toc_ready=bool(manual_toc_ready),
        manual_toc_summary=manual_toc_summary,
        pipeline_state=pipeline_state,
        max_body_chars=_effective_max_body_chars(max_body_chars),
        include_diagnostic_entries=bool(include_diagnostic_entries),
        slug=str(slug or doc_id),
        doc_id=doc_id,
        repo_units=repo_units,
        progress_callback=progress_callback,
        visual_toc_bundle=visual_toc_bundle,
    )
    return snapshot, pipeline_state


def load_phase6_for_doc(
    doc_id: str,
    *,
    include_diagnostic_entries: bool = False,
    slug: str = "",
    repo: SQLiteRepository | None = None,
    max_body_chars: int | None = None,
    pipeline_state_override: str | None = None,
    pages: list[dict] | None = None,
    overlay_repo_units: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Phase6Structure:
    repo = repo or SQLiteRepository()
    if pages is None:
        pages = _safe_list(getattr(repo, "load_pages", None), doc_id)
    else:
        pages = list(pages or [])

    snapshot, _pipeline_state = _load_module_snapshot_for_doc(
        doc_id,
        repo=repo,
        pages=pages,
        max_body_chars=max_body_chars,
        pipeline_state_override=pipeline_state_override,
        overlay_repo_units=overlay_repo_units,
        include_diagnostic_entries=bool(include_diagnostic_entries),
        slug=str(slug or doc_id),
        progress_callback=progress_callback,
    )
    return snapshot.phase6_shadow


def _resolve_phase6_from_snapshot(snapshot: Any) -> Phase6Structure | None:
    if isinstance(snapshot, Phase6Structure):
        return snapshot

    if isinstance(snapshot, dict):
        for key in ("phase6", "phase6_shadow", "_phase6"):
            maybe_phase6 = snapshot.get(key)
            if isinstance(maybe_phase6, Phase6Structure):
                return maybe_phase6
    else:
        for attr in ("phase6", "phase6_shadow"):
            maybe_phase6 = getattr(snapshot, attr, None)
            if isinstance(maybe_phase6, Phase6Structure):
                return maybe_phase6
    return None


def build_phase6_status_for_doc(
    doc_id: str,
    *,
    snapshot: Any | None = None,
    repo: SQLiteRepository | None = None,
) -> dict[str, Any]:
    repo = repo or SQLiteRepository()
    run = _safe_dict(getattr(repo, "get_latest_fnm_run", None), doc_id)
    run_validation = _safe_json_loads(run.get("validation_json"))
    phase6 = _resolve_phase6_from_snapshot(snapshot)
    if phase6 is None:
        phase6 = load_phase6_for_doc(
            doc_id,
            include_diagnostic_entries=False,
            slug=doc_id,
            repo=repo,
            pipeline_state_override=None,
        )
    return _status_payload(
        status=phase6.status,
        summary=phase6.summary,
        run_validation=run_validation,
    )


def build_phase6_export_bundle_for_doc(
    doc_id: str,
    *,
    include_diagnostic_entries: bool = False,
    repo: SQLiteRepository | None = None,
    snapshot: Any | None = None,
) -> dict[str, Any]:
    phase6 = _resolve_phase6_from_snapshot(snapshot)
    if phase6 is not None:
        return _export_bundle_payload(phase6)
    return _load_persisted_export_bundle_payload_or_raise(doc_id)


def build_phase6_export_zip_for_doc(
    doc_id: str,
    *,
    include_diagnostic_entries: bool = False,
    repo: SQLiteRepository | None = None,
    snapshot: Any | None = None,
) -> bytes:
    repo = repo or SQLiteRepository()
    phase6 = _resolve_phase6_from_snapshot(snapshot)
    if phase6 is not None:
        export_bundle = _bundle_with_export_validation_log(
            phase6.export_bundle,
            phase6=phase6,
            doc_id=doc_id,
        )
        return build_export_zip(export_bundle)
    persisted_payload = _load_persisted_export_bundle_payload_or_raise(doc_id)
    latest_run = _safe_dict(getattr(repo, "get_latest_fnm_run", None), doc_id)
    export_bundle = _bundle_with_export_validation_log(
        _export_bundle_record_from_payload(persisted_payload),
        doc_id=doc_id,
        run=latest_run,
    )
    return build_export_zip(export_bundle)


def audit_phase6_export_for_doc(
    doc_id: str,
    *,
    slug: str = "",
    zip_path: str = "",
    zip_bytes: bytes | None = None,
    repo: SQLiteRepository | None = None,
    snapshot: Any | None = None,
) -> dict[str, Any]:
    repo = repo or SQLiteRepository()
    phase6 = _resolve_phase6_from_snapshot(snapshot)
    if phase6 is None:
        phase6 = load_phase6_for_doc(
            doc_id,
            include_diagnostic_entries=False,
            slug=slug or doc_id,
            repo=repo,
        )
    payload = zip_bytes
    if payload is None and str(zip_path or "").strip():
        path = Path(str(zip_path or "").strip())
        if path.exists():
            payload = path.read_bytes()
    report, _summary = audit_phase6_export(
        phase6,
        slug=str(slug or doc_id),
        zip_bytes=payload,
    )
    file_reports = [_to_plain(row) for row in report.files]
    return _summarize_book_audit(
        slug=str(slug or doc_id),
        doc_id=doc_id,
        zip_path=str(zip_path or report.zip_path or ""),
        structure_state=str(report.structure_state or ""),
        blocking_reasons=list(report.blocking_reasons or []),
        manual_toc_summary=dict(report.manual_toc_summary or {}),
        toc_role_summary=dict(report.toc_role_summary or {}),
        chapter_titles=list(report.chapter_titles or []),
        file_reports=file_reports,
    )


def _persist_phase6_to_repo(
    doc_id: str,
    phase6: Phase6Structure,
    *,
    repo: SQLiteRepository,
    clear_translate_state: bool = True,
) -> None:
    chapter_title_by_id = {
        str(row.chapter_id or ""): str(row.title or "")
        for row in phase6.chapters
        if str(row.chapter_id or "")
    }
    region_rows = _serialize_note_regions_for_repo(list(phase6.note_regions or []))
    region_pages_by_id = {
        str(row.get("region_id") or ""): list(row.get("pages") or [])
        for row in region_rows
        if str(row.get("region_id") or "")
    }
    note_kind_by_region_id = {
        str(row.get("region_id") or ""): (
            "endnote" if str(row.get("region_kind") or "").startswith("book_endnote") or str(row.get("region_kind") or "").startswith("chapter_endnote") or str(row.get("region_kind") or "") == "endnote" else "footnote"
        )
        for row in region_rows
        if str(row.get("region_id") or "")
    }
    title_hint_by_region_id = {
        str(row.get("region_id") or ""): str(row.get("title_hint") or "")
        for row in region_rows
        if str(row.get("region_id") or "")
    }
    effective_note_links = list(phase6.effective_note_links or phase6.note_links or [])
    repo.replace_fnm_structure(
        doc_id,
        pages=_serialize_pages_for_repo(list(phase6.pages or [])),
        chapters=[_to_plain(row) for row in phase6.chapters],
        heading_candidates=_serialize_heading_candidates_for_repo(list(phase6.heading_candidates or [])),
        note_regions=region_rows,
        chapter_note_modes=_serialize_chapter_note_modes_for_repo(
            list(phase6.chapter_note_modes or []),
            chapter_title_by_id=chapter_title_by_id,
            region_pages_by_id=region_pages_by_id,
        ),
        section_heads=_serialize_section_heads_for_repo(list(phase6.section_heads or [])),
        note_items=_serialize_note_items_for_repo(
            list(phase6.note_items or []),
            note_kind_by_region_id=note_kind_by_region_id,
            title_hint_by_region_id=title_hint_by_region_id,
        ),
        body_anchors=[_to_plain(row) for row in phase6.body_anchors],
        note_links=[_to_plain(row) for row in effective_note_links],
        structure_reviews=_serialize_structure_reviews(list(phase6.structure_reviews or [])),
    )
    repo.replace_fnm_data(
        doc_id,
        notes=[_to_plain(row) for row in phase6.diagnostic_notes],
        units=_serialize_units_for_repo(doc_id, list(phase6.translation_units or [])),
        preserve_structure=True,
    )
    if clear_translate_state:
        clear_fnm_export_bundle(doc_id)
        from translation.translate_store import _clear_translate_state

        _clear_translate_state(doc_id)


def run_phase6_pipeline_for_doc(
    doc_id: str,
    *,
    max_body_chars: int | None = None,
    repo: SQLiteRepository | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    repo = repo or SQLiteRepository()
    pages = _safe_list(getattr(repo, "load_pages", None), doc_id)
    run_id = int(getattr(repo, "create_fnm_run")(doc_id, status="running"))
    if not pages:
        repo.update_fnm_run(doc_id, run_id, status="error", error_msg="未找到 OCR 页面数据")
        return {"ok": False, "error": "no_pages", "run_id": run_id}

    try:
        phase6 = load_phase6_for_doc(
            doc_id,
            include_diagnostic_entries=False,
            slug=doc_id,
            repo=repo,
            max_body_chars=max_body_chars,
            pipeline_state_override="done",
            pages=pages,
            overlay_repo_units=False,
            progress_callback=progress_callback,
        )
        _persist_phase6_to_repo(doc_id, phase6, repo=repo)
        _run_id, status_payload, _validation_payload = _update_latest_fnm_run_from_phase6(
            doc_id,
            phase6,
            repo=repo,
        )
        note_count = len(phase6.note_items)
        unit_count = len(phase6.translation_units)
        section_count = len(phase6.chapters)
        page_count = len(pages)
        return {
            "ok": True,
            "run_id": run_id,
            "page_count": page_count,
            "section_count": section_count,
            "note_count": note_count,
            "unit_count": unit_count,
            "structure_state": str(status_payload.get("structure_state") or "ready"),
            "manual_toc_required": bool(status_payload.get("manual_toc_required")),
            "blocking_reasons": list(status_payload.get("blocking_reasons") or []),
            "review_counts": dict(status_payload.get("review_counts") or {}),
            "export_ready_real": bool(status_payload.get("export_ready_real")),
        }
    except Exception as exc:
        repo.update_fnm_run(doc_id, run_id, status="error", error_msg=str(exc))
        return {"ok": False, "error": str(exc), "run_id": run_id}


def run_post_translate_export_checks_for_doc(
    doc_id: str,
    *,
    max_repair_rounds: int = 3,
    repo: SQLiteRepository | None = None,
) -> dict[str, Any]:
    repo = repo or SQLiteRepository()
    pages = _safe_list(getattr(repo, "load_pages", None), doc_id)
    if not pages:
        return {"ok": False, "error": "no_pages"}
    from translation.translate_store import _load_translate_state, _save_translate_state

    max_rounds = max(0, int(max_repair_rounds or 0))
    clear_fnm_export_bundle(doc_id)
    precheck_snapshot = _load_translate_state(doc_id)
    translation_blockers = _tail_translation_issue_payloads(
        doc_id,
        repo=repo,
        snapshot=precheck_snapshot,
    )
    translation_attempt_history = [
        dict(item)
        for item in list(precheck_snapshot.get("translation_attempt_history") or [])
        if isinstance(item, dict)
    ]
    _save_translate_state(
        doc_id,
        running=bool(precheck_snapshot.get("running", False)),
        stop_requested=bool(precheck_snapshot.get("stop_requested", False)),
        phase=precheck_snapshot.get("phase", "running"),
        fnm_tail_state="post_translate_checking",
        export_bundle_available=False,
        export_has_blockers=bool(translation_blockers),
        tail_blocking_summary=_tail_blocking_summary(
            translation_blockers=translation_blockers,
            export_blocking_reasons=[],
        ),
    )

    def _load_phase6_snapshot() -> Phase6Structure:
        phase6_snapshot = load_phase6_for_doc(
            doc_id,
            include_diagnostic_entries=False,
            slug=doc_id,
            repo=repo,
            pipeline_state_override="done",
            pages=pages,
            # 最终校验需要基于当前 repo 中已提交的译文做审计，不能回退到新生成的 pending frozen units。
            overlay_repo_units=True,
        )
        _persist_phase6_to_repo(
            doc_id,
            phase6_snapshot,
            repo=repo,
            clear_translate_state=False,
        )
        return phase6_snapshot

    phase6 = _load_phase6_snapshot()
    repair_rounds: list[dict[str, Any]] = []

    if not bool(phase6.export_audit.can_ship):
        from FNM_RE.llm_repair import run_llm_repair
        from persistence.storage import resolve_fnm_model_pool_specs
        _save_translate_state(
            doc_id,
            running=bool(precheck_snapshot.get("running", False)),
            stop_requested=bool(precheck_snapshot.get("stop_requested", False)),
            phase=precheck_snapshot.get("phase", "running"),
            fnm_tail_state="repairing",
            export_bundle_available=False,
            export_has_blockers=True,
            tail_blocking_summary=_tail_blocking_summary(
                translation_blockers=translation_blockers,
                export_blocking_reasons=list(phase6.status.blocking_reasons or []),
            ),
        )

        for round_no in range(1, max_rounds + 1):
            round_record: dict[str, Any] = {"round": round_no}
            repair_result = None
            model_attempts: list[dict[str, Any]] = []
            for spec in resolve_fnm_model_pool_specs():
                model_args = {
                    "provider": str(spec.provider or "").strip(),
                    "model_id": str(spec.model_id or "").strip(),
                    "api_key": str(spec.api_key or "").strip(),
                    "base_url": str(spec.base_url or "").strip(),
                    "request_overrides": dict(spec.request_overrides or {}),
                    "display_label": str(spec.display_label or spec.model_id or "").strip(),
                }
                if not model_args["api_key"]:
                    model_attempts.append(
                        {
                            "model_id": model_args["model_id"],
                            "model_label": model_args["display_label"],
                            "provider": model_args["provider"],
                            "result": "skipped_no_api_key",
                        }
                    )
                    continue
                try:
                    repair_result = run_llm_repair(
                        doc_id,
                        repo=repo,
                        cluster_limit=None,
                        auto_apply=True,
                        clear_materialized_overrides=(round_no == 1),
                        model_args=model_args,
                    )
                except Exception as exc:
                    model_attempts.append(
                        {
                            "model_id": model_args["model_id"],
                            "model_label": model_args["display_label"],
                            "provider": model_args["provider"],
                            "result": "error",
                            "error": str(exc),
                        }
                    )
                    continue
                suggestion_count = int(repair_result.get("suggestion_count") or 0)
                auto_applied_count = int(repair_result.get("auto_applied_count") or 0)
                model_attempts.append(
                    {
                        "model_id": model_args["model_id"],
                        "model_label": model_args["display_label"],
                        "provider": model_args["provider"],
                        "result": "used",
                        "suggestion_count": suggestion_count,
                        "auto_applied_count": auto_applied_count,
                    }
                )
                if suggestion_count > 0 or auto_applied_count > 0:
                    break
                repair_result = None

            round_record["model_attempts"] = model_attempts
            if repair_result is None:
                round_record["error"] = "no_repair_model_succeeded"
                round_record["post_round_can_ship"] = bool(phase6.export_audit.can_ship)
                round_record["post_round_blocking_reasons"] = list(phase6.status.blocking_reasons or [])
                round_record["post_round_blocking_files"] = _phase6_blocking_file_payloads(phase6)
                repair_rounds.append(round_record)
                continue

            round_record.update(
                {
                    "suggestion_count": int(repair_result.get("suggestion_count") or 0),
                    "auto_applied_count": int(repair_result.get("auto_applied_count") or 0),
                    "action_counts": dict(repair_result.get("action_counts") or {}),
                    "auto_action_counts": dict(repair_result.get("auto_action_counts") or {}),
                    "usage_summary": dict(repair_result.get("usage_summary") or {}),
                }
            )
            if int(repair_result.get("auto_applied_count") or 0) > 0:
                phase6 = _load_phase6_snapshot()
            round_record["post_round_can_ship"] = bool(phase6.export_audit.can_ship)
            round_record["post_round_blocking_reasons"] = list(phase6.status.blocking_reasons or [])
            round_record["post_round_blocking_files"] = _phase6_blocking_file_payloads(phase6)
            repair_rounds.append(round_record)
            if bool(phase6.export_audit.can_ship):
                break

    final_blocking_reasons = list(phase6.status.blocking_reasons or [])
    final_can_ship = bool(phase6.export_audit.can_ship and not translation_blockers)
    repair_payload = {
        "trigger": "after_translate",
        "max_repair_rounds": max_rounds,
        "attempted_rounds": len(repair_rounds),
        "final_can_ship": final_can_ship,
        "final_blocking_reasons": final_blocking_reasons,
        "final_blocking_files": _phase6_blocking_file_payloads(phase6),
        "translation_blockers": translation_blockers,
        "translation_attempt_history": translation_attempt_history,
        "repair_rounds": repair_rounds,
        "updated_at": int(time.time()),
    }
    run_id, status_payload, validation_payload = _update_latest_fnm_run_from_phase6(
        doc_id,
        phase6,
        repo=repo,
        validation_extra={"post_translate_export_check": repair_payload},
    )
    save_fnm_export_bundle(doc_id, _export_bundle_payload(phase6))
    final_tail_blocking_summary = _tail_blocking_summary(
        translation_blockers=translation_blockers,
        export_blocking_reasons=final_blocking_reasons,
    )
    _save_translate_state(
        doc_id,
        running=bool(precheck_snapshot.get("running", False)),
        stop_requested=bool(precheck_snapshot.get("stop_requested", False)),
        phase=precheck_snapshot.get("phase", "running"),
        fnm_tail_state="done",
        export_bundle_available=True,
        export_has_blockers=bool(final_tail_blocking_summary),
        tail_blocking_summary=final_tail_blocking_summary,
    )
    return {
        "ok": True,
        "run_id": run_id,
        "export_ready_real": bool(status_payload.get("export_ready_real") and not translation_blockers),
        "export_bundle_available": True,
        "export_has_blockers": bool(final_tail_blocking_summary),
        "tail_blocking_summary": final_tail_blocking_summary,
        "fnm_tail_state": "done",
        "structure_state": str(status_payload.get("structure_state") or ""),
        "blocking_reasons": list(status_payload.get("blocking_reasons") or []),
        "translation_blockers": translation_blockers,
        "repair_rounds": repair_rounds,
        "post_translate_export_check": repair_payload,
        "validation": validation_payload,
    }


def list_phase6_diagnostic_notes_for_doc(
    doc_id: str,
    *,
    repo: SQLiteRepository | None = None,
) -> list[dict]:
    phase6 = load_phase6_for_doc(
        doc_id,
        include_diagnostic_entries=False,
        slug=doc_id,
        repo=repo,
    )
    rows = [_to_plain(row) for row in phase6.diagnostic_notes]
    rows.sort(
        key=lambda row: (
            int(row.get("section_start_page") or 0),
            int(row.get("start_page") or 0),
            str(row.get("kind") or ""),
            str(row.get("note_id") or ""),
        )
    )
    return rows


def list_phase6_diagnostic_entries_for_doc(
    doc_id: str,
    *,
    pages: list[dict] | None = None,
    visible_bps: list[int] | None = None,
    repo: SQLiteRepository | None = None,
) -> list[dict]:
    phase6 = load_phase6_for_doc(
        doc_id,
        include_diagnostic_entries=False,
        slug=doc_id,
        repo=repo,
        pages=pages,
    )
    visible = {int(bp) for bp in (visible_bps or []) if int(bp) > 0}
    rows = []
    for row in phase6.diagnostic_pages:
        payload = _to_plain(row)
        bp = int(payload.get("_pageBP") or 0)
        if visible and bp not in visible:
            continue
        rows.append(payload)
    rows.sort(key=lambda row: int(row.get("_pageBP") or 0))
    return rows


def get_phase6_diagnostic_entry_for_doc(
    doc_id: str,
    bp: int,
    *,
    pages: list[dict] | None = None,
    allow_fallback: bool = True,
    repo: SQLiteRepository | None = None,
) -> dict | None:
    if not allow_fallback:
        return None
    target = int(bp)
    for row in list_phase6_diagnostic_entries_for_doc(
        doc_id,
        pages=pages,
        visible_bps=[target],
        repo=repo,
    ):
        if int(row.get("_pageBP") or 0) == target:
            return row
    return None
