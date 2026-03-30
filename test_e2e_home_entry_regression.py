#!/usr/bin/env python3
"""首页进入阅读链路的浏览器级回归测试。"""

from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
import config
from config import ensure_dirs, list_docs
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server


ROOT = Path(__file__).resolve().parent
LIVE_USER_DATA_DIR = ROOT / "local_data" / "user_data"
REAL_DOC_FIXTURES = [
    {
        "slug": "michel_foucault",
        "name": "2011 - Michel Foucault.pdf",
        "page_count": 423,
        "toc_source": "user",
        "expect_toc_menu": True,
    },
    {
        "slug": "swidler",
        "name": "Talk of love _ how culture matters -- Swidler, Ann, 1944- -- Paperback ed, Chicago, post 20056], 2003 -- The University Of Chicago Press -- 9780226786902 -- eaecedd9f3cf957295f83e50e8239189 -- Anna’s Archive.pdf",
        "page_count": 316,
        "toc_source": "auto",
        "expect_toc_menu": False,
    },
]
WATCHED_ENDPOINT_KEYWORDS = (
    "/start_translate_all",
    "/translate_status",
    "/translate_api_usage_data",
    "/pdf_page/",
    "/pdf_toc",
    "/api/toc/set_offset",
    "/imgs/",
)
INVALID_DOC_IDS = {"", "undefined", "null", "None", None}


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _ServerThread(threading.Thread):
    def __init__(self, app, host: str, port: int):
        super().__init__(daemon=True)
        self._server = make_server(host, port, app, threaded=True)

    def run(self):
        self._server.serve_forever()

    def shutdown(self):
        self._server.shutdown()


class HomeEntryRegressionE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = tempfile.mkdtemp(prefix="home-entry-e2e-")
        cls._clone_live_user_data(cls.temp_root)
        cls._patch_config_dirs(os.path.join(cls.temp_root, "user_data"))
        ensure_dirs()
        cls.artifact_dir = Path(tempfile.gettempdir()) / "home_entry_regression_artifacts" / time.strftime("%Y%m%d-%H%M%S")
        cls.artifact_dir.mkdir(parents=True, exist_ok=True)
        cls.doc_fixtures = cls._load_doc_fixtures()
        cls._patchers = [
            patch.object(
                app_module,
                "get_translate_args",
                return_value={
                    "model_id": "regression-fake-model",
                    "api_key": "regression-fake-key",
                    "provider": "fake",
                    "display_label": "Regression Fake Model",
                },
            ),
            patch.object(app_module, "start_translate_task", return_value=True),
        ]
        for patcher in cls._patchers:
            patcher.start()

        cls.port = _find_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server = _ServerThread(app_module.app, "127.0.0.1", cls.port)
        cls.server.start()
        cls._wait_for_server_ready()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.shutdown()
            cls.server.join(timeout=2.0)
        for patcher in getattr(cls, "_patchers", []):
            patcher.stop()
        shutil.rmtree(getattr(cls, "temp_root", ""), ignore_errors=True)

    @classmethod
    def _patch_config_dirs(cls, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    @classmethod
    def _clone_live_user_data(cls, root: str):
        if not LIVE_USER_DATA_DIR.exists():
            raise AssertionError(f"当前用户库不存在: {LIVE_USER_DATA_DIR}")
        target = Path(root) / "user_data"
        shutil.copytree(LIVE_USER_DATA_DIR, target, dirs_exist_ok=True)

    @classmethod
    def _wait_for_server_ready(cls):
        import requests

        deadline = time.time() + 10.0
        last_error = ""
        while time.time() < deadline:
            try:
                resp = requests.get(cls.base_url + "/", timeout=0.5)
                if resp.status_code == 200:
                    return
            except Exception as exc:  # pragma: no cover - 仅用于启动期重试
                last_error = str(exc)
            time.sleep(0.1)
        raise AssertionError(f"测试服务未能按时启动: {last_error}")

    @classmethod
    def _load_doc_fixtures(cls) -> list[dict]:
        docs_by_name = {item.get("name"): item for item in list_docs()}
        fixtures = []
        missing = []
        for spec in REAL_DOC_FIXTURES:
            meta = docs_by_name.get(spec["name"])
            if not meta:
                missing.append(spec["name"])
                continue
            doc_id = meta["id"]
            source_pdf = Path(config.DOCS_DIR) / doc_id / "source.pdf"
            if not source_pdf.exists():
                raise AssertionError(f"真实文档缺少 source.pdf: {source_pdf}")
            actual_page_count = int(meta.get("page_count", 0) or 0)
            if actual_page_count != spec["page_count"]:
                raise AssertionError(
                    f"{spec['name']} 页数不符: 期望 {spec['page_count']}，实际 {actual_page_count}"
                )
            actual_toc_source = str(meta.get("toc_source") or "auto")
            if actual_toc_source != spec["toc_source"]:
                raise AssertionError(
                    f"{spec['name']} toc_source 不符: 期望 {spec['toc_source']}，实际 {actual_toc_source}"
                )
            fixtures.append({
                "slug": spec["slug"],
                "name": spec["name"],
                "doc_id": doc_id,
                "page_count": actual_page_count,
                "toc_source": actual_toc_source,
                "expect_toc_menu": spec["expect_toc_menu"],
            })
        if missing:
            raise AssertionError("当前用户库缺少指定真实文档:\n" + "\n".join(missing))
        return fixtures

    def test_home_entry_preserves_doc_id_across_reading_controls_for_real_docs(self):
        report = {
            "base_url": self.base_url,
            "artifact_dir": str(self.artifact_dir),
            "docs": [],
        }
        failures: list[str] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            all_dialogs = []
            all_console = []
            all_pageerrors = []
            all_responses = []
            current_step = {"name": "boot"}

            def on_dialog(dialog):
                all_dialogs.append({
                    "step": current_step["name"],
                    "type": dialog.type,
                    "message": dialog.message,
                })
                dialog.accept()

            def on_console(msg):
                if msg.type not in {"warning", "error"}:
                    return
                all_console.append({
                    "step": current_step["name"],
                    "type": msg.type,
                    "text": msg.text,
                })

            def on_pageerror(err):
                all_pageerrors.append({
                    "step": current_step["name"],
                    "message": str(err),
                })

            def on_response(resp):
                if not any(key in resp.url for key in WATCHED_ENDPOINT_KEYWORDS):
                    return
                content_type = resp.headers.get("content-type", "")
                summary = ""
                if "application/json" in content_type or "text/" in content_type:
                    try:
                        summary = resp.text()[:300]
                    except Exception:  # pragma: no cover - 仅用于诊断采样
                        summary = ""
                elif "image/" in content_type:
                    summary = content_type
                all_responses.append({
                    "step": current_step["name"],
                    "url": resp.url,
                    "status": resp.status,
                    "content_type": content_type,
                    "summary": summary,
                })

            page.on("dialog", on_dialog)
            page.on("console", on_console)
            page.on("pageerror", on_pageerror)
            page.on("response", on_response)

            for doc in self.doc_fixtures:
                doc_report = {
                    "name": doc["name"],
                    "doc_id": doc["doc_id"],
                    "steps": [],
                }
                report["docs"].append(doc_report)
                current_step["name"] = f"{doc['slug']}::home_open"
                page.goto(self.base_url + "/")
                self._wait_for_home(page)
                self._capture_step(
                    page=page,
                    doc=doc,
                    step_name="home_open",
                    doc_report=doc_report,
                    all_dialogs=all_dialogs,
                    all_console=all_console,
                    all_pageerrors=all_pageerrors,
                    all_responses=all_responses,
                    current_step=current_step,
                )

                doc_item = page.locator(".doc-item").filter(has_text=doc["name"]).first
                if doc_item.count() != 1:
                    failures.append(f"{doc['name']} / 首页文档列表未找到唯一条目")
                    self._save_html_dump(page, doc, "home_missing_doc_item")
                    continue

                is_current = doc_item.locator(".doc-current-badge").count() > 0
                if not is_current:
                    current_step["name"] = f"{doc['slug']}::home_switch"
                    with page.expect_navigation(wait_until="networkidle"):
                        doc_item.get_by_role("button", name="切换").click()
                    switch_step = self._capture_step(
                        page=page,
                        doc=doc,
                        step_name="home_switch",
                        doc_report=doc_report,
                        all_dialogs=all_dialogs,
                        all_console=all_console,
                        all_pageerrors=all_pageerrors,
                        all_responses=all_responses,
                        current_step=current_step,
                    )
                    self._check_home_selected(doc, switch_step, failures, page)

                start_link = page.locator("a[data-reading-entry='1']").filter(has_text="从 PDF").first
                href = start_link.get_attribute("href") or ""
                if doc["doc_id"] not in href:
                    failures.append(f"{doc['name']} / 首页开始阅读链接未携带正确 doc_id: {href}")
                    self._save_html_dump(page, doc, "home_start_link_missing_doc_id")

                current_step["name"] = f"{doc['slug']}::reading_from_home"
                with page.expect_navigation(wait_until="load"):
                    start_link.click()
                reading_step = self._capture_step(
                    page=page,
                    doc=doc,
                    step_name="reading_from_home",
                    doc_report=doc_report,
                    all_dialogs=all_dialogs,
                    all_console=all_console,
                    all_pageerrors=all_pageerrors,
                    all_responses=all_responses,
                    current_step=current_step,
                    reading_page=True,
                    wait_for_auto_sync=True,
                )
                self._check_reading_state(doc, reading_step, failures, page, require_pdf_success=False)
                self._check_response_statuses(doc, reading_step, failures, page, endpoints=("/start_translate_all", "/translate_status", "/imgs/"))

                current_step["name"] = f"{doc['slug']}::after_usage"
                page.locator("#usageBtn").click()
                usage_step = self._capture_step(
                    page=page,
                    doc=doc,
                    step_name="after_usage",
                    doc_report=doc_report,
                    all_dialogs=all_dialogs,
                    all_console=all_console,
                    all_pageerrors=all_pageerrors,
                    all_responses=all_responses,
                    current_step=current_step,
                    reading_page=True,
                )
                self._check_reading_state(doc, usage_step, failures, page, require_pdf_success=False)
                self._check_no_dialog(doc, usage_step, failures, page, "刷新用量面板失败")
                self._check_response_statuses(doc, usage_step, failures, page, endpoints=("/translate_api_usage_data",))

                current_step["name"] = f"{doc['slug']}::after_orig"
                page.locator("#origBtn").click()
                orig_step = self._capture_step(
                    page=page,
                    doc=doc,
                    step_name="after_orig",
                    doc_report=doc_report,
                    all_dialogs=all_dialogs,
                    all_console=all_console,
                    all_pageerrors=all_pageerrors,
                    all_responses=all_responses,
                    current_step=current_step,
                    reading_page=True,
                )
                self._check_reading_state(doc, orig_step, failures, page, require_pdf_success=False)

                pdf_btn = page.locator("#pdfBtn")
                if pdf_btn.count() > 0:
                    current_step["name"] = f"{doc['slug']}::after_pdf"
                    pdf_btn.click()
                    pdf_step = self._capture_step(
                        page=page,
                        doc=doc,
                        step_name="after_pdf",
                        doc_report=doc_report,
                        all_dialogs=all_dialogs,
                        all_console=all_console,
                        all_pageerrors=all_pageerrors,
                        all_responses=all_responses,
                        current_step=current_step,
                        reading_page=True,
                        wait_for_pdf_image=True,
                    )
                    self._check_reading_state(doc, pdf_step, failures, page, require_pdf_success=True)
                    self._check_response_statuses(doc, pdf_step, failures, page, endpoints=("/pdf_page/",))

                if doc.get("expect_toc_menu"):
                    toc_btn = page.locator("#tocBtn")
                    if toc_btn.count() < 1:
                        dump = self._save_html_dump(page, doc, "missing_toc_menu")
                        failures.append(f"{doc['name']} / 阅读页未出现目录按钮 / HTML: {dump}")
                    else:
                        current_step["name"] = f"{doc['slug']}::after_toc_jump"
                        toc_btn.click()
                        enabled_toc_item = page.locator(".toc-item:not([disabled])").first
                        if enabled_toc_item.count() < 1:
                            dump = self._save_html_dump(page, doc, "missing_toc_item")
                            failures.append(f"{doc['name']} / 目录菜单无可跳转条目 / HTML: {dump}")
                        else:
                            enabled_toc_item.click()
                            toc_step = self._capture_step(
                                page=page,
                                doc=doc,
                                step_name="after_toc_jump",
                                doc_report=doc_report,
                                all_dialogs=all_dialogs,
                                all_console=all_console,
                                all_pageerrors=all_pageerrors,
                                all_responses=all_responses,
                                current_step=current_step,
                                reading_page=True,
                            )
                            self._check_reading_state(doc, toc_step, failures, page, require_pdf_success=False)

            browser.close()

        report_path = self.artifact_dir / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if failures:
            self.fail("首页进入阅读浏览器回归失败:\n- " + "\n- ".join(failures) + f"\n诊断报告: {report_path}")

    def test_home_entry_initial_doc_id_probe(self):
        doc = self.doc_fixtures[0]
        probe_path = self.artifact_dir / "initial_probe.json"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            pageerrors = []

            def on_pageerror(err):
                pageerrors.append(str(err))

            page.on("pageerror", on_pageerror)
            page.goto(self.base_url + "/")
            self._wait_for_home(page)
            doc_item = page.locator(".doc-item").filter(has_text=doc["name"]).first
            if doc_item.locator(".doc-current-badge").count() < 1:
                with page.expect_navigation(wait_until="networkidle"):
                    doc_item.get_by_role("button", name="切换").click()
            start_link = page.locator("a[data-reading-entry='1']").filter(has_text="从 PDF").first
            with page.expect_navigation(wait_until="load"):
                start_link.click()
            self._wait_for_reading(page, wait_for_auto_sync=True)
            state = self._collect_page_state(page)
            payload = {
                "doc": doc,
                "state": state,
                "pageerrors": pageerrors,
                "url": page.url,
            }
            probe_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            browser.close()

        self.assertEqual(doc["doc_id"], state["url_doc_id"], f"URL doc_id 异常，见 {probe_path}")
        self.assertEqual(doc["doc_id"], state["lexical_current_doc_id"], f"词法 currentDocId 异常，见 {probe_path}")
        self.assertEqual(doc["doc_id"], state["current_doc_id"], f"window.currentDocId 异常，见 {probe_path}")
        self.assertEqual([], pageerrors, f"阅读页脚本报错，见 {probe_path}")

    def test_swidler_reading_flow_skips_placeholder_pages(self):
        doc = next(item for item in self.doc_fixtures if item["slug"] == "swidler")
        expected_sequence = [1, 3, 5, 6, 9]
        report_path = self.artifact_dir / "swidler_placeholder_skip.json"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.goto(self.base_url + "/")
            self._wait_for_home(page)

            doc_item = page.locator(".doc-item").filter(has_text=doc["name"]).first
            if doc_item.locator(".doc-current-badge").count() < 1:
                with page.expect_navigation(wait_until="networkidle"):
                    doc_item.get_by_role("button", name="切换").click()

            start_link = page.locator("a[data-reading-entry='1']").filter(has_text="从 PDF").first
            with page.expect_navigation(wait_until="load"):
                start_link.click()
            self._wait_for_reading(page, wait_for_auto_sync=True)

            observed_bps = [int(page.evaluate("() => Number(new URL(window.location.href).searchParams.get('bp') || 0)"))]
            initial_html = page.content()
            self.assertNotIn('data-page-bp="2"', initial_html, report_path)
            self.assertNotIn('data-page-bp="4"', initial_html, report_path)
            self.assertNotIn('data-page-bp="7"', initial_html, report_path)
            self.assertNotIn('data-page-bp="8"', initial_html, report_path)
            self.assertNotIn('data-page-bp="10"', initial_html, report_path)
            self.assertNotIn('data-pdf-bp="2"', initial_html, report_path)
            self.assertNotIn('data-pdf-bp="4"', initial_html, report_path)
            self.assertNotIn('data-pdf-bp="7"', initial_html, report_path)
            self.assertNotIn('data-pdf-bp="8"', initial_html, report_path)
            self.assertNotIn('data-pdf-bp="10"', initial_html, report_path)

            for _ in expected_sequence[1:]:
                next_btn = page.locator("a.floating-page-nav-btn.next").first
                with page.expect_navigation(wait_until="load"):
                    next_btn.click()
                self._wait_for_reading(page, wait_for_auto_sync=False)
                observed_bps.append(
                    int(page.evaluate("() => Number(new URL(window.location.href).searchParams.get('bp') || 0)"))
                )

            payload = {
                "doc": doc,
                "expected_sequence": expected_sequence,
                "observed_bps": observed_bps,
                "final_url": page.url,
            }
            report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            browser.close()

        self.assertEqual(expected_sequence, observed_bps, f"Swidler 翻页未正确跳过空页，见 {report_path}")

    def _capture_step(
        self,
        *,
        page,
        doc: dict,
        step_name: str,
        doc_report: dict,
        all_dialogs: list[dict],
        all_console: list[dict],
        all_pageerrors: list[dict],
        all_responses: list[dict],
        current_step: dict,
        reading_page: bool = False,
        wait_for_auto_sync: bool = False,
        wait_for_pdf_image: bool = False,
    ) -> dict:
        dialog_start = len(all_dialogs)
        console_start = len(all_console)
        pageerror_start = len(all_pageerrors)
        response_start = len(all_responses)
        if reading_page:
            self._wait_for_reading(page, wait_for_auto_sync=wait_for_auto_sync)
            if wait_for_pdf_image:
                try:
                    page.wait_for_function(
                        """
                        () => Array.from(document.querySelectorAll('img.pdf-img'))
                          .some(img => img.complete && img.naturalWidth > 0)
                        """,
                        timeout=4000,
                    )
                except PlaywrightTimeoutError:
                    pass
        else:
            self._wait_for_home(page)

        screenshot = self._save_screenshot(page, doc, step_name)
        state = self._collect_page_state(page)
        step = {
            "step": step_name,
            "state": state,
            "dialogs": all_dialogs[dialog_start:],
            "console": all_console[console_start:],
            "pageerrors": all_pageerrors[pageerror_start:],
            "responses": all_responses[response_start:],
            "screenshot": screenshot,
        }
        doc_report["steps"].append(step)
        current_step["name"] = f"{doc['slug']}::{step_name}::captured"
        return step

    def _wait_for_home(self, page):
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)

    def _wait_for_reading(self, page, *, wait_for_auto_sync: bool):
        page.wait_for_load_state("load")
        try:
            page.wait_for_function("() => typeof window.currentDocId !== 'undefined'", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        if wait_for_auto_sync:
            try:
                page.wait_for_function(
                    "() => new URL(window.location.href).searchParams.get('auto') !== '1'",
                    timeout=4000,
                )
            except PlaywrightTimeoutError:
                pass
        page.wait_for_timeout(1600)

    def _collect_page_state(self, page) -> dict:
        return page.evaluate(
            """
            () => {
              const params = new URLSearchParams(window.location.search);
              const lexicalCurrentDocId = (() => {
                try {
                  return window.eval("typeof currentDocId === 'undefined' ? '__undefined__' : String(currentDocId)");
                } catch (err) {
                  return '__error__:' + String(err);
                }
              })();
              const windowCurrentDocId = typeof window.currentDocId === 'undefined'
                ? '__undefined__'
                : String(window.currentDocId);
              const bodyText = document.body ? document.body.innerText : '';
              const pdfImages = Array.from(document.querySelectorAll('img.pdf-img'));
              const tocItems = Array.from(document.querySelectorAll('.toc-item'));
              return {
                url: window.location.href,
                path: window.location.pathname,
                query: window.location.search,
                lexical_current_doc_id: lexicalCurrentDocId,
                current_doc_id: windowCurrentDocId,
                url_doc_id: params.get('doc_id'),
                auto: params.get('auto'),
                start_bp: params.get('start_bp'),
                usage: params.get('usage'),
                orig: params.get('orig'),
                pdf: params.get('pdf'),
                body_has_missing_doc: bodyText.includes('未找到当前文档'),
                body_has_start_fail: bodyText.includes('启动失败'),
                body_has_usage_fail: bodyText.includes('刷新用量面板失败'),
                loaded_pdf_images: pdfImages.filter(img => img.complete && img.naturalWidth > 0).length,
                pdf_button_visible: !!document.querySelector('#pdfBtn'),
                toc_button_visible: !!document.querySelector('#tocBtn'),
                enabled_toc_items: tocItems.filter(item => !item.disabled).length,
              };
            }
            """
        )

    def _save_screenshot(self, page, doc: dict, step_name: str) -> str:
        path = self.artifact_dir / f"{doc['slug']}_{step_name}.png"
        page.screenshot(path=str(path), full_page=True)
        return str(path)

    def _save_html_dump(self, page, doc: dict, step_name: str) -> str:
        path = self.artifact_dir / f"{doc['slug']}_{step_name}.html"
        path.write_text(page.content(), encoding="utf-8")
        return str(path)

    def _check_home_selected(self, doc: dict, step: dict, failures: list[str], page):
        body = page.locator(".doc-item").filter(has_text=doc["name"]).first
        if body.locator(".doc-current-badge").count() > 0:
            return
        dump = self._save_html_dump(page, doc, step["step"])
        failures.append(f"{doc['name']} / 切换后首页未标记为当前文档，HTML: {dump}")

    def _check_reading_state(self, doc: dict, step: dict, failures: list[str], page, *, require_pdf_success: bool):
        state = step["state"]
        expected_doc_id = doc["doc_id"]
        if state["current_doc_id"] in INVALID_DOC_IDS or state["current_doc_id"] != expected_doc_id:
            dump = self._save_html_dump(page, doc, step["step"])
            failures.append(
                f"{doc['name']} / {step['step']} / window.currentDocId 异常: {state['current_doc_id']} / lexical={state['lexical_current_doc_id']} / 期望 {expected_doc_id} / HTML: {dump}"
            )
        if state["url_doc_id"] in INVALID_DOC_IDS or state["url_doc_id"] != expected_doc_id:
            dump = self._save_html_dump(page, doc, step["step"])
            failures.append(
                f"{doc['name']} / {step['step']} / URL doc_id 异常: {state['url_doc_id']} / 期望 {expected_doc_id} / HTML: {dump}"
            )
        if state["body_has_missing_doc"] or state["body_has_start_fail"] or state["body_has_usage_fail"]:
            dump = self._save_html_dump(page, doc, step["step"])
            failures.append(
                f"{doc['name']} / {step['step']} / 页面文案出现当前文档异常或启动失败 / HTML: {dump}"
            )
        if step["pageerrors"]:
            dump = self._save_html_dump(page, doc, step["step"])
            failures.append(
                f"{doc['name']} / {step['step']} / 页面脚本报错: {step['pageerrors'][0]['message']} / HTML: {dump}"
            )
        self._check_no_dialog(doc, step, failures, page, "未找到当前文档")
        if doc.get("expect_toc_menu") and not state["toc_button_visible"]:
            dump = self._save_html_dump(page, doc, step["step"])
            failures.append(f"{doc['name']} / {step['step']} / 应出现目录按钮但未出现 / HTML: {dump}")
        if require_pdf_success and state["loaded_pdf_images"] < 1:
            dump = self._save_html_dump(page, doc, step["step"])
            failures.append(f"{doc['name']} / {step['step']} / PDF 图片未成功加载 / HTML: {dump}")

    def _check_no_dialog(self, doc: dict, step: dict, failures: list[str], page, keyword: str):
        bad = [item for item in step["dialogs"] if keyword in item["message"]]
        if not bad:
            return
        dump = self._save_html_dump(page, doc, step["step"])
        failures.append(
            f"{doc['name']} / {step['step']} / 弹窗出现“{keyword}”: {bad[0]['message']} / HTML: {dump}"
        )

    def _check_response_statuses(self, doc: dict, step: dict, failures: list[str], page, *, endpoints: tuple[str, ...]):
        relevant = [
            item for item in step["responses"]
            if any(endpoint in item["url"] for endpoint in endpoints)
        ]
        for item in relevant:
            if item["status"] < 400:
                continue
            dump = self._save_html_dump(page, doc, step["step"])
            failures.append(
                f"{doc['name']} / {step['step']} / 请求失败 {item['status']} {item['url']} / HTML: {dump}"
            )


if __name__ == "__main__":
    unittest.main()
