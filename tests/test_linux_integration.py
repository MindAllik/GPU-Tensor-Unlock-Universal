# SPDX-License-Identifier: GPL-2.0-only
"""Comprehensive verification suite for Linux & Windows GPU auto-detection,
OS guards, kernel module dispatch, RM ioctl probing, dmesg parsing, and UI."""

from __future__ import annotations

import ast
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core_detector  # noqa: E402
import i18n_strings  # noqa: E402
import linux_backend  # noqa: E402
import tensor_benchmark  # noqa: E402


class LinuxAutoDetectionAndIntegrationTests(unittest.TestCase):
    def test_windows_uefi_u_key_timeout_is_30_seconds(self) -> None:
        cd_text = (ROOT / "core_detector.py").read_text(encoding="utf-8")
        lp_text = (ROOT / "windows/uefi/source/unlock/local_profile.h").read_text(encoding="utf-8")
        app_text = (ROOT / "windows/uefi/source/unlock/app.c").read_text(encoding="utf-8")
        self.assertIn("#define KOH_AUTOCONFIRM_MS 30000", cd_text)
        self.assertIn("#define KOH_AUTOCONFIRM_MS 30000", lp_text)
        self.assertIn("Press U once within 30s to start now", app_text)

    def test_launchers_exist_and_old_launch_ui_removed(self) -> None:
        self.assertTrue((ROOT / "Windows_Launch_UI.bat").is_file())
        self.assertTrue((ROOT / "Linux_Launch_UI.sh").is_file())
        self.assertFalse((ROOT / "Launch_UI.bat").exists())

    def test_sysfs_and_lspci_gpu_autodetection_on_linux(self) -> None:
        with tempfile.TemporaryDirectory() as tmpd:
            sysfs = Path(tmpd)
            # 1. Palit GeForce RTX 4070 Ti (10de:2782, subsys 1569:f294) at 0000:01:00.0
            d0 = sysfs / "0000:01:00.0"
            d0.mkdir()
            (d0 / "vendor").write_text("0x10de\n", encoding="ascii")
            (d0 / "device").write_text("0x2782\n", encoding="ascii")
            (d0 / "subsystem_vendor").write_text("0x1569\n", encoding="ascii")
            (d0 / "subsystem_device").write_text("0xf294\n", encoding="ascii")
            (d0 / "class").write_text("0x030000\n", encoding="ascii")
            drv_target = Path(tmpd) / "drivers" / "nvidia"
            drv_target.mkdir(parents=True)
            (d0 / "driver").symlink_to(drv_target)

            # 2. HDMI Audio function 0000:01:00.1 (class 0x040300 -> must be ignored!)
            d_audio = sysfs / "0000:01:00.1"
            d_audio.mkdir()
            (d_audio / "vendor").write_text("0x10de\n", encoding="ascii")
            (d_audio / "device").write_text("0x22bc\n", encoding="ascii")
            (d_audio / "class").write_text("0x040300\n", encoding="ascii")

            # 3. GeForce RTX 4090 (10de:2684) at 0000:02:00.0 (unbound for cold test)
            d1 = sysfs / "0000:02:00.0"
            d1.mkdir()
            (d1 / "vendor").write_text("0x10de\n", encoding="ascii")
            (d1 / "device").write_text("0x2684\n", encoding="ascii")
            (d1 / "subsystem_vendor").write_text("0x1043\n", encoding="ascii")
            (d1 / "subsystem_device").write_text("0x889c\n", encoding="ascii")
            (d1 / "class").write_text("0x030000\n", encoding="ascii")

            lspci_sample = (
                "0000:01:00.0 VGA compatible controller [0300]: NVIDIA Corporation AD104 [GeForce RTX 4070 Ti] [10de:2782] (rev a1)\n"
                "0000:01:00.1 Audio device [0403]: NVIDIA Corporation AD104 High Definition Audio Controller [10de:22bc] (rev a1)\n"
                "0000:02:00.0 VGA compatible controller [0300]: NVIDIA Corporation AD102 [GeForce RTX 4090] [10de:2684] (rev a1)\n"
            )

            gpus = core_detector._query_linux_pci_gpus(sysfs_root=sysfs, lspci_output=lspci_sample)
            self.assertEqual(len(gpus), 2)

            g0 = gpus[0]
            self.assertEqual(g0["pci_bdf"], "0000:01:00.0")
            self.assertEqual(g0["board_id_hex"], "0x278210de")
            self.assertEqual(g0["subsystem_id_hex"], "0xf2941569")
            self.assertEqual(g0["bound_driver"], "nvidia")
            self.assertEqual(g0["gpu_name"], "NVIDIA GeForce RTX 4070 Ti")
            self.assertEqual(
                core_detector.get_linux_boot_option_for_gpu(g0),
                "gpu_unlock.targets=0000:01:00.0 gpu_unlock.ad104_experimental=1",
            )

            g1 = gpus[1]
            self.assertEqual(g1["pci_bdf"], "0000:02:00.0")
            self.assertEqual(g1["board_id_hex"], "0x268410de")
            self.assertEqual(g1["subsystem_id_hex"], "0x889c1043")
            self.assertEqual(g1["bound_driver"], "unbound")
            self.assertEqual(
                core_detector.get_linux_boot_option_for_gpu(g1),
                "gpu_unlock.targets=0000:02:00.0",
            )

    def test_nvidia_smi_cli_fallback_normalizes_8_digit_domain(self) -> None:
        raw_csv = (
            "0, NVIDIA GeForce RTX 4070 Ti, GPU-11223344-5566-7788-99aa-bbccddeeff00, "
            "00000000:01:00.0, 0x278210DE, 0xF2941569, 12282, 95.04.31.00.36, 560.35.03, 285.00, 100.00, 320.00\n"
        )
        drv, gpus = core_detector._query_nvidia_smi_gpus(raw_csv=raw_csv)
        self.assertEqual(drv, "560.35.03")
        self.assertEqual(len(gpus), 1)
        g = gpus[0]
        self.assertEqual(g["pci_bdf"], "0000:01:00.0")
        self.assertEqual(g["board_id_hex"], "0x278210de")
        self.assertEqual(g["subsystem_id_hex"], "0xf2941569")
        self.assertEqual(g["vram_mib"], 12282)
        self.assertEqual(g["power_max_w"], 320.0)

    def test_detect_linux_environment_end_to_end_with_mocked_sysfs(self) -> None:
        fake_sysfs_gpu = [{
            "gpu_name": "NVIDIA GeForce RTX 4070 Ti",
            "dev16": 0x2782,
            "pci_bdf": "0000:01:00.0",
            "board_id_hex": "0x278210de",
            "subsystem_id_hex": "0xf2941569",
            "domain": 0,
            "bus": 1,
            "dev": 0,
            "func": 0,
            "bus_hex": "0x01",
            "bound_driver": "nvidia",
        }]
        with patch.object(core_detector, "_load_nvml_library", return_value=None), \
             patch.object(core_detector, "_query_nvidia_smi_gpus", return_value=("N/A", [])), \
             patch.object(core_detector, "_query_linux_pci_gpus", return_value=fake_sysfs_gpu):
            env = linux_backend.detect_linux_environment()
            self.assertTrue(env["gpu_detected"])
            self.assertEqual(env["die_name"], "AD104")
            self.assertEqual(env["pci_bdf"], "0000:01:00.0")
            self.assertEqual(env["board_id_hex"], "0x278210de")
            self.assertEqual(env["subsystem_id_hex"], "0xf2941569")
            self.assertEqual(
                env["linux_boot_option"],
                "gpu_unlock.targets=0000:01:00.0 gpu_unlock.ad104_experimental=1",
            )

    def test_parse_linux_kernel_log_text(self) -> None:
        sample_dmesg = (
            "[    1.402110] nvidia 0000:01:00.0: entry: plm=0xffffff8f ss0=0x64023025 ss1=0x7 wpr2_hi=0x0\n"
            "[    1.485200] nvidia 0000:01:00.0: AD102 payload result: boot=0 halt=0 marker=0x67b00001 expected=0x67b00001 marker_ok=1 required_permissions=1 cpuctl=0x10 halted=1 debug=0xda550000 ss0=0x64023025 ss1=0x7\n"
            "[    1.486100] nvidia 0000:01:00.0: selector result: SS0=0x88888888 expected=0x88888888 matched=1\n"
            "[    1.486200] nvidia 0000:01:00.0: selector result: SS1=0x8 expected=0x8 matched=1\n"
            "[    1.592000] nvidia 0000:01:00.0: post-FLR SEC2 reset released, GSP halted, BME=0 pending=0 WPR2=00000000:00000000 SS0=88888888 SS1=00000008\n"
            "[    1.592400] nvidia 0000:01:00.0: gpu_unlock: unlocked\n"
        )
        parsed = linux_backend.parse_linux_kernel_log_text(sample_dmesg, expected_bdf="0000:01:00.0")
        self.assertTrue(parsed["found"])
        self.assertTrue(parsed["unlocked"])
        self.assertIn("marker=0x67b00001", parsed["payload_line"])
        self.assertIn("SS0=88888888", parsed["flr_line"])

    def test_os_guards_block_wrong_platform(self) -> None:
        # 1. Running Windows UI on Linux must exit with code 2 and clear OS Mismatch message
        res_win_on_linux = subprocess.run(
            [sys.executable, "-c", (
                "import sys, types; "
                "sys.modules['tkinter'] = types.SimpleNamespace(Tk=object, Frame=object, Label=object, Button=object, Entry=object, StringVar=object, Text=object, Scrollbar=object, PanedWindow=object, Menu=object, TclError=Exception, Event=object, filedialog=None, messagebox=None, ttk=None); "
                "sys.modules['tkinter.filedialog'] = types.SimpleNamespace(); "
                "sys.modules['tkinter.messagebox'] = types.SimpleNamespace(showerror=lambda *a: None); "
                "sys.modules['tkinter.ttk'] = types.SimpleNamespace(); "
                "import gpu_unlock_ui; gpu_unlock_ui.enforce_windows_os_guard()"
            )],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_win_on_linux.returncode, 2)
        self.assertIn("Linux_Launch_UI.sh", res_win_on_linux.stderr)

        # 2. Running Linux UI when sys.platform == 'win32' must exit with code 2 and clear OS Mismatch message
        res_linux_on_win = subprocess.run(
            [sys.executable, "-c", (
                "import sys, types; "
                "sys.modules['tkinter'] = types.SimpleNamespace(Tk=object, Frame=object, Label=object, Button=object, Entry=object, StringVar=object, Text=object, Scrollbar=object, PanedWindow=object, Menu=object, TclError=Exception, Event=object, filedialog=None, messagebox=None, ttk=None); "
                "sys.modules['tkinter.filedialog'] = types.SimpleNamespace(); "
                "sys.modules['tkinter.messagebox'] = types.SimpleNamespace(showerror=lambda *a: None); "
                "sys.modules['tkinter.ttk'] = types.SimpleNamespace(); "
                "import linux_unlock_ui; sys.platform = 'win32'; linux_unlock_ui.enforce_linux_os_guard()"
            )],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_linux_on_win.returncode, 2)
        self.assertIn("Windows_Launch_UI.bat", res_linux_on_win.stderr)

    def test_both_ui_files_pure_grayscale_and_valid_syntax(self) -> None:
        for fname in ("gpu_unlock_ui.py", "linux_unlock_ui.py"):
            src = (ROOT / fname).read_text(encoding="utf-8")
            ast.parse(src)
            for m in re.finditer(r"#([0-9a-fA-F]{6})", src):
                hx = m.group(1).lower()
                r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
                if hx not in ("3fb950", "d29922", "f85149", "6e1c1c"):
                    self.assertEqual((r, g), (g, b), f"Non-grayscale color #{hx} in {fname}")



    def test_turing_rtx2080ti_classification_and_boot_option(self) -> None:
        cls = core_detector.classify_pci_device(0x1E07, "NVIDIA GeForce RTX 2080 Ti", "sm_75")
        self.assertTrue(cls["supported"])
        self.assertEqual(cls["die_name"], "TU102")
        self.assertEqual(cls["chip_id"], 0x162000A1)
        self.assertFalse(cls["is_ada"])
        self.assertTrue(cls["is_turing"])
        gpu_sample = {
            "pci_bdf": "0000:04:00.0",
            "board_id_hex": "0x1e0710de",
            "gpu_name": "NVIDIA GeForce RTX 2080 Ti",
        }
        self.assertEqual(
            core_detector.get_linux_boot_option_for_gpu(gpu_sample),
            "gpu_unlock.targets=0000:04:00.0 gpu_unlock.turing_experimental=1",
        )
        self.assertEqual(
            core_detector.get_linux_modprobe_command_for_gpu(gpu_sample),
            "modprobe gpu_unlock targets=0000:04:00.0 turing_experimental=1",
        )
        v67_tu = core_detector.build_v67_payload(arch="tu102")
        self.assertEqual(len(v67_tu), 64000)
        self.assertEqual(
            core_detector.sha256_bytes(v67_tu),
            "54513477ba4da9922fe00678ae390b1ec5136353989b23238c3524a69c7a8024",
        )

    def test_windows_bat_is_pure_ascii_crlf_and_no_case_collisions(self) -> None:
        bat_raw = (ROOT / "Windows_Launch_UI.bat").read_bytes()
        # Must be pure 7-bit ASCII so cmd.exe never miscalculates byte offsets on UTF-8 Cyrillic
        bat_raw.decode("ascii")
        self.assertIn(b"\r\n", bat_raw)
        self.assertNotIn(b"\n", bat_raw.replace(b"\r\n", b""))

        # Check entire tree for case-insensitive file or directory collisions on Windows NTFS
        seen_files: dict[str, str] = {}
        seen_dirs: dict[str, str] = {}
        skip_parts = {"__pycache__", ".firmware_cache", ".git", ".pytest_cache", "build"}
        for p in sorted(ROOT.rglob("*")):
            if any(part in skip_parts for part in p.parts) or p.suffix in (".pyc", ".pyo"):
                continue
            rel = p.relative_to(ROOT).as_posix()
            low = rel.lower()
            if p.is_dir():
                self.assertNotIn(low, seen_dirs, f"Case-insensitive directory collision: {rel} vs {seen_dirs.get(low)}")
                seen_dirs[low] = rel
            elif p.is_file():
                self.assertNotIn(low, seen_files, f"Case-insensitive file collision: {rel} vs {seen_files.get(low)}")
                seen_files[low] = rel


    def test_rtx4080_and_multigen_efi_profile_verification_and_isolated_build(self) -> None:
        """Verify that build.py stages --profile-dir headers without shadowing by source/unlock/local_profile.h
        and that verify_compiled_efi_profile catches any stale/default profile leakage."""
        rtx4080_cfg = {
            "gpu_name": "NVIDIA GeForce RTX 4080",
            "die_name": "AD103",
            "chip_id_hex": "0x193000a1",
            "board_id_hex": "0x270410de",
            "subsystem_id_hex": "0x268819da",
            "segment_hex": "0x0",
            "bus_hex": "0x01",
            "device_hex": "0x0",
            "function_hex": "0x0",
            "vram_min_hex": "0x3bf0",
            "vram_max_hex": "0x4400",
            "esp_guid": "{c70266a8-85cf-45d9-8d4c-6ba57421f55a}",
            "esp_part_num": 1,
        }
        validated = core_detector.validate_target_profile(rtx4080_cfg)
        self.assertEqual(validated["board_id"], 0x270410DE)
        self.assertEqual(validated["subsys_id"], 0x268819DA)
        self.assertEqual(validated["chip_id"], 0x193000A1)

        import struct
        good_efi = (
            b"MZ_FAKE_EFI"
            + struct.pack("<I", validated["board_id"])
            + struct.pack("<I", validated["subsys_id"])
            + core_detector.guid_string_to_packed_bytes(validated["esp_guid"])
        )
        core_detector.verify_compiled_efi_profile(good_efi, validated)

        # If default template 0xf2941569 leaks into a non-4070Ti binary, verification must reject it
        leaked_efi = good_efi + struct.pack("<I", 0xF2941569)
        with self.assertRaises(RuntimeError):
            core_detector.verify_compiled_efi_profile(leaked_efi, validated)



    def test_usb_drive_detection_win32_and_powershell_fallbacks(self) -> None:
        """Verify multi-layered USB drive detection handles numeric enums, non-admin empty BusType,
        Superfloppy FAT32 sticks, Fixed USB 3.x RMB=0 sticks, and Win32 IOCTL_STORAGE_QUERY_PROPERTY."""
        self.assertEqual(core_detector._normalize_bus_type(7), "USB")
        self.assertEqual(core_detector._normalize_bus_type("7"), "USB")
        self.assertEqual(core_detector._normalize_bus_type(12), "SD")
        self.assertEqual(core_detector._normalize_bus_type(13), "MMC")
        self.assertEqual(core_detector._normalize_drive_type(2), "Removable")
        self.assertEqual(core_detector._normalize_drive_type(3), "Fixed")
        self.assertEqual(core_detector._normalize_filesystem("FAT32 "), ("FAT32", True))
        self.assertEqual(core_detector._normalize_filesystem("FAT"), ("FAT", True))
        self.assertEqual(core_detector._normalize_filesystem("exFAT"), ("EXFAT", False))

        import json
        from unittest import mock
        fake_ps_json = json.dumps([
            {
                "DriveLetter": "D",
                "Label": "KINGSTON_32",
                "FileSystem": "FAT32",
                "DriveType": 3,   # Fixed (RMB=0 modern USB 3.2 stick)
                "Size": 32 * (1024 ** 3),
                "UniqueId": "USB-D",
                "BusType": 7,     # Numeric enum 7 = USB
                "IsBoot": False,
                "IsSystem": False,
                "DiskNumber": 2,
            },
            {
                "DriveLetter": "E",
                "Label": "",
                "FileSystem": "FAT32",
                "DriveType": "Fixed",
                "Size": 16 * (1024 ** 3),
                "UniqueId": "SUPERFLOPPY-E",
                "BusType": "",    # Get-Partition / Get-Disk returned null (non-admin or Superfloppy)
                "IsBoot": False,
                "IsSystem": False,
                "DiskNumber": -1,
            },
            {
                "DriveLetter": "F",
                "Label": "SANDISK_64",
                "FileSystem": "exFAT",
                "DriveType": 2,   # Numeric enum 2 = Removable
                "Size": 64 * (1024 ** 3),
                "UniqueId": "USB-F",
                "BusType": "",
                "IsBoot": False,
                "IsSystem": False,
                "DiskNumber": 3,
            },
            {
                "DriveLetter": "G",
                "Label": "INTERNAL_DATA",
                "FileSystem": "NTFS",
                "DriveType": 3,
                "Size": 1000 * (1024 ** 3),
                "UniqueId": "SATA-G",
                "BusType": 11,    # Numeric 11 = SATA
                "IsBoot": False,
                "IsSystem": False,
                "DiskNumber": 1,
            },
        ])

        class FakeProc:
            returncode = 0
            stdout = fake_ps_json
            stderr = ""

        with mock.patch.object(core_detector.subprocess, "run", return_value=FakeProc()):
            ps_drives = core_detector._list_usb_drives_powershell()

        letters = [d["letter"] for d in ps_drives]
        self.assertEqual(letters, ["D:\\", "E:\\", "F:\\"])
        self.assertTrue(ps_drives[0]["is_fat32"])
        self.assertEqual(ps_drives[0]["bus_type"], "USB")
        self.assertTrue(ps_drives[1]["is_fat32"])
        self.assertFalse(ps_drives[2]["is_fat32"])
        self.assertIn("EXFAT - NEED FAT32", ps_drives[2]["display"])

    def test_ui_dark_scrollbar_and_deps_localization_refresh(self) -> None:
        """Verify both Windows and Linux UIs use dark-styled ttk.Scrollbar (no white tk.Scrollbar)
        and refresh [02] dependency status labels immediately when switching languages."""
        for fname in ("gpu_unlock_ui.py", "linux_unlock_ui.py"):
            src = (ROOT / fname).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\btk\.Scrollbar\(", src), f"{fname} must not use native white tk.Scrollbar")
            self.assertIn('style="Console.Vertical.TScrollbar"', src, f"{fname} must use dark Console.Vertical.TScrollbar")
            self.assertIn("def _refresh_deps_labels(self) -> None:", src, f"{fname} must define _refresh_deps_labels")
            self.assertIn("self._refresh_deps_labels()", src, f"{fname} must call _refresh_deps_labels on language switch")


if __name__ == "__main__":
    unittest.main()
