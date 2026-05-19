"""Phase 3-6 子进程：从 DB 加载 → note_linking + freeze + merge + export → 退出。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_phase3_6_subprocess(doc_id: str, pdf_path: str = "") -> dict:
    from persistence.sqlite_store import SQLiteRepository
    from FNM_RE.app.mainline import run_phase6_pipeline_for_doc

    repo = SQLiteRepository()
    # 从 DB 加载已有 Phase 1-2 数据继续跑后续阶段
    phase6 = run_phase6_pipeline_for_doc(
        doc_id, repo=repo, pdf_path=pdf_path,
        pipeline_state_override="phase2",  # 跳过 Phase 1-2
    )

    return {
        "chapters": len(phase6.export_chapters or []),
        "links_matched": sum(1 for l in (phase6.note_links or []) if getattr(l, "status", "") == "matched"),
        "blocking": list(phase6.structure_reviews or []),
    }


if __name__ == "__main__":
    args = json.loads(sys.stdin.read())
    result = run_phase3_6_subprocess(
        doc_id=args["doc_id"],
        pdf_path=args.get("pdf_path", ""),
    )
    print(json.dumps(result, ensure_ascii=False))
