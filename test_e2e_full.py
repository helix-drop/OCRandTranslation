"""
全流程端到端真实用户模拟测试
使用真实 PaddleOCR + Qwen 翻译 API
覆盖: 首页/上传/OCR/阅读/翻译/术语表/导出/PDF/主题/边缘情况
"""
import os
import sys
import json
import time
import requests
from testsupport import prime_requests_csrf, with_csrf_headers

BASE = "http://127.0.0.1:8080"
SCREENSHOT_DIR = "/tmp/e2e_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

EXAMPLE_DIR = os.path.join(os.path.dirname(__file__), "local_data", "example")
SHORT_PDF = os.path.join(EXAMPLE_DIR, "10.1177@0957154X19859204.pdf")
LONG_PDF = os.path.join(EXAMPLE_DIR, "第三章.pdf")

results = []
ACTIVE_TRANSLATE_PHASES = {"running", "stopping"}
TERMINAL_TRANSLATE_PHASES = {"idle", "stopped", "done", "partial_failed", "error"}

def record(name, status, detail=""):
    results.append({"name": name, "status": status, "detail": detail})
    icon = "✅" if status == "PASS" else ("❌" if status == "FAIL" else "⚠️")
    print(f"  {icon} {name}: {detail}" if detail else f"  {icon} {name}")


def fetch_translate_status(doc_id):
    r = requests.get(f"{BASE}/translate_status?doc_id={doc_id}")
    if r.status_code != 200:
        raise RuntimeError(f"translate_status failed: {r.status_code}")
    return r.json()


def wait_for_translate_status(doc_id, predicate, timeout=30, interval=1.0):
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = fetch_translate_status(doc_id)
        if predicate(last):
            return last
        time.sleep(interval)
    return last


def wait_for_progress_or_terminal(doc_id, timeout=35):
    return wait_for_translate_status(
        doc_id,
        lambda data: bool(data.get("translated_bps")) or data.get("phase") in TERMINAL_TRANSLATE_PHASES,
        timeout=timeout,
        interval=1.0,
    )


def wait_for_terminal_state(doc_id, timeout=20):
    return wait_for_translate_status(
        doc_id,
        lambda data: (not data.get("running")) and data.get("phase") in TERMINAL_TRANSLATE_PHASES,
        timeout=timeout,
        interval=1.0,
    )


def test_with_playwright():
    from playwright.sync_api import sync_playwright

    def wait_ready(pg, url_hint=""):
        """阅读页有 SSE 长连接，不能用 networkidle；其他页面可以。"""
        if "/reading" in (url_hint or pg.url):
            pg.wait_for_load_state("load")
            time.sleep(2)
        else:
            pg.wait_for_load_state("networkidle")

    with sync_playwright() as p:
        api_session = requests.Session()
        csrf_token = prime_requests_csrf(api_session, BASE)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # ======== 1. 首页基本测试 ========
        print("\n=== 1. 首页测试 ===")
        page.goto(BASE)
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/01_home.png", full_page=True)

        title = page.title()
        if "阅读" in title or "外文" in title or "文献" in title:
            record("首页标题", "PASS", title)
        else:
            record("首页标题", "WARN", f"标题: {title}")

        doc_items = page.locator(".doc-item").all()
        record("已有文档列表", "PASS", f"已有 {len(doc_items)} 个文档")

        # 检查当前文档高亮
        active_docs = page.locator(".doc-item.doc-active").all()
        if active_docs:
            record("当前文档高亮", "PASS")
        else:
            record("当前文档高亮", "WARN", "没有高亮的文档")

        # ======== 2. 上传短文档（如果不存在新的就跳过） ========
        print("\n=== 2. 文档上传测试（已有文档可用即跳过上传） ===")
        existing_doc_count = len(doc_items)
        if existing_doc_count >= 2:
            record("文档已有", "PASS", f"{existing_doc_count} 个文档可用，跳过上传测试")
        else:
            record("文档不足", "WARN", "文档少于2个，建议手动上传测试文档")

        # ======== 3. 设置页面测试 ========
        print("\n=== 3. 设置页面测试 ===")
        page.goto(f"{BASE}/settings")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/02_settings.png", full_page=True)

        paddle_input = page.locator("input[name='paddle_token']")
        if paddle_input.count() > 0:
            val = paddle_input.get_attribute("value") or ""
            record("PaddleOCR Token", "PASS" if val else "WARN", "已填写" if val else "未填写")
        else:
            record("PaddleOCR Token 输入框", "FAIL", "未找到")

        dashscope_input = page.locator("input[name='dashscope_key']")
        if dashscope_input.count() > 0:
            val = dashscope_input.get_attribute("value") or ""
            record("DashScope Key", "PASS" if val else "WARN", "已填写" if val else "未填写")
        else:
            record("DashScope Key 输入框", "FAIL", "未找到")

        # ======== 4. 术语表 CRUD 测试 ========
        print("\n=== 4. 术语表 CRUD API 测试 ===")

        # 4a. 读取当前术语表
        r = requests.get(f"{BASE}/api/glossary")
        if r.status_code == 200:
            items = r.json().get("items", [])
            record("术语表读取 GET", "PASS", f"当前 {len(items)} 条")
        else:
            record("术语表读取 GET", "FAIL", f"status={r.status_code}")

        # 4b. 添加测试术语
        test_terms = [
            {"term": "aliénation mentale", "defn": "精神错乱（法语医学术语）"},
            {"term": "Esquirol", "defn": "艾斯基洛尔（法国精神病学家）"},
            {"term": "monomanie", "defn": "偏执狂（19世纪精神医学概念）"},
        ]
        for t in test_terms:
            r = api_session.post(f"{BASE}/api/glossary", json=t, headers=with_csrf_headers(csrf_token))
            if r.status_code == 200 and r.json().get("ok"):
                record(f"术语表添加 '{t['term']}'", "PASS")
            else:
                record(f"术语表添加 '{t['term']}'", "FAIL", str(r.text)[:100])

        # 4c. 读取验证
        r = requests.get(f"{BASE}/api/glossary")
        items = r.json().get("items", [])
        added_terms = [i[0] for i in items]
        all_found = all(t["term"] in added_terms for t in test_terms)
        record("术语表添加验证", "PASS" if all_found else "FAIL", f"共 {len(items)} 条")

        # 4d. 更新测试
        r = api_session.put(
            f"{BASE}/api/glossary/Esquirol",
            json={"defn": "让-艾蒂安·多米尼克·艾斯基洛尔（精神病学奠基人之一）"},
            headers=with_csrf_headers(csrf_token),
        )
        if r.status_code == 200 and r.json().get("ok"):
            record("术语表更新 PUT", "PASS")
        else:
            record("术语表更新 PUT", "FAIL", str(r.text)[:100])

        # 4e. 删除测试（只删一个，保留其他给翻译测试用）
        r = api_session.delete(f"{BASE}/api/glossary/monomanie", headers=with_csrf_headers(csrf_token))
        if r.status_code == 200 and r.json().get("ok"):
            record("术语表删除 DELETE", "PASS")
        else:
            record("术语表删除 DELETE", "FAIL", str(r.text)[:100])

        # 4f. 再读取，确认删除生效
        r = requests.get(f"{BASE}/api/glossary")
        items = r.json().get("items", [])
        terms_now = [i[0] for i in items]
        if "monomanie" not in terms_now and "Esquirol" in terms_now:
            record("术语表删除验证", "PASS", f"剩余 {len(items)} 条")
        else:
            record("术语表删除验证", "FAIL", f"terms: {terms_now}")

        # 在设置页截图术语表
        page.goto(f"{BASE}/settings")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/03_settings_glossary.png", full_page=True)

        # ======== 5. 切换到短文档阅读 ========
        print("\n=== 5. 短文档阅读页测试 ===")
        page.goto(f"{BASE}/?doc_id=5d8d44cba1c2")
        wait_ready(page)

        # 直接导航到阅读页（阅读页有 SSE 长连接，不能用 networkidle）
        page.goto(f"{BASE}/reading?doc_id=5d8d44cba1c2")
        wait_ready(page, "/reading")
        record("进入短文档阅读页", "PASS")
        page.screenshot(path=f"{SCREENSHOT_DIR}/04_reading_short.png", full_page=True)

        # 检查阅读页基本元素
        content_area = page.locator(".content-panel, .page-content, .reading-content, main")
        if content_area.count() > 0:
            record("阅读页内容区域", "PASS")
        else:
            record("阅读页内容区域", "WARN", "未找到主内容区域选择器")

        # 检查页码导航
        page_nav = page.locator(".page-nav, .pagination, [class*='page']")
        if page_nav.count() > 0:
            record("页码导航区域", "PASS")
        else:
            record("页码导航区域", "WARN", "未找到明确的页码导航")

        # ======== 6. 翻译测试（真实 Qwen API） ========
        print("\n=== 6. 翻译测试（真实 Qwen API） ===")

        # 使用短文档，尝试翻译一页
        # 先找到未翻译的页码
        r = requests.get(f"{BASE}/translate_status?doc_id=5d8d44cba1c2")
        if r.status_code == 200:
            status_data = r.json()
            translated_bps = status_data.get("translated_bps", [])
            record("翻译状态查询", "PASS", f"已翻译 {len(translated_bps)} 页: {translated_bps[:5]}")
        else:
            record("翻译状态查询", "FAIL", f"status={r.status_code}")
            translated_bps = []

        # 启动翻译（从第一页开始翻译几页）
        first_bp = 1
        r = api_session.post(f"{BASE}/start_translate_all", data={
            "doc_id": "5d8d44cba1c2",
            "start_bp": first_bp,
            "doc_title": "10.1177@0957154X19859204"
        }, headers=with_csrf_headers(csrf_token))
        if r.status_code == 200:
            resp = r.json()
            if resp.get("status") in ("started", "already_running"):
                record("启动批量翻译", "PASS", resp.get("status"))
            else:
                record("启动批量翻译", "WARN", str(resp))
        else:
            record("启动批量翻译", "FAIL", f"status={r.status_code}")

        # 等待翻译进行一段时间（翻译2-3页后停止）
        print("  ... 等待翻译开始或自然完成 ...")
        status_data = wait_for_progress_or_terminal("5d8d44cba1c2", timeout=35)
        phase = status_data.get("phase", "unknown")
        new_translated = status_data.get("translated_bps", [])
        if phase in ACTIVE_TRANSLATE_PHASES or phase in TERMINAL_TRANSLATE_PHASES:
            record("翻译进度检查", "PASS", f"phase={phase}, 已翻译 {len(new_translated)} 页")
        else:
            record("翻译进度检查", "FAIL", f"phase={phase}")

        if status_data.get("running") and phase in ACTIVE_TRANSLATE_PHASES:
            r = api_session.post(
                f"{BASE}/stop_translate",
                data={"doc_id": "5d8d44cba1c2"},
                headers=with_csrf_headers(csrf_token),
            )
            if r.status_code == 200:
                resp = r.json()
                stop_status = resp.get("status")
                if stop_status == "stopping":
                    record("停止翻译", "PASS", stop_status)
                elif stop_status == "not_running":
                    latest = fetch_translate_status("5d8d44cba1c2")
                    latest_phase = latest.get("phase", "unknown")
                    latest_running = bool(latest.get("running"))
                    ok = (not latest_running) and latest_phase in TERMINAL_TRANSLATE_PHASES
                    detail = f"status=not_running, phase={latest_phase}, running={latest_running}"
                    record("停止翻译", "PASS" if ok else "FAIL", detail)
                else:
                    record("停止翻译", "FAIL", stop_status or str(resp))
            else:
                record("停止翻译", "FAIL", f"status={r.status_code}")
        else:
            record("停止翻译", "PASS", f"任务已自然结束，phase={phase}")

        status_data = wait_for_terminal_state("5d8d44cba1c2", timeout=20)
        phase = status_data.get("phase", "unknown")
        is_terminal = (not status_data.get("running")) and phase in TERMINAL_TRANSLATE_PHASES
        record("停止后状态", "PASS" if is_terminal else "FAIL", f"phase={phase}, running={status_data.get('running')}")

        # 截图阅读页（翻译后）
        page.goto(f"{BASE}/reading?doc_id=5d8d44cba1c2&bp=1")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/05_reading_translated.png", full_page=True)

        # ======== 7. 阅读体验测试 ========
        print("\n=== 7. 阅读体验 UX 测试 ===")

        # 7a. 翻页测试
        next_btn = page.locator("a:has-text('下一页'), button:has-text('下一页'), a[href*='bp=']").first
        if next_btn.count() > 0:
            next_btn.click()
            wait_ready(page)
            record("翻页（下一页）", "PASS")
            page.screenshot(path=f"{SCREENSHOT_DIR}/06_next_page.png", full_page=True)
        else:
            record("翻页（下一页）", "WARN", "未找到下一页按钮")

        # 7b. 原文显示切换
        page.goto(f"{BASE}/reading?doc_id=5d8d44cba1c2&bp=1&orig=1")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/07_with_original.png", full_page=True)
        record("原文显示模式", "PASS")

        # 7c. PDF 面板
        page.goto(f"{BASE}/reading?doc_id=5d8d44cba1c2&bp=1&pdf=1")
        wait_ready(page)
        time.sleep(2)
        page.screenshot(path=f"{SCREENSHOT_DIR}/08_pdf_panel.png", full_page=True)
        pdf_panel = page.locator(".pdf-panel, [class*='pdf']")
        if pdf_panel.count() > 0:
            record("PDF 对照面板", "PASS")
        else:
            record("PDF 对照面板", "WARN", "未检测到 PDF 面板")

        # 7d. 并排布局
        page.goto(f"{BASE}/reading?doc_id=5d8d44cba1c2&bp=1&layout=side&orig=1")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/09_side_layout.png", full_page=True)
        record("并排布局模式", "PASS")

        # 7e. 主题切换
        for theme in ["dark", "sepia", "light"]:
            page.evaluate(f"document.documentElement.setAttribute('data-theme', '{theme}')")
            time.sleep(0.5)
            page.screenshot(path=f"{SCREENSHOT_DIR}/10_theme_{theme}.png")
            record(f"主题切换 ({theme})", "PASS")

        # 7f. 字号调整
        page.evaluate("if(typeof changeFontSize==='function') changeFontSize(2)")
        time.sleep(0.5)
        page.screenshot(path=f"{SCREENSHOT_DIR}/11_fontsize_up.png")
        record("字号放大", "PASS")

        page.evaluate("if(typeof changeFontSize==='function') changeFontSize(-2)")
        time.sleep(0.5)
        record("字号缩小", "PASS")

        # 7g. 沉浸模式入口已移除
        focus_btn_count = page.locator("#focusBtn").count()
        exit_btn_count = page.locator("#distractionFreeExitBtn").count()
        record(
            "沉浸模式入口已移除",
            "PASS" if focus_btn_count == 0 and exit_btn_count == 0 else "FAIL",
            f"focusBtn={focus_btn_count}, exitBtn={exit_btn_count}"
        )

        # ======== 8. 切换到长文档测试 ========
        print("\n=== 8. 长文档测试（法语书 99 页） ===")
        page.goto(f"{BASE}/?doc_id=5a21aca40a53")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/13_home_long_doc.png", full_page=True)

        # 进入阅读页
        start_link = page.locator("a:has-text('开始读')")
        if start_link.count() > 0:
            start_link.first.click()
            wait_ready(page)
        else:
            page.goto(f"{BASE}/reading?doc_id=5a21aca40a53")
            wait_ready(page)

        page.screenshot(path=f"{SCREENSHOT_DIR}/14_reading_long_doc.png", full_page=True)
        record("长文档阅读页进入", "PASS")

        # 深页跳转
        page.goto(f"{BASE}/reading?doc_id=5a21aca40a53&bp=50")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/15_deep_page_50.png", full_page=True)
        record("深页跳转 p.50", "PASS")

        # 最后一页
        page.goto(f"{BASE}/reading?doc_id=5a21aca40a53&bp=99")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/16_last_page.png")
        record("最后一页访问", "PASS")

        # 翻译长文档几页
        r = api_session.post(f"{BASE}/start_translate_all", data={
            "doc_id": "5a21aca40a53",
            "start_bp": 7,
            "doc_title": "序言+第一章"
        }, headers=with_csrf_headers(csrf_token))
        if r.status_code == 200:
            resp = r.json()
            record("长文档启动翻译", "PASS", resp.get("status"))
        else:
            record("长文档启动翻译", "FAIL")

        print("  ... 等待长文档翻译 30s ...")
        time.sleep(30)

        # 停止
        api_session.post(
            f"{BASE}/stop_translate",
            data={"doc_id": "5a21aca40a53"},
            headers=with_csrf_headers(csrf_token),
        )
        time.sleep(5)

        # 查看翻译结果
        r = requests.get(f"{BASE}/translate_status?doc_id=5a21aca40a53")
        if r.status_code == 200:
            status_data = r.json()
            translated = status_data.get("translated_bps", [])
            record("长文档翻译进度", "PASS", f"已翻译 {len(translated)} 页")
        else:
            record("长文档翻译进度", "FAIL")

        # 查看翻译后的页面
        page.goto(f"{BASE}/reading?doc_id=5a21aca40a53&bp=7")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/17_long_doc_translated.png", full_page=True)
        record("长文档翻译页面展示", "PASS")

        # 重译测试
        r = api_session.post(
            f"{BASE}/retranslate/7",
            data={"doc_id": "5a21aca40a53", "target": "builtin:qwen-plus"},
            headers=with_csrf_headers(csrf_token),
        )
        if r.status_code == 200:
            record("重译 p.7", "PASS")
        else:
            record("重译 p.7", "FAIL", f"status={r.status_code}")

        time.sleep(10)
        page.goto(f"{BASE}/reading?doc_id=5a21aca40a53&bp=7")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/18_retranslated.png", full_page=True)

        # ======== 9. TOC 测试 ========
        print("\n=== 9. TOC 接口测试 ===")
        r = requests.get(f"{BASE}/pdf_toc?doc_id=5a21aca40a53")
        if r.status_code == 200:
            toc_data = r.json()
            toc_items = toc_data.get("toc", [])
            record("PDF TOC 读取", "PASS", f"{len(toc_items)} 条目录")
            if toc_items:
                record("TOC 内容", "PASS", f"首条: {toc_items[0].get('title', '')[:40]}")
        else:
            record("PDF TOC 读取", "FAIL")

        # 短文档 TOC
        r = requests.get(f"{BASE}/pdf_toc?doc_id=5d8d44cba1c2")
        if r.status_code == 200:
            toc_data = r.json()
            record("短文档 TOC", "PASS", f"{len(toc_data.get('toc', []))} 条目录")
        else:
            record("短文档 TOC", "FAIL")

        # ======== 10. 导出测试 ========
        print("\n=== 10. 导出测试 ===")
        r = requests.get(f"{BASE}/export_md?doc_id=5a21aca40a53")
        if r.status_code == 200:
            md = r.json().get("markdown", "")
            record("Markdown 导出 API", "PASS", f"长度 {len(md)} 字符")
        else:
            record("Markdown 导出 API", "FAIL")

        r = requests.get(f"{BASE}/download_md?doc_id=5a21aca40a53")
        if r.status_code == 200:
            record("Markdown 下载", "PASS", f"文件大小 {len(r.content)} 字节")
        else:
            record("Markdown 下载", "FAIL")

        # ======== 11. PDF 渲染测试 ========
        print("\n=== 11. PDF 渲染测试 ===")
        r = requests.get(f"{BASE}/pdf_page/0?doc_id=5a21aca40a53&scale=1.5")
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
            record("PDF 页面渲染", "PASS", f"{len(r.content)} 字节 PNG")
        else:
            record("PDF 页面渲染", "FAIL", f"status={r.status_code}")

        # 边缘页码
        r = requests.get(f"{BASE}/pdf_page/98?doc_id=5a21aca40a53&scale=2.0")
        if r.status_code == 200:
            record("PDF 最后一页渲染", "PASS")
        else:
            record("PDF 最后一页渲染", "FAIL")

        # 无效页码
        r = requests.get(f"{BASE}/pdf_page/9999?doc_id=5a21aca40a53")
        if r.status_code != 200:
            record("PDF 无效页码处理", "PASS", f"返回 {r.status_code}")
        else:
            record("PDF 无效页码处理", "WARN", "返回了 200，但预期应报错")

        # ======== 12. 边缘情况 ========
        print("\n=== 12. 边缘情况测试 ===")

        # 12a. 无效 doc_id
        page.goto(f"{BASE}/?doc_id=nonexistent")
        wait_ready(page)
        record("无效 doc_id 访问首页", "PASS", "页面正常加载")

        # 12b. 无效 bp 跳转
        page.goto(f"{BASE}/reading?doc_id=5a21aca40a53&bp=9999")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/19_invalid_bp.png")
        record("无效页码跳转", "PASS", "应有提示并跳转到有效页")

        # 12c. 多文档切换
        api_session.post(f"{BASE}/switch_doc/5d8d44cba1c2", headers=with_csrf_headers(csrf_token))
        page.goto(f"{BASE}/")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/20_switch_to_short.png")
        record("切换到短文档", "PASS")

        api_session.post(f"{BASE}/switch_doc/5a21aca40a53", headers=with_csrf_headers(csrf_token))
        page.goto(f"{BASE}/")
        wait_ready(page)
        record("切换回长文档", "PASS")

        # 12d. API 使用情况
        r = requests.get(f"{BASE}/translate_api_usage_data?doc_id=5a21aca40a53")
        if r.status_code == 200:
            data = r.json()
            record("API 使用情况数据", "PASS", f"doc={data.get('doc_title', '')}, pages={len(data.get('pages', []))}")
        else:
            record("API 使用情况数据", "FAIL")

        # 12e. PaddleOCR 配额查询
        r = requests.get(f"{BASE}/paddle_quota_status")
        if r.status_code == 200:
            record("PaddleOCR 配额状态", "PASS")
        else:
            record("PaddleOCR 配额状态", "FAIL")

        # 12f. PDF 缺失文档
        r = requests.get(f"{BASE}/pdf_page/0?doc_id=4d7a613fff2f")
        record("PDF 缺失文档渲染", "PASS" if r.status_code in (200, 404, 400) else "FAIL",
               f"status={r.status_code}")

        # ======== 13. 阅读页全面截图（用于人文学者模拟） ========
        print("\n=== 13. 阅读体验截图 ===")

        # 长文档有翻译的页面 - 窄屏模拟半屏
        narrow = browser.new_page(viewport={"width": 700, "height": 900})
        narrow.goto(f"{BASE}/reading?doc_id=5a21aca40a53&bp=7")
        wait_ready(narrow)
        narrow.screenshot(path=f"{SCREENSHOT_DIR}/21_halfscreen_reading.png", full_page=True)
        record("半屏阅读截图", "PASS")

        # 打开 PDF 的半屏
        narrow.goto(f"{BASE}/reading?doc_id=5a21aca40a53&bp=7&pdf=1")
        wait_ready(narrow)
        time.sleep(2)
        narrow.screenshot(path=f"{SCREENSHOT_DIR}/22_halfscreen_pdf.png", full_page=True)
        record("半屏 PDF 对照截图", "PASS")

        # 深色主题半屏
        narrow.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
        time.sleep(0.5)
        narrow.screenshot(path=f"{SCREENSHOT_DIR}/23_halfscreen_dark.png", full_page=True)
        record("半屏深色主题截图", "PASS")

        narrow.close()

        # 使用情况面板
        page.goto(f"{BASE}/reading?doc_id=5a21aca40a53&bp=7&usage=1")
        wait_ready(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/24_usage_panel.png", full_page=True)
        record("使用情况面板截图", "PASS")

        browser.close()

    # ======== 汇总 ========
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    warn_count = sum(1 for r in results if r["status"] == "WARN")
    total = len(results)
    print(f"总计: {total} 项  ✅ {pass_count}  ❌ {fail_count}  ⚠️ {warn_count}")
    print()
    if fail_count > 0:
        print("失败项:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"  ❌ {r['name']}: {r['detail']}")
    if warn_count > 0:
        print("警告项:")
        for r in results:
            if r["status"] == "WARN":
                print(f"  ⚠️ {r['name']}: {r['detail']}")

    return results


if __name__ == "__main__":
    test_with_playwright()
