# SPDX-License-Identifier: GPL-2.0-only
"""Check the generated payloads, single-source README.md version, and shared install layout."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(os.environ.get("GPU_UNLOCK_ASSETS", "/nonexistent"))
sys.path.insert(0, str(ROOT / "firmware"))
import generate_v67  # noqa: E402


def read_readme_version() -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"\*\*Version:\s*([0-9]+\.[0-9]+\.[0-9]+)\*\*", text)
    if not m:
        raise AssertionError("Could not find **Version: X.Y.Z** in README.md")
    return m.group(1)


class PackageTests(unittest.TestCase):
    @unittest.skipUnless((ASSETS / "booter_load_ad102.bin").is_file(),
                         "set GPU_UNLOCK_ASSETS to the pinned GA/Ada/Turing asset directory")
    def test_firmware_package_contains_pinned_ada_assets_and_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["make", "-s", f"DESTDIR={directory}", f"ASSETS={ASSETS}",
                            "install-firmware"], cwd=ROOT, check=True)
            installed = Path(directory) / "usr/lib/firmware/gpu-unlock/610.43.03"
            manifest = json.loads((ROOT / "firmware/ada-610.43.03.json").read_text())
            for name, digest in manifest["derived_assets"].items():
                self.assertEqual(hashlib.sha256((installed / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(hashlib.sha256((installed / "gsp_ga10x.bin").read_bytes()).hexdigest(),
                             manifest["shared_gsp"]["sha256"])
            payload_pin = self.manifest()["generated_ad102_payload"]
            self.assertEqual(hashlib.sha256((installed / payload_pin["filename"]).read_bytes()).hexdigest(),
                             payload_pin["sha256"])

    def test_v67_payload_matches_pin(self):
        digest = hashlib.sha256(generate_v67.build_payload()).hexdigest()
        self.assertEqual(digest, generate_v67.PAYLOAD_SHA256)
        self.assertEqual(digest, self.manifest()["generated_payload"]["sha256"])

    def test_install_uses_standard_paths(self):
        version = read_readme_version()
        self.assertFalse((ROOT / "VERSION").exists(), "Standalone VERSION file must not exist; README.md is the single source of truth")
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["make", "-s", f"DESTDIR={directory}", "install-dkms",
                            "install-mkinitcpio", "install-initramfs-tools",
                            "install-dracut"],
                           cwd=ROOT, check=True)
            root = Path(directory)
            paths = {path.relative_to(root).as_posix() for path in root.rglob("*")
                     if path.is_file()}
            for expected in (f"usr/src/gpu-unlock-{version}/dkms.conf",
                             f"usr/src/gpu-unlock-{version}/main.c",
                             "etc/mkinitcpio.conf.d/zz-gpu-unlock.conf",
                             "usr/share/initramfs-tools/modules.d/gpu-unlock.conf",
                             "usr/lib/dracut/dracut.conf.d/gpu-unlock.conf",
                             "usr/share/doc/gpu-unlock/README.md"):
                self.assertIn(expected, paths)
            installed_dkms = (root / f"usr/src/gpu-unlock-{version}/dkms.conf").read_text()
            self.assertIn(f'PACKAGE_VERSION="{version}"', installed_dkms)
            self.assertFalse(any(path.endswith(".mod.c") for path in paths))
            self.assertFalse(any("modprobe.d" in path for path in paths))
            dropin = root / "etc/mkinitcpio.conf.d/zz-gpu-unlock.conf"
            for before, after in (("zfs nvidia nvidia_drm", "zfs gpu_unlock nvidia nvidia_drm"),
                                  ("zfs", "zfs gpu_unlock"),
                                  ("zfs gpu_unlock? nvidia", "zfs gpu_unlock nvidia")):
                result = subprocess.run(["bash", "-c", f"MODULES=({before}); . {dropin}; echo ${{MODULES[*]}}"],
                                        capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout.strip(), after)

    def test_pkgbuild_pins_match_manifest(self):
        manifest = json.loads((ROOT / "firmware/artifacts-610.43.03.json").read_text())
        pkgbuild = (ROOT / "packaging/arch/PKGBUILD").read_text()
        for index in (0, 2):
            artifact = manifest["source_artifacts"][index]
            self.assertIn(artifact["sha256"], pkgbuild)
            self.assertIn(artifact["url"].rsplit("/", 1)[0], pkgbuild)
        self.assertIn("README.md", pkgbuild)

    def test_native_versions_derive_from_readme(self):
        version = read_readme_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        spec = (ROOT / "packaging/rpm/gpu-unlock.spec").read_text()
        self.assertIn("README.md", spec)
        for index in (0, 2):
            self.assertIn(self.manifest()["source_artifacts"][index]["sha256"], spec)
        rules = (ROOT / "debian/rules").read_text()
        self.assertIn("README.md", rules)

    @staticmethod
    def manifest():
        return json.loads((ROOT / "firmware/artifacts-610.43.03.json").read_text())
