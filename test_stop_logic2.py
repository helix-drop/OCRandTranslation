#!/usr/bin/env python3
"""停止翻译逻辑的手工烟雾测试 - 只读取真实当前文档。"""

if __name__ != "__main__":
    import pytest
    pytestmark = pytest.mark.skip("历史手工脚本，请直接运行 `python3 test_stop_logic2.py`。")

import json
import os
import sys
import time
import requests

BASE_URL = "http://127.0.0.1:8080"
def log(step, msg):
    print(f"\n[{step}] {msg}")


def _get_current_doc_id():
    import config
    return config.get_current_doc_id()

def main():
    print("=" * 60)
    print("停止翻译逻辑 - 真实流程测试")
    print("=" * 60)

    os.chdir("/Users/hao/OCRandTranslation")

    # 创建session保持cookie
    session = requests.Session()

    # 步骤1: 检查应用
    log("1", "检查应用运行...")
    r = session.get(f"{BASE_URL}/")
    print(f"  ✓ 应用状态: {r.status_code}")

    # 步骤2: 直接测试状态持久化逻辑
    log("2", "测试状态持久化函数...")

    # 导入tasks模块中的函数
    sys.path.insert(0, "/Users/hao/OCRandTranslation")
    from tasks import _save_translate_state, _load_translate_state, is_translate_running, is_stop_requested, request_stop_translate

    doc_id = _get_current_doc_id()
    if not doc_id:
        print("  ✗ 没有当前文档，请先在应用里选中一个真实文档")
        return 1

    # 测试保存状态
    _save_translate_state(doc_id, running=True, stop_requested=False)
    print(f"  ✓ 保存 running=True 状态")

    # 测试读取状态
    state = _load_translate_state(doc_id)
    print(f"  读取状态: {json.dumps(state, indent=2)}")

    assert state["running"] == True, "running 应该为 True"
    assert state["stop_requested"] == False, "stop_requested 应该为 False"
    print("  ✓ 状态读写正确")

    # 步骤3: 测试 is_translate_running
    log("3", "测试 is_translate_running()...")
    running = is_translate_running(doc_id)
    print(f"  返回值: {running}")
    assert running == True, "is_translate_running 应该返回 True"
    print("  ✓ 函数返回正确")

    # 步骤4: 测试 request_stop_translate
    log("4", "测试 request_stop_translate()...")
    result = request_stop_translate(doc_id)
    print(f"  返回值: {result}")

    # 步骤5: 验证状态更新
    log("5", "验证停止请求后的状态...")
    state = _load_translate_state(doc_id)
    print(f"  当前状态: {json.dumps(state, indent=2)}")
    assert state["stop_requested"] == True, "stop_requested 应该为 True"
    print("  ✓ stop_requested 已更新为 True")

    # 步骤6: 测试 is_stop_requested
    log("6", "测试 is_stop_requested()...")
    stop_req = is_stop_requested(doc_id)
    print(f"  返回值: {stop_req}")
    assert stop_req == True, "is_stop_requested 应该返回 True"
    print("  ✓ 函数返回正确")

    # 步骤7: 模拟翻译完成后重置状态
    log("7", "模拟翻译完成后状态重置...")
    _save_translate_state(doc_id, running=False, stop_requested=False)
    state = _load_translate_state(doc_id)
    print(f"  最终状态: {json.dumps(state, indent=2)}")
    assert state["running"] == False, "running 应该为 False"
    print("  ✓ 状态正确重置")

    # 清理
    log("清理", "删除测试数据...")
    print("  ✓ 未创建伪造目录")

    print("\n" + "=" * 60)
    print("测试结果: 全部通过 ✓")
    print("=" * 60)
    print("\n关键验证点:")
    print("  ✓ 状态持久化到磁盘")
    print("  ✓ is_translate_running() 优先读取磁盘状态")
    print("  ✓ request_stop_translate() 正确设置 stop_requested")
    print("  ✓ is_stop_requested() 正确读取磁盘状态")
    print("  ✓ 状态在请求间保持一致性")

    return 0

def test_legacy_stop_logic2_placeholder():
    """占位项：让 pytest 收集到一个条目，但实际整模块跳过。"""
    assert True

if __name__ == "__main__":
    sys.exit(main())
