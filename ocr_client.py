"""PaddleOCR API 客户端，用于调用版面解析服务。支持大PDF自动分片。"""
import base64
import io
import requests

from pypdf import PdfReader, PdfWriter

API_URL = "https://e2k8b6b77ba5qei2.aistudio-app.com/layout-parsing"
CHUNK_SIZE = 90  # 每次最多上传90页，PaddleOCR限制100页

# 版面解析接口按官方字段名组织请求参数。
# 当前应用场景是论文/图书阅读，因此显式开启版面区域、表格和公式识别，
# 同时关闭图表、印章等与阅读场景无关的能力，减少噪声。
DEFAULT_LAYOUT_PARSING_OPTIONS = {
    "useDocOrientationClassify": True,
    "useTextlineOrientation": False,
    "useSealRecognition": False,
    "useTableRecognition": True,
    "useFormulaRecognition": True,
    "useChartRecognition": False,
    "useRegionDetection": True,
    "formatBlockContent": False,
    "visualize": False,
}


def _build_layout_parsing_options(file_type: int, overrides: dict | None = None) -> dict:
    options = dict(DEFAULT_LAYOUT_PARSING_OPTIONS)
    # 文本图像矫正更适合拍照图片，不适合 PDF 文字页。
    options["useDocUnwarping"] = (file_type == 1)
    if overrides:
        options.update(overrides)
    return options


def _send_ocr_request(
    file_data_b64: str,
    token: str,
    file_type: int,
    request_options: dict,
) -> dict:
    """发送单次 OCR 请求，返回 result 字典。"""
    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "file": file_data_b64,
        "fileType": file_type,
    }
    payload.update(request_options)

    response = requests.post(API_URL, json=payload, headers=headers, timeout=300)

    if response.status_code == 429:
        raise RuntimeError("超出单日解析最大页数(3000页)，请明天再试或申请提升配额。")
    if response.status_code == 413:
        raise RuntimeError("请求体过大，请减少PDF文件的页数或文件大小。")
    if response.status_code == 503:
        raise RuntimeError("当前请求过多，请稍后再试。")
    if response.status_code == 504:
        raise RuntimeError("网关超时，请稍后再试。")
    if response.status_code != 200:
        msg = response.text[:300] if response.text else ""
        raise RuntimeError(f"PaddleOCR API 错误 {response.status_code}: {msg}")

    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError("PaddleOCR API 返回了无法解析的 JSON") from exc

    if not isinstance(body, dict):
        raise RuntimeError("PaddleOCR API 返回了无法识别的响应结构")

    error_code = body.get("errorCode")
    if error_code not in (None, 0):
        raise RuntimeError(body.get("errorMsg") or f"PaddleOCR API 返回错误码 {error_code}")

    if "result" not in body:
        raise RuntimeError("PaddleOCR API 响应缺少 result 字段")

    return body["result"]


def _split_pdf_bytes(file_bytes: bytes, chunk_size: int = CHUNK_SIZE) -> list[bytes]:
    """将大PDF按 chunk_size 页切割，返回每个分片的bytes列表。"""
    reader = PdfReader(io.BytesIO(file_bytes))
    total = len(reader.pages)
    if total <= chunk_size:
        return [file_bytes]

    chunks = []
    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total)
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        chunks.append(buf.getvalue())
    return chunks


def _merge_ocr_results(results: list[dict]) -> dict:
    """合并多个分片的OCR结果为一个统一结果。"""
    merged_layouts = []
    for chunk_idx, result in enumerate(results):
        layouts = result.get("layoutParsingResults", [])
        merged_layouts.extend(layouts)
    # 返回与单次调用相同结构
    return {"layoutParsingResults": merged_layouts}


def get_pdf_page_count(file_bytes: bytes) -> int:
    """获取PDF页数。"""
    reader = PdfReader(io.BytesIO(file_bytes))
    return len(reader.pages)


def call_paddle_ocr_bytes(
    file_bytes: bytes,
    token: str,
    file_type: int,
    on_progress=None,
    **kwargs,
) -> dict:
    """
    调用 PaddleOCR 版面解析 API（直接传入字节数据）。
    对于超过 CHUNK_SIZE 页的PDF，自动分片上传并合并结果。

    Args:
        file_bytes: 文件字节数据
        token: PaddleOCR API 令牌
        file_type: 0=PDF, 1=图片
        on_progress: 可选回调 (current_chunk, total_chunks)
    """
    request_options = _build_layout_parsing_options(file_type, kwargs)

    # 图片不需要分片
    if file_type != 0:
        b64 = base64.b64encode(file_bytes).decode("ascii")
        return _send_ocr_request(b64, token, file_type, request_options=request_options)

    # PDF: 检查是否需要分片
    chunks = _split_pdf_bytes(file_bytes)

    if len(chunks) == 1:
        b64 = base64.b64encode(file_bytes).decode("ascii")
        return _send_ocr_request(b64, token, file_type, request_options=request_options)

    # 多分片：逐个上传，合并结果
    all_results = []
    for i, chunk_bytes in enumerate(chunks):
        if on_progress:
            on_progress(i + 1, len(chunks))
        b64 = base64.b64encode(chunk_bytes).decode("ascii")
        result = _send_ocr_request(b64, token, file_type, request_options=request_options)
        all_results.append(result)

    return _merge_ocr_results(all_results)
