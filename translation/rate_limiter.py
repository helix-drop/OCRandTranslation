"""按模型主动节流：RPM / RPD / TPM 滑动窗口。

配置来源：model_capabilities.py 中每个模型的 `rate_limits: {rpm, rpd, tpm}`。
0 表示不限。
"""

import threading
import time
from collections import deque


class RateLimiter:
    """单个模型的速率限制器（线程安全）。

    - rpm: 每分钟最大请求数
    - rpd: 每日最大请求数
    - tpm: 每分钟最大 token 数

    调用 acquire() 会阻塞直到允许通过。
    不主动限制则全部默认 0（不限）。
    """

    def __init__(self, rpm: int = 0, rpd: int = 0, tpm: int = 0):
        self._lock = threading.Lock()
        self._rpm = max(0, int(rpm or 0))
        self._rpd = max(0, int(rpd or 0))
        self._tpm = max(0, int(tpm or 0))

        self._request_times: deque[float] = deque()
        self._daily_request_times: deque[float] = deque()
        self._token_times: deque[tuple[float, int]] = deque()  # (timestamp, token_count)

    def acquire(self, tokens: int = 1, timeout: float = 120.0) -> bool:
        """尝试获取许可。tokens 是预估消耗 token 数。

        返回 True 表示获取成功，False 表示超时。
        """
        if self._rpm <= 0 and self._rpd <= 0 and self._tpm <= 0:
            return True

        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._prune(now)

                # 检查是否可以立即通过
                can_pass = True
                wait_until = 0.0

                if self._rpm > 0 and len(self._request_times) >= self._rpm:
                    can_pass = False
                    wait_until = max(wait_until, self._request_times[0] + 60.0)

                if self._rpd > 0 and len(self._daily_request_times) >= self._rpd:
                    can_pass = False
                    wait_until = max(wait_until, self._daily_request_times[0] + 86400.0)

                if self._tpm > 0 and tokens > 0:
                    current_tokens = sum(t for _, t in self._token_times)
                    if current_tokens + tokens > self._tpm:
                        can_pass = False
                        # 等最早的一批 token 过期
                        if self._token_times:
                            wait_until = max(wait_until, self._token_times[0][0] + 60.0)

                if can_pass:
                    self._request_times.append(now)
                    self._daily_request_times.append(now)
                    if tokens > 0:
                        self._token_times.append((now, tokens))
                    return True

            # 需要等待
            remaining = wait_until - time.monotonic()
            if remaining <= 0:
                continue
            if remaining > (deadline - time.monotonic()):
                return False
            time.sleep(min(remaining, 1.0))

    def _prune(self, now: float) -> None:
        """清理过期窗口。调用方需持有 _lock。"""
        minute_ago = now - 60.0
        day_ago = now - 86400.0

        while self._request_times and self._request_times[0] < minute_ago:
            self._request_times.popleft()
        while self._daily_request_times and self._daily_request_times[0] < day_ago:
            self._daily_request_times.popleft()
        while self._token_times and self._token_times[0][0] < minute_ago:
            self._token_times.popleft()


# 全局模型限流器缓存
_limiters: dict[str, RateLimiter] = {}
_limiters_lock = threading.Lock()


def get_limiter(model_id: str, rpm: int = 0, rpd: int = 0, tpm: int = 0) -> RateLimiter:
    """获取或创建模型对应的限流器。"""
    with _limiters_lock:
        if model_id not in _limiters:
            _limiters[model_id] = RateLimiter(rpm=rpm, rpd=rpd, tpm=tpm)
        return _limiters[model_id]
