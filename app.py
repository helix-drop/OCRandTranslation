"""外文文献阅读器 Flask 入口。"""

from __future__ import annotations

import os
import sys

from config import LOCAL_DATA_DIR, check_write_permission, ensure_dirs
from persistence.sqlite_bootstrap import initialize_runtime_databases
from web.app_factory import create_app


app = create_app()


def main() -> int:
    can_write, error_msg = check_write_permission()
    if not can_write:
        print("=" * 60)
        print("错误：无法访问数据目录")
        print("=" * 60)
        print(error_msg)
        print("-" * 60)
        print(f"数据目录: {LOCAL_DATA_DIR}")
        print("=" * 60)
        return 1

    ensure_dirs()
    initialize_runtime_databases(include_legacy_app_db=False)
    print(f"数据目录: {LOCAL_DATA_DIR}")
    session_log_path = os.environ.get("APP_SESSION_LOG_PATH", "").strip()
    if session_log_path:
        print(f"会话日志: {session_log_path}")
    debug_env = os.getenv("FLASK_DEBUG", "").strip().lower()
    debug_mode = debug_env in ("1", "true", "yes", "on")
    app.run(debug=debug_mode, port=8080, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
