"""子进程调度器：按阶段拆分子进程，每个子进程结束后 OS 强制回收内存。"""
import json, os, subprocess, sys, time
from typing import Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def _run_subprocess(script_name: str, doc_id: str, pdf_path: str = "", label: str = "") -> dict:
    """执行一个子进程阶段，返回 JSON 摘要。"""
    script = os.path.join(_SCRIPT_DIR, script_name)
    payload = json.dumps({"doc_id": doc_id, "pdf_path": pdf_path})
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, script],
        input=payload, capture_output=True, text=True, timeout=900,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    elapsed = time.time() - t0
    if proc.returncode != 0:
        err = (proc.stderr or "")[-500:]
        raise RuntimeError(f"{label} subprocess failed (code={proc.returncode}): {err}")
    # 提取最后一行 JSON 输出
    lines = [l for l in (proc.stdout or "").strip().split("\n") if l.strip().startswith("{")]
    result = json.loads(lines[-1]) if lines else {}
    print(f"[{label}] done in {elapsed:.0f}s: {json.dumps(result, ensure_ascii=False)}")
    return result


def run_pipeline_in_subprocesses(doc_id: str, pdf_path: str = "") -> dict[str, Any]:
    """分三阶段子进程运行完整 pipeline。"""

    print("[subprocess] Phase 1: toc_structure + book_note_profile")
    r1 = _run_subprocess("subprocess_phase1.py", doc_id, pdf_path, "Phase1")

    print("[subprocess] Phase 2: chapter_layers + note regions + note items")
    r2 = _run_subprocess("subprocess_phase2.py", doc_id, pdf_path, "Phase2")

    # Phase 3-6 轻量，可在同一子进程运行，但独立子进程确保内存隔离
    print("[subprocess] Phases 3-6: link + freeze + merge + export")
    r36 = _run_subprocess("subprocess_phase3_6.py", doc_id, pdf_path, "Phases3-6")

    return {"phase1": r1, "phase2": r2, "phases3_6": r36}
