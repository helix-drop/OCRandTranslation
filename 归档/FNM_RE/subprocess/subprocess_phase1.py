"""Phase 1 子进程入口：加载页面 → TOC + book_note_profile → 写 DB → 退出。
子进程退出后 OS 回收全部内存（~600 MB），主进程从 DB 读取结果继续。
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_phase1_subprocess(doc_id: str, pdf_path: str = "") -> dict:
    """在子进程中运行 Phase 1，结果写入 DB，返回轻量摘要。"""
    from persistence.sqlite_store import SQLiteRepository
    from FNM_RE.modules.toc_structure import build_toc_structure
    from FNM_RE.modules.book_note_type import build_book_note_profile

    repo = SQLiteRepository()
    pages = repo.load_pages_phase1(doc_id)

    # Phase 1a: TOC
    toc_result = build_toc_structure(pages, toc_items=None, pdf_path=pdf_path)

    # Phase 1b: Book note profile
    book_type_result = build_book_note_profile(toc_result.data, pages)

    # 持久化 Phase 1 结果
    from FNM_RE.app.persist_helpers import (
        serialize_pages_for_repo,
        serialize_heading_candidates_for_repo,
        serialize_section_heads_for_repo,
        to_plain,
    )
    repo.replace_fnm_phase1_products(
        doc_id,
        pages=serialize_pages_for_repo(list(toc_result.data.pages or [])),
        chapters=[to_plain(r) for r in (toc_result.data.chapters or [])],
        heading_candidates=serialize_heading_candidates_for_repo(
            list(toc_result.diagnostics.get("heading_candidates") or [])
        ),
        section_heads=serialize_section_heads_for_repo(list(toc_result.data.section_heads or [])),
    )

    # 返回轻量摘要（不包含大对象）
    return {
        "chapters": len(toc_result.data.chapters),
        "section_heads": len(toc_result.data.section_heads),
        "book_type": str(book_type_result.data.book_type),
        "blocking": list(toc_result.gate_report.reasons or []),
    }


if __name__ == "__main__":
    # 由主进程通过 subprocess.run() 调用
    args = json.loads(sys.stdin.read())
    result = run_phase1_subprocess(
        doc_id=args["doc_id"],
        pdf_path=args.get("pdf_path", ""),
    )
    print(json.dumps(result, ensure_ascii=False))
