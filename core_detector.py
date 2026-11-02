#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Universal Hardware Inspector, Firmware Asset Builder, and UEFI Compiler
for NVIDIA Ada Lovelace (AD10x), Ampere (GA10x) & Turing (TU10x) GPUs on Windows 10 / 11."""

from __future__ import annotations

import ctypes
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Callable

APP_ROOT = Path(__file__).resolve().parent
UEFI_DIR = APP_ROOT / "windows" / "uefi"
CACHE_DIR = APP_ROOT / ".firmware_cache"
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024  # 1 GiB hard cap (nvidia-utils .pkg.tar.zst is ~285 MB)

CHIP_BY_PMC: dict[str, tuple[int, bool]] = {
    "AD102": (0x192000A1, True),
    "AD103": (0x193000A1, True),
    "AD104": (0x194000A1, True),
    "AD106": (0x196000A1, True),
    "AD107": (0x197000A1, True),
    "GA102": (0x172000A1, False),
    "GA103": (0x173000A1, False),
    "GA104": (0x174000A1, False),
    "GA106": (0x176000A1, False),
    "TU102": (0x162000A1, False),
    "TU104": (0x164000A1, False),
    "TU106": (0x166000A1, False),
}

# Explicit versioned allowlist of desktop Ada Lovelace (AD10x) & Ampere (GA10x) PCI Device IDs.
# Format: dev16 -> (die_name, default_pmc_boot0, is_ada, support_tier, model_name)
SUPPORT_MATRIX: dict[int, tuple[str, int, bool, str, str]] = {
    # Hardware-tested profiles
    0x2684: ("AD102", 0x192000A1, True, "hardware_tested", "GeForce RTX 4090"),
    0x2782: ("AD104", 0x194000A1, True, "hardware_tested", "GeForce RTX 4070 Ti"),
    0x2204: ("GA102", 0x172000A1, False, "hardware_tested", "GeForce RTX 3090"),
    0x2206: ("GA102", 0x172000A1, False, "hardware_tested", "GeForce RTX 3080"),
    # Experimental / simulated desktop Ada Lovelace SKUs
    0x2685: ("AD102", 0x192000A1, True, "experimental_simulated", "GeForce RTX 4090 D"),
    0x2689: ("AD102", 0x192000A1, True, "experimental_simulated", "GeForce RTX 4070 Ti SUPER (AD102)"),
    0x2702: ("AD103", 0x193000A1, True, "experimental_simulated", "GeForce RTX 4080 SUPER"),
    0x2704: ("AD103", 0x193000A1, True, "experimental_simulated", "GeForce RTX 4080"),
    0x2705: ("AD103", 0x193000A1, True, "experimental_simulated", "GeForce RTX 4070 Ti SUPER"),
    0x2709: ("AD103", 0x193000A1, True, "experimental_simulated", "GeForce RTX 4070 (AD103)"),
    0x2783: ("AD104", 0x194000A1, True, "experimental_simulated", "GeForce RTX 4070 SUPER"),
    0x2786: ("AD104", 0x194000A1, True, "experimental_simulated", "GeForce RTX 4070"),
    0x27B0: ("AD104", 0x194000A1, True, "experimental_simulated", "GeForce RTX 4060 Ti (AD104)"),
    0x2803: ("AD106", 0x196000A1, True, "experimental_simulated", "GeForce RTX 4060 Ti 8GB"),
    0x2805: ("AD106", 0x196000A1, True, "experimental_simulated", "GeForce RTX 4060 Ti 16GB"),
    0x2808: ("AD106", 0x196000A1, True, "experimental_simulated", "GeForce RTX 4060 (AD106)"),
    0x2882: ("AD107", 0x197000A1, True, "experimental_simulated", "GeForce RTX 4060"),
    # Experimental / simulated desktop Ampere SKUs
    0x2203: ("GA102", 0x172000A1, False, "experimental_simulated", "GeForce RTX 3090 Ti"),
    0x2207: ("GA102", 0x172000A1, False, "experimental_simulated", "GeForce RTX 3070 Ti (GA102)"),
    0x2208: ("GA102", 0x172000A1, False, "experimental_simulated", "GeForce RTX 3080 Ti"),
    0x220A: ("GA102", 0x172000A1, False, "experimental_simulated", "GeForce RTX 3080 12GB"),
    0x2216: ("GA102", 0x172000A1, False, "experimental_simulated", "GeForce RTX 3080 LHR"),
    0x2414: ("GA103", 0x173000A1, False, "experimental_simulated", "GeForce RTX 3060 Ti (GA103)"),
    0x2482: ("GA104", 0x174000A1, False, "experimental_simulated", "GeForce RTX 3070 Ti"),
    0x2484: ("GA104", 0x174000A1, False, "experimental_simulated", "GeForce RTX 3070"),
    0x2486: ("GA104", 0x174000A1, False, "experimental_simulated", "GeForce RTX 3060 Ti"),
    0x2487: ("GA104", 0x174000A1, False, "experimental_simulated", "GeForce RTX 3060 (GA104)"),
    0x2488: ("GA104", 0x174000A1, False, "experimental_simulated", "GeForce RTX 3070 LHR"),
    0x2489: ("GA104", 0x174000A1, False, "experimental_simulated", "GeForce RTX 3060 Ti LHR"),
    0x2503: ("GA106", 0x176000A1, False, "experimental_simulated", "GeForce RTX 3060"),
    0x2504: ("GA106", 0x176000A1, False, "experimental_simulated", "GeForce RTX 3060 LHR"),
    # Experimental / simulated desktop Turing (RTX 20-series / CMP) SKUs
    0x1E04: ("TU102", 0x162000A1, False, "experimental_simulated", "GeForce RTX 2080 Ti"),
    0x1E07: ("TU102", 0x162000A1, False, "experimental_simulated", "GeForce RTX 2080 Ti Rev. A"),
    0x1E02: ("TU102", 0x162000A1, False, "experimental_simulated", "NVIDIA TITAN RTX"),
    0x1E09: ("TU102", 0x162000A1, False, "experimental_simulated", "NVIDIA CMP 50HX"),
    0x1E81: ("TU104", 0x164000A1, False, "experimental_simulated", "GeForce RTX 2080 SUPER"),
    0x1E82: ("TU104", 0x164000A1, False, "experimental_simulated", "GeForce RTX 2080"),
    0x1E87: ("TU104", 0x164000A1, False, "experimental_simulated", "GeForce RTX 2080 Rev. A"),
    0x1E84: ("TU104", 0x164000A1, False, "experimental_simulated", "GeForce RTX 2070 SUPER"),
    0x1F02: ("TU106", 0x166000A1, False, "experimental_simulated", "GeForce RTX 2070"),
    0x1F07: ("TU106", 0x166000A1, False, "experimental_simulated", "GeForce RTX 2070 Rev. A"),
    0x1F06: ("TU106", 0x166000A1, False, "experimental_simulated", "GeForce RTX 2060 SUPER"),
    0x1F47: ("TU106", 0x166000A1, False, "experimental_simulated", "GeForce RTX 2060 SUPER (TU106)"),
    0x1F08: ("TU106", 0x166000A1, False, "experimental_simulated", "GeForce RTX 2060 6GB"),
    0x1F03: ("TU106", 0x166000A1, False, "experimental_simulated", "GeForce RTX 2060 12GB"),
    0x1F0B: ("TU106", 0x166000A1, False, "experimental_simulated", "NVIDIA CMP 40HX"),
}


def classify_pci_device(device_id_16: int, gpu_name: str = "", sm_version: str = "") -> dict[str, Any]:
    """Classify a 16-bit NVIDIA PCI Device ID against the explicit SUPPORT_MATRIX."""
    name_up = (gpu_name or "").upper()
    is_mobile_hint = any(tok in name_up for tok in ("LAPTOP", "MOBILE", "MAX-Q"))
    if device_id_16 in SUPPORT_MATRIX and not is_mobile_hint:
        die, chip_id, is_ada, tier, model = SUPPORT_MATRIX[device_id_16]
        is_turing = die.startswith("TU10")
        expected_sm = "sm_75" if is_turing else ("sm_89" if is_ada else "sm_86")
        if sm_version and sm_version != expected_sm:
            return {
                "supported": False,
                "support_tier": "unsupported",
                "die_name": "UNSUPPORTED",
                "chip_id": 0,
                "is_ada": False,
                "is_turing": False,
                "reason": f"Compute capability {sm_version} conflicts with PCI ID 0x{device_id_16:04x} (expected {expected_sm})",
            }
        return {
            "supported": True,
            "support_tier": tier,
            "die_name": die,
            "chip_id": chip_id,
            "is_ada": is_ada,
            "is_turing": is_turing,
            "model_hint": model,
            "reason": "OK",
        }
    return {
        "supported": False,
        "support_tier": "unsupported",
        "die_name": "UNSUPPORTED",
        "chip_id": 0,
        "is_ada": False,
        "is_turing": False,
        "reason": f"PCI Device ID 0x{device_id_16:04x} ({gpu_name or 'unknown'}) is not in SUPPORT_MATRIX",
    }


def infer_die_and_chip(device_id_16: int, gpu_name: str = "", sm_version: str = "") -> tuple[str, int, bool]:
    res = classify_pci_device(device_id_16, gpu_name, sm_version)
    return res["die_name"], res["chip_id"], res["is_ada"]


ASSET_SPECS_ADA = {
    "booter_load_ad102.bin": (57672, "6ee05b20e1dc244c08c052f36ef28469b8d09f4955d1fe33e48a179e11a7fd49"),
    "v67-ad102-610.43.03-four-plm.bin": (64000, "44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb"),
    "gsp_ga10x.bin": (84277400, "572373620a37418f24dc16b5031c39338778c3257e48e8408de9a57291b24f3a"),
    "gsp_boot_ad102.bin": (36864, "45d6335a8185d6ff13e8d1484cea73f68d3d13aa1c19dc080ed1c3482dd5bac0"),
    "gsp_boot_desc_ad102.bin": (84, "83f8f3f1f5f9496e0ea8fc7103c2beb64d0b6de2f5ffe725f13514de5a95fa42"),
}

ASSET_SPECS_GA = {
    "booter_load_ga102.bin": (61256, "056cbc064a888f80717726c54d7f64fcd68044d123870c95a74f37f4975dcaa4"),
    "v67-ga102-610.43.03.bin": (64000, "2a0aa1f86d0b6afff5214d641d87d46dc98ef06ed908ff05d0ddbad5ffb7e197"),
    "gsp_ga10x.bin": (84277400, "572373620a37418f24dc16b5031c39338778c3257e48e8408de9a57291b24f3a"),
    "gsp_boot_ga102.bin": (24576, "3df651acb174fd5f5561a1996965b192f50c5d763168446ed0d4ead19d895768"),
    "gsp_boot_desc_ga102.bin": (84, "cc5a3fc1f4c47f2fe107b1b68f0176d8a448e6dec84b575e5560ccef5262bf15"),
}

ASSET_SPECS_TU = {
    "booter_load_tu102.bin": (59224, "a5cd2eb6a92f343003eb3da67905318dc24f59f77dc02fb48b6389098fbffdb5"),
    "v67-tu102-610.43.03.bin": (64000, "54513477ba4da9922fe00678ae390b1ec5136353989b23238c3524a69c7a8024"),
    "gsp_tu10x.bin": (46778072, "d9d9e0f23ccaa9f82e6879c97a7fb0962a421f7b713ba9ff2169641d34ef47be"),
    "gsp_boot_tu102.bin": (16384, "b2bdccbb79ad4dd48d85c35b00d9ccdf34625bd323805be3f9045a4a24d09fa5"),
    "gsp_boot_desc_tu102.bin": (84, "d66ab92e021b08d58045569df6956ef1bc742c57e7b31736b172578df87eb0e8"),
}

SOURCE_C_FILES = {
    "g_bindata_kgspGetBinArchiveBooterLoadUcode_AD102.c": (
        "0504f640bc36d03c3b617b1d80cf6eee1c8022cdfffb52ed22405aaa316a1460",
        "https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/452cec62d827034798072827d3866d1881662b77/src/nvidia/generated/g_bindata_kgspGetBinArchiveBooterLoadUcode_AD102.c",
    ),
    "g_bindata_kgspGetBinArchiveGspRmBoot_AD102.c": (
        "da110719ed6b680f26f3f7158f6731d1ff20fa859857238e23ac4935bd4cd91c",
        "https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/452cec62d827034798072827d3866d1881662b77/src/nvidia/generated/g_bindata_kgspGetBinArchiveGspRmBoot_AD102.c",
    ),
    "g_bindata_kgspGetBinArchiveBooterLoadUcode_GA102.c": (
        "04cd3db7f670adc4efd79d2e76217bb809fffddfbd6f1af884cde2af26dd39af",
        "https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/452cec62d827034798072827d3866d1881662b77/src/nvidia/generated/g_bindata_kgspGetBinArchiveBooterLoadUcode_GA102.c",
    ),
    "g_bindata_kgspGetBinArchiveGspRmBoot_GA102.c": (
        "35e5aa9075ad3898b6022ffd5820c953d809caa7dabd530cfc1a83dc2a67c5bd",
        "https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/452cec62d827034798072827d3866d1881662b77/src/nvidia/generated/g_bindata_kgspGetBinArchiveGspRmBoot_GA102.c",
    ),
    "g_bindata_kgspGetBinArchiveBooterLoadUcode_TU102.c": (
        "4f894b21139bc52f713fb0e78b7e3489054463689c3eb993ec6a6f598d7ef9aa",
        "https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/452cec62d827034798072827d3866d1881662b77/src/nvidia/generated/g_bindata_kgspGetBinArchiveBooterLoadUcode_TU102.c",
    ),
    "g_bindata_kgspGetBinArchiveGspRmBoot_TU102.c": (
        "5185662535c9c55ffcb1a67698db5ca4fc852aa9ab1746072855bd1839c73742",
        "https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/452cec62d827034798072827d3866d1881662b77/src/nvidia/generated/g_bindata_kgspGetBinArchiveGspRmBoot_TU102.c",
    ),
}

SOURCE_TARBALL_URL = "https://download.nvidia.com/XFree86/NVIDIA-kernel-module-source/NVIDIA-kernel-module-source-610.43.03.tar.xz"
SOURCE_TARBALL_SHA256 = "7e118923c7a23edc36114d63273a46e3e04e9af98695a42203e7ac2dfe9fc1dc"
PACKAGE_URL = "https://archive.cachyos.org/archive/cachyos-v3/nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst"
PACKAGE_SHA256 = "e17e7c92eeffa178b0fe1f40eb17a47095f8fc3ce4a77bf115cf5bd5a4df86e9"

GA102_PATCHED_WORDS = {
    0x1100: 0x00000007,
    0xF948: 0xFFFFFFFF,
    0xF950: 0x00000D44,
    0xF960: 0x00823804,
    0xF968: 0x00001FCE,
    0xF974: 0x00000000,
    0xF97C: 0x00001101,
    0xF980: 0x000084C8,
    0xF984: 0x00008E18,
    0xF98C: 0x000084C8,
    0xF990: 0x00000000,
    0xF998: 0x00001FCE,
    0xF9A4: 0x0000FFBC,
    0xF9AC: 0x00005789,
    0xF9BC: 0x00000D44,
    0xF9CC: 0x00000003,
    0xF9D4: 0x00001FCE,
    0xF9E8: 0x00000D52,
    0xF9EC: 0x000081EE,
}

AD102_PATCHED_WORDS = {
    0x1100: 0x00000007,
    0xF948: 0xFFFFF0FF,
    0xF950: 0x000021B2,
    0xF960: 0x001FA7CC,
    0xF968: 0x000033FC,
    0xF974: 0xFFFFFFFF,
    0xF97C: 0x0000256F,
    0xF980: 0x00007A02,
    0xF984: 0x009A0148,
    0xF98C: 0x000033FC,
    0xF998: 0xFFFFFFFF,
    0xF9A0: 0x0000256F,
    0xF9A4: 0x00007A02,
    0xF9A8: 0x001FA7C4,
    0xF9B0: 0x000033FC,
    0xF9BC: 0xFFFFFFFF,
    0xF9C4: 0x0000256F,
    0xF9C8: 0x00007A02,
    0xF9CC: 0x00823804,
    0xF9D4: 0x000033FC,
    0xF9E0: 0x67B00001,
    0xF9E8: 0x0000256F,
    0xF9EC: 0x00007A02,
    0xF9F8: 0x000031B5,
    0xF9FC: 0x0000771E,
}


TU102_PATCHED_WORDS = {
    0x1100: 0x00000007,
    0xF938: 0x00006140,
    0xF940: 0x001FA7CC,
    0xF944: 0xFFFFF0FF,
    0xF94C: 0x000010B9,
    0xF950: 0x00006140,
    0xF958: 0x00409650,
    0xF95C: 0xFFFFFFFF,
    0xF964: 0x000010B9,
    0xF968: 0x00006140,
    0xF970: 0x00409650,
    0xF974: 0xFFFFFFFF,
    0xF97C: 0x000010B9,
    0xF980: 0x00006140,
    0xF988: 0x00409650,
    0xF98C: 0xFFFFFFFF,
    0xF994: 0x000010B9,
    0xF998: 0x00006140,
    0xF9A0: 0x00409650,
    0xF9A4: 0xFFFFFFFF,
    0xF9AC: 0x000010B9,
    0xF9B0: 0x00006140,
    0xF9B8: 0x00409650,
    0xF9BC: 0xFFFFFFFF,
    0xF9C4: 0x000010B9,
    0xF9C8: 0x00006140,
    0xF9D4: 0x00000003,
    0xF9DC: 0x00006521,
    0xF9E0: 0x00007F27,
    0xF9EC: 0x00000CCB,
    0xF9F0: 0x00007EA4,
}


def build_v67_payload(is_ada: bool = True, arch: str | None = None) -> bytes:
    if arch == "tu102" or (isinstance(is_ada, str) and is_ada.lower() == "tu102"):
        word = (0x000004A7).to_bytes(4, "little")
        payload = bytearray(word * (0xFA00 // 4))
        for offset, value in TU102_PATCHED_WORDS.items():
            payload[offset : offset + 4] = value.to_bytes(4, "little")
        return bytes(payload)
    word = (0x0000019C).to_bytes(4, "little")
    payload = bytearray(word * (0xFA00 // 4))
    table = AD102_PATCHED_WORDS if is_ada else GA102_PATCHED_WORDS
    for offset, value in table.items():
        payload[offset : offset + 4] = value.to_bytes(4, "little")
    return bytes(payload)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def find_llvm_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    candidates = [
        Path(r"C:\Program Files\LLVM\bin") / f"{name}.exe",
        Path(r"C:\Program Files (x86)\LLVM\bin") / f"{name}.exe",
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\Llvm\x64\bin") / f"{name}.exe",
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Tools\Llvm\x64\bin") / f"{name}.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def check_zst_support() -> tuple[bool, str]:
    try:
        import zstandard as zstd  # type: ignore
        dctx = zstd.ZstdDecompressor()
        cctx = zstd.ZstdCompressor()
        if dctx.decompress(cctx.compress(b"gpu-unlock-zst-probe")) == b"gpu-unlock-zst-probe":
            return True, "python-zstandard"
    except Exception:
        pass
    zstd_exe = shutil.which("zstd.exe") or shutil.which("zstd")
    tar_exe = shutil.which("tar.exe") or shutil.which("tar")
    if tar_exe and zstd_exe:
        return True, f"tar + {Path(zstd_exe).name}"
    if tar_exe:
        try:
            res = subprocess.run(
                [tar_exe, "--help"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if "--zstd" in (res.stdout + res.stderr):
                return True, f"system tar ({Path(tar_exe).name})"
        except Exception:
            pass
    return False, "missing"


def guid_string_to_c_macro(guid_str: str) -> str:
    if not isinstance(guid_str, str):
        raise ValueError("GUID must be a string")
    clean = guid_str.strip().strip("{}").replace("-", "")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", clean):
        raise ValueError(f"Invalid GUID string: {guid_str}")
    if int(clean, 16) == 0:
        raise ValueError("Refusing all-zero inert GUID")
    d1 = int(clean[0:8], 16)
    d2 = int(clean[8:12], 16)
    d3 = int(clean[12:16], 16)
    d4 = [int(clean[16 + 2 * i : 18 + 2 * i], 16) for i in range(8)]
    d4_str = ",".join(f"0x{b:02x}" for b in d4)
    return f"0x{d1:08x}U,0x{d2:04x}U,0x{d3:04x}U,{{{d4_str}}}"


def _parse_hex_int(val: Any, field_name: str, min_val: int, max_val: int) -> int:
    if isinstance(val, int) and not isinstance(val, bool):
        parsed = val
    elif isinstance(val, str):
        s = val.strip().rstrip("uUlL")
        if not re.fullmatch(r"(0[xX][0-9a-fA-F]+|\d+)", s):
            raise ValueError(f"Invalid numeric literal for {field_name}: {val!r}")
        parsed = int(s, 0)
    else:
        raise ValueError(f"Invalid type for {field_name}: {type(val).__name__}")
    if not (min_val <= parsed <= max_val):
        raise ValueError(f"Field {field_name}={parsed:#x} out of range [{min_val:#x}..{max_val:#x}]")
    return parsed


def validate_target_profile(config: dict[str, Any]) -> dict[str, Any]:
    """Strictly validate every field of a target hardware profile before generating C headers (H-01, F19)."""
    if not isinstance(config, dict):
        raise ValueError("Profile config must be a dictionary")

    board_id = _parse_hex_int(config.get("board_id_hex", ""), "board_id_hex", 0x000110DE, 0xFFFF10DE)
    if (board_id & 0xFFFF) != 0x10DE:
        raise ValueError(f"board_id_hex must have NVIDIA vendor ID 0x10de (got {board_id:#010x})")
    dev16 = (board_id >> 16) & 0xFFFF
    support = classify_pci_device(dev16, str(config.get("gpu_name", "")))
    if not support["supported"]:
        raise ValueError(support["reason"])

    subsys_id = _parse_hex_int(config.get("subsystem_id_hex", ""), "subsystem_id_hex", 1, 0xFFFFFFFF)
    chip_id = _parse_hex_int(config.get("chip_id_hex", ""), "chip_id_hex", 0x160000A1, 0x19F000A1)
    die_name = str(config.get("die_name", "")).strip()
    if die_name not in CHIP_BY_PMC:
        raise ValueError(f"Unsupported die_name: {die_name!r}")

    # Require die_name and chip_id to match the canonical SUPPORT_MATRIX entry for dev16!
    if die_name != support["die_name"]:
        raise ValueError(
            f"Die mismatch for PCI Device ID 0x{dev16:04x}: expected {support['die_name']}, got {die_name}"
        )
    if chip_id != support["chip_id"]:
        raise ValueError(
            f"Chip ID mismatch for {die_name} (PCI 0x{dev16:04x}): expected {support['chip_id']:#010x}, got {chip_id:#010x}"
        )
    is_ada = support["is_ada"]
    is_turing = support.get("is_turing", False)

    seg = _parse_hex_int(config.get("segment_hex", 0), "segment_hex", 0, 0xFFFF)
    bus = _parse_hex_int(config.get("bus_hex", ""), "bus_hex", 0, 0xFF)
    dev = _parse_hex_int(config.get("device_hex", 0), "device_hex", 0, 0x1F)
    func = _parse_hex_int(config.get("function_hex", 0), "function_hex", 0, 0x7)

    vram_min = _parse_hex_int(config.get("vram_min_hex", ""), "vram_min_hex", 0x400, 0x40000)
    vram_max = _parse_hex_int(config.get("vram_max_hex", ""), "vram_max_hex", vram_min, 0x40000)
    if vram_max - vram_min > 0x1000:
        raise ValueError(f"VRAM range [{vram_min:#x}..{vram_max:#x}] is wider than 4096 MiB")

    esp_guid = str(config.get("esp_guid", "")).strip()
    esp_macro = guid_string_to_c_macro(esp_guid)
    esp_part = _parse_hex_int(config.get("esp_part_num", 0), "esp_part_num", 0, 128)

    clean_guid = esp_guid.strip("{}").replace("-", "")
    first_dword = int(clean_guid[0:8], 16) ^ 1
    payload_macro = guid_string_to_c_macro(f"{{{first_dword:08x}-{clean_guid[8:12]}-{clean_guid[12:16]}-{clean_guid[16:20]}-{clean_guid[20:32]}}}")

    prom_sha = str(config.get("prom_sha256", "AUTO") or "AUTO").strip()
    rom_sha = str(config.get("rom_sha256", "AUTO") or "AUTO").strip()
    for label, val in (("prom_sha256", prom_sha), ("rom_sha256", rom_sha)):
        if not re.fullmatch(r"(AUTO|[0-9a-fA-F]{64})", val):
            raise ValueError(f"Invalid {label}: must be 'AUTO' or 64-char hex SHA-256")

    unattended = 1 if bool(config.get("unattended_autofire", False)) else 0

    return {
        "gpu_name": str(config.get("gpu_name") or support["model_hint"]),
        "die_name": die_name,
        "is_ada": is_ada,
        "is_turing": is_turing,
        "support_tier": support["support_tier"],
        "board_id": board_id,
        "subsys_id": subsys_id,
        "chip_id": chip_id,
        "seg": seg,
        "bus": bus,
        "dev": dev,
        "func": func,
        "vram_min": vram_min,
        "vram_max": vram_max,
        "esp_guid": esp_guid,
        "esp_macro": esp_macro,
        "esp_part": esp_part,
        "payload_macro": payload_macro,
        "prom_sha": prom_sha if prom_sha == "AUTO" else prom_sha.lower(),
        "rom_sha": rom_sha if rom_sha == "AUTO" else rom_sha.lower(),
        "unattended": unattended,
    }


def _load_nvml_library() -> ctypes.CDLL | None:
    search_paths = [
        r"C:\Windows\System32\nvml.dll",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll",
        "nvml.dll",
        "libnvidia-ml.so.1",
        "libnvidia-ml.so",
        "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1",
        "/usr/lib/x86_64-linux-gnu/nvidia/current/libnvidia-ml.so.1",
        "/usr/lib64/libnvidia-ml.so.1",
        "/usr/lib/libnvidia-ml.so.1",
        "/lib/x86_64-linux-gnu/libnvidia-ml.so.1",
        "/lib64/libnvidia-ml.so.1",
    ]
    if sys.platform.startswith("win"):
        driver_store = glob.glob(r"C:\Windows\System32\DriverStore\FileRepository\nv*\nvml.dll")
        search_paths.extend(driver_store)
    for lib_name in search_paths:
        try:
            return ctypes.CDLL(lib_name)
        except OSError:
            continue
    return None


def _query_cuda_sm_info() -> dict[tuple[int, int, int], dict[str, Any]]:
    """Query CUDA Driver API (nvcuda.dll) for exact silicon Compute Capability keyed by (domain, bus, device)."""
    by_loc: dict[tuple[int, int, int], dict[str, Any]] = {}
    for name in (
        r"C:\Windows\System32\nvcuda.dll",
        "nvcuda.dll",
        "libcuda.so.1",
        "libcuda.so",
        "/usr/lib/x86_64-linux-gnu/libcuda.so.1",
        "/usr/lib/x86_64-linux-gnu/nvidia/current/libcuda.so.1",
        "/usr/lib64/libcuda.so.1",
        "/usr/lib/libcuda.so.1",
        "/lib/x86_64-linux-gnu/libcuda.so.1",
        "/lib64/libcuda.so.1",
    ):
        try:
            cuda = ctypes.CDLL(name)
            break
        except OSError:
            cuda = None
    if cuda is None:
        return by_loc
    try:
        if cuda.cuInit(0) != 0:
            return by_loc
        cnt = ctypes.c_int(0)
        if cuda.cuDeviceGetCount(ctypes.byref(cnt)) != 0:
            return by_loc
        for idx in range(cnt.value):
            dev = ctypes.c_int(0)
            if cuda.cuDeviceGet(ctypes.byref(dev), idx) != 0:
                continue

            def _attr(aid: int) -> tuple[bool, int]:
                v = ctypes.c_int(0)
                rc = cuda.cuDeviceGetAttribute(ctypes.byref(v), aid, dev)
                return (rc == 0), v.value

            ok_bus, bus_id = _attr(33)       # CU_DEVICE_ATTRIBUTE_PCI_BUS_ID
            ok_dev, pci_dev = _attr(34)      # CU_DEVICE_ATTRIBUTE_PCI_DEVICE_ID
            ok_maj, cc_maj = _attr(75)       # CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MAJOR
            ok_min, cc_min = _attr(76)       # CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MINOR
            ok_dom, dom_id = _attr(50)       # CU_DEVICE_ATTRIBUTE_PCI_DOMAIN_ID
            if not (ok_bus and ok_dev and ok_maj and ok_min) or cc_maj <= 0:
                continue
            dom_val = dom_id if ok_dom else 0
            by_loc[(dom_val, bus_id, pci_dev)] = {
                "sm_version": f"sm_{cc_maj}{cc_min}",
                "cc_major": cc_maj,
                "cc_minor": cc_min,
                "pci_device": pci_dev,
                "pci_domain": dom_val,
            }
    except Exception:
        pass
    return by_loc


def _query_windows_pnp_gpus() -> list[dict[str, Any]]:
    """Fallback & cross-verification directly from Windows pci.sys via Get-PnpDevice."""
    results: list[dict[str, Any]] = []
    if not sys.platform.startswith("win"):
        return results
    ps_cmd = (
        "Get-PnpDevice -Class Display -PresentOnly | Where-Object { $_.InstanceId -match '^PCI\\\\VEN_10DE' } | "
        "ForEach-Object { "
        "$bus = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_BusNumber').Data; "
        "$addr = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_Address').Data; "
        "[PSCustomObject]@{ Name=$_.FriendlyName; InstanceId=$_.InstanceId; Bus=$bus; Addr=$addr } "
        "} | ConvertTo-Json -Compress"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode == 0 and res.stdout.strip():
            parsed = json.loads(res.stdout.strip())
            if isinstance(parsed, dict):
                parsed = [parsed]
            for item in parsed:
                inst = str(item.get("InstanceId", "")).upper()
                m = re.search(r"VEN_10DE&DEV_([0-9A-F]{4})&SUBSYS_([0-9A-F]{8})", inst)
                if m and item.get("Bus") is not None:
                    dev16 = int(m.group(1), 16)
                    sub32 = int(m.group(2), 16)
                    bus_num = int(item.get("Bus"))
                    addr = int(item.get("Addr") or 0)
                    dev_num = (addr >> 16) & 0x1F
                    func_num = addr & 0x7
                    results.append({
                        "gpu_name": item.get("Name") or "NVIDIA GPU",
                        "dev16": dev16,
                        "board_id_hex": f"0x{dev16:04x}10de",
                        "subsystem_id_hex": f"0x{sub32:08x}",
                        "domain": 0,
                        "bus": bus_num,
                        "dev": dev_num,
                        "func": func_num,
                        "bus_hex": f"0x{bus_num:02x}",
                    })
    except Exception:
        pass
    return results


NOMINAL_VRAM_MIB: dict[int, int] = {
    0x2684: 24564, 0x2685: 24564, 0x2689: 16376,
    0x2702: 16376, 0x2704: 16380, 0x2705: 16376, 0x2709: 12282,
    0x2782: 12282, 0x2783: 12282, 0x2786: 12282, 0x27B0: 8188,
    0x2803: 8188, 0x2805: 16380, 0x2808: 8188, 0x2882: 8188,
    0x2203: 24564, 0x2204: 24576, 0x2206: 10240, 0x2207: 8192,
    0x2208: 12288, 0x220A: 12288, 0x2216: 10240, 0x2414: 8192,
    0x2482: 8192, 0x2484: 8192, 0x2486: 8192, 0x2487: 12288,
    0x2488: 8192, 0x2489: 8192, 0x2503: 12288, 0x2504: 12288,
    0x1E04: 11264, 0x1E07: 11264, 0x1E02: 24576, 0x1E09: 10240,
    0x1E81: 8192, 0x1E82: 8192, 0x1E87: 8192, 0x1E84: 8192,
    0x1F02: 8192, 0x1F07: 8192, 0x1F06: 8192, 0x1F47: 8192,
    0x1F08: 6144, 0x1F03: 12288, 0x1F0B: 8192,
}


def get_linux_modprobe_command_for_gpu(gpu: dict[str, Any]) -> str:
    """Return the exact modprobe command to load gpu_unlock.ko live for the detected GPU."""
    bdf = str(gpu.get("pci_bdf") or "").strip().lower()
    board_hex = str(gpu.get("board_id_hex") or "").strip().lower()
    if not bdf or not board_hex.startswith("0x"):
        return "UNSUPPORTED"
    try:
        dev16 = (int(board_hex, 16) >> 16) & 0xFFFF
    except ValueError:
        return "UNSUPPORTED"
    cls = classify_pci_device(dev16, str(gpu.get("gpu_name") or ""))
    if not cls["supported"]:
        return "UNSUPPORTED"
    if cls.get("is_turing"):
        return f"modprobe gpu_unlock targets={bdf} turing_experimental=1"
    if not cls["is_ada"] or dev16 == 0x2684:
        return f"modprobe gpu_unlock targets={bdf}"
    if dev16 in (0x2702, 0x2704, 0x2705, 0x2709):
        return f"modprobe gpu_unlock targets={bdf} ad103_experimental=1"
    if dev16 in (0x2782, 0x2783, 0x2786, 0x27B0):
        return f"modprobe gpu_unlock targets={bdf} ad104_experimental=1"
    return f"modprobe gpu_unlock targets={bdf} ada_experimental=1"


def get_linux_boot_option_for_gpu(gpu: dict[str, Any]) -> str:
    """Return the exact kernel command line option string for gpu_unlock.ko on Linux."""
    bdf = str(gpu.get("pci_bdf") or "").strip().lower()
    board_hex = str(gpu.get("board_id_hex") or "").strip().lower()
    if not bdf or not board_hex.startswith("0x"):
        return "UNSUPPORTED"
    try:
        dev16 = (int(board_hex, 16) >> 16) & 0xFFFF
    except ValueError:
        return "UNSUPPORTED"
    cls = classify_pci_device(dev16, str(gpu.get("gpu_name") or ""))
    if not cls["supported"]:
        return "UNSUPPORTED"
    if cls.get("is_turing"):
        return f"gpu_unlock.targets={bdf} gpu_unlock.turing_experimental=1"
    if not cls["is_ada"] or dev16 == 0x2684:
        return f"gpu_unlock.targets={bdf}"
    if dev16 in (0x2702, 0x2704, 0x2705, 0x2709):
        return f"gpu_unlock.targets={bdf} gpu_unlock.ad103_experimental=1"
    if dev16 in (0x2782, 0x2783, 0x2786, 0x27B0):
        return f"gpu_unlock.targets={bdf} gpu_unlock.ad104_experimental=1"
    return f"gpu_unlock.targets={bdf} gpu_unlock.ada_experimental=1"


def _normalize_pci_bdf(raw_bdf: str) -> tuple[str, int, int, int, int]:
    """Normalize 8-digit NVML/nvidia-smi domain (00000000:01:00.0) to standard 4-digit Linux BDF (0000:01:00.0)."""
    m = re.match(r"^([0-9a-fA-F]{4,8}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])$", raw_bdf.strip())
    if not m:
        return ("", 0, 0, 0, 0)
    dom = int(m.group(1), 16) & 0xFFFF
    bus = int(m.group(2), 16) & 0xFF
    dev = int(m.group(3), 16) & 0x1F
    func = int(m.group(4), 16) & 0x7
    return (f"{dom:04x}:{bus:02x}:{dev:02x}.{func}", dom, bus, dev, func)


def _query_linux_pci_gpus(
    sysfs_root: Path | None = None,
    lspci_output: str | None = None,
) -> list[dict[str, Any]]:
    """Query Linux kernel PCI sysfs (/sys/bus/pci/devices) and lspci -Dnn for NVIDIA display GPUs."""
    results: list[dict[str, Any]] = []
    if sysfs_root is None and lspci_output is None and not sys.platform.startswith("linux"):
        return results

    lspci_names: dict[str, str] = {}
    lspci_devs: dict[str, int] = {}
    if lspci_output is None and sys.platform.startswith("linux"):
        lspci_exe = shutil.which("lspci") or ("/usr/bin/lspci" if Path("/usr/bin/lspci").exists() else "/sbin/lspci")
        try:
            res = subprocess.run([lspci_exe, "-Dnn"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                lspci_output = res.stdout
        except Exception:
            lspci_output = ""

    if lspci_output:
        for line in lspci_output.splitlines():
            m = re.match(
                r"^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])\s+"
                r"(?:VGA compatible controller|3D controller|Display controller)[^:]*:\s*(.+)$",
                line.strip(),
                re.I,
            )
            if not m:
                continue
            bdf_norm, _, _, _, _ = _normalize_pci_bdf(m.group(1))
            desc = m.group(2).strip()
            id_m = re.search(r"\[10de:([0-9a-fA-F]{4})\]", desc, re.I)
            if not bdf_norm or not id_m:
                continue
            dev16 = int(id_m.group(1), 16)
            lspci_devs[bdf_norm] = dev16
            bracket_names = re.findall(r"\[([^\[\]]+)\]", desc)
            human_model = ""
            for bn in bracket_names:
                if not re.fullmatch(r"10de:[0-9a-fA-F]{4}", bn, re.I) and not re.fullmatch(r"[0-9a-fA-F]{4}", bn):
                    human_model = f"NVIDIA {bn}" if not bn.upper().startswith("NVIDIA") else bn
                    break
            if not human_model and dev16 in SUPPORT_MATRIX:
                human_model = f"NVIDIA {SUPPORT_MATRIX[dev16][4]}"
            lspci_names[bdf_norm] = human_model or "NVIDIA GPU"

    sroot = sysfs_root if sysfs_root is not None else Path("/sys/bus/pci/devices")
    seen_bdfs: set[str] = set()
    if sroot.exists() and sroot.is_dir():
        for dev_dir in sorted(sroot.iterdir(), key=lambda x: x.name):
            bdf_norm, dom, bus, dev, func = _normalize_pci_bdf(dev_dir.name)
            if not bdf_norm:
                continue
            try:
                ven_txt = (dev_dir / "vendor").read_text(encoding="ascii").strip()
                dev_txt = (dev_dir / "device").read_text(encoding="ascii").strip()
                if int(ven_txt, 16) != 0x10DE:
                    continue
                if (dev_dir / "class").exists():
                    cls_val = int((dev_dir / "class").read_text(encoding="ascii").strip(), 16)
                    if ((cls_val >> 16) & 0xFF) != 0x03:
                        continue
                dev16 = int(dev_txt, 16) & 0xFFFF
                sub_ven16 = 0x10DE
                sub_dev16 = dev16
                if (dev_dir / "subsystem_vendor").exists() and (dev_dir / "subsystem_device").exists():
                    sv = int((dev_dir / "subsystem_vendor").read_text(encoding="ascii").strip(), 16) & 0xFFFF
                    sd = int((dev_dir / "subsystem_device").read_text(encoding="ascii").strip(), 16) & 0xFFFF
                    if sv or sd:
                        sub_ven16, sub_dev16 = sv, sd
                drv_name = "unbound"
                drv_link = dev_dir / "driver"
                if drv_link.exists() or drv_link.is_symlink():
                    try:
                        drv_name = Path(os.readlink(drv_link)).name
                    except OSError:
                        drv_name = "bound"
                model_name = lspci_names.get(bdf_norm)
                if not model_name:
                    if dev16 in SUPPORT_MATRIX:
                        model_name = f"NVIDIA {SUPPORT_MATRIX[dev16][4]}"
                    else:
                        model_name = f"NVIDIA PCI 10de:{dev16:04x}"
                seen_bdfs.add(bdf_norm)
                results.append({
                    "gpu_name": model_name,
                    "dev16": dev16,
                    "pci_bdf": bdf_norm,
                    "board_id_hex": f"0x{(dev16 << 16) | 0x10de:08x}",
                    "subsystem_id_hex": f"0x{(sub_dev16 << 16) | sub_ven16:08x}",
                    "domain": dom,
                    "bus": bus,
                    "dev": dev,
                    "func": func,
                    "bus_hex": f"0x{bus:02x}",
                    "bound_driver": drv_name,
                })
            except Exception:
                continue

    for bdf_norm, dev16 in sorted(lspci_devs.items()):
        if bdf_norm in seen_bdfs:
            continue
        _, dom, bus, dev, func = _normalize_pci_bdf(bdf_norm)
        results.append({
            "gpu_name": lspci_names.get(bdf_norm, f"NVIDIA PCI 10de:{dev16:04x}"),
            "dev16": dev16,
            "pci_bdf": bdf_norm,
            "board_id_hex": f"0x{(dev16 << 16) | 0x10de:08x}",
            "subsystem_id_hex": f"0x{(dev16 << 16) | 0x10de:08x}",
            "domain": dom,
            "bus": bus,
            "dev": dev,
            "func": func,
            "bus_hex": f"0x{bus:02x}",
            "bound_driver": "unknown",
        })
    return results


def _query_nvidia_smi_gpus(raw_csv: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Fallback query via nvidia-smi CLI if ctypes NVML library is not directly loadable."""
    gpus: list[dict[str, Any]] = []
    drv_ver = "N/A"
    if raw_csv is None:
        smi_exe = (
            r"C:\Windows\System32\nvidia-smi.exe"
            if sys.platform.startswith("win") and Path(r"C:\Windows\System32\nvidia-smi.exe").exists()
            else (shutil.which("nvidia-smi") or "/usr/bin/nvidia-smi")
        )
        try:
            res = subprocess.run(
                [
                    smi_exe,
                    "--query-gpu=index,name,uuid,pci.bus_id,pci.device_id,pci.sub_device_id,memory.total,vbios_version,driver_version,power.default_limit,power.min_limit,power.max_limit",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if res.returncode != 0 or not res.stdout.strip():
                return drv_ver, gpus
            raw_csv = res.stdout.strip()
        except Exception:
            return drv_ver, gpus

    for line in raw_csv.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 12:
            continue
        try:
            idx_s, name_s, uuid_s, bdf_s, dev_hex, sub_hex, vram_s, vbios_s, dver_s, pdef_s, pmin_s, pmax_s = parts[:12]
            bdf_norm, dom, bus, dev, func = _normalize_pci_bdf(bdf_s)
            if not bdf_norm:
                continue
            dev32 = int(dev_hex, 16)
            sub32 = int(sub_hex, 16)
            dev16 = (dev32 >> 16) & 0xFFFF
            vram_mib = int(round(float(vram_s)))
            low = max(1024, (vram_mib - 64) & ~0xF)
            high = (vram_mib + 64 + 0xF) & ~0xF
            drv_ver = dver_s or drv_ver

            def _flt(s: str) -> float:
                try:
                    return round(float(s), 1)
                except Exception:
                    return 0.0

            gpus.append({
                "index": int(idx_s),
                "gpu_name": name_s,
                "gpu_uuid": uuid_s,
                "pci_bdf": bdf_norm,
                "domain": dom,
                "bus": bus,
                "dev": dev,
                "func": func,
                "dev16": dev16,
                "board_id_hex": f"0x{dev32:08x}",
                "subsystem_id_hex": f"0x{sub32:08x}",
                "vram_mib": vram_mib,
                "vram_min_hex": f"0x{low:x}",
                "vram_max_hex": f"0x{high:x}",
                "vbios_version": vbios_s,
                "power_default_w": _flt(pdef_s),
                "power_min_w": _flt(pmin_s),
                "power_max_w": _flt(pmax_s),
            })
        except Exception:
            continue
    return drv_ver, gpus


def _parse_bdf_function(bus_id_bytes: bytes) -> int:
    try:
        s = bus_id_bytes.decode("ascii", errors="ignore").strip("\x00").strip()
        if "." in s:
            return int(s.rsplit(".", 1)[1], 16) & 0x7
    except Exception:
        pass
    return 0


def detect_host_environment() -> dict[str, Any]:
    """Detect GPU hardware via triple-source cross-verification (NVML + CUDA + Windows PnP)."""
    zst_ok, zst_method = check_zst_support()
    info: dict[str, Any] = {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "gpu_detected": False,
        "support_tier": "unsupported",
        "verification_sources": [],
        "gpus": [],
        "gpu_name": "NOT DETECTED",
        "gpu_uuid": "",
        "pci_bdf": "",
        "board_id_hex": "",
        "subsystem_id_hex": "",
        "segment_hex": "0x0",
        "bus_hex": "",
        "device_hex": "0x0",
        "function_hex": "0x0",
        "die_name": "UNSUPPORTED",
        "chip_id_hex": "",
        "is_ada": False,
        "vram_mib": 0,
        "vram_min_hex": "",
        "vram_max_hex": "",
        "vbios_version": "N/A",
        "driver_version": "N/A",
        "power_default_w": 0.0,
        "power_min_w": 0.0,
        "power_max_w": 0.0,
        "esp_guid": "",
        "esp_part_num": 0,
        "esp_disk_part": "NOT DETECTED",
        "esp_ambiguous": False,
        "esp_candidates": [],
        "secure_boot_enabled": None,
        "bitlocker_protection_on": None,
        "clang_path": find_llvm_tool("clang"),
        "lld_path": find_llvm_tool("lld-link"),
        "zst_ok": zst_ok,
        "zst_method": zst_method,
    }

    cuda_by_loc = _query_cuda_sm_info()
    pnp_gpus = _query_windows_pnp_gpus()
    linux_pci_gpus = _query_linux_pci_gpus()
    nvml = _load_nvml_library()

    if nvml is not None:
        nvml_initialized = False
        try:
            if nvml.nvmlInit_v2() == 0:
                nvml_initialized = True
                drv_buf = ctypes.create_string_buffer(80)
                if nvml.nvmlSystemGetDriverVersion(drv_buf, 80) == 0:
                    info["driver_version"] = drv_buf.value.decode("utf-8", errors="replace")

                count = ctypes.c_uint(0)
                if nvml.nvmlDeviceGetCount_v2(ctypes.byref(count)) == 0 and count.value > 0:
                    class NvmlPciInfo(ctypes.Structure):
                        _fields_ = [
                            ("busIdLegacy", ctypes.c_char * 16),
                            ("domain", ctypes.c_uint),
                            ("bus", ctypes.c_uint),
                            ("device", ctypes.c_uint),
                            ("pciDeviceId", ctypes.c_uint),
                            ("pciSubSystemId", ctypes.c_uint),
                            ("busId", ctypes.c_char * 32),
                        ]

                    class NvmlMemory(ctypes.Structure):
                        _fields_ = [
                            ("total", ctypes.c_ulonglong),
                            ("free", ctypes.c_ulonglong),
                            ("used", ctypes.c_ulonglong),
                        ]

                    for idx in range(count.value):
                        handle = ctypes.c_void_p()
                        if nvml.nvmlDeviceGetHandleByIndex_v2(idx, ctypes.byref(handle)) != 0:
                            continue
                        pci = NvmlPciInfo()
                        if nvml.nvmlDeviceGetPciInfo_v3(handle, ctypes.byref(pci)) != 0:
                            continue

                        name_buf = ctypes.create_string_buffer(96)
                        gpu_name = "NVIDIA GPU"
                        if nvml.nvmlDeviceGetName(handle, name_buf, 96) == 0:
                            gpu_name = name_buf.value.decode("utf-8", errors="replace")

                        uuid_buf = ctypes.create_string_buffer(96)
                        gpu_uuid = ""
                        if hasattr(nvml, "nvmlDeviceGetUUID") and nvml.nvmlDeviceGetUUID(handle, uuid_buf, 96) == 0:
                            gpu_uuid = uuid_buf.value.decode("utf-8", errors="replace")

                        vbios_buf = ctypes.create_string_buffer(64)
                        vbios_ver = "N/A"
                        if nvml.nvmlDeviceGetVbiosVersion(handle, vbios_buf, 64) == 0:
                            vbios_ver = vbios_buf.value.decode("utf-8", errors="replace")

                        mem = NvmlMemory()
                        vram_mib = 0
                        vram_min_hex = ""
                        vram_max_hex = ""
                        if nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) == 0 and mem.total > 0:
                            vram_mib = int(round(mem.total / (1024 * 1024)))
                            low = max(1024, (vram_mib - 64) & ~0xF)
                            high = (vram_mib + 64 + 0xF) & ~0xF
                            vram_min_hex = f"0x{low:x}"
                            vram_max_hex = f"0x{high:x}"

                        def_pl = ctypes.c_uint(0)
                        min_pl = ctypes.c_uint(0)
                        max_pl = ctypes.c_uint(0)
                        p_def = 0.0
                        p_min = 0.0
                        p_max = 0.0
                        if nvml.nvmlDeviceGetPowerManagementDefaultLimit(handle, ctypes.byref(def_pl)) == 0:
                            p_def = round(def_pl.value / 1000.0, 1)
                        if nvml.nvmlDeviceGetPowerManagementLimitConstraints(handle, ctypes.byref(min_pl), ctypes.byref(max_pl)) == 0:
                            p_min = round(min_pl.value / 1000.0, 1)
                            p_max = round(max_pl.value / 1000.0, 1)

                        func_num = _parse_bdf_function(pci.busId or pci.busIdLegacy)
                        dev16 = (pci.pciDeviceId >> 16) & 0xFFFF
                        c_info = cuda_by_loc.get((pci.domain, pci.bus, pci.device), {})
                        sm_ver = c_info.get("sm_version", "")
                        sources = ["NVML"]
                        if sm_ver:
                            sources.append(f"CUDA ({sm_ver})")
                        board_hex = f"0x{pci.pciDeviceId:08x}"
                        subsys_hex = f"0x{pci.pciSubSystemId:08x}"
                        for pg in pnp_gpus:
                            if (
                                pg["bus"] == pci.bus
                                and pg["dev"] == pci.device
                                and pg["func"] == func_num
                                and pg["board_id_hex"] == board_hex
                                and pg["subsystem_id_hex"] == subsys_hex
                            ):
                                sources.append("Windows PCI.sys")
                                break
                        bound_driver = "nvidia"
                        for lg in linux_pci_gpus:
                            if (
                                lg["domain"] == pci.domain
                                and lg["bus"] == pci.bus
                                and lg["dev"] == pci.device
                                and lg["func"] == func_num
                                and lg["board_id_hex"] == board_hex
                            ):
                                sources.append("Linux sysfs/PCI")
                                bound_driver = lg.get("bound_driver", "nvidia")
                                break

                        cls = classify_pci_device(dev16, gpu_name, sm_ver)
                        bdf_str = f"{pci.domain:04x}:{pci.bus:02x}:{pci.device:02x}.{func_num}"
                        gpu_entry = {
                            "index": idx,
                            "gpu_name": gpu_name,
                            "gpu_uuid": gpu_uuid,
                            "pci_bdf": bdf_str,
                            "board_id_hex": board_hex,
                            "subsystem_id_hex": subsys_hex,
                            "segment_hex": f"0x{pci.domain:x}",
                            "bus_hex": f"0x{pci.bus:02x}",
                            "device_hex": f"0x{pci.device:x}",
                            "function_hex": f"0x{func_num:x}",
                            "die_name": cls["die_name"],
                            "chip_id_hex": f"0x{cls['chip_id']:08x}" if cls["chip_id"] else "",
                            "is_ada": cls["is_ada"],
                            "support_tier": cls["support_tier"],
                            "supported": cls["supported"],
                            "vram_mib": vram_mib,
                            "vram_min_hex": vram_min_hex,
                            "vram_max_hex": vram_max_hex,
                            "vbios_version": vbios_ver,
                            "power_default_w": p_def,
                            "power_min_w": p_min,
                            "power_max_w": p_max,
                            "bound_driver": bound_driver,
                            "linux_boot_option": get_linux_boot_option_for_gpu({
                                "pci_bdf": bdf_str,
                                "board_id_hex": board_hex,
                                "gpu_name": gpu_name,
                            }),
                            "verification_sources": sources,
                        }
                        info["gpus"].append(gpu_entry)
        except Exception:
            pass
        finally:
            if nvml_initialized:
                try:
                    nvml.nvmlShutdown()
                except Exception:
                    pass

    # Fallback 1: If ctypes NVML failed to load, try nvidia-smi CLI
    if not info["gpus"]:
        smi_drv, smi_gpus = _query_nvidia_smi_gpus()
        if smi_drv != "N/A":
            info["driver_version"] = smi_drv
        for sg in smi_gpus:
            c_info = cuda_by_loc.get((sg["domain"], sg["bus"], sg["dev"]), {})
            sm_ver = c_info.get("sm_version", "")
            cls = classify_pci_device(sg["dev16"], sg["gpu_name"], sm_ver)
            sources = ["nvidia-smi CLI"]
            if sm_ver:
                sources.append(f"CUDA ({sm_ver})")
            bound_drv = "nvidia"
            for lg in linux_pci_gpus:
                if lg["pci_bdf"] == sg["pci_bdf"] and lg["board_id_hex"] == sg["board_id_hex"]:
                    sources.append("Linux sysfs/PCI")
                    bound_drv = lg.get("bound_driver", "nvidia")
                    break
            info["gpus"].append({
                "index": sg["index"],
                "gpu_name": sg["gpu_name"],
                "gpu_uuid": sg["gpu_uuid"],
                "pci_bdf": sg["pci_bdf"],
                "board_id_hex": sg["board_id_hex"],
                "subsystem_id_hex": sg["subsystem_id_hex"],
                "segment_hex": f"0x{sg['domain']:x}",
                "bus_hex": f"0x{sg['bus']:02x}",
                "device_hex": f"0x{sg['dev']:x}",
                "function_hex": f"0x{sg['func']:x}",
                "die_name": cls["die_name"],
                "chip_id_hex": f"0x{cls['chip_id']:08x}" if cls["chip_id"] else "",
                "is_ada": cls["is_ada"],
                "support_tier": cls["support_tier"],
                "supported": cls["supported"],
                "vram_mib": sg["vram_mib"],
                "vram_min_hex": sg["vram_min_hex"],
                "vram_max_hex": sg["vram_max_hex"],
                "vbios_version": sg["vbios_version"],
                "power_default_w": sg["power_default_w"],
                "power_min_w": sg["power_min_w"],
                "power_max_w": sg["power_max_w"],
                "bound_driver": bound_drv,
                "linux_boot_option": get_linux_boot_option_for_gpu(sg),
                "verification_sources": sources,
            })

    # If NVML was unavailable, populate limited PnP / Linux sysfs fallback entries so hardware visibility is preserved
    if not info["gpus"] and pnp_gpus:
        for idx, pg in enumerate(pnp_gpus):
            c_info = cuda_by_loc.get((pg.get("domain", 0), pg["bus"], pg["dev"]), {})
            sm_ver = c_info.get("sm_version", "")
            cls = classify_pci_device(pg["dev16"], pg["gpu_name"], sm_ver)
            sources = ["Windows PCI.sys (PnP fallback — VRAM/UUID require NVML)"]
            if sm_ver:
                sources.append(f"CUDA ({sm_ver})")
            bdf_str = f"{pg.get('domain', 0):04x}:{pg['bus']:02x}:{pg['dev']:02x}.{pg['func']}"
            info["gpus"].append({
                "index": idx,
                "gpu_name": pg["gpu_name"],
                "gpu_uuid": "",
                "pci_bdf": bdf_str,
                "board_id_hex": pg["board_id_hex"],
                "subsystem_id_hex": pg["subsystem_id_hex"],
                "segment_hex": f"0x{pg.get('domain', 0):x}",
                "bus_hex": pg["bus_hex"],
                "device_hex": f"0x{pg['dev']:x}",
                "function_hex": f"0x{pg['func']:x}",
                "die_name": cls["die_name"],
                "chip_id_hex": f"0x{cls['chip_id']:08x}" if cls["chip_id"] else "",
                "is_ada": cls["is_ada"],
                "support_tier": cls["support_tier"],
                "supported": cls["supported"],
                "vram_mib": 0,
                "vram_min_hex": "",
                "vram_max_hex": "",
                "vbios_version": "N/A",
                "power_default_w": 0.0,
                "power_min_w": 0.0,
                "power_max_w": 0.0,
                "bound_driver": "nvlddmkm",
                "linux_boot_option": get_linux_boot_option_for_gpu({
                    "pci_bdf": bdf_str,
                    "board_id_hex": pg["board_id_hex"],
                    "gpu_name": pg["gpu_name"],
                }),
                "verification_sources": sources,
            })

    if not info["gpus"] and linux_pci_gpus:
        for idx, lg in enumerate(linux_pci_gpus):
            c_info = cuda_by_loc.get((lg["domain"], lg["bus"], lg["dev"]), {})
            sm_ver = c_info.get("sm_version", "")
            cls = classify_pci_device(lg["dev16"], lg["gpu_name"], sm_ver)
            sources = ["Linux sysfs/PCI (lspci + /sys/bus/pci/devices)"]
            if sm_ver:
                sources.append(f"CUDA ({sm_ver})")
            nom_vram = NOMINAL_VRAM_MIB.get(lg["dev16"], 0)
            low = max(1024, (nom_vram - 64) & ~0xF) if nom_vram else 0
            high = ((nom_vram + 64 + 0xF) & ~0xF) if nom_vram else 0
            info["gpus"].append({
                "index": idx,
                "gpu_name": lg["gpu_name"],
                "gpu_uuid": "",
                "pci_bdf": lg["pci_bdf"],
                "board_id_hex": lg["board_id_hex"],
                "subsystem_id_hex": lg["subsystem_id_hex"],
                "segment_hex": f"0x{lg['domain']:x}",
                "bus_hex": lg["bus_hex"],
                "device_hex": f"0x{lg['dev']:x}",
                "function_hex": f"0x{lg['func']:x}",
                "die_name": cls["die_name"],
                "chip_id_hex": f"0x{cls['chip_id']:08x}" if cls["chip_id"] else "",
                "is_ada": cls["is_ada"],
                "support_tier": cls["support_tier"],
                "supported": cls["supported"],
                "vram_mib": nom_vram,
                "vram_min_hex": f"0x{low:x}" if low else "",
                "vram_max_hex": f"0x{high:x}" if high else "",
                "vbios_version": "N/A (driver unbound)",
                "power_default_w": 0.0,
                "power_min_w": 0.0,
                "power_max_w": 0.0,
                "bound_driver": lg.get("bound_driver", "unbound"),
                "linux_boot_option": get_linux_boot_option_for_gpu(lg),
                "verification_sources": sources,
            })

    if info["gpus"]:
        chosen = next((g for g in info["gpus"] if g["supported"]), info["gpus"][0])
        info["gpu_detected"] = bool(chosen["vram_mib"] > 0 and chosen["board_id_hex"] and chosen["subsystem_id_hex"])
        for k in (
            "gpu_name", "gpu_uuid", "pci_bdf", "board_id_hex", "subsystem_id_hex",
            "segment_hex", "bus_hex", "device_hex", "function_hex", "die_name",
            "chip_id_hex", "is_ada", "support_tier", "vram_mib", "vram_min_hex",
            "vram_max_hex", "vbios_version", "power_default_w", "power_min_w",
            "power_max_w", "bound_driver", "linux_boot_option", "verification_sources",
        ):
            info[k] = chosen[k]

    if sys.platform.startswith("win"):
        ps_cmd = (
            "$bootDisks = @(Get-Disk | Where-Object { $_.IsBoot -eq $true -or $_.IsSystem -eq $true } | Select-Object -ExpandProperty Number); "
            "$esps = @(Get-Partition | Where-Object { $_.GptType -eq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' } | "
            "Select-Object DiskNumber, PartitionNumber, Guid, @{N='OnBootDisk';E={$bootDisks -contains $_.DiskNumber}}); "
            "$sb = try { [bool](Confirm-SecureBootUEFI) } catch { $null }; "
            "$bl = try { $v = Get-BitLockerVolume -MountPoint 'C:' -ErrorAction Stop; ($v.ProtectionStatus -eq 'On' -or $v.VolumeStatus -ne 'FullyDecrypted') } catch { $null }; "
            "[PSCustomObject]@{ Esps=$esps; SecureBoot=$sb; BitLocker=$bl } | ConvertTo-Json -Compress -Depth 4"
        )
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if res.returncode == 0 and res.stdout.strip():
                payload = json.loads(res.stdout.strip())
                info["secure_boot_enabled"] = payload.get("SecureBoot")
                info["bitlocker_protection_on"] = payload.get("BitLocker")
                esps = payload.get("Esps") or []
                if isinstance(esps, dict):
                    esps = [esps]
                info["esp_candidates"] = esps
                boot_esps = [e for e in esps if e.get("OnBootDisk") and e.get("Guid")]
                if len(boot_esps) == 1:
                    chosen_esp = boot_esps[0]
                elif len(esps) == 1 and esps[0].get("Guid"):
                    chosen_esp = esps[0]
                else:
                    chosen_esp = boot_esps[0] if boot_esps else None
                    if len(esps) > 1:
                        info["esp_ambiguous"] = True
                if chosen_esp:
                    info["esp_guid"] = str(chosen_esp["Guid"])
                    info["esp_part_num"] = int(chosen_esp.get("PartitionNumber") or 0)
                    info["esp_disk_part"] = f"Disk {chosen_esp.get('DiskNumber')}, Part {chosen_esp.get('PartitionNumber')}"
        except Exception:
            pass

    return info


def get_live_cli_verification_command() -> str:
    """Return the exact transparent CLI command string displayed to the user in the UI."""
    return (
        'nvidia-smi --query-gpu=index,name,uuid,pci.bus_id,pci.device_id,pci.sub_device_id,'
        'memory.total,vbios_version,power.default_limit,power.max_limit --format=csv,noheader,nounits'
    )


def run_live_cli_verification(log_fn: Callable[[str], None] = print) -> dict[str, Any]:
    """Execute the transparent nvidia-smi and Windows PowerShell hardware queries and print raw + parsed output."""
    smi_cmd_str = get_live_cli_verification_command()
    log_fn("=" * 76)
    log_fn(f"[CLI CHECK 1/2] $ {smi_cmd_str}")
    smi_exe = (
        r"C:\Windows\System32\nvidia-smi.exe"
        if sys.platform.startswith("win") and Path(r"C:\Windows\System32\nvidia-smi.exe").exists()
        else (shutil.which("nvidia-smi") or "nvidia-smi")
    )
    smi_args = [
        smi_exe,
        "--query-gpu=index,name,uuid,pci.bus_id,pci.device_id,pci.sub_device_id,memory.total,vbios_version,power.default_limit,power.max_limit",
        "--format=csv,noheader,nounits",
    ]
    parsed_gpus: list[dict[str, Any]] = []
    raw_smi = ""
    try:
        res = subprocess.run(
            smi_args,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw_smi = (res.stdout or res.stderr).strip()
        log_fn(raw_smi if raw_smi else "(empty output)")
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 10:
                    idx_s, name_s, uuid_s, bdf_s, dev_hex, sub_hex, vram_s, vbios_s, pdef_s, pmax_s = parts[:10]
                    dev32 = int(dev_hex, 16) if dev_hex.lower().startswith("0x") else int(dev_hex, 16)
                    dev16 = (dev32 >> 16) & 0xFFFF
                    cls = classify_pci_device(dev16, name_s)
                    vram_mib = int(float(vram_s))
                    low = max(1024, (vram_mib - 64) & ~0xF)
                    high = (vram_mib + 64 + 0xF) & ~0xF
                    parsed_row = {
                        "index": idx_s,
                        "name": name_s,
                        "uuid": uuid_s,
                        "pci_bdf": bdf_s,
                        "GU_BOARD_ID": f"0x{dev32:08x}U",
                        "GU_BOARD_SUBSYSTEM": f"{sub_hex.lower()}U" if sub_hex.lower().startswith("0x") else f"0x{sub_hex.lower()}U",
                        "die": cls["die_name"],
                        "GU_BOARD_CHIP": f"0x{cls['chip_id']:08x}U" if cls["chip_id"] else "UNSUPPORTED",
                        "vram_mib": vram_mib,
                        "GU_VRAM_MIN_MIB": f"0x{low:x}U",
                        "GU_VRAM_MAX_MIB": f"0x{high:x}U",
                        "vbios": vbios_s,
                        "power_default_w": pdef_s,
                        "power_max_w": pmax_s,
                    }
                    parsed_gpus.append(parsed_row)
                    log_fn(
                        f"  -> [GPU #{idx_s}] {name_s} | UUID={uuid_s}\n"
                        f"     BDF={bdf_s} | GU_BOARD_ID={parsed_row['GU_BOARD_ID']} | GU_BOARD_SUBSYSTEM={parsed_row['GU_BOARD_SUBSYSTEM']}\n"
                        f"     Die={parsed_row['die']} | GU_BOARD_CHIP={parsed_row['GU_BOARD_CHIP']} | "
                        f"VRAM={vram_mib} MiB [{parsed_row['GU_VRAM_MIN_MIB']}..{parsed_row['GU_VRAM_MAX_MIB']}] | "
                        f"VBIOS={vbios_s} | Power={pdef_s}W / Max {pmax_s}W"
                    )
    except Exception as exc:
        log_fn(f"[WARN] nvidia-smi execution error: {exc}")

    raw_ps = ""
    if sys.platform.startswith("win"):
        ps_query = (
            "Get-Partition | Where-Object { $_.GptType -eq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' } | "
            "Select-Object DiskNumber, PartitionNumber, Guid"
        )
        log_fn("-" * 76)
        log_fn(f"[CLI CHECK 2/2] PS> {ps_query}")
        try:
            res_ps = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_query],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            raw_ps = (res_ps.stdout or res_ps.stderr).strip()
            log_fn(raw_ps if raw_ps else "(no GPT EFI System Partition found)")
        except Exception as exc:
            log_fn(f"[WARN] PowerShell query error: {exc}")
    log_fn("=" * 76)
    return {"command": smi_cmd_str, "raw_smi": raw_smi, "raw_ps": raw_ps, "gpus": parsed_gpus}


def list_usb_drives() -> list[dict[str, Any]]:
    """Enumerate verified removable USB / SD FAT32 drives on Windows 10/11."""
    drives: list[dict[str, Any]] = []
    if not sys.platform.startswith("win"):
        return drives
    ps_cmd = (
        "Get-Volume | Where-Object { $_.DriveLetter -ne $null -and $_.DriveLetter -ne 'C' } | ForEach-Object { "
        "$v = $_; "
        "$p = Get-Partition -DriveLetter $v.DriveLetter -ErrorAction SilentlyContinue; "
        "$d = if ($p) { Get-Disk -Number $p.DiskNumber -ErrorAction SilentlyContinue } else { $null }; "
        "[PSCustomObject]@{ "
        "DriveLetter=$v.DriveLetter; Label=$v.FileSystemLabel; FileSystem=$v.FileSystem; "
        "DriveType=$v.DriveType; Size=$v.Size; UniqueId=$v.UniqueId; "
        "BusType=if($d){$d.BusType}else{''}; IsBoot=if($d){[bool]$d.IsBoot}else{$false}; "
        "IsSystem=if($d){[bool]$d.IsSystem}else{$false}; DiskNumber=if($d){$d.Number}else{-1} "
        "} } | ConvertTo-Json -Compress"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode == 0 and res.stdout.strip():
            parsed = json.loads(res.stdout.strip())
            if isinstance(parsed, dict):
                parsed = [parsed]
            for item in parsed:
                dl = str(item.get("DriveLetter", "")).strip().upper()
                if not dl or dl == "C":
                    continue
                if item.get("IsBoot") or item.get("IsSystem"):
                    continue
                bus_type = str(item.get("BusType") or "").upper()
                dtype = str(item.get("DriveType") or "")
                fs = str(item.get("FileSystem") or "RAW").upper()
                if dtype != "Removable" and bus_type not in ("USB", "SD"):
                    continue
                size_gb = round((item.get("Size") or 0) / (1024**3), 1)
                label = item.get("Label") or "USB_DRIVE"
                drives.append({
                    "letter": f"{dl}:\\",
                    "label": label,
                    "filesystem": fs,
                    "drive_type": dtype,
                    "bus_type": bus_type,
                    "unique_id": str(item.get("UniqueId") or ""),
                    "disk_number": int(item.get("DiskNumber") or -1),
                    "size_gb": size_gb,
                    "is_fat32": fs == "FAT32",
                    "display": f"{dl}:\\ [{label} | {fs} | {size_gb} GB | {bus_type or dtype}]",
                })
    except Exception:
        pass
    return drives


def _is_reparse_or_symlink(path: Path) -> bool:
    """Check if path is a symlink, junction, or Windows reparse point.
    Return False ONLY when the path does not exist (FileNotFoundError); fail closed (True) on other OSErrors."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    import stat as stat_mod
    if stat_mod.S_ISLNK(st.st_mode):
        return True
    file_attrs = getattr(st, "st_file_attributes", 0)
    if file_attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
        return True
    return False


def _ensure_safe_directory_tree(base: Path) -> None:
    curr = base
    while True:
        if _is_reparse_or_symlink(curr):
            raise ValueError(f"Security violation: target or ancestor is a symlink/reparse point: {curr}")
        if curr.parent == curr:
            break
        curr = curr.parent

    if base.exists():
        for sub in ("EFI", "EFI/Boot", "GPU-UNLOCK", "GPU-UNLOCK/ASSETS"):
            candidate = base / sub
            if _is_reparse_or_symlink(candidate):
                raise ValueError(f"Security violation: {candidate} is a symlink/reparse point")
            if candidate.exists() and candidate.is_dir():
                for child in candidate.iterdir():
                    if _is_reparse_or_symlink(child):
                        raise ValueError(f"Security violation: {child} is a symlink/reparse point")


def _write_verified_file(dest: Path, data: bytes, expected_sha256: str) -> None:
    if _is_reparse_or_symlink(dest):
        raise ValueError(f"Refusing to write through symlink/reparse point: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_or_symlink(dest.parent):
        raise ValueError(f"Refusing to write inside symlink/reparse directory: {dest.parent}")

    fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".stage", dir=str(dest.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    if dest.stat().st_size != len(data) or sha256_file(dest) != expected_sha256:
        raise IOError(f"Readback verification failed for {dest}")


def _array_bytes(text: str, label: str) -> bytes:
    marker = f"BINDATA_LABEL_{label}_data[]"
    if text.count(marker) != 1:
        raise ValueError(f"missing or duplicate {label}")
    start = text.index(marker)
    window = text[max(0, start - 400) : start]
    compression = re.findall(r"COMPRESSION: (YES|NO)", window)
    sizes = re.findall(r"DATA SIZE \(bytes\): (\d+)", window)
    expected = int(sizes[-1])
    compressed = compression[-1] == "YES"
    declaration = re.match(re.escape(marker) + r"\s*=\s*\{([^}]*)\};", text[start:], re.S)
    if not declaration:
        raise ValueError("malformed byte-array declaration")
    tokens = declaration[1].strip().rstrip(",").split(",")
    raw = bytes(int(item, 16) for item in tokens)
    if compressed:
        inflater = zlib.decompressobj(-15)
        data = inflater.decompress(raw, expected + 1)
        crc, size = struct.unpack("<II", inflater.unused_data)
        if size != expected or crc != zlib.crc32(data):
            raise ValueError(f"CRC/size mismatch in {label}")
    else:
        data = raw
    if len(data) != expected:
        raise ValueError(f"{label} size mismatch")
    return data


def build_booter_bundle(source_text: str) -> bytes:
    image = _array_bytes(source_text, "IMAGE_PROD")
    header = _array_bytes(source_text, "HEADER_PROD")
    signatures = _array_bytes(source_text, "SIG_PROD")
    patch_loc = _array_bytes(source_text, "PATCH_LOC")
    patch_meta = _array_bytes(source_text, "PATCH_META")
    num_sigs = _array_bytes(source_text, "NUM_SIGS")
    fields = struct.unpack("<9I", header)
    loc = struct.unpack("<I", patch_loc)[0]
    _fuse, engine, ucode = struct.unpack("<3I", patch_meta)
    count = struct.unpack("<I", num_sigs)[0]
    hdr = struct.pack(
        "<14I",
        fields[0], fields[1], fields[2], fields[3], fields[4], fields[5], fields[6],
        fields[7], fields[8], loc, ucode, engine, count, len(signatures),
    )
    prefix = struct.pack("<II", 0x314C5442, 1) + hdr + struct.pack("<II", len(image), len(signatures))
    return prefix + image + signatures


def _find_shared_cached_file(filename: str, expected_sha256: str, log_fn: Callable[[str], None] | None = None) -> Path | None:
    """Check persistent user cache folders (~/.cache/gpu-tensor-unlock and ~/.cache/gpu-unlock/inputs)
    so unpacking a new ZIP never re-downloads 285 MB if already downloaded earlier on this PC."""
    for cand_dir in (
        Path.home() / ".cache" / "gpu-tensor-unlock",
        Path.home() / ".cache" / "gpu-unlock" / "inputs",
    ):
        cand = cand_dir / filename
        try:
            if cand.is_file() and not _is_reparse_or_symlink(cand) and sha256_file(cand) == expected_sha256:
                if log_fn:
                    log_fn(f"[CACHE] Reusing verified {filename} from {cand_dir}")
                return cand
        except Exception:
            continue
    return None


def _save_to_shared_cache(src_file: Path, expected_sha256: str) -> None:
    """Mirror verified large firmware files into ~/.cache/gpu-tensor-unlock for future runs."""
    try:
        shared_dir = Path.home() / ".cache" / "gpu-tensor-unlock"
        shared_dir.mkdir(parents=True, exist_ok=True)
        target = shared_dir / src_file.name
        if not target.exists() and not _is_reparse_or_symlink(shared_dir):
            shutil.copy2(src_file, target)
            if sha256_file(target) != expected_sha256:
                target.unlink(missing_ok=True)
    except Exception:
        pass


def download_verified(url: str, dest: Path, expected_sha256: str, log_fn: Callable[[str], None]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_or_symlink(dest.parent) or _is_reparse_or_symlink(dest):
        raise ValueError(f"Security violation: cache path {dest} is a symlink/reparse point")
    if dest.exists() and sha256_file(dest) == expected_sha256:
        log_fn(f"[OK] Cached: {dest.name}")
        return dest

    shared_hit = _find_shared_cached_file(dest.name, expected_sha256, log_fn)
    if shared_hit is not None:
        try:
            shutil.copy2(shared_hit, dest)
            if sha256_file(dest) == expected_sha256:
                return dest
        except Exception:
            return shared_hit

    req = urllib.request.Request(url, headers={"User-Agent": "GPU-Tensor-Unlock-Universal"})
    fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".part", dir=str(dest.parent))
    tmp = Path(tmp_name)
    total_read = 0
    try:
        with urllib.request.urlopen(req, timeout=180) as resp, os.fdopen(fd, "wb") as out:
            content_len = 0
            try:
                content_len = int(resp.headers.get("Content-Length") or 0)
            except Exception:
                content_len = 0
            if content_len > 0:
                log_fn(f"[DOWNLOAD] {dest.name} ({content_len / (1024 * 1024):.1f} MB) ...")
            else:
                log_fn(f"[DOWNLOAD] {dest.name} ...")
            start_ts = time.monotonic()
            last_log_ts = start_ts
            while chunk := resp.read(256 * 1024):
                total_read += len(chunk)
                if total_read > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"Download exceeded safety limit of {MAX_DOWNLOAD_BYTES} bytes")
                out.write(chunk)
                now = time.monotonic()
                if (now - last_log_ts) >= 2.0:
                    elapsed = max(0.001, now - start_ts)
                    speed_mb = (total_read / (1024 * 1024)) / elapsed
                    if content_len > 0:
                        pct = (total_read * 100.0) / content_len
                        log_fn(
                            f"[DOWNLOAD] {dest.name}: {total_read / (1024 * 1024):.1f} / {content_len / (1024 * 1024):.1f} MB "
                            f"({pct:.0f}%, {speed_mb:.1f} MB/s)"
                        )
                    else:
                        log_fn(f"[DOWNLOAD] {dest.name}: {total_read / (1024 * 1024):.1f} MB ({speed_mb:.1f} MB/s)")
                    last_log_ts = now
            out.flush()
            os.fsync(out.fileno())
        actual = sha256_file(tmp)
        if actual != expected_sha256:
            raise ValueError(f"SHA-256 mismatch for {dest.name}: expected {expected_sha256}, got {actual}")
        os.replace(tmp, dest)
        _save_to_shared_cache(dest, expected_sha256)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    log_fn(f"[OK] Verified SHA-256: {dest.name}")
    return dest


def extract_gsp_from_zst(pkg_path: Path, dest_gsp: Path, member_name: str = "gsp_ga10x.bin") -> None:
    member = f"usr/lib/firmware/nvidia/610.43.03/{member_name}"
    try:
        import zstandard as zstd  # type: ignore
        with pkg_path.open("rb") as fh:
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(fh) as reader:
                with tarfile.open(fileobj=reader, mode="r|") as tf:
                    for m in tf:
                        if m.name == member:
                            extracted_f = tf.extractfile(m)
                            if extracted_f is None:
                                raise ValueError(f"Member {member} has no file payload")
                            data = extracted_f.read()
                            dest_gsp.write_bytes(data)
                            return
    except ImportError:
        pass

    tar_exe = shutil.which("tar.exe") or shutil.which("tar")
    if tar_exe:
        with tempfile.TemporaryDirectory() as tmpd:
            res = subprocess.run(
                [tar_exe, "-xf", str(pkg_path), "-C", tmpd, member],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if res.returncode != 0:
                raise RuntimeError(f"tar extraction failed: {res.stderr.strip() or res.stdout.strip()}")
            extracted = Path(tmpd) / member
            shutil.move(str(extracted), str(dest_gsp))
            return

    raise RuntimeError("Neither Python 'zstandard' nor Zstd-capable 'tar' is available to unpack .pkg.tar.zst")


def build_and_stage_usb(
    config: dict[str, Any],
    usb_out: str | Path,
    log_fn: Callable[[str], None] = print,
    target_mode: str = "usb",
) -> Path:
    """Validate profile, compile BOOTX64.EFI in an isolated build dir, and stage onto USB or export folder."""
    if target_mode not in ("usb", "export"):
        raise ValueError(f"Invalid target_mode: {target_mode!r} (must be 'usb' or 'export')")

    validated = validate_target_profile(config)

    raw_str = str(usb_out).strip().strip('"').strip("'")
    if not raw_str:
        raise ValueError("Target path cannot be empty")
    # Check root paths BEFORE rstrip('\\/') so '/' never collapses into '' -> Path('.')!
    if raw_str in ("/", "\\") or re.fullmatch(r"[cC]:[\\/]*", raw_str):
        raise ValueError(f"Refusing to write to system root volume: {raw_str}")

    raw_path = Path(raw_str)
    if _is_reparse_or_symlink(raw_path):
        raise ValueError(f"Security violation: target path is a symlink or reparse point: {raw_path}")

    cleaned_out = raw_str.rstrip("\\/")
    if len(cleaned_out) == 1 and cleaned_out.isalpha():
        cleaned_out = f"{cleaned_out}:\\"
    elif len(cleaned_out) == 2 and cleaned_out[0].isalpha() and cleaned_out[1] == ":":
        cleaned_out = f"{cleaned_out}\\"

    usb_root = Path(cleaned_out)
    _ensure_safe_directory_tree(usb_root)
    usb_root = usb_root.resolve()
    _ensure_safe_directory_tree(usb_root)

    if usb_root.drive.upper() == "C:" or str(usb_root) in ("/", "\\"):
        raise ValueError(f"Refusing to write to system root volume: {usb_root}")

    if target_mode == "usb":
        verified_drives = list_usb_drives()
        norm_root = str(usb_root).rstrip("\\/").upper()
        matched_drive = next(
            (d for d in verified_drives if d["letter"].rstrip("\\/").upper() == norm_root),
            None,
        )
        if matched_drive is None:
            raise ValueError(
                f"Target '{usb_root}' is not a verified removable USB/SD drive. "
                "Use 'export' mode to stage into a local folder."
            )
        if not matched_drive.get("is_fat32"):
            raise ValueError(f"USB drive {matched_drive['letter']} is formatted as {matched_drive['filesystem']}; FAT32 is required for UEFI boot.")

    is_ada = validated["is_ada"]
    is_turing = validated.get("is_turing", False)
    chip_tag = "tu102" if is_turing else ("ad102" if is_ada else "ga102")
    specs = ASSET_SPECS_TU if is_turing else (ASSET_SPECS_ADA if is_ada else ASSET_SPECS_GA)

    clang_bin = find_llvm_tool("clang")
    lld_bin = find_llvm_tool("lld-link")
    if not clang_bin or not lld_bin:
        raise FileNotFoundError("LLVM (clang / lld-link) not found. Install LLVM dependencies first.")

    with tempfile.TemporaryDirectory(prefix="gpu_unlock_build_") as tmp_build_root:
        tmp_root = Path(tmp_build_root)
        prof_dir = tmp_root / "profile"
        build_dir = tmp_root / "out"
        prof_dir.mkdir(parents=True, exist_ok=True)
        build_dir.mkdir(parents=True, exist_ok=True)

        local_profile_text = f"""/* SPDX-License-Identifier: GPL-2.0-only */
/* Auto-generated by Universal GPU Tensor Unlock UI */
#pragma once

#define GU_BOARD_ID 0x{validated['board_id']:08x}U
#define GU_BOARD_SUBSYSTEM 0x{validated['subsys_id']:08x}U
#define GU_BOARD_CHIP 0x{validated['chip_id']:08x}U
#define GU_BOARD_SEGMENT 0x{validated['seg']:x}U
#define GU_BOARD_BUS 0x{validated['bus']:02x}U
#define GU_BOARD_DEVICE 0x{validated['dev']:x}U
#define GU_BOARD_FUNCTION 0x{validated['func']:x}U
#define GU_BOARD_CLASS_REV 0x030000a1U
#define GU_VRAM_MIN_MIB 0x{validated['vram_min']:x}U
#define GU_VRAM_MAX_MIB 0x{validated['vram_max']:x}U
#define GU_ARCH_ADA {1 if is_ada else 0}
#define GU_ARCH_TURING {1 if is_turing else 0}
#define GU_EXPECTED_COLD_PLM 0xffffff8fU
#define GU_EXPECTED_POST_FLR_PLM 0xffffffffU

#define KOH_WINDOWS_ESP_GUID {validated['esp_macro']}
#define KOH_WINDOWS_ESP_PART {validated['esp_part']}U
#define KOH_PAYLOAD_ESP_GUID {validated['payload_macro']}
#define KOH_AUTOCONFIRM_MS 30000
#define KOH_UNATTENDED_AUTOFIRE {validated['unattended']}
"""
        prom_profile_text = f"""#ifndef GU_PROM_PROFILE_H
#define GU_PROM_PROFILE_H
#define GU_PROM_BAR_OFFSET 0x300000U
#define GU_PROM_VIEW_BYTES 0xd6c00U
#define GU_PROM_MAX_BYTES 0x100000U
#define GU_UEFI_ROM_BYTES 0x24a00U
#define GU_PROM_VIEW_SHA256 "{validated['prom_sha']}"
#define GU_UEFI_ROM_SHA256 "{validated['rom_sha']}"
#endif
"""
        (prof_dir / "local_profile.h").write_text(local_profile_text, encoding="utf-8")
        (prof_dir / "prom_profile.h").write_text(prom_profile_text, encoding="utf-8")

        log_fn(
            f"[OK] Validated profile: GPU={validated['gpu_name']} ({validated['die_name']}, tier={validated['support_tier']}) "
            f"BDF={validated['seg']:04x}:{validated['bus']:02x}:{validated['dev']:02x}.{validated['func']} "
            f"PCI=0x{validated['board_id']:08x} SUBSYS=0x{validated['subsys_id']:08x}"
        )

        # Pass --clang and --linker explicitly to build.py
        log_fn(f"[BUILD] Compiling BOOTX64.EFI in isolated build dir via {Path(clang_bin).name} + {Path(lld_bin).name}...")
        res = subprocess.run(
            [
                sys.executable,
                str(UEFI_DIR / "build.py"),
                "--clang",
                clang_bin,
                "--linker",
                lld_bin,
                "--enable-experiment",
                "--profile-dir",
                str(prof_dir),
                "--build-dir",
                str(build_dir),
            ],
            cwd=UEFI_DIR,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode != 0:
            err_detail = (res.stderr or "") + ("\n" + res.stdout if res.stdout else "")
            raise RuntimeError(f"UEFI compilation failed (exit {res.returncode}):\n{err_detail.strip()}")

        built_efi = build_dir / "BOOTX64.EFI"
        if not built_efi.exists():
            raise RuntimeError("Build succeeded but BOOTX64.EFI was not produced")
        efi_bytes = built_efi.read_bytes()
        efi_sha = sha256_bytes(efi_bytes)

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        v67_name = "v67-tu102-610.43.03.bin" if is_turing else ("v67-ad102-610.43.03-four-plm.bin" if is_ada else "v67-ga102-610.43.03.bin")
        v67_bytes = build_v67_payload(is_ada=is_ada, arch="tu102" if is_turing else None)
        if len(v67_bytes) != specs[v67_name][0] or sha256_bytes(v67_bytes) != specs[v67_name][1]:
            raise ValueError(f"Generated {v67_name} failed SHA-256 verification")

        booter_c_name = f"g_bindata_kgspGetBinArchiveBooterLoadUcode_{chip_tag.upper()}.c"
        boot_c_name = f"g_bindata_kgspGetBinArchiveGspRmBoot_{chip_tag.upper()}.c"
        c_texts: dict[str, str] = {}
        for cname in (booter_c_name, boot_c_name):
            csha, curl = SOURCE_C_FILES[cname]
            cpath = CACHE_DIR / cname
            try:
                download_verified(curl, cpath, csha, log_fn)
                c_texts[cname] = cpath.read_text(encoding="ascii")
            except Exception as exc:
                log_fn(f"[INFO] GitHub fetch fallback ({exc}), using NVIDIA 610.43.03 source tarball...")
                tar_path = download_verified(
                    SOURCE_TARBALL_URL,
                    CACHE_DIR / "NVIDIA-kernel-module-source-610.43.03.tar.xz",
                    SOURCE_TARBALL_SHA256,
                    log_fn,
                )
                with tarfile.open(tar_path, mode="r:xz") as tf:
                    for m in tf:
                        for target_c in (booter_c_name, boot_c_name):
                            tsha, _ = SOURCE_C_FILES[target_c]
                            if m.name.endswith("/src/nvidia/generated/" + target_c):
                                extracted_f = tf.extractfile(m)
                                if extracted_f is None:
                                    continue
                                raw = extracted_f.read()
                                if sha256_bytes(raw) != tsha:
                                    raise ValueError(f"SHA-256 mismatch for {target_c}")
                                (CACHE_DIR / target_c).write_bytes(raw)
                                c_texts[target_c] = raw.decode("ascii")
                break

        booter_bin = build_booter_bundle(c_texts[booter_c_name])
        boot_bin = _array_bytes(c_texts[boot_c_name], "UCODE_IMAGE_PROD")
        desc_bin = _array_bytes(c_texts[boot_c_name], "UCODE_DESC_PROD")

        assets_dir = usb_root / "GPU-UNLOCK" / "ASSETS"
        efi_boot_dir = usb_root / "EFI" / "Boot"
        assets_dir.mkdir(parents=True, exist_ok=True)
        efi_boot_dir.mkdir(parents=True, exist_ok=True)
        _ensure_safe_directory_tree(usb_root)

        for fname, blob in (
            (v67_name, v67_bytes),
            (f"booter_load_{chip_tag}.bin", booter_bin),
            (f"gsp_boot_{chip_tag}.bin", boot_bin),
            (f"gsp_boot_desc_{chip_tag}.bin", desc_bin),
        ):
            exp_sz, exp_sha = specs[fname]
            if len(blob) != exp_sz or sha256_bytes(blob) != exp_sha:
                raise ValueError(f"Verification failed for {fname}")
            _write_verified_file(assets_dir / fname, blob, exp_sha)
            log_fn(f"[OK] Staged & verified {fname} ({exp_sz} bytes)")

        gsp_fname = "gsp_tu10x.bin" if is_turing else "gsp_ga10x.bin"
        gsp_dest = assets_dir / gsp_fname
        exp_gsp_sz, exp_gsp_sha = specs[gsp_fname]
        if gsp_dest.exists() and not _is_reparse_or_symlink(gsp_dest) and gsp_dest.stat().st_size == exp_gsp_sz and sha256_file(gsp_dest) == exp_gsp_sha:
            log_fn(f"[OK] Reused existing verified {gsp_fname} on target")
        else:
            cached_gsp = CACHE_DIR / gsp_fname
            if not (cached_gsp.exists() and cached_gsp.stat().st_size == exp_gsp_sz and sha256_file(cached_gsp) == exp_gsp_sha):
                shared_gsp = _find_shared_cached_file(gsp_fname, exp_gsp_sha, log_fn)
                if shared_gsp is not None:
                    shutil.copy2(shared_gsp, cached_gsp)
            if not (cached_gsp.exists() and cached_gsp.stat().st_size == exp_gsp_sz and sha256_file(cached_gsp) == exp_gsp_sha):
                pkg_path = download_verified(
                    PACKAGE_URL,
                    CACHE_DIR / "nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst",
                    PACKAGE_SHA256,
                    log_fn,
                )
                log_fn(f"[EXTRACT] Unpacking {gsp_fname} ({exp_gsp_sz / (1024 * 1024):.1f} MB)...")
                extract_gsp_from_zst(pkg_path, cached_gsp, member_name=gsp_fname)
                if sha256_file(cached_gsp) != exp_gsp_sha:
                    cached_gsp.unlink(missing_ok=True)
                    raise ValueError(f"Extracted {gsp_fname} SHA-256 mismatch!")
                _save_to_shared_cache(cached_gsp, exp_gsp_sha)
            log_fn(f"[USB] Writing {gsp_fname} ({exp_gsp_sz / (1024 * 1024):.1f} MB) to target drive (may take 10-30s on FAT32)...")
            _write_verified_file(gsp_dest, cached_gsp.read_bytes(), exp_gsp_sha)
            log_fn(f"[OK] Staged & verified {gsp_fname} ({exp_gsp_sz:,} bytes)")

        # Backup any pre-existing foreign BOOTX64.EFI and verify backup SHA-256 even if backup file already exists!
        journal_path = usb_root / "GPU-UNLOCK" / "INSTALL_JOURNAL.JSON"
        known_own_shas: set[str] = set()
        if journal_path.exists() and not _is_reparse_or_symlink(journal_path):
            try:
                old_j = json.loads(journal_path.read_text(encoding="utf-8"))
                if isinstance(old_j, dict) and isinstance(old_j.get("bootx64_sha256"), str):
                    known_own_shas.add(old_j["bootx64_sha256"])
            except Exception:
                pass

        target_efi = efi_boot_dir / "BOOTX64.EFI"
        backup_name: str | None = None
        if target_efi.exists():
            if _is_reparse_or_symlink(target_efi):
                raise ValueError(f"Security violation: {target_efi} is a symlink/reparse point")
            existing_bytes = target_efi.read_bytes()
            existing_sha = sha256_bytes(existing_bytes)
            if existing_sha != efi_sha and existing_sha not in known_own_shas:
                backup_name = f"BOOTX64.BACKUP_{existing_sha[:16]}.EFI"
                backup_path = efi_boot_dir / backup_name
                need_write_backup = True
                if backup_path.exists():
                    if _is_reparse_or_symlink(backup_path):
                        raise ValueError(f"Security violation: backup path {backup_path} is a symlink/reparse point")
                    if backup_path.stat().st_size == len(existing_bytes) and sha256_file(backup_path) == existing_sha:
                        need_write_backup = False
                if need_write_backup:
                    _write_verified_file(backup_path, existing_bytes, existing_sha)
                    log_fn(f"[BACKUP] Verified & preserved existing foreign bootloader as {backup_name}")

        _write_verified_file(target_efi, efi_bytes, efi_sha)
        journal_data = {
            "schema_version": 2,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "target_mode": target_mode,
            "profile": {
                "gpu_name": validated["gpu_name"],
                "die_name": validated["die_name"],
                "support_tier": validated["support_tier"],
                "board_id_hex": f"0x{validated['board_id']:08x}",
                "subsystem_id_hex": f"0x{validated['subsys_id']:08x}",
                "bdf": f"{validated['seg']:04x}:{validated['bus']:02x}:{validated['dev']:02x}.{validated['func']}",
            },
            "bootx64_sha256": efi_sha,
            "bootx64_size": len(efi_bytes),
            "foreign_bootloader_backup": backup_name,
            "assets": {k: {"size": v[0], "sha256": v[1]} for k, v in specs.items()},
        }
        journal_bytes = json.dumps(journal_data, indent=2, ensure_ascii=False).encode("utf-8")
        _write_verified_file(journal_path, journal_bytes, sha256_bytes(journal_bytes))
        log_fn(f"[OK] Published {target_efi} ({len(efi_bytes)} bytes, SHA256={efi_sha[:16]}...)")
        return usb_root


def read_latest_usb_report(usb_out: str | Path, expected_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Find and parse RUNxx/REPORT.TXT from the target USB drive or export folder,
    enforcing a 1 MiB size limit and cross-checking profile identity against INSTALL_JOURNAL.JSON."""
    cleaned_out = str(usb_out).strip().strip('"').strip("'").rstrip("\\/")
    if len(cleaned_out) == 1 and cleaned_out.isalpha():
        cleaned_out = f"{cleaned_out}:\\"
    elif len(cleaned_out) == 2 and cleaned_out[0].isalpha() and cleaned_out[1] == ":":
        cleaned_out = f"{cleaned_out}\\"
    usb_root = Path(cleaned_out)

    discovered_runs: list[dict[str, Any]] = []
    for folder_name in ("GPU-UNLOCK",):
        parent = usb_root / folder_name
        if not parent.exists() or _is_reparse_or_symlink(parent):
            continue
        folder_runs: list[dict[str, Any]] = []
        for run_dir in parent.iterdir():
            if not run_dir.is_dir() or _is_reparse_or_symlink(run_dir):
                continue
            m = re.fullmatch(r"RUN(\d{2,})", run_dir.name)
            if not m:
                continue
            rep = run_dir / "REPORT.TXT"
            if rep.exists() and rep.is_file() and not _is_reparse_or_symlink(rep):
                st = rep.stat()
                if st.st_size > 1048576:
                    continue
                folder_runs.append({
                    "slot": int(m.group(1)),
                    "run_name": run_dir.name,
                    "folder": folder_name,
                    "path": rep,
                    "mtime": st.st_mtime,
                })
        if folder_runs:
            folder_runs.sort(key=lambda r: (r["slot"], r["mtime"]))
            discovered_runs = folder_runs
            break

    if not discovered_runs:
        return {"found": False, "error": f"No valid REPORT.TXT (<= 1 MiB) found on {usb_root}", "runs": []}

    chosen = discovered_runs[-1]
    latest: Path = chosen["path"]
    with latest.open("rb") as fh:
        raw_bytes = fh.read(1048576)
    text = raw_bytes.decode("utf-8", errors="replace")

    final_lines: list[str] = []
    ss0_line = ""
    ss1_line = ""
    handoff_prepared = False
    rep_board_id: int | None = None
    rep_subsys_id: int | None = None

    for line in text.splitlines():
        s = line.strip()
        if s.startswith("RUN_ID="):
            m_hdr = re.search(r"BOARD_ID=(0x[0-9a-fA-F]+)\s+SUBSYSTEM=(0x[0-9a-fA-F]+)", s)
            if m_hdr:
                rep_board_id = int(m_hdr.group(1), 16)
                rep_subsys_id = int(m_hdr.group(2), 16)
        elif s.startswith("config[00]="):
            m_cfg0 = re.match(r"config\[00\]=([0-9a-fA-F]{8})", s)
            if m_cfg0 and rep_board_id is None:
                rep_board_id = int(m_cfg0.group(1), 16)
        elif s.startswith("config[20]="):
            parts = s.split()
            if len(parts) >= 4 and rep_subsys_id is None:
                try:
                    rep_subsys_id = int(parts[3], 16)
                except ValueError:
                    pass
        elif s.startswith("FINAL "):
            final_lines.append(s)
        elif s.startswith("SELECTOR RESULT: SS0"):
            ss0_line = s
        elif s.startswith("SELECTOR RESULT: SS1"):
            ss1_line = s
        elif s == "HANDOFF_STATE stage=handoff_prepared" or s.startswith("stage=before_StartImage"):
            handoff_prepared = True

    # Cross-check report identity against INSTALL_JOURNAL.JSON and/or expected_profile
    profile_matched = True
    journal_path = usb_root / "GPU-UNLOCK" / "INSTALL_JOURNAL.JSON"
    if journal_path.exists() and not _is_reparse_or_symlink(journal_path):
        try:
            jdata = json.loads(journal_path.read_text(encoding="utf-8"))
            jprof = jdata.get("profile") or {}
            j_board = int(str(jprof.get("board_id_hex", "0")), 16)
            j_subsys = int(str(jprof.get("subsystem_id_hex", "0")), 16)
            if j_board and j_subsys:
                if rep_board_id != j_board or rep_subsys_id != j_subsys:
                    profile_matched = False
        except Exception:
            profile_matched = False

    if expected_profile and expected_profile.get("board_id_hex") and expected_profile.get("subsystem_id_hex"):
        try:
            e_board = int(str(expected_profile["board_id_hex"]).rstrip("uUlL"), 16)
            e_subsys = int(str(expected_profile["subsystem_id_hex"]).rstrip("uUlL"), 16)
            if rep_board_id != e_board or rep_subsys_id != e_subsys:
                profile_matched = False
        except Exception:
            profile_matched = False

    final_line = final_lines[-1] if final_lines else ""
    final_ok = bool(
        len(final_lines) == 1
        and re.fullmatch(
            r"FINAL status=(0x0|0) stage=post-unlock-handoff attempted=1 driver_release=[01] clean=1",
            final_line,
        )
    )
    selectors_ok = ("matched=1 status=0" in ss0_line) and ("matched=1 status=0" in ss1_line)
    has_identity = (rep_board_id is not None and rep_subsys_id is not None)

    return {
        "found": True,
        "path": str(latest),
        "folder": chosen["folder"],
        "run_name": chosen["run_name"],
        "runs": [r["run_name"] for r in discovered_runs],
        "board_id_hex": f"0x{rep_board_id:08x}" if rep_board_id is not None else None,
        "subsystem_id_hex": f"0x{rep_subsys_id:08x}" if rep_subsys_id is not None else None,
        "profile_matched": profile_matched and has_identity,
        "success": final_ok and selectors_ok and handoff_prepared and profile_matched and has_identity,
        "final_line": final_line,
        "ss0_line": ss0_line,
        "ss1_line": ss1_line,
        "text": text,
    }


def _readback_nvml_power_limit_watts(gpu_uuid: str) -> float | None:
    nvml = _load_nvml_library()
    if nvml is None:
        return None
    inited = False
    try:
        if nvml.nvmlInit_v2() != 0:
            return None
        inited = True
        handle = ctypes.c_void_p()
        if hasattr(nvml, "nvmlDeviceGetHandleByUUID"):
            rc = nvml.nvmlDeviceGetHandleByUUID(gpu_uuid.encode("ascii"), ctypes.byref(handle))
            if rc != 0:
                return None
        else:
            return None
        pl_mw = ctypes.c_uint(0)
        if nvml.nvmlDeviceGetPowerManagementLimit(handle, ctypes.byref(pl_mw)) == 0:
            return round(pl_mw.value / 1000.0, 1)
    except Exception:
        return None
    finally:
        if inited:
            try:
                nvml.nvmlShutdown()
            except Exception:
                pass
    return None


def set_gpu_power_limit(
    gpu_uuid: str,
    target_watts: float,
    min_watts: float,
    max_watts: float,
    log_fn: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Set GPU power limit bound to a specific GPU UUID, using ShellExecuteExW elevation when required,
    and verifying the applied limit via NVML or nvidia-smi readback (F16 / M-07 / U09)."""
    if not gpu_uuid or not re.fullmatch(r"GPU-[0-9a-fA-F-]{32,40}", gpu_uuid.strip()):
        raise ValueError("Refusing to set power limit without a verified GPU UUID")
    if min_watts <= 0 or max_watts <= 0 or not (min_watts <= target_watts <= max_watts):
        raise ValueError(f"Requested power limit {target_watts} W is outside verified hardware constraints [{min_watts}..{max_watts}] W")

    watts_int = int(round(target_watts))
    smi_path = (
        r"C:\Windows\System32\nvidia-smi.exe"
        if sys.platform.startswith("win") and Path(r"C:\Windows\System32\nvidia-smi.exe").exists()
        else (shutil.which("nvidia-smi") or "")
    )
    if not smi_path:
        raise FileNotFoundError("nvidia-smi executable not found")

    args = ["-i", gpu_uuid.strip(), "-pl", str(watts_int)]
    log_fn(f"[POWER] Executing: {smi_path} {' '.join(args)}")
    res = subprocess.run(
        [smi_path, *args],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    if res.returncode != 0 and sys.platform.startswith("win"):
        log_fn("[POWER] Requesting Administrator privilege (UAC) for nvidia-smi...")
        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SW_HIDE = 0

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint32),
                ("fMask", ctypes.c_uint32),
                ("hwnd", ctypes.c_void_p),
                ("lpVerb", ctypes.c_wchar_p),
                ("lpFile", ctypes.c_wchar_p),
                ("lpParameters", ctypes.c_wchar_p),
                ("lpDirectory", ctypes.c_wchar_p),
                ("nShow", ctypes.c_int),
                ("hInstApp", ctypes.c_void_p),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", ctypes.c_wchar_p),
                ("hkeyClass", ctypes.c_void_p),
                ("dwHotKey", ctypes.c_uint32),
                ("hIcon", ctypes.c_void_p),
                ("hProcess", ctypes.c_void_p),
            ]

        sei = SHELLEXECUTEINFOW()
        sei.cbSize = ctypes.sizeof(sei)
        sei.fMask = SEE_MASK_NOCLOSEPROCESS
        sei.lpVerb = "runas"
        sei.lpFile = smi_path
        sei.lpParameters = f"-i {gpu_uuid.strip()} -pl {watts_int}"
        sei.nShow = SW_HIDE

        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        if not shell32.ShellExecuteExW(ctypes.byref(sei)) or not sei.hProcess:
            raise RuntimeError("Administrator elevation cancelled or failed")
        try:
            wait_rc = kernel32.WaitForSingleObject(sei.hProcess, 15000)
            if wait_rc != 0:
                raise RuntimeError(f"Elevated nvidia-smi timed out (WaitForSingleObject={wait_rc})")
            exit_code = ctypes.c_uint32(1)
            kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(exit_code))
            if exit_code.value != 0:
                raise RuntimeError(f"Elevated nvidia-smi exited with code {exit_code.value}")
        finally:
            kernel32.CloseHandle(sei.hProcess)
    elif res.returncode != 0:
        raise RuntimeError(f"nvidia-smi failed (exit {res.returncode}): {(res.stderr or res.stdout).strip()}")

    # Mandatory readback verification via NVML or nvidia-smi --query-gpu=power.limit
    readback_w = _readback_nvml_power_limit_watts(gpu_uuid.strip())
    if readback_w is None:
        q_res = subprocess.run(
            [smi_path, "-i", gpu_uuid.strip(), "--query-gpu=power.limit", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if q_res.returncode == 0 and q_res.stdout.strip():
            try:
                readback_w = round(float(q_res.stdout.strip().splitlines()[0].strip()), 1)
            except ValueError:
                readback_w = None

    if readback_w is None or abs(readback_w - watts_int) > 1.5:
        raise RuntimeError(
            f"Power limit readback verification failed: requested {watts_int} W, hardware reported {readback_w} W"
        )

    return {"ok": True, "status": "APPLIED", "gpu_uuid": gpu_uuid.strip(), "target_watts": watts_int, "readback_watts": readback_w}
