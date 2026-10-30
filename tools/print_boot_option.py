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
}


def candidates(lspci_output: str) -> list[tuple[str, str]]:
    found = []
    for line in lspci_output.splitlines():
        address = re.match(r"^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])\s", line)
        device = re.search(r"\[10de:(2684|2705|2782)\]", line, re.I)
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
              "(10de:2705), or experimental RTX 4070 Ti (10de:2782) was found.", file=sys.stderr)
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
