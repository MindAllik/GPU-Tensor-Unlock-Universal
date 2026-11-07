#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Print exact, supported NVIDIA PCI boot options without changing the host."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import core_detector  # noqa: E402


def _build_devices_map() -> dict[str, tuple[str, str]]:
    devices: dict[str, tuple[str, str]] = {}
    for dev16, (die, _chip_id, is_ada, _tier, model) in sorted(core_detector.SUPPORT_MATRIX.items()):
        hex_id = f"{dev16:04x}"
        short_model = re.sub(r"^NVIDIA\s+", "", model)
        short_model = re.sub(r"^GeForce\s+", "", short_model)
        if dev16 == 0x1E07:
            short_model = "RTX 2080 Ti"
        elif dev16 == 0x1F47:
            short_model = "RTX 2060 SUPER"
        boot_opt = core_detector.get_linux_boot_option_for_gpu({
            "pci_bdf": "0000:01:00.0",
            "board_id_hex": f"0x{dev16:04x}10de",
            "gpu_name": model,
        })
        extra = ""
        if " " in boot_opt:
            extra = " " + boot_opt.split(" ", 1)[1]
        is_exp = bool(extra)
        label = f"{short_model} (experimental)" if is_exp else short_model
        devices[hex_id] = (label, extra)
    return devices


DEVICES: dict[str, tuple[str, str]] = _build_devices_map()
_DEVICE_REGEX = "|".join(sorted(DEVICES.keys()))


def candidates(lspci_output: str) -> list[tuple[str, str]]:
    found = []
    for line in lspci_output.splitlines():
        address = re.match(r"^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])\s", line)
        device = re.search(rf"\[10de:({_DEVICE_REGEX})\]", line, re.I)
        if address and device:
            found.append((address.group(1).lower(), device.group(1).lower()))
    return found


def main() -> int:
    try:
        result = subprocess.run(["lspci", "-Dnn"], check=True, capture_output=True,
                                text=True, timeout=10)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"Could not read PCI devices: {error}. Install pciutils and retry.", file=sys.stderr)
        return 1
    found = candidates(result.stdout)
    if not found:
        print("No supported NVIDIA Ada Lovelace (RTX 40-series), Ampere (RTX 30-series), "
              "or Turing (RTX 20-series) card was found.", file=sys.stderr)
        return 2
    for address, device in found:
        label, extra = DEVICES[device]
        options = f"gpu_unlock.targets={address}{extra}"
        print(f"{label} at {address} [10de:{device}]:")
        print(options)
        print()
    if len(found) > 1:
        print("Choose one exact card for the first cold test; do not combine addresses.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
