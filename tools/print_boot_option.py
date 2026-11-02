#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Print exact, supported NVIDIA PCI boot options without changing the host."""
import re
import subprocess
import sys


DEVICES = {
    "2684": ("RTX 4090", ""),
    "2705": ("RTX 4070 Ti SUPER (experimental)", " gpu_unlock.ad103_experimental=1"),
    "2782": ("RTX 4070 Ti (experimental)", " gpu_unlock.ad104_experimental=1"),
    "1e04": ("RTX 2080 Ti (experimental)", " gpu_unlock.turing_experimental=1"),
    "1e07": ("RTX 2080 Ti (experimental)", " gpu_unlock.turing_experimental=1"),
    "1e02": ("TITAN RTX (experimental)", " gpu_unlock.turing_experimental=1"),
    "1e81": ("RTX 2080 SUPER (experimental)", " gpu_unlock.turing_experimental=1"),
    "1e82": ("RTX 2080 (experimental)", " gpu_unlock.turing_experimental=1"),
    "1e87": ("RTX 2080 Rev. A (experimental)", " gpu_unlock.turing_experimental=1"),
    "1e84": ("RTX 2070 SUPER (experimental)", " gpu_unlock.turing_experimental=1"),
    "1f02": ("RTX 2070 (experimental)", " gpu_unlock.turing_experimental=1"),
    "1f07": ("RTX 2070 Rev. A (experimental)", " gpu_unlock.turing_experimental=1"),
    "1f06": ("RTX 2060 SUPER (experimental)", " gpu_unlock.turing_experimental=1"),
    "1f47": ("RTX 2060 SUPER (experimental)", " gpu_unlock.turing_experimental=1"),
    "1f08": ("RTX 2060 6GB (experimental)", " gpu_unlock.turing_experimental=1"),
    "1f03": ("RTX 2060 12GB (experimental)", " gpu_unlock.turing_experimental=1"),
    "1e09": ("CMP 50HX (experimental)", " gpu_unlock.turing_experimental=1"),
    "1f0b": ("CMP 40HX (experimental)", " gpu_unlock.turing_experimental=1"),
}

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
        print("No supported RTX 4090 (10de:2684), experimental RTX 4070 Ti SUPER "
              "(10de:2705), experimental RTX 4070 Ti (10de:2782), or experimental "
              "RTX 20-series / Turing card was found.", file=sys.stderr)
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
