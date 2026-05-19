"""子进程 worker：执行 sup_recovery + visual_anchor_recovery。

父进程 spawn → worker 计算 → stdout 输出 JSON → worker 退出 → OS 回收全部内存。

内存优化：
- 使用 load_pages_phase1（轻量加载，跳过 payload_json 解析）
- ChapterLayers 数据从 DB 按需读取，避免 stdin 传输全量 body_pages 文本
"""
import json, sys


def _reconstruct_chapter_layers_from_db(repo, doc_id: str, chapter_page_ranges: dict):
    """从 DB 重建轻量 ChapterLayers，仅用于 visual_anchor_recovery。"""
    from FNM_RE.modules.types import (
        ChapterLayer, ChapterLayers, BodyPageLayer,
        LayerNoteRegion, LayerNoteItem,
    )

    # 从 fnm_chapter_body_pages 读取每章 body_pages
    body_pages_rows = repo.list_fnm_chapter_body_pages_all(doc_id) or []
    import json as _json
    body_pages_by_ch: dict[str, list[BodyPageLayer]] = {}
    for row in body_pages_rows:
        ch_id = str(row.get("chapter_id") or "")
        raw_bp = row.get("body_pages_json") or "{}"
        bp_data = _json.loads(raw_bp) if isinstance(raw_bp, str) else dict(raw_bp or {})
        bp_list = bp_data.get("body_pages") if isinstance(bp_data, dict) else (bp_data or [])
        if not isinstance(bp_list, list):
            bp_list = []
        for bp in bp_list:
            body_pages_by_ch.setdefault(ch_id, []).append(
                BodyPageLayer(
                    page_no=int(bp.get("page_no") or 0),
                    text=str(bp.get("text") or ""),
                    split_reason=str(bp.get("split_reason") or ""),
                    source_role=str(bp.get("source_role") or ""),
                )
            )

    # 从 fnm_note_items 读取 note items
    note_items_raw = repo.list_fnm_note_items(doc_id) or []
    # 从 fnm_note_regions 读取 note_kind 映射
    regions_for_ni = repo.list_fnm_note_regions(doc_id) or []
    note_kind_by_region: dict[str, str] = {}
    for r in regions_for_ni:
        rid = str(r.get("region_id") or "")
        nk = str(r.get("note_kind") or "")
        if rid and nk:
            note_kind_by_region[rid] = nk
    note_items = [
        LayerNoteItem(
            note_item_id=str(row.get("note_item_id") or ""),
            region_id=str(row.get("region_id") or ""),
            chapter_id=str(row.get("chapter_id") or ""),
            page_no=int(row.get("page_no") or 0),
            marker=str(row.get("marker") or ""),
            marker_type=str(row.get("marker_type") or ""),
            text=str(row.get("text") or ""),
            source=str(row.get("source") or "fnm_re"),
            source_page_label=str(row.get("source_page_label") or ""),
            is_reconstructed=bool(row.get("is_reconstructed")),
            review_required=bool(row.get("review_required")),
            note_kind=note_kind_by_region.get(str(row.get("region_id") or ""), "endnote"),
        )
        for row in note_items_raw
    ]

    # 从 fnm_note_regions 读取 note regions
    regions_raw = repo.list_fnm_note_regions(doc_id) or []
    import json as _json
    regions = [
        LayerNoteRegion(
            region_id=str(row.get("region_id") or ""),
            chapter_id=str(row.get("chapter_id") or ""),
            page_start=int(row.get("page_start") or 0),
            page_end=int(row.get("page_end") or 0),
            pages=_json.loads(row.get("pages_json") or "[]"),
            note_kind=str(row.get("note_kind") or ""),
            scope=str(row.get("scope") or "chapter"),
            source=str(row.get("source") or "fnm_re"),
            heading_text=str(row.get("heading_text") or ""),
            region_first_note_item_marker=str(row.get("region_first_note_item_marker") or ""),
            review_required=bool(row.get("review_required")),
        )
        for row in regions_raw
    ]

    # 从 fnm_chapters 读取 chapter 列表
    chapters_raw = repo.list_fnm_chapters(doc_id) or []
    chapter_order: dict[str, int] = {}
    chapters: list[ChapterLayer] = []
    for idx, row in enumerate(chapters_raw):
        ch_id = str(row.get("chapter_id") or "")
        chapter_order[ch_id] = idx
        start_p, end_p = chapter_page_ranges.get(ch_id, (0, 0))
        chapters.append(
            ChapterLayer(
                chapter_id=ch_id,
                title=str(row.get("title") or ""),
                policy_applied={},
                body_pages=list(body_pages_by_ch.get(ch_id, [])),
                footnote_items=[
                    ni for ni in note_items
                    if str(ni.chapter_id) == ch_id and str(ni.marker_type or "").startswith("footnote")
                ],
                endnote_items=[
                    ni for ni in note_items
                    if str(ni.chapter_id) == ch_id and not str(ni.marker_type or "").startswith("footnote")
                ],
                endnote_regions=[
                    r for r in regions
                    if str(r.chapter_id) == ch_id and str(r.note_kind or "") == "endnote"
                ],
            )
        )

    return ChapterLayers(chapters=chapters, regions=regions, note_items=note_items)


def main():
    params = json.loads(sys.stdin.buffer.read())
    doc_id = params["doc_id"]
    pdf_path = params["pdf_path"]
    chapter_note_markers = {k: set(v) for k, v in params["chapter_note_markers"].items()}
    chapter_page_ranges = {k: tuple(v) for k, v in params["chapter_page_ranges"].items()}

    # ── 轻量加载 pages（跳过 payload_json 解析，节省 200-300 MB）──
    from persistence.sqlite_store import SQLiteRepository
    repo = SQLiteRepository()
    pages = (getattr(repo, "load_pages_phase1", None) or repo.load_pages)(doc_id)
    if not pages:
        sys.stdout.buffer.write(json.dumps({"enriched_map": {}, "vr_overrides": {}}).encode())
        return

    # 保存修改前的 markdown 以检测变化
    original_md: dict[int, str] = {}
    for p in pages:
        pn = int(p.get("pdfPage") or p.get("page_no") or 0)
        if pn > 0:
            original_md[pn] = str(p.get("markdown") or p.get("enriched_markdown") or "")

    # ── sup_recovery ──
    from FNM_RE.modules.sup_recovery import recover_book_chapter_scoped
    recover_book_chapter_scoped(
        pages, chapter_note_markers, chapter_page_ranges,
        pdf_path=pdf_path,
    )

    # 收集 enriched_markdown 变化
    enriched_map: dict[int, str] = {}
    for p in pages:
        pn = int(p.get("pdfPage") or p.get("page_no") or 0)
        if pn <= 0:
            continue
        new_md = str(p.get("enriched_markdown") or "")
        if new_md and new_md != original_md.get(pn, ""):
            enriched_map[pn] = new_md

    # ── 释放 pages + 清理缓存（visual_anchor_recovery 从 DB 重读，不持有两份）──
    original_md = None  # 释放原始 markdown dict
    pages = None
    import gc as _gc
    try:
        from FNM_RE.modules.sup_recovery import _LAYER3_CACHE, _VISION_CLIENT_CACHE
        _LAYER3_CACHE.clear()
        _VISION_CLIENT_CACHE.clear()
    except Exception:
        pass
    _gc.collect()

    # ── visual_anchor_recovery（从 DB 读取，避免 stdin 传输全量 body_pages）──
    vr_overrides: dict = {}
    if params.get("has_chapter_layers"):
        try:
            from FNM_RE.modules.visual_anchor_recovery import build_visual_recovery_overrides
            from FNM_RE.modules.note_linking import _phase2_from_chapter_layers as _resolve_phase2
            from FNM_RE.stages.body_anchors import build_body_anchors as _build_body_anchors

            # 轻量重载 pages（仅 visual_anchor_recovery 需要 page metadata）
            _vr_pages = (getattr(repo, "load_pages_phase1", None) or repo.load_pages)(doc_id) if doc_id else []
            cl = _reconstruct_chapter_layers_from_db(repo, doc_id, chapter_page_ranges)
            # 同步 sup_recovery 的 enriched_markdown 到 ChapterLayers body_pages
            for chapter in cl.chapters:
                for bp in chapter.body_pages:
                    pn = int(bp.page_no or 0)
                    if pn in enriched_map:
                        bp.text = enriched_map[pn]
            phase2_for_gap, _, _ = _resolve_phase2(cl)
            gap_anchors, _ = _build_body_anchors(phase2_for_gap, pages=_vr_pages, pdf_path=pdf_path)
            vr_overrides = build_visual_recovery_overrides(
                phase2=phase2_for_gap, body_anchors=gap_anchors,
                pages=pages, pdf_path=pdf_path,
            )
            # 转换 key 为 str 以便 JSON 序列化
            vr_overrides = {
                str(scope): {
                    str(key): payload for key, payload in items.items()
                } for scope, items in vr_overrides.items()
            }
        except Exception as exc:
            print(f"[sup_recovery_worker] visual_recovery failed: {exc}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            vr_overrides = {}

    # 释放 pages 引用
    pages = None

    # 收集 token 用量 + 逐条 trace
    try:
        from FNM_RE.shared.token_counter import get_usage_summary, _counts
        usage_summary = get_usage_summary()
        _traces = list(_counts)
    except Exception:
        usage_summary = {}
        _traces = []

    result = json.dumps({
        "enriched_map": enriched_map, "vr_overrides": vr_overrides,
        "usage_summary": usage_summary,
        "_traces": _traces,
    }, ensure_ascii=False)
    # 优先写入临时文件（避免 stdout buffer 截断大 JSON），fallback 到 stdout
    import os as _os
    out_path = _os.environ.get("FNM_WORKER_OUTPUT_PATH", "")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result)
    sys.stdout.buffer.write(result.encode())


if __name__ == "__main__":
    main()
