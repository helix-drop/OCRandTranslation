#!/usr/bin/env python3
"""测试辅助：CSRF token 提取与请求封装。"""

from __future__ import annotations

import re


_CSRF_META_RE = re.compile(r'<meta name="csrf-token" content="([^"]+)"')


def extract_csrf_token(html: str) -> str:
    match = _CSRF_META_RE.search(str(html or ""))
    if not match:
        raise AssertionError("未在 HTML 中找到 CSRF token")
    return match.group(1)


def prime_requests_csrf(session, base_url: str, path: str = "/") -> str:
    resp = session.get(base_url.rstrip("/") + path)
    resp.raise_for_status()
    return extract_csrf_token(resp.text)


def with_csrf_headers(token: str, headers: dict | None = None) -> dict:
    merged = dict(headers or {})
    merged["X-CSRF-Token"] = str(token or "")
    return merged


class ClientCSRFMixin:
    """给 Flask test_client 注入 CSRF token 的便捷封装。"""

    client = None

    def _ensure_csrf_token(self) -> str:
        if self.client is None:
            raise AssertionError("client 尚未初始化")
        with self.client.session_transaction() as sess:
            token = str(sess.get("_csrf_token") or "test-csrf-token")
            sess["_csrf_token"] = token
            return token

    def _post(self, url: str, data: dict | None = None, **kwargs):
        payload = dict(data or {})
        payload.setdefault("_csrf_token", self._ensure_csrf_token())
        return self.client.post(url, data=payload, **kwargs)

    def _post_json(self, url: str, json: dict | None = None, headers: dict | None = None, **kwargs):
        return self.client.post(
            url,
            json=json,
            headers=with_csrf_headers(self._ensure_csrf_token(), headers),
            **kwargs,
        )

    def _put_json(self, url: str, json: dict | None = None, headers: dict | None = None, **kwargs):
        return self.client.put(
            url,
            json=json,
            headers=with_csrf_headers(self._ensure_csrf_token(), headers),
            **kwargs,
        )

    def _delete(self, url: str, headers: dict | None = None, **kwargs):
        return self.client.delete(
            url,
            headers=with_csrf_headers(self._ensure_csrf_token(), headers),
            **kwargs,
        )
