"""Phase 2 子进程：从 DB 加载 Phase1 结果 → chapter_layers → 写 DB → 退出。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_phase2_subprocess(doc_id: str, pdf_path: str = "") -> dict:
    from persistence.sqlite_store import SQLiteRepository
    from FNM_RE.modules.toc_structure import build_toc_structure
    from FNM_RE.modules.book_note_type import build_book_note_profile
    from FNM_RE.modules.chapter_split import build_chapter_layers

    repo = SQLiteRepository()
    pages = repo.load_pages(doc_id)  # Phase2 需要完整 pages (fnBlocks 等)
    toc_data = build_toc_structure(pages, toc_items=None, pdf_path=pdf_path).data
    book_data = build_book_note_profile(toc_data, pages).data

    result = build_chapter_layers(
        toc_data, book_data, pages,
        pdf_path=pdf_path,
        doc_id=doc_id,
        repo=repo,
    )
    repo.replace_fnm_phase2_products(doc_id, toc_data, book_data, result.data)

    return {
        "chapters": len(result.data.chapters),
        "note_items": len(result.data.note_items),
        "regions": len(result.data.regions),
        "blocking": list(result.gate_report.reasons or []),
    }


if __name__ == "__main__":
    args = json.loads(sys.stdin.read())
    result = run_phase2_subprocess(
        doc_id=args["doc_id"],
        pdf_path=args.get("pdf_path", ""),
    )
    print(json.dumps(result, ensure_ascii=False))
