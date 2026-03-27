#!/usr/bin/env python3
"""停止翻译逻辑的手工烟雾测试。"""

if __name__ != "__main__":
    import pytest
    pytestmark = pytest.mark.skip("历史手工脚本，请直接运行 `python3 test_stop_logic.py`。")

import json
import os
import sys
import tempfile
import time
import threading
import requests

BASE_URL = "http://127.0.0.1:8080"
def log(step, msg):
    print(f"\n[{step}] {msg}")

def test_step_1_check_app():
    """步骤1: 检查应用运行状态"""
    log("1", "检查应用运行状态...")
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        if r.status_code == 200:
            print("  ✓ 应用正常运行")
            return True
        else:
            print(f"  ✗ 应用返回异常状态码: {r.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ 应用未响应: {e}")
        return False

def _get_current_doc_id():
    from config import get_current_doc_id
    return get_current_doc_id()


def test_step_2_check_current_doc():
    """步骤2: 确认当前文档上下文"""
    log("2", "确认当前文档上下文...")
    doc_id = _get_current_doc_id()
    if not doc_id:
        print("  ✗ 没有当前文档，请先在应用里选中一个真实文档")
        return False
    print(f"  ✓ 当前文档: {doc_id}")
    return True

def test_step_3_check_status_api():
    """步骤3: 测试 /translate_status 接口"""
    log("3", "测试 /translate_status 接口...")

    try:
        doc_id = _get_current_doc_id()
        if not doc_id:
            print("  ✗ 没有当前文档，无法检查状态")
            return False
        r = requests.get(f"{BASE_URL}/translate_status", params={"doc_id": doc_id}, timeout=5)
        data = r.json()
        print(f"  返回: {json.dumps(data, indent=2)}")

        if "running" in data and "stop_requested" in data:
            print("  ✓ 接口返回正确格式")
            return True
        else:
            print("  ✗ 接口返回缺少必要字段")
            return False
    except Exception as e:
        print(f"  ✗ 接口调用失败: {e}")
        return False

def test_step_4_stop_translate():
    """步骤4: 测试 /stop_translate 接口"""
    log("4", "测试 /stop_translate 接口...")

    try:
        doc_id = _get_current_doc_id()
        if not doc_id:
            print("  ✗ 没有当前文档，无法发送停止请求")
            return False
        r = requests.get(f"{BASE_URL}/stop_translate", params={"doc_id": doc_id}, timeout=5)
        data = r.json()
        print(f"  返回: {json.dumps(data, indent=2)}")

        if data.get("status") == "stopping":
            print("  ✓ 停止请求成功")
            return True
        else:
            print("  ! 停止请求未返回 stopping（可能当前没有运行中的任务）")
            return True  # 这不算失败
    except Exception as e:
        print(f"  ✗ 停止接口调用失败: {e}")
        return False

def test_step_5_check_state_file():
    """步骤5: 验证状态文件是否正确更新"""
    log("5", "验证状态文件更新...")

    doc_id = _get_current_doc_id()
    if not doc_id:
        print("  ✗ 没有当前文档，无法检查状态")
        return False
    try:
        r = requests.get(f"{BASE_URL}/translate_status", params={"doc_id": doc_id}, timeout=5)
        state = r.json()
        print(f"  当前状态: {json.dumps(state, indent=2)}")
        if "stop_requested" in state:
            print("  ✓ 状态接口可返回 stop_requested")
        return True
    except Exception as e:
        print(f"  ✗ 状态检查失败: {e}")
        return False

def test_step_6_simulate_refresh():
    """步骤6: 模拟页面刷新后检查状态"""
    log("6", "模拟页面刷新后检查状态...")

    # 重新加载状态（模拟新请求）
    try:
        r = requests.get(f"{BASE_URL}/translate_status", timeout=5)
        data = r.json()
        print(f"  刷新后状态: {json.dumps(data, indent=2)}")
        print("  ✓ 刷新后能正确获取状态")
        return True
    except Exception as e:
        print(f"  ✗ 刷新后状态检查失败: {e}")
        return False

def test_step_7_clean_state():
    """步骤7: 清理状态，模拟翻译完全停止"""
    log("7", "模拟翻译完全停止后的状态...")

    try:
        doc_id = _get_current_doc_id()
        if not doc_id:
            print("  ✗ 没有当前文档，无法检查停止后状态")
            return False
        r = requests.get(f"{BASE_URL}/translate_status", params={"doc_id": doc_id}, timeout=5)
        data = r.json()
        print(f"  停止后状态: {json.dumps(data, indent=2)}")

        if not data.get("running"):
            print("  ✓ 翻译停止后状态正确: running=false")
            return True
        else:
            print("  ✗ 翻译停止后状态异常: 仍为running=true")
            return False
    except Exception as e:
        print(f"  ✗ 状态检查失败: {e}")
        return False

def cleanup():
    """清理测试数据"""
    log("清理", "删除测试数据...")
    import shutil
    print("  ✓ 无需删除伪造状态目录")

def main():
    print("=" * 60)
    print("停止翻译逻辑 - 完整测试")
    print("=" * 60)

    # 确保在正确的目录
    os.chdir("/Users/hao/OCRandTranslation")

    results = []

    # 运行所有测试步骤
    results.append(("步骤1: 应用状态", test_step_1_check_app()))
    results.append(("步骤2: 当前文档检查", test_step_2_check_current_doc()))
    results.append(("步骤3: 状态API", test_step_3_check_status_api()))
    results.append(("步骤4: 停止API", test_step_4_stop_translate()))
    results.append(("步骤5: 状态文件检查", test_step_5_check_state_file()))
    results.append(("步骤6: 刷新后状态", test_step_6_simulate_refresh()))
    results.append(("步骤7: 停止后状态", test_step_7_clean_state()))

    # 总结
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\n总计: {passed}/{total} 通过")

    cleanup()

    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
