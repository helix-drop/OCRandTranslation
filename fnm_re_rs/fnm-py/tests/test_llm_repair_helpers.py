"""M2.B6: llm_repair helpers — resolve_repair_model_args / render_repair_page_data_url."""

import json

import fnm_re_rs
import pytest


def test_resolve_repair_model_args_returns_json():
    """resolve_repair_model_args 应返回有效的 model_args JSON dict."""
    result = fnm_re_rs.resolve_repair_model_args_json()
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    keys = {"provider", "model_id", "api_key", "base_url", "display_label"}
    assert keys.intersection(parsed.keys()), f"缺少模型参数字段，有: {list(parsed.keys())}"


def test_render_repair_page_data_url_type_error():
    """参数类型不对应抛 TypeError."""
    with pytest.raises(TypeError):
        fnm_re_rs.render_repair_page_data_url_json(123, 0, 1.3)
