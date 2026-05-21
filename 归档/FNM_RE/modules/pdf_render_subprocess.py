"""父侧 helper：通过微进程渲染 PDF 页面，每次调用 subprocess.run → 渲染完 OS 回收全部内存。

用法：
  data_url = render_sup_l3_data_url(pdf_path, page_no)
  data_url = render_repair_page_data_url(pdf_path, file_idx)
  stats = get_render_stats()  # 查询累计统计

不做进程池，不做 fallback 到进程内渲染。
页面级 LRU 缓存（max 8 页）：同页不同 marker 复用渲染结果。
"""
import json, os, subprocess, sys
from collections import OrderedDict

_RENDERER_MODULE = "FNM_RE.modules._pdf_render_worker"
_RENDER_TIMEOUT = 30  # 秒
_PAGE_CACHE_MAX = 8  # 最多缓存 8 页渲染结果

# ── 页面渲染缓存 ──
_page_cache: OrderedDict = OrderedDict()
_cache_hits = 0

# ── 模块级累计统计 ──
_render_stats = {
    "total_renders": 0,
    "total_render_ms": 0,
    "total_failures": 0,
    "max_render_ms": 0,
    "max_peak_rss_mb": 0,
    "max_bytes_len": 0,
    "last_data_url_len": 0,
    "last_render_ms": 0,
    "last_peak_rss_mb": 0,
    "cache_hits": 0,
}


def get_render_stats() -> dict:
    """返回当前累计渲染统计，不重置。"""
    r = dict(_render_stats)
    if r["total_renders"] > 0:
        r["avg_render_ms"] = r["total_render_ms"] // r["total_renders"]
    else:
        r["avg_render_ms"] = 0
    return r


def _reset_render_stats() -> None:
    """重置统计（测试用）。"""
    for k in _render_stats:
        _render_stats[k] = 0


def _run_renderer(params: dict) -> str | None:
    """调用微进程渲染，返回 data_url 或 None。同时更新模块级统计。"""
    # 页面缓存：同页同模式复用
    cache_key = (
        str(params.get("pdf_path") or ""),
        int(params.get("page_no") or params.get("file_idx") or 0),
        str(params.get("mode") or ""),
    )
    if cache_key in _page_cache:
        _page_cache.move_to_end(cache_key)
        global _cache_hits
        _cache_hits += 1
        _render_stats["cache_hits"] = _cache_hits
        return _page_cache[cache_key]

    try:
        proc = subprocess.run(
            [sys.executable, "-m", _RENDERER_MODULE],
            input=json.dumps(params),
            capture_output=True, text=True, timeout=_RENDER_TIMEOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        if proc.returncode != 0:
            _render_stats["total_failures"] += 1
            return None
        lines = [l for l in (proc.stdout or "").strip().split("\n") if l.strip().startswith("{")]
        result = json.loads(lines[-1]) if lines else {}
        if result.get("error") or not result.get("data_url"):
            _render_stats["total_failures"] += 1
            return None

        # 聚合统计
        _render_stats["total_renders"] += 1
        render_ms = int(result.get("render_ms") or 0)
        _render_stats["total_render_ms"] += render_ms
        _render_stats["last_render_ms"] = render_ms
        _render_stats["max_render_ms"] = max(_render_stats["max_render_ms"], render_ms)
        peak = int(result.get("peak_rss_mb") or 0)
        _render_stats["last_peak_rss_mb"] = peak
        _render_stats["max_peak_rss_mb"] = max(_render_stats["max_peak_rss_mb"], peak)
        blen = int(result.get("bytes_len") or 0)
        _render_stats["max_bytes_len"] = max(_render_stats["max_bytes_len"], blen)
        data_url = str(result.get("data_url") or "")
        _render_stats["last_data_url_len"] = len(data_url)
        # 存入页面缓存
        _page_cache[cache_key] = data_url
        while len(_page_cache) > _PAGE_CACHE_MAX:
            _page_cache.popitem(last=False)
        return data_url or None
    except Exception:
        _render_stats["total_failures"] += 1
        return None


def render_sup_l3_data_url(pdf_path: str, page_no: int) -> str | None:
    """复刻 sup_recovery._vision_find_superscript 的 5x/裁剪/PNG 渲染，返回 data URL。"""
    return _run_renderer({
        "mode": "sup_l3_clip",
        "pdf_path": pdf_path,
        "page_no": page_no,
    })


def render_repair_page_data_url(pdf_path: str, file_idx: int) -> str | None:
    """复刻 llm_repair._render_repair_page_image 的 1.3x/全页/JPEG 渲染，返回 data URL。"""
    return _run_renderer({
        "mode": "repair_page",
        "pdf_path": pdf_path,
        "file_idx": file_idx,
    })
