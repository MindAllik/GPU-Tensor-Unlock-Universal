# SPDX-License-Identifier: GPL-2.0-only
"""Verify PCI candidate detection and boot option formatting for Ada and Turing targets."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import print_boot_option  # noqa: E402


class PrintBootOptionTests(unittest.TestCase):
    def test_candidates_parses_rtx4090_4070tis_and_4070ti(self):
        sample = (
            "0000:01:00.0 VGA compatible controller [0300]: NVIDIA Corporation AD104 [GeForce RTX 4070 Ti] [10de:2782] (rev a1)\n"
            "0000:01:00.1 Audio device [0403]: NVIDIA Corporation AD104 High Definition Audio Controller [10de:22bc] (rev a1)\n"
            "0000:02:00.0 VGA compatible controller [0300]: NVIDIA Corporation AD103 [GeForce RTX 4070 Ti SUPER] [10de:2705] (rev a1)\n"
            "0000:03:00.0 VGA compatible controller [0300]: NVIDIA Corporation AD102 [GeForce RTX 4090] [10de:2684] (rev a1)\n"
        )
        self.assertEqual(
            print_boot_option.candidates(sample),
            [("0000:01:00.0", "2782"), ("0000:02:00.0", "2705"), ("0000:03:00.0", "2684")],
        )

    def test_main_prints_ad104_experimental_flag_for_2782(self):
        sample = "0000:01:00.0 VGA compatible controller [0300]: NVIDIA Corporation AD104 [GeForce RTX 4070 Ti] [10de:2782] (rev a1)\n"
        out = io.StringIO()
        with patch("subprocess.run") as mock_run, patch("sys.stdout", out):
            mock_run.return_value.stdout = sample
            rc = print_boot_option.main()
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("RTX 4070 Ti (experimental) at 0000:01:00.0 [10de:2782]:", text)
        self.assertIn("gpu_unlock.targets=0000:01:00.0 gpu_unlock.ad104_experimental=1", text)

    def test_main_prints_turing_experimental_flag_for_1e07(self):
        sample = "0000:04:00.0 VGA compatible controller [0300]: NVIDIA Corporation TU102 [GeForce RTX 2080 Ti Rev. A] [10de:1e07] (rev a1)\n"
        out = io.StringIO()
        with patch("subprocess.run") as mock_run, patch("sys.stdout", out):
            mock_run.return_value.stdout = sample
            rc = print_boot_option.main()
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("RTX 2080 Ti (experimental) at 0000:04:00.0 [10de:1e07]:", text)
        self.assertIn("gpu_unlock.targets=0000:04:00.0 gpu_unlock.turing_experimental=1", text)


if __name__ == "__main__":
    unittest.main()
