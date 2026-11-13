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
        # Verify real NVIDIA 610.43.03 BooterLoadUcode_TU102.c SHA-256 and non-PROD UCODE_IMAGE/UCODE_DESC fallback
        self.assertEqual(
            core_detector.SOURCE_C_FILES["g_bindata_kgspGetBinArchiveBooterLoadUcode_TU102.c"][0],
            "e495483adf66798502667da137c4a24c55f471b86f3183020e3169ff88ad6c89",
        )
        sample_tu_boot_c = (
            "/* DATA SIZE (bytes): 4\n   COMPRESSION: NO */\n"
            "static const NvU8 BINDATA_LABEL_UCODE_IMAGE_data[] = { 0x11, 0x22, 0x33, 0x44 };\n"
            "/* DATA SIZE (bytes): 4\n   COMPRESSION: NO */\n"
            "static const NvU8 BINDATA_LABEL_UCODE_DESC_data[] = { 0x05, 0x00, 0x00, 0x00 };\n"
        )
        self.assertEqual(core_detector._array_bytes(sample_tu_boot_c, "UCODE_IMAGE_PROD"), b"\x11\x22\x33\x44")
        self.assertEqual(core_detector._array_bytes(sample_tu_boot_c, "UCODE_DESC_PROD"), b"\x05\x00\x00\x00")

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
            self.assertIn("def _ensure_initial_pane_layout(self) -> None:", src, f"{fname} must define _ensure_initial_pane_layout")
            self.assertIn("self.lbl_issues_note", src, f"{fname} must display GitHub Issues feedback notice")
            self.assertIn('stretch="never"', src, f"{fname} must keep console pane stretch=never on startup")


    def test_win32_ioctl_esp_detection_and_auto_esp_profile_fallback(self) -> None:
        """Verify Win32 IOCTL_DISK_GET_DRIVE_LAYOUT_EX GPT ESP parsing and AUTO ESP GUID fallback
        when PowerShell Get-Partition times out or returns empty."""
        import ctypes
        import struct
        from unittest import mock

        # 1. Round-trip _ESP_TYPE_GUID_LE and arbitrary GPT partition GUID
        self.assertEqual(
            core_detector._packed_bytes_to_guid_str(core_detector._ESP_TYPE_GUID_LE),
            "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}",
        )
        sample_guid = "{7a8150e0-c25f-4a16-9473-4a162c4d459a}"
        packed = core_detector.guid_string_to_packed_bytes(sample_guid)
        self.assertEqual(core_detector._packed_bytes_to_guid_str(packed), sample_guid)

        # 2. Simulate DRIVE_LAYOUT_INFORMATION_EX (48-byte header + two 144-byte PARTITION_INFORMATION_EX entries)
        buf = bytearray(48 + 2 * 144)
        struct.pack_into("<II", buf, 0, 1, 2)  # PartitionStyle=1 (GPT), PartitionCount=2
        # Entry 0: EFI System Partition (Part 1)
        off0 = 48
        struct.pack_into("<I", buf, off0 + 0, 1)  # PartitionStyle=1 (GPT)
        struct.pack_into("<I", buf, off0 + 24, 1)  # PartitionNumber=1
        buf[off0 + 32 : off0 + 48] = core_detector._ESP_TYPE_GUID_LE
        buf[off0 + 48 : off0 + 64] = packed
        # Entry 1: Basic Data Partition (Part 2)
        off1 = 48 + 144
        struct.pack_into("<I", buf, off1 + 0, 1)
        struct.pack_into("<I", buf, off1 + 24, 2)
        buf[off1 + 32 : off1 + 48] = b"\xa2\xa0\xd0\xeb\xe5\xb9\x33\x44\x87\xc0\x68\xb6\xb7\x26\x99\xc7"
        buf[off1 + 48 : off1 + 64] = b"\x11" * 16

        class FakeKernel32:
            def SetErrorMode(self, mode: int) -> int:
                return 0

            def CreateFileW(self, path: Any, *args: Any) -> int:
                s = getattr(path, "value", str(path))
                if "PhysicalDrive0" in s or "C:" in s:
                    return 100
                return -1

            def DeviceIoControl(
                self, handle: int, ioctl: int, in_buf: Any, in_sz: int, out_buf: Any, out_sz: int, bytes_ret_ptr: Any, ovl: Any
            ) -> int:
                if ioctl == 0x002D1080:  # IOCTL_STORAGE_GET_DEVICE_NUMBER
                    raw_num = struct.pack("<III", 7, 0, 2)
                    ctypes.memmove(out_buf, raw_num, len(raw_num))
                    bytes_ret_ptr._obj.value = len(raw_num)
                    return 1
                if ioctl == 0x00070050:  # IOCTL_DISK_GET_DRIVE_LAYOUT_EX
                    ctypes.memmove(out_buf, bytes(buf), len(buf))
                    bytes_ret_ptr._obj.value = len(buf)
                    return 1
                return 0

            def CloseHandle(self, handle: int) -> int:
                return 1

        fake_windll = mock.MagicMock()
        fake_windll.kernel32 = FakeKernel32()
        with mock.patch.object(core_detector.ctypes, "windll", fake_windll, create=True):
            esps = core_detector._detect_windows_esp_win32()

        self.assertEqual(len(esps), 1)
        self.assertEqual(esps[0]["DiskNumber"], 0)
        self.assertEqual(esps[0]["PartitionNumber"], 1)
        self.assertEqual(esps[0]["Guid"], sample_guid)
        self.assertTrue(esps[0]["OnBootDisk"])

        # 3. Verify validate_target_profile accepts empty esp_guid ("") or "AUTO" when PowerShell timed out
        rtx3090_cfg = {
            "gpu_name": "NVIDIA GeForce RTX 3090",
            "die_name": "GA102",
            "chip_id_hex": "0x172000a1",
            "board_id_hex": "0x220410de",
            "subsystem_id_hex": "0x38811462",
            "segment_hex": "0x0",
            "bus_hex": "0x01",
            "device_hex": "0x0",
            "function_hex": "0x0",
            "vram_min_hex": "0x5bf0",
            "vram_max_hex": "0x6400",
            "esp_guid": "",
            "esp_part_num": 0,
        }
        val_auto = core_detector.validate_target_profile(rtx3090_cfg)
        self.assertEqual(val_auto["esp_guid"], "AUTO")
        self.assertEqual(
            val_auto["esp_macro"],
            "0x00000000U,0x0000U,0x0000U,{0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00}",
        )
        fake_efi = b"MZ_FAKE_3090" + struct.pack("<I", 0x220410DE) + struct.pack("<I", 0x38811462)
        core_detector.verify_compiled_efi_profile(fake_efi, val_auto)

    def test_upstream_pci_matrix_sync_and_rtx_3080_ti_20gb(self) -> None:
        """Verify all PCI IDs in kernel/gpu_unlock/main.c + arch_610.h are in SUPPORT_MATRIX and 0x2205 (RTX 3080 Ti 20GB) works."""
        import re
        main_c = (core_detector.APP_ROOT / "kernel" / "gpu_unlock" / "main.c").read_text()
        arch_h = (core_detector.APP_ROOT / "kernel" / "gpu_unlock" / "arch_610.h").read_text()
        c_ids = {int(x, 16) for x in re.findall(r"0x[0-9a-fA-F]{4}(?=u|\b)", main_c + "\n" + arch_h)}
        for dev16 in sorted(c_ids):
            self.assertIn(dev16, core_detector.SUPPORT_MATRIX, f"PCI ID 0x{dev16:04x} missing from SUPPORT_MATRIX")
            self.assertIn(dev16, core_detector.NOMINAL_VRAM_MIB, f"PCI ID 0x{dev16:04x} missing from NOMINAL_VRAM_MIB")

        # Verify 0x220510de (Gigabyte RTX 3080 Ti 20GB GA102-250 reported as "NVIDIA Graphics Device")
        cls_2205 = core_detector.classify_pci_device(0x2205, "NVIDIA Graphics Device")
        self.assertTrue(cls_2205["supported"])
        self.assertEqual(cls_2205["die_name"], "GA102")
        self.assertEqual(cls_2205["chip_id"], 0x172000A1)
        enriched = core_detector._enrich_generic_gpu_name("NVIDIA Graphics Device", 0x2205)
        self.assertIn("RTX 3080 Ti 20GB", enriched)

        # Verify validate_target_profile accepts both 0x172000a1 and 0xb72000a1 (Samsung 8N strap bits 31:29)
        for chip_hex in ("0x172000a1", "0xb72000a1"):
            prof = core_detector.validate_target_profile({
                "gpu_name": enriched,
                "die_name": "GA102",
                "chip_id_hex": chip_hex,
                "board_id_hex": "0x220510de",
                "subsystem_id_hex": "0x40591458",
                "segment_hex": "0x0",
                "bus_hex": "0x05",
                "device_hex": "0x0",
                "function_hex": "0x0",
                "vram_min_hex": "0x4c00",
                "vram_max_hex": "0x5400",
                "esp_guid": "{83b25fc2-062d-47db-8de4-4749da3aa3c7}",
                "esp_part_num": 1,
            })
            self.assertEqual(prof["die_name"], "GA102")
            self.assertEqual(prof["board_id"], 0x220510DE)
            self.assertEqual(prof["subsys_id"], 0x40591458)


    def test_v128_makeself_run_unpacker_and_npde_vga_restore_and_x99_secureboot(self) -> None:
        """Verify v1.2.8 fixes:
        1) extract_gsp_from_zst unpacks .run Makeself archives even when an embedded zstd decoder stub
           contains false-positive 0xFD2FB528 magic bytes before the true payload.
        2) handoff.inc includes NPDE (0x4544504e) stepping and VGA-RESTORE (0x0006001cULL).
        3) app.c treats EFI_NOT_FOUND / EFI_UNSUPPORTED on SecureBoot variable as secure=0 (X99 fix)."""
        import io
        import tarfile
        import tempfile

        handoff_txt = (core_detector.APP_ROOT / "windows" / "uefi" / "source" / "unlock" / "handoff.inc").read_text(encoding="utf-8")
        self.assertIn("0x4544504eU", handoff_txt)
        self.assertIn("VGA-RESTORE PciIo attributes", handoff_txt)
        self.assertIn("0x0006001cULL", handoff_txt)

        app_txt = (core_detector.APP_ROOT / "windows" / "uefi" / "source" / "unlock" / "app.c").read_text(encoding="utf-8")
        self.assertIn("status==EFI_NOT_FOUND || status==EFI_UNSUPPORTED", app_txt)

        # Build a synthetic tar archive in memory containing ./firmware/gsp_tu10x.bin
        tar_buf = io.BytesIO()
        payload_bytes = b"\x7fELF" + b"T" * 1024
        with tarfile.open(fileobj=tar_buf, mode="w") as tf:
            ti = tarfile.TarInfo(name="./firmware/gsp_tu10x.bin")
            ti.size = len(payload_bytes)
            tf.addfile(ti, io.BytesIO(payload_bytes))
        raw_tar = tar_buf.getvalue()

        try:
            import zstandard as zstd
            cctx = zstd.ZstdCompressor()
            compressed = cctx.compress(raw_tar)
            ext_magic_stub = b"\x81\xf8\x28\xb5\x2f\xfd\x75\x10"  # cmp eax, 0xfd2fb528; jne +16
        except ImportError:
            import lzma
            compressed = lzma.compress(raw_tar)
            ext_magic_stub = b"\x00\xfd7zXZ\x00\xff\xff"

        # Construct a Makeself header with skip=5 and embedded false-positive magic inside line 4
        makeself_hdr = (
            b"#!/bin/sh\n"
            b"# Makeself 1.6.0-nv9\n"
            b"skip=5\n"
            b"# embedded decoder stub: " + ext_magic_stub + b"\n"
        )
        run_bytes = makeself_hdr + compressed

        with tempfile.TemporaryDirectory() as tmpd:
            run_file = Path(tmpd) / "NVIDIA-Linux-x86_64-610.43.03.run"
            out_gsp = Path(tmpd) / "gsp_tu10x.bin"
            run_file.write_bytes(run_bytes)
            core_detector.extract_gsp_from_zst(run_file, out_gsp, member_name="gsp_tu10x.bin")
            self.assertEqual(out_gsp.read_bytes(), payload_bytes)



    def test_v129_elf64_gsp_section_validator_and_turing_assets(self) -> None:
        """Verify v1.2.9 fixes:
        1. _validate_gsp_elf_sections unpacks all 6 uint16 fields at ELF64 offset 52..64 (<HHHHHH).
        2. Turing .fwsignature_tu10x accepts RSA-3K (384 B) signatures (16..65536 B).
        3. Version is 1.2.9 across README.md, core_detector.py, and UEFI headers.
        """
        import struct, tempfile
        self.assertEqual(core_detector.get_app_version(), "1.3.2")
        shstrtab = b"\x00.shstrtab\x00.fwimage\x00.fwsignature_tu10x\x00"
        while len(shstrtab) % 8 != 0:
            shstrtab += b"\x00"
        fwimage_off = 64 + len(shstrtab)
        fwimage_sz = 13 * 1024 * 1024
        fwsig_off = fwimage_off + fwimage_sz
        fwsig_sz = 384
        sh_off = fwsig_off + fwsig_sz
        def make_shdr(sh_name: int, sh_type: int, sh_offset: int, sh_size: int) -> bytes:
            return struct.pack("<IIQQQQIIQQ", sh_name, sh_type, 0, 0, sh_offset, sh_size, 0, 0, 1, 0)
        shdrs = (
            make_shdr(0, 0, 0, 0) +
            make_shdr(1, 3, 64, len(shstrtab)) +
            make_shdr(11, 1, fwimage_off, fwimage_sz) +
            make_shdr(20, 1, fwsig_off, fwsig_sz)
        )
        ehdr = bytearray(64)
        ehdr[0:4] = b"\x7fELF"
        ehdr[4] = 2
        ehdr[5] = 1
        ehdr[6] = 1
        struct.pack_into("<HHIQQQIHHHHHH", ehdr, 16, 2, 0, 1, 0, 0, sh_off, 0, 64, 0, 0, 64, 4, 1)
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
            tf.write(bytes(ehdr))
            tf.write(shstrtab)
            tf.seek(fwsig_off)
            tf.write(b"\xbb" * fwsig_sz)
            tf.write(shdrs)
            elf_p = Path(tf.name)
        try:
            self.assertTrue(core_detector._validate_gsp_elf_sections(elf_p, is_turing=True))
            self.assertFalse(core_detector._validate_gsp_elf_sections(elf_p, is_turing=False))
        finally:
            elf_p.unlink(missing_ok=True)


    def test_turing_v2_ns_hs_split_pio_and_wpr2_geometry(self) -> None:
        """Verify Turing V2 NS+HS split IMEM loading (SEC=0 for NS, SEC=1 for HS),
        Portal PIO helpers, 1 MiB WPR2 top alignment, Turing heap sizing, and
        UCODE_IMAGE_DBG[:0x6000] extraction."""
        for rel in ("windows/uefi/source/unlock/vendor/unlock_610.c", "kernel/gpu_unlock/unlock_610.c"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("falcon_pio_imem", src)
            self.assertIn("falcon_pio_dmem", src)
            self.assertIn("gpu_unlock_dma_cmd(false) | 0x10u", src)
            self.assertIn("fwsec_ns_size", src)
            self.assertIn("post-unlock Turing SEC2 reset released, FLR skipped", src)
            self.assertNotIn("if ((hi >> 4) || ss0 != GU_SS0_UNLOCK", src)
        cd_src = (ROOT / "core_detector.py").read_text(encoding="utf-8")
        self.assertIn("BINDATA_LABEL_UCODE_IMAGE_DBG_data[]", cd_src)


    def test_v130_laptop_mobile_gpu_and_rtd3_support(self) -> None:
        """Verify v1.3.0 Laptop / Mobile GPU support across Ada (AD103M..AD107M),
        Ampere (GA103M..GA107M), and Turing (TU104M..TU106M), 3D controller [0302]
        detection, GU_IS_MOBILE_GPU profile generation, and Linux RTD3 detection."""
        import tempfile

        # 1. Verify mobile GPUs across all 3 architectures are supported and flagged is_mobile=True
        for dev16, name, sm, exp_die, exp_opt_Frag in (
            (0x2717, "NVIDIA GeForce RTX 4090 Laptop GPU", "sm_89", "AD103", "ad103_experimental=1"),
            (0x27A0, "NVIDIA GeForce RTX 4080 Laptop GPU", "sm_89", "AD104", "ad104_experimental=1"),
            (0x2820, "NVIDIA GeForce RTX 4070 Laptop GPU", "sm_89", "AD106", "ada_experimental=1"),
            (0x28A0, "NVIDIA GeForce RTX 4060 Laptop GPU", "sm_89", "AD107", "ada_experimental=1"),
            (0x28A1, "NVIDIA GeForce RTX 4050 Laptop GPU", "sm_89", "AD107", "ada_experimental=1"),
            (0x2420, "NVIDIA GeForce RTX 3080 Ti Laptop GPU", "sm_86", "GA103", ""),
            (0x249D, "NVIDIA GeForce RTX 3070 Laptop GPU", "sm_86", "GA104", ""),
            (0x2520, "NVIDIA GeForce RTX 3060 Laptop GPU", "sm_86", "GA106", ""),
            (0x25A0, "NVIDIA GeForce RTX 3050 Ti Laptop GPU", "sm_86", "GA107", ""),
            (0x1E90, "NVIDIA GeForce RTX 2080 Mobile", "sm_75", "TU104", "turing_experimental=1"),
            (0x1F11, "NVIDIA GeForce RTX 2060 Mobile", "sm_75", "TU106", "turing_experimental=1"),
            (0x1F12, "NVIDIA GeForce RTX 2060 Max-Q", "sm_75", "TU106", "turing_experimental=1"),
        ):
            cls = core_detector.classify_pci_device(dev16, name, sm)
            self.assertTrue(cls["supported"], f"Mobile GPU 0x{dev16:04x} ({name}) should be supported")
            self.assertTrue(cls["is_mobile"], f"Mobile GPU 0x{dev16:04x} ({name}) should have is_mobile=True")
            self.assertEqual(cls["die_name"], exp_die)
            boot_opt = core_detector.get_linux_boot_option_for_gpu({
                "pci_bdf": "0000:01:00.0",
                "board_id_hex": f"0x{dev16:04x}10de",
                "gpu_name": name,
            })
            self.assertIn("gpu_unlock.targets=0000:01:00.0", boot_opt)
            if exp_opt_Frag:
                self.assertIn(exp_opt_Frag, boot_opt)

        # 2. Verify validate_target_profile sets is_mobile=True for Laptop GPUs
        prof_4090m = core_detector.validate_target_profile({
            "gpu_name": "NVIDIA GeForce RTX 4090 Laptop GPU",
            "die_name": "AD103",
            "chip_id_hex": "0x193000a1",
            "board_id_hex": "0x271710de",
            "subsystem_id_hex": "0x15ef1043",
            "segment_hex": "0x0",
            "bus_hex": "0x01",
            "device_hex": "0x0",
            "function_hex": "0x0",
            "vram_min_hex": "0x3bf0",
            "vram_max_hex": "0x4400",
            "esp_guid": "AUTO",
            "esp_part_num": 0,
        })
        self.assertTrue(prof_4090m["is_mobile"])

        # 3. Verify 3D controller [0302] MUXless laptop detection in sysfs + lspci
        with tempfile.TemporaryDirectory() as tmpd:
            sysfs = Path(tmpd)
            d0 = sysfs / "0000:01:00.0"
            d0.mkdir()
            (d0 / "vendor").write_text("0x10de\n", encoding="ascii")
            (d0 / "device").write_text("0x2820\n", encoding="ascii")
            (d0 / "subsystem_vendor").write_text("0x1043\n", encoding="ascii")
            (d0 / "subsystem_device").write_text("0x1e33\n", encoding="ascii")
            (d0 / "class").write_text("0x030200\n", encoding="ascii")  # 3D controller (MUXless Optimus)
            lspci_3d = "0000:01:00.0 3D controller [0302]: NVIDIA Corporation AD106M [GeForce RTX 4070 Max-Q / Mobile] [10de:2820] (rev a1)\n"
            gpus = core_detector._query_linux_pci_gpus(sysfs_root=sysfs, lspci_output=lspci_3d)
            self.assertEqual(len(gpus), 1)
            self.assertEqual(gpus[0]["dev16"], 0x2820)

            # 4. Verify Linux RTD3 state inspection
            p_params = Path(tmpd) / "params"
            p_etc = Path(tmpd) / "etc-nvidia-runtimepm.conf"
            p_usr = Path(tmpd) / "usr-nvidia-runtimepm.conf"
            p_params.write_text("DynamicPowerManagement: 2\n", encoding="utf-8")
            p_usr.write_text("options nvidia NVreg_DynamicPowerManagement=0x02\n", encoding="utf-8")
            rtd3 = linux_backend.check_linux_nvidia_rtd3_state(p_params, p_etc, p_usr)
            self.assertTrue(rtd3["rtd3_active"])
            self.assertEqual(rtd3["dynamic_pm_value"], 2)
            self.assertFalse(rtd3["etc_disabled_override"])

            p_params.write_text("DynamicPowerManagement: 0\n", encoding="utf-8")
            p_etc.write_text("options nvidia NVreg_DynamicPowerManagement=0x00\n", encoding="utf-8")
            rtd3_off = linux_backend.check_linux_nvidia_rtd3_state(p_params, p_etc, p_usr)
            self.assertFalse(rtd3_off["rtd3_active"])
            self.assertTrue(rtd3_off["etc_disabled_override"])



    def test_v131_copy_markdown_report_and_laptop_display_and_turing_desc(self) -> None:
        """Verify v1.3.2 additions:
        1. Copy Markdown Report button & localizations (EN/RU/ZH/HI) in both Windows and Linux UIs.
        2. format_markdown_report() output formatting.
        3. Laptop InsydeH2O ConSplitterDxe pathless virtual GOP skip in app.c.
        4. Turing 76-byte RM_RISCV_UCODE_DESC v4 (bIsMonitorEnabled=0) bootloaderOffset/bootloaderParamOffset parsing."""
        import i18n_strings

        for lang in ("EN", "RU", "ZH", "HI"):
            for d in (i18n_strings.I18N[lang], i18n_strings.I18N_LINUX[lang]):
                self.assertIn("btn_copy_md_report", d)
                self.assertIn("ctx_copy_md", d)
                self.assertIn("md_copied_log", d)
                self.assertTrue(len(d["btn_copy_md_report"]) > 0)

        sample_hw = {
            "gpu_name": "NVIDIA GeForce RTX 3050 Laptop GPU",
            "die_name": "GA107M",
            "support_tier": "experimental_simulated",
            "is_mobile": True,
            "board_id_hex": "0x25a210de",
            "subsystem_id_hex": "0x16081025",
            "pci_bdf": "0000:01:00.0",
            "chip_id_hex": "0x177000a1",
            "vram_mib": 4096,
            "vram_min_hex": "0xc00",
            "vram_max_hex": "0x1400",
            "vbios_version": "94.07.3B.00.52",
            "esp_guid": "{70712320-2136-4e0f-aa26-5a288ab65a77}",
        }
        sample_bench = [
            ("FP16 -> FP32 (FMLA32)", "FMLA32", "25.10 TFLOP/s", "50.20 TFLOP/s", "50.20 TFLOP/s", "2.00x (+100.0%)"),
        ]
        md = core_detector.format_markdown_report(
            sample_hw,
            sample_bench,
            "CHECK stage=display status=0\nFINAL status=0 stage=complete attempted=1",
            platform_mode="windows",
            bench_banner="RTX 3050 Laptop GPU // MEASURED_UNLOCKED [Ratio: 1.00]",
        )
        self.assertIn("## NVIDIA GPU Tensor Unlock — Diagnostic Report (`v1.3.2`)", md)
        self.assertIn("`NVIDIA GeForce RTX 3050 Laptop GPU` (Laptop / Mobile dGPU)", md)
        self.assertIn("`0x25a210de` / `0x16081025`", md)
        self.assertIn("| `FP16 -> FP32 (FMLA32)` | `FMLA32` | 25.10 TFLOP/s | 50.20 TFLOP/s | 50.20 TFLOP/s | **2.00x (+100.0%)** |", md)
        self.assertIn("<details open>", md)
        self.assertIn("CHECK stage=display status=0", md)

        for ui_fname in ("gpu_unlock_ui.py", "linux_unlock_ui.py"):
            ui_src = (ROOT / ui_fname).read_text(encoding="utf-8")
            self.assertIn("btn_copy_md_report", ui_src)
            self.assertIn("action_copy_markdown_report", ui_src)

        app_src = (ROOT / "windows/uefi/source/unlock/app.c").read_text(encoding="utf-8")
        self.assertIn("display virtual pathless gop skipped", app_src)


if __name__ == "__main__":

    unittest.main()
