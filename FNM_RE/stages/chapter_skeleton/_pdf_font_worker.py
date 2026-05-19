"""子进程 worker：解析 PDF 并提取 font band heading candidates。

父进程 spawn → worker 计算 → stdout 输出 JSON → worker 退出 → OS 回收全部内存。
"""
import json, sys


def main():
    params = json.loads(sys.stdin.buffer.read())
    pdf_path = params["pdf_path"]
    candidate_file_indices = set(params["candidate_file_indices"])
    file_idx_to_page_no = {int(k): int(v) for k, v in params["file_idx_to_page_no"].items()}
    candidate_pages = set(params["candidate_pages"])
    page_role_by_no = {int(k): v for k, v in params["page_role_by_no"].items()}
    total_pages = params["total_pages"]

    from pathlib import Path
    file_bytes = Path(pdf_path).read_bytes()
    from document.pdf_extract import extract_pdf_text
    pdf_pages = extract_pdf_text(file_bytes, page_indices=candidate_file_indices)
    del file_bytes

    from FNM_RE.stages.chapter_skeleton.heading_candidates import _extract_candidates_from_pdf_pages
    candidates = _extract_candidates_from_pdf_pages(
        pdf_pages, candidate_pages, file_idx_to_page_no,
        page_role_by_no, total_pages,
    )
    sys.stdout.buffer.write(json.dumps(candidates, ensure_ascii=False).encode())


if __name__ == "__main__":
    main()
