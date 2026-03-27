"""
人文学者阅读模拟测试 - Mad Acts 论文 (25页)
模拟陈思远（33岁历史学博后）半屏阅读场景
覆盖: 封面→目录→正文→脚注→PDF对照→主题→深页→边缘页
"""
import time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
DOC_ID = "f32dece616c9"
SD = "/tmp/mad_acts_screenshots"

import os
os.makedirs(SD, exist_ok=True)

def wait_ready(pg):
    if "/reading" in pg.url:
        pg.wait_for_load_state("load")
        time.sleep(2)
    else:
        pg.wait_for_load_state("networkidle")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    # ====== 阶段1: 落座感知 (全宽 + 半屏) ======
    print("=== 阶段1: 落座感知 ===")

    # 全宽首页
    full = browser.new_page(viewport={"width": 1280, "height": 900})
    full.goto(f"{BASE}/?doc_id={DOC_ID}")
    wait_ready(full)
    full.screenshot(path=f"{SD}/01_home_full.png", full_page=True)
    print("  01 首页(全宽)")

    # 全宽进入阅读页 - 封面 p.1
    full.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=1")
    wait_ready(full)
    full.screenshot(path=f"{SD}/02_reading_cover.png", full_page=True)
    print("  02 封面 p.1")

    # 半屏阅读 (模拟左侧浏览器, 右侧笔记)
    half = browser.new_page(viewport={"width": 700, "height": 900})

    # 目录页 p.3
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=3")
    wait_ready(half)
    half.screenshot(path=f"{SD}/03_toc_half.png", full_page=True)
    print("  03 目录页 p.3(半屏)")

    # 之前失败的目录续页 p.5 (修复后应有翻译)
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=5")
    wait_ready(half)
    half.screenshot(path=f"{SD}/04_toc_cont_p5.png", full_page=True)
    print("  04 目录续页 p.5(半屏)")

    # ====== 阶段2: 持续阅读模拟 ======
    print("\n=== 阶段2: 持续阅读 ===")

    # 正文起始页 (应该在目录之后)
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=11")
    wait_ready(half)
    half.screenshot(path=f"{SD}/05_body_p11_half.png", full_page=True)
    print("  05 正文 p.11(半屏)")

    # 正文 p.15 - 深入阅读
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=15")
    wait_ready(half)
    half.screenshot(path=f"{SD}/06_body_p15_half.png", full_page=True)
    print("  06 正文 p.15(半屏)")

    # 显示原文模式
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=15&orig=1")
    wait_ready(half)
    half.screenshot(path=f"{SD}/07_orig_p15_half.png", full_page=True)
    print("  07 原文+翻译 p.15(半屏)")

    # 并排模式
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=15&orig=1&layout=side")
    wait_ready(half)
    half.screenshot(path=f"{SD}/08_side_p15_half.png", full_page=True)
    print("  08 并排 p.15(半屏)")

    # PDF 对照
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=15&pdf=1")
    wait_ready(half)
    time.sleep(2)
    half.screenshot(path=f"{SD}/09_pdf_p15_half.png", full_page=True)
    print("  09 PDF对照 p.15(半屏)")

    # ====== 阶段3: 操作摩擦点 ======
    print("\n=== 阶段3: 操作摩擦 ===")

    # 翻页到 p.16
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=16")
    wait_ready(half)
    half.screenshot(path=f"{SD}/10_next_p16.png", full_page=True)
    print("  10 翻页到 p.16")

    # 跳转到深页 p.25 (最后一页)
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=25")
    wait_ready(half)
    half.screenshot(path=f"{SD}/11_deep_p25.png", full_page=True)
    print("  11 深页 p.25(最后)")

    # 跳回 p.1 (返回操作)
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=1")
    wait_ready(half)
    half.screenshot(path=f"{SD}/12_return_p1.png", full_page=True)
    print("  12 返回 p.1")

    # 版权页 p.2 (之前失败,现在应有翻译)
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=2")
    wait_ready(half)
    half.screenshot(path=f"{SD}/13_copyright_p2.png", full_page=True)
    print("  13 版权页 p.2")

    # 附录目录 p.10 (之前失败)
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=10")
    wait_ready(half)
    half.screenshot(path=f"{SD}/14_appendix_p10.png", full_page=True)
    print("  14 附录目录 p.10")

    # ====== 主题测试 ======
    print("\n=== 主题与视觉 ===")

    # 护眼主题 - 正文页
    half.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=20")
    wait_ready(half)
    half.evaluate("document.documentElement.setAttribute('data-theme', 'sepia')")
    time.sleep(0.5)
    half.screenshot(path=f"{SD}/15_sepia_p20.png", full_page=True)
    print("  15 护眼主题 p.20")

    # 深色主题
    half.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
    time.sleep(0.5)
    half.screenshot(path=f"{SD}/16_dark_p20.png", full_page=True)
    print("  16 深色主题 p.20")

    # 沉浸模式
    half.evaluate("document.documentElement.setAttribute('data-theme', '')")
    time.sleep(0.3)
    half.evaluate("if(typeof toggleDistractionFree==='function') toggleDistractionFree()")
    time.sleep(0.5)
    half.screenshot(path=f"{SD}/17_immersive_p20.png", full_page=True)
    print("  17 沉浸模式 p.20")
    half.evaluate("if(typeof toggleDistractionFree==='function') toggleDistractionFree()")

    # ====== 全宽正文质量检查 ======
    print("\n=== 全宽正文质量 ===")
    full.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=15&orig=1&layout=side")
    wait_ready(full)
    full.screenshot(path=f"{SD}/18_full_side_p15.png", full_page=True)
    print("  18 全宽并排 p.15")

    full.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=20&pdf=1")
    wait_ready(full)
    time.sleep(2)
    full.screenshot(path=f"{SD}/19_full_pdf_p20.png", full_page=True)
    print("  19 全宽PDF对照 p.20")

    # 脚注页
    full.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=13")
    wait_ready(full)
    full.screenshot(path=f"{SD}/20_footnotes_p13.png", full_page=True)
    print("  20 脚注页 p.13")

    # 无效页码边缘
    full.goto(f"{BASE}/reading?doc_id={DOC_ID}&bp=999")
    wait_ready(full)
    full.screenshot(path=f"{SD}/21_invalid_bp.png", full_page=True)
    print("  21 无效页码")

    # 导出
    import requests
    r = requests.get(f"{BASE}/export_md?doc_id={DOC_ID}")
    md = r.json().get("markdown", "")
    print(f"  22 导出 Markdown: {len(md)} chars")

    full.close()
    half.close()
    browser.close()

print("\n=== 截图完成 ===")
print(f"共 21 张截图保存在 {SD}/")
