#!/usr/bin/env python3
"""受控启动器脚本测试。"""

from __future__ import annotations

import unittest
from pathlib import Path

import managed_launcher


ROOT = Path(__file__).resolve().parent


class ManagedLauncherTest(unittest.TestCase):
    def test_launcher_scripts_are_ascii_only_for_cross_platform_shells(self):
        script_names = [
            "start_managed.sh",
            "start_managed.ps1",
            "start_managed.bat",
            "managed_launcher.py",
        ]

        for script_name in script_names:
            with self.subTest(script_name=script_name):
                content = (ROOT / script_name).read_text(encoding="utf-8")
                self.assertTrue(
                    content.isascii(),
                    f"{script_name} must stay ASCII-only to avoid PowerShell encoding issues",
                )

    def test_legacy_launcher_scripts_have_been_removed(self):
        for script_name in ("start.sh", "start.ps1", "start.bat"):
            with self.subTest(script_name=script_name):
                self.assertFalse((ROOT / script_name).exists())

    def test_build_browser_command_for_macos_uses_app_mode_and_temp_profile(self):
        profile_root = "/" + "tmp"
        cmd = managed_launcher.build_browser_command(
            system="Darwin",
            browser_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            profile_dir=f"{profile_root}/ocr-reader-profile",
            url="http://localhost:8080",
        )

        self.assertEqual(cmd[0], "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        self.assertIn(f"--user-data-dir={profile_root}/ocr-reader-profile", cmd)
        self.assertIn("--new-window", cmd)
        self.assertIn("http://localhost:8080", cmd)

    def test_build_browser_command_for_windows_uses_app_mode_and_temp_profile(self):
        cmd = managed_launcher.build_browser_command(
            system="Windows",
            browser_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            profile_dir=r"C:\Temp\ocr-reader-profile",
            url="http://localhost:8080",
        )

        self.assertEqual(cmd[0], r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        self.assertIn(r"--user-data-dir=C:\Temp\ocr-reader-profile", cmd)
        self.assertIn("--new-window", cmd)
        self.assertIn("http://localhost:8080", cmd)

    def test_start_managed_wrappers_delegate_to_managed_launcher(self):
        shell_script = (ROOT / "start_managed.sh").read_text(encoding="utf-8")
        powershell_script = (ROOT / "start_managed.ps1").read_text(encoding="utf-8")
        batch_script = (ROOT / "start_managed.bat").read_text(encoding="utf-8")

        self.assertIn("managed_launcher.py", powershell_script)
        self.assertIn("start_managed.ps1", batch_script)
        self.assertIn("OCR Reader (normal browser mode)", shell_script)


if __name__ == "__main__":
    unittest.main()
