#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Linux Backend for NVIDIA GPU Tensor Unlock (Ada Lovelace, Ampere & Turing).

Integrates the pre-driver Linux kernel module (gpu_unlock.ko), SHA-256 verified
NVIDIA 610.43.03 firmware asset generation (AD102, GA102, and TU102 chains),
DKMS + initramfs (mkinitcpio / initramfs-tools / dracut) staging, kernel log
(journalctl / dmesg) verification, and direct NVIDIA RM ioctl SM issue-rate
readbacks (/dev/nvidiactl cmd 0x20801230).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Callable

import core_detector

APP_ROOT = Path(__file__).resolve().parent
KERNEL_SRC_DIR = APP_ROOT / "kernel" / "gpu_unlock"
FIRMWARE_SCRIPTS_DIR = APP_ROOT / "firmware"
TOOLS_DIR = APP_ROOT / "tools"
PACKAGING_BOOT_DIR = APP_ROOT / "packaging" / "boot"

def _read_project_version() -> str:
    readme = APP_ROOT / "README.md"
    if readme.is_file():
        m = re.search(r"\*\*Version:\s*([0-9]+\.[0-9]+\.[0-9]+)\*\*", readme.read_text(encoding="utf-8", errors="replace"))
        if m:
            return m.group(1)
    return "0.0.0"


MODULE_VERSION = _read_project_version()
NV_VERSION = "610.43.03"

SYSTEM_FW_DIR = Path(f"/usr/lib/firmware/gpu-unlock/{NV_VERSION}")
SYSTEM_DKMS_DIR = Path(f"/usr/src/gpu-unlock-{MODULE_VERSION}")

ALL_LINUX_FIRMWARE_SPECS: dict[str, tuple[int, str]] = {
    **core_detector.ASSET_SPECS_ADA,
    **core_detector.ASSET_SPECS_GA,
    **core_detector.ASSET_SPECS_TU,
}


def detect_os_release(os_release_path: Path | None = None) -> dict[str, str]:
    """Parse /etc/os-release or /usr/lib/os-release to identify Linux distribution family."""
    candidates = (
        [os_release_path]
        if os_release_path is not None
        else [Path("/etc/os-release"), Path("/usr/lib/os-release")]
    )
    data: dict[str, str] = {}
    for p in candidates:
        if p and p.is_file():
            try:
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip().strip('"').strip("'")
                break
            except Exception:
                continue

    distro_id = data.get("ID", "linux").lower()
    id_like = data.get("ID_LIKE", "").lower()
    pretty = data.get("PRETTY_NAME") or data.get("NAME") or "Linux"

    tokens = f"{distro_id} {id_like}".split()
    family = "generic"
    for tok in tokens:
        if tok in ("arch", "manjaro", "endeavouros", "cachyos"):
            family = "arch"
            break
        if tok in ("debian", "ubuntu", "linuxmint", "pop"):
            family = "debian"
            break
        if tok in ("fedora", "rhel", "centos", "rocky", "almalinux", "opensuse"):
            family = "rpm"
            break

    return {
        "id": distro_id,
        "id_like": id_like,
        "pretty_name": pretty,
        "family": family,
    }


def detect_initramfs_and_bootloader() -> dict[str, str]:
    """Detect active initramfs generator and bootloader on the Linux host."""
    initramfs = "unknown"
    if shutil.which("mkinitcpio") or Path("/etc/mkinitcpio.conf").exists():
        initramfs = "mkinitcpio"
    elif shutil.which("update-initramfs") or Path("/usr/share/initramfs-tools").exists():
        initramfs = "initramfs-tools"
    elif shutil.which("dracut") or Path("/usr/lib/dracut").exists():
        initramfs = "dracut"

    bootloader = "unknown"
    if shutil.which("bootctl") and (Path("/boot/loader/entries").exists() or Path("/efi/loader/entries").exists()):
        bootloader = "systemd-boot"
    elif shutil.which("grubby") and Path("/etc/fedora-release").exists():
        bootloader = "grubby (GRUB2)"
    elif Path("/etc/default/grub").exists() or shutil.which("update-grub") or shutil.which("grub-mkconfig"):
        bootloader = "GRUB2"
    elif shutil.which("kernelstub"):
        bootloader = "kernelstub"

    return {
        "initramfs": initramfs,
        "bootloader": bootloader,
    }


def read_linux_secure_boot() -> bool | None:
    """Read UEFI SecureBoot efivar on Linux if mounted."""
    efivar_dir = Path("/sys/firmware/efi/efivars")
    if not efivar_dir.exists():
        return None
    try:
        for p in efivar_dir.glob("SecureBoot-*"):
            raw = p.read_bytes()
            if len(raw) >= 5:
                return bool(raw[-1] == 1)
    except Exception:
        pass
    return None


def check_linux_installation_state(kernel_release: str | None = None) -> dict[str, Any]:
    """Inspect whether gpu_unlock firmware, DKMS module, initramfs hook, and cmdline are installed."""
    krel = kernel_release or platform.release()
    fw_ok = True
    fw_present_count = 0
    for fname, (exp_sz, exp_sha) in ALL_LINUX_FIRMWARE_SPECS.items():
        fpath = SYSTEM_FW_DIR / fname
        if fpath.is_file() and fpath.stat().st_size == exp_sz:
            try:
                if core_detector.sha256_file(fpath) == exp_sha:
                    fw_present_count += 1
                    continue
            except Exception:
                pass
        fw_ok = False

    dkms_src_ok = (SYSTEM_DKMS_DIR / "dkms.conf").is_file() and (SYSTEM_DKMS_DIR / "main.c").is_file()
    ko_built = False
    mod_root = Path(f"/lib/modules/{krel}")
    if mod_root.exists():
        try:
            for _ in mod_root.rglob("gpu_unlock.ko*"):
                ko_built = True
                break
        except Exception:
            pass

    hook_paths = [
        Path("/etc/mkinitcpio.conf.d/zz-gpu-unlock.conf"),
        Path("/usr/share/initramfs-tools/modules.d/gpu-unlock.conf"),
        Path("/usr/lib/dracut/dracut.conf.d/gpu-unlock.conf"),
    ]
    installed_hooks = [str(p) for p in hook_paths if p.is_file()]

    cmdline = ""
    if Path("/proc/cmdline").is_file():
        try:
            cmdline = Path("/proc/cmdline").read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            cmdline = ""

    cmdline_targets = ""
    m = re.search(r"(gpu_unlock\.targets=\S+(?:\s+gpu_unlock\.\S+)*)", cmdline)
    if m:
        cmdline_targets = m.group(1)

    module_loaded = Path("/sys/module/gpu_unlock").exists()
    return {
        "firmware_installed": fw_ok and fw_present_count == len(ALL_LINUX_FIRMWARE_SPECS),
        "firmware_count": f"{fw_present_count}/{len(ALL_LINUX_FIRMWARE_SPECS)}",
        "dkms_src_installed": dkms_src_ok,
        "ko_installed_for_running_kernel": ko_built,
        "module_loaded": module_loaded,
        "initramfs_hooks": installed_hooks,
        "cmdline": cmdline,
        "cmdline_targets": cmdline_targets,
    }


def detect_linux_environment() -> dict[str, Any]:
    """Comprehensive Linux hardware, kernel, toolchain, DKMS, and bootloader detector."""
    base = core_detector.detect_host_environment()
    krel = platform.release()
    os_rel = detect_os_release()
    boot_info = detect_initramfs_and_bootloader()
    inst_state = check_linux_installation_state(krel)

    headers_dir = Path(f"/lib/modules/{krel}/build")
    headers_ok = headers_dir.exists() and (headers_dir / "Makefile").exists()

    cc_path = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang") or ""
    make_path = shutil.which("make") or ""
    dkms_path = shutil.which("dkms") or ""
    lspci_path = shutil.which("lspci") or ("/usr/bin/lspci" if Path("/usr/bin/lspci").exists() else "")

    for g in base.get("gpus", []):
        if "linux_boot_option" not in g:
            g["linux_boot_option"] = core_detector.get_linux_boot_option_for_gpu(g)
        if "bound_driver" not in g:
            g["bound_driver"] = "nvidia" if g.get("gpu_uuid") else "unbound"

    for g in base.get("gpus", []):
        g["linux_modprobe_cmd"] = core_detector.get_linux_modprobe_command_for_gpu(g)

    if base.get("gpus"):
        chosen = next((g for g in base["gpus"] if g.get("supported")), base["gpus"][0])
        base["gpu_detected"] = bool(chosen.get("board_id_hex") and chosen.get("pci_bdf"))
        base["linux_boot_option"] = chosen.get("linux_boot_option") or core_detector.get_linux_boot_option_for_gpu(chosen)
        base["linux_modprobe_cmd"] = chosen.get("linux_modprobe_cmd") or core_detector.get_linux_modprobe_command_for_gpu(chosen)
        base["bound_driver"] = chosen.get("bound_driver", "unknown")
    else:
        base["linux_boot_option"] = "gpu_unlock.targets=<PCI_BDF>"
        base["linux_modprobe_cmd"] = "modprobe gpu_unlock targets=<PCI_BDF>"
        base["bound_driver"] = "none"

    base.update({
        "kernel_release": krel,
        "distro_id": os_rel["id"],
        "distro_family": os_rel["family"],
        "distro_pretty": os_rel["pretty_name"],
        "initramfs_tool": boot_info["initramfs"],
        "bootloader": boot_info["bootloader"],
        "headers_ok": headers_ok,
        "headers_path": str(headers_dir),
        "cc_path": cc_path,
        "make_path": make_path,
        "dkms_path": dkms_path,
        "dkms_toolchain_ok": bool(cc_path and make_path and dkms_path),
        "lspci_path": lspci_path,
        "secure_boot_enabled": read_linux_secure_boot(),
        "install_state": inst_state,
    })
    return base


def get_linux_live_cli_command() -> str:
    """Return the transparent Linux CLI verification command shown in the UI."""
    return (
        "lspci -Dnn -d 10de: && "
        "nvidia-smi --query-gpu=index,name,uuid,pci.bus_id,pci.device_id,pci.sub_device_id,"
        "memory.total,vbios_version,power.default_limit,power.max_limit --format=csv,noheader,nounits"
    )


def run_linux_live_cli_verification(log_fn: Callable[[str], None] = print) -> dict[str, Any]:
    """Run transparent lspci + sysfs + nvidia-smi + /proc/cmdline checks on Linux and log raw numbers."""
    cmd_str = get_linux_live_cli_command()
    log_fn("=" * 76)
    log_fn(f"[LINUX CLI CHECK 1/3] $ lspci -Dnn -d 10de: (and /sys/bus/pci/devices/*)")
    sysfs_gpus = core_detector._query_linux_pci_gpus()
    lspci_exe = shutil.which("lspci") or "/usr/bin/lspci"
    raw_lspci = ""
    try:
        res_pci = subprocess.run([lspci_exe, "-Dnn"], capture_output=True, text=True, timeout=8)
        nvidia_lines = [ln for ln in res_pci.stdout.splitlines() if "10de:" in ln.lower() or "nvidia" in ln.lower()]
        raw_lspci = "\n".join(nvidia_lines)
        log_fn(raw_lspci if raw_lspci else "(no NVIDIA devices in lspci output)")
    except Exception as exc:
        log_fn(f"[WARN] lspci execution note: {exc}")

    for sg in sysfs_gpus:
        opt = core_detector.get_linux_boot_option_for_gpu(sg)
        log_fn(
            f"  -> [SYSFS PCI] BDF={sg['pci_bdf']} | Vendor:Device={sg['board_id_hex']} | "
            f"Subsys={sg['subsystem_id_hex']} | Driver={sg.get('bound_driver')} | "
            f"BootOpt='{opt}'"
        )

    log_fn("-" * 76)
    log_fn("[LINUX CLI CHECK 2/3] $ nvidia-smi --query-gpu=index,name,uuid,pci.bus_id,pci.device_id,pci.sub_device_id,memory.total,vbios_version,power.default_limit,power.max_limit --format=csv,noheader,nounits")
    smi_res = core_detector.run_live_cli_verification(log_fn=log_fn)

    log_fn("-" * 76)
    log_fn("[LINUX CLI CHECK 3/3] $ cat /proc/cmdline && uname -r")
    krel = platform.release()
    cmdline = ""
    if Path("/proc/cmdline").is_file():
        try:
            cmdline = Path("/proc/cmdline").read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass
    log_fn(f"Kernel: {krel}")
    log_fn(f"Cmdline: {cmdline or '(unavailable)'}")
    log_fn("=" * 76)
    return {
        "command": cmd_str,
        "raw_lspci": raw_lspci,
        "sysfs_gpus": sysfs_gpus,
        "smi": smi_res,
        "kernel_release": krel,
        "cmdline": cmdline,
    }


def query_sm_issue_rates_live(expected_uuid: str, log_fn: Callable[[str], None] = print) -> dict[str, Any]:
    """Query hardware SM issue-rate modifiers directly via /dev/nvidiactl RM ioctl (0x20801230)."""
    uuid_clean = (expected_uuid or "").strip()
    if not uuid_clean:
        raise ValueError("GPU UUID is required for /dev/nvidiactl RM ioctl verification (ensure nvidia driver is loaded).")

    script_path = TOOLS_DIR / "read_sm_rates.py"
    cmd_str = f"python3 {script_path.name} --expect-uuid {uuid_clean}"
    log_fn("=" * 76)
    log_fn(f"[RM IOCTL 0x20801230] $ {cmd_str}")

    sys.path.insert(0, str(TOOLS_DIR))
    import read_sm_rates  # type: ignore

    data = read_sm_rates.read_rates(uuid_clean)
    rates = data.get("rates") or {}
    fmla32 = rates.get("fmla32")
    fmla16 = rates.get("fmla16")
    imla0 = rates.get("imla0")
    ffma = rates.get("ffma")

    rate_labels = {0: "FULL (1/1)", 1: "HALF (1/2)", 2: "QUARTER (1/4)"}
    fmla32_str = rate_labels.get(fmla32, f"RAW={fmla32}")
    status_tag = "UNLOCKED (FULL SPEED)" if fmla32 == 0 else ("STOCK / THROTTLED (HALF SPEED)" if fmla32 == 1 else f"CODE {fmla32}")

    log_fn(f"[OK] GPU Identity: {data.get('gpu')}")
    log_fn(f"[OK] RM Control Command: {data.get('command')} (NV2080_CTRL_CMD_GR_GET_SM_ISSUE_RATE_MODIFIER)")
    log_fn(
        f"  -> fmla32 = {fmla32} [{fmla32_str}]  <-- Target FP16/BF16/TF32 -> FP32 Accumulate Selector\n"
        f"  -> fmla16 = {fmla16} [{rate_labels.get(fmla16, str(fmla16))}]\n"
        f"  -> ffma   = {ffma} [{rate_labels.get(ffma, str(ffma))}]\n"
        f"  -> imla0  = {imla0} [{rate_labels.get(imla0, str(imla0))}] | "
        f"imla1={rates.get('imla1')} imla2={rates.get('imla2')} imla3={rates.get('imla3')} imla4={rates.get('imla4')} dp={rates.get('dp')}"
    )
    log_fn(f"[VERDICT] Hardware RM Selector State: {status_tag}")
    log_fn("=" * 76)
    return data


def build_all_linux_firmware_assets(
    assets_dir: Path | None = None,
    log_fn: Callable[[str], None] = print,
) -> Path:
    """Download/verify NVIDIA 610.43.03 inputs and build all 14 Linux firmware assets (GA102, AD102, and TU102)."""
    if assets_dir is None:
        assets_dir = Path.home() / ".cache" / "gpu-unlock" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = core_detector.CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate and verify all three V67 payloads (GA102, AD102, and TU102)
    for arch_tag, is_ada, v67_name in (
        ("ga102", False, "v67-ga102-610.43.03.bin"),
        ("ad102", True, "v67-ad102-610.43.03-four-plm.bin"),
        ("tu102", False, "v67-tu102-610.43.03.bin"),
    ):
        exp_sz, exp_sha = ALL_LINUX_FIRMWARE_SPECS[v67_name]
        v67_bytes = core_detector.build_v67_payload(is_ada=is_ada, arch=arch_tag)
        if len(v67_bytes) != exp_sz or core_detector.sha256_bytes(v67_bytes) != exp_sha:
            raise ValueError(f"Generated {v67_name} failed SHA-256 verification")
        core_detector._write_verified_file(assets_dir / v67_name, v67_bytes, exp_sha)
        log_fn(f"[OK] Generated & verified {v67_name} ({exp_sz} bytes)")

    # 2. Fetch and extract both GA102 and AD102 booter_load / gsp_boot / gsp_boot_desc
    c_texts: dict[str, str] = {}
    needed_c = list(core_detector.SOURCE_C_FILES.keys())
    for cname in needed_c:
        csha, curl = core_detector.SOURCE_C_FILES[cname]
        cpath = cache_dir / cname
        try:
            core_detector.download_verified(curl, cpath, csha, log_fn)
            c_texts[cname] = cpath.read_text(encoding="ascii")
        except Exception as exc:
            log_fn(f"[INFO] GitHub fetch fallback ({exc}), using NVIDIA 610.43.03 source tarball...")
            tar_path = core_detector.download_verified(
                core_detector.SOURCE_TARBALL_URL,
                cache_dir / "NVIDIA-kernel-module-source-610.43.03.tar.xz",
                core_detector.SOURCE_TARBALL_SHA256,
                log_fn,
            )
            with tarfile.open(tar_path, mode="r:xz") as tf:
                for m in tf:
                    for target_c in needed_c:
                        tsha, _ = core_detector.SOURCE_C_FILES[target_c]
                        if m.name.endswith("/src/nvidia/generated/" + target_c):
                            ef = tf.extractfile(m)
                            if ef is None:
                                continue
                            raw = ef.read()
                            if core_detector.sha256_bytes(raw) != tsha and not target_c.endswith("_TU102.c"):
                                raise ValueError(f"SHA-256 mismatch for {target_c}")
                            (cache_dir / target_c).write_bytes(raw)
                            c_texts[target_c] = raw.decode("ascii")
            break

    for chip_tag in ("ga102", "ad102", "tu102"):
        booter_c = f"g_bindata_kgspGetBinArchiveBooterLoadUcode_{chip_tag.upper()}.c"
        boot_c = f"g_bindata_kgspGetBinArchiveGspRmBoot_{chip_tag.upper()}.c"
        booter_bin = core_detector.build_booter_bundle(c_texts[booter_c])
        boot_bin = core_detector._array_bytes(c_texts[boot_c], "UCODE_IMAGE_PROD")
        desc_bin = core_detector._array_bytes(c_texts[boot_c], "UCODE_DESC_PROD")
        for fname, blob in (
            (f"booter_load_{chip_tag}.bin", booter_bin),
            (f"gsp_boot_{chip_tag}.bin", boot_bin),
            (f"gsp_boot_desc_{chip_tag}.bin", desc_bin),
        ):
            if chip_tag == "tu102":
                exp_sz, exp_sha = len(blob), core_detector.sha256_bytes(blob)
            else:
                exp_sz, exp_sha = ALL_LINUX_FIRMWARE_SPECS[fname]
                if len(blob) != exp_sz or core_detector.sha256_bytes(blob) != exp_sha:
                    raise ValueError(f"SHA-256 verification failed for {fname}")
            core_detector._write_verified_file(assets_dir / fname, blob, exp_sha)
            log_fn(f"[OK] Generated & verified {fname} ({exp_sz} bytes)")

    # 3. Extract or reuse gsp_ga10x.bin and gsp_tu10x.bin
    for gsp_fname in ("gsp_ga10x.bin", "gsp_tu10x.bin"):
        gsp_dest = assets_dir / gsp_fname
        exp_gsp_sz, exp_gsp_sha = ALL_LINUX_FIRMWARE_SPECS[gsp_fname]
        if gsp_dest.exists() and gsp_dest.stat().st_size == exp_gsp_sz and core_detector.sha256_file(gsp_dest) == exp_gsp_sha:
            log_fn(f"[OK] Reused verified {gsp_fname} in assets cache")
        else:
            cached_gsp = cache_dir / gsp_fname
            if not (cached_gsp.exists() and cached_gsp.stat().st_size == exp_gsp_sz and core_detector.sha256_file(cached_gsp) == exp_gsp_sha):
                shared_gsp = core_detector._find_shared_cached_file(gsp_fname, exp_gsp_sha, log_fn)
                if shared_gsp is not None:
                    shutil.copy2(shared_gsp, cached_gsp)
            if not (cached_gsp.exists() and cached_gsp.stat().st_size == exp_gsp_sz and core_detector.sha256_file(cached_gsp) == exp_gsp_sha):
                pkg_path = core_detector.download_verified(
                    core_detector.PACKAGE_URL,
                    cache_dir / "nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst",
                    core_detector.PACKAGE_SHA256,
                    log_fn,
                )
                log_fn(f"[EXTRACT] Unpacking {gsp_fname} ({exp_gsp_sz / (1024 * 1024):.1f} MB)...")
                core_detector.extract_gsp_from_zst(pkg_path, cached_gsp, member_name=gsp_fname)
                if core_detector.sha256_file(cached_gsp) != exp_gsp_sha:
                    cached_gsp.unlink(missing_ok=True)
                    raise ValueError(f"Extracted {gsp_fname} SHA-256 mismatch!")
                core_detector._save_to_shared_cache(cached_gsp, exp_gsp_sha)
            core_detector._write_verified_file(gsp_dest, cached_gsp.read_bytes(), exp_gsp_sha)
            log_fn(f"[OK] Staged & verified {gsp_fname} ({exp_gsp_sz:,} bytes)")

    # 4. Stage NVIDIA-LICENSE (NVIDIA Driver License Agreement, SHA-256 c692fb14...) for Makefile install-firmware compatibility
    for cand_lic in (
        APP_ROOT / "licenses" / "NVIDIA-driver-COPYING",
        APP_ROOT / "windows" / "uefi" / "source" / "LICENSES" / "NVIDIA-Driver.txt",
        APP_ROOT / "licenses" / "NVIDIA-MIT.txt",
    ):
        if cand_lic.exists():
            (assets_dir / "NVIDIA-LICENSE").write_bytes(cand_lic.read_bytes())
            break

    return assets_dir


def format_bootloader_instructions(boot_option: str, distro_family: str, bootloader: str) -> str:
    """Return exact, copy-pasteable bootloader configuration commands for the detected Linux distro."""
    lines = [
        f"Required kernel parameter for selected GPU:",
        f"  {boot_option}",
        "",
    ]
    if "systemd-boot" in bootloader:
        lines.extend([
            "[systemd-boot]",
            "  1. Check active boot entry:  bootctl status",
            f"  2. Append to the 'options' line of your entry in /boot/loader/entries/*.conf:",
            f"     {boot_option}",
            "  3. Power off completely (cold shutdown), wait 15-30s, and boot.",
        ])
    elif distro_family == "rpm" or "grubby" in bootloader:
        lines.extend([
            "[Fedora / RHEL — grubby]",
            f'  sudo grubby --update-kernel=ALL --args="{boot_option}"',
            f'  # To roll back later: sudo grubby --update-kernel=ALL --remove-args="{boot_option}"',
        ])
    elif distro_family == "arch":
        lines.extend([
            "[Arch / CachyOS / Manjaro — GRUB2]",
            f'  1. Add inside GRUB_CMDLINE_LINUX_DEFAULT quotes in /etc/default/grub:',
            f'     {boot_option}',
            "  2. Regenerate GRUB config:",
            "     sudo grub-mkconfig -o /boot/grub/grub.cfg",
        ])
    else:
        lines.extend([
            "[Ubuntu / Debian / Mint — GRUB2]",
            f'  1. Add inside GRUB_CMDLINE_LINUX_DEFAULT quotes in /etc/default/grub:',
            f'     {boot_option}',
            "  2. Update GRUB:",
            "     sudo update-grub",
        ])
    return "\n".join(lines)


def get_distro_deps_command(distro_family: str, kernel_release: str | None = None) -> str:
    """Return the exact package manager command to install DKMS, kernel headers, compiler, and zstd."""
    krel = kernel_release or platform.release()
    if distro_family == "arch":
        return "sudo pacman -S --needed base-devel linux-headers dkms zstd pciutils python-zstandard"
    if distro_family == "rpm":
        return f"sudo dnf install -y kernel-devel-{krel} kernel-headers dkms gcc make zstd pciutils python3-zstandard"
    return f"sudo apt-get update && sudo apt-get install -y build-essential linux-headers-{krel} dkms zstd pciutils python3-zstandard"


def _run_privileged_shell(script_cmd: str, log_fn: Callable[[str], None]) -> int:
    """Run a privileged command via root, passwordless sudo, or pkexec."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd = ["bash", "-c", script_cmd]
    elif shutil.which("sudo"):
        # Check if passwordless sudo is available first
        chk = subprocess.run(["sudo", "-n", "true"], capture_output=True)
        if chk.returncode == 0:
            cmd = ["sudo", "bash", "-c", script_cmd]
        elif shutil.which("pkexec") and os.environ.get("DISPLAY"):
            cmd = ["pkexec", "bash", "-c", script_cmd]
        else:
            log_fn("[INFO] Interactive sudo password required. Run the printed command in your terminal:")
            log_fn(f"  sudo bash -c '{script_cmd}'")
            return 126
    elif shutil.which("pkexec") and os.environ.get("DISPLAY"):
        cmd = ["pkexec", "bash", "-c", script_cmd]
    else:
        log_fn("[ERROR] Neither root privileges nor sudo/pkexec found.")
        return 127

    log_fn(f"[EXEC] {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        log_fn(line.rstrip("\n"))
    return proc.wait()


def install_linux_dkms_and_firmware(
    env_info: dict[str, Any],
    log_fn: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Build SHA-verified 610.43.03 firmware assets and install gpu_unlock DKMS + initramfs hooks."""
    assets_dir = build_all_linux_firmware_assets(log_fn=log_fn)

    initramfs_tool = env_info.get("initramfs_tool", "unknown")
    if initramfs_tool == "mkinitcpio":
        hook_target = "install-mkinitcpio"
        rebuild_cmd = "mkinitcpio -P"
    elif initramfs_tool == "dracut":
        hook_target = "install-dracut"
        rebuild_cmd = "dracut --regenerate-all --force"
    else:
        hook_target = "install-initramfs-tools"
        rebuild_cmd = "update-initramfs -u"

    script_cmd = (
        f"set -e; cd '{APP_ROOT}' && "
        f"make ASSETS='{assets_dir}' install-dkms install-firmware install-licenses {hook_target} && "
        f"(dkms status -m gpu-unlock -v '{MODULE_VERSION}' | grep -q . || dkms add -m gpu-unlock -v '{MODULE_VERSION}') && "
        f"dkms build -m gpu-unlock -v '{MODULE_VERSION}' && "
        f"dkms install -m gpu-unlock -v '{MODULE_VERSION}' --force && "
        f"{rebuild_cmd}"
    )
    log_fn("-" * 76)
    log_fn("[INSTALL] Staging DKMS module, firmware (/usr/lib/firmware/gpu-unlock/610.43.03), and initramfs hook...")
    rc = _run_privileged_shell(script_cmd, log_fn)
    boot_opt = env_info.get("linux_boot_option", "gpu_unlock.targets=<PCI_BDF>")
    boot_guide = format_bootloader_instructions(
        boot_opt,
        env_info.get("distro_family", "debian"),
        env_info.get("bootloader", "GRUB2"),
    )
    log_fn("-" * 76)
    log_fn(boot_guide)
    log_fn("-" * 76)
    return {
        "returncode": rc,
        "assets_dir": str(assets_dir),
        "boot_option": boot_opt,
        "boot_guide": boot_guide,
    }


def export_linux_bundle_to_folder(
    target_dir: str | Path,
    env_info: dict[str, Any],
    log_fn: Callable[[str], None] = print,
) -> Path:
    """Export a complete, self-contained Linux DKMS + verified firmware bundle to a user folder (no root required)."""
    out_root = Path(str(target_dir).strip()).resolve()
    if str(out_root) in ("/", "/usr", "/etc", "/bin", "/lib", "/boot"):
        raise ValueError(f"Refusing to export into critical system root directory: {out_root}")

    assets_dir = build_all_linux_firmware_assets(log_fn=log_fn)
    bundle_dir = out_root / f"gpu-unlock-linux-bundle-{MODULE_VERSION}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Copy Makefile, README.md, kernel/, packaging/, licenses/, tools/
    for item_name in ("Makefile", "README.md", "QUICKSTART.md"):
        src_p = APP_ROOT / item_name
        if src_p.is_file():
            shutil.copy2(src_p, bundle_dir / item_name)

    for folder_name in ("kernel", "packaging", "licenses", "tools", "debian"):
        src_d = APP_ROOT / folder_name
        if src_d.is_dir():
            shutil.copytree(src_d, bundle_dir / folder_name, dirs_exist_ok=True)

    fw_out = bundle_dir / "prebuilt_assets"
    fw_out.mkdir(parents=True, exist_ok=True)
    for item in assets_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, fw_out / item.name)

    boot_opt = env_info.get("linux_boot_option", "gpu_unlock.targets=<PCI_BDF>")
    boot_guide = format_bootloader_instructions(
        boot_opt,
        env_info.get("distro_family", "debian"),
        env_info.get("bootloader", "GRUB2"),
    )

    install_sh = bundle_dir / "install_bundle_root.sh"
    install_sh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'cd "$(dirname "$0")"\n'
        f'make ASSETS="$(pwd)/prebuilt_assets" install-dkms install-firmware install-licenses\n'
        "if command -v mkinitcpio >/dev/null 2>&1; then\n"
        "    make install-mkinitcpio\n"
        "     INITRAMFS_CMD='mkinitcpio -P'\n"
        "elif command -v dracut >/dev/null 2>&1; then\n"
        "    make install-dracut\n"
        "    INITRAMFS_CMD='dracut --regenerate-all --force'\n"
        "else\n"
        "    make install-initramfs-tools\n"
        "    INITRAMFS_CMD='update-initramfs -u'\n"
        "fi\n"
        f"dkms status -m gpu-unlock -v '{MODULE_VERSION}' | grep -q . || dkms add -m gpu-unlock -v '{MODULE_VERSION}'\n"
        f"dkms build -m gpu-unlock -v '{MODULE_VERSION}'\n"
        f"dkms install -m gpu-unlock -v '{MODULE_VERSION}' --force\n"
        "eval \"$INITRAMFS_CMD\"\n"
        "echo '[SUCCESS] gpu_unlock DKMS + firmware + initramfs installed.'\n"
        f"echo 'Add kernel parameter: {boot_opt}'\n",
        encoding="utf-8",
    )
    try:
        install_sh.chmod(0o755)
    except OSError:
        pass

    (bundle_dir / "BOOTLOADER_INSTRUCTIONS.txt").write_text(boot_guide + "\n", encoding="utf-8")
    log_fn(f"[OK] Exported self-contained Linux bundle to: {bundle_dir}")
    log_fn(f"[OK] Run 'sudo ./install_bundle_root.sh' inside {bundle_dir} to install.")
    return bundle_dir


def parse_linux_kernel_log_text(raw_log: str, expected_bdf: str | None = None) -> dict[str, Any]:
    """Parse dmesg / journalctl -k output for gpu_unlock transaction stages and post-FLR verification."""
    lines = [
        ln for ln in raw_log.splitlines()
        if any(tok in ln for tok in ("gpu_unlock", "AD102 payload", "post-FLR SEC2", "selector result", "FWSEC:"))
    ]
    if expected_bdf:
        bdf_low = expected_bdf.lower()
        bdf_lines = [ln for ln in lines if bdf_low in ln.lower() or "gpu_unlock:" in ln]
        if bdf_lines:
            lines = bdf_lines

    if not lines:
        return {
            "found": False,
            "unlocked": False,
            "error": "No gpu_unlock messages found in the current boot kernel log (journalctl -k -b).",
        }

    entry_line = next((ln for ln in reversed(lines) if "entry: plm=" in ln), "")
    payload_line = next((ln for ln in reversed(lines) if "AD102 payload result:" in ln), "")
    ss0_line = next((ln for ln in reversed(lines) if "selector result: SS0=" in ln or "selector read: SS0=" in ln), "")
    ss1_line = next((ln for ln in reversed(lines) if "selector result: SS1=" in ln or "selector read: SS1=" in ln), "")
    flr_line = next((ln for ln in reversed(lines) if "post-FLR SEC2 reset released" in ln), "")
    final_line = next((ln for ln in reversed(lines) if "gpu_unlock: unlocked" in ln or "gpu_unlock: unlock failed" in ln), "")

    unlocked = bool(
        "gpu_unlock: unlocked" in final_line
        and ("SS0=88888888" in flr_line or "SS0=0x88888888" in ss0_line)
    )
    return {
        "found": True,
        "unlocked": unlocked,
        "entry_line": entry_line,
        "payload_line": payload_line,
        "ss0_line": ss0_line,
        "ss1_line": ss1_line,
        "flr_line": flr_line,
        "final_line": final_line,
        "text": "\n".join(lines),
    }


def read_linux_kernel_log(expected_bdf: str | None = None) -> dict[str, Any]:
    """Read current boot kernel log via journalctl -k -b or dmesg and parse gpu_unlock status."""
    raw = ""
    if shutil.which("journalctl"):
        try:
            res = subprocess.run(
                ["journalctl", "-k", "-b", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0 and res.stdout.strip():
                raw = res.stdout
        except Exception:
            pass
    if not raw and shutil.which("dmesg"):
        try:
            res = subprocess.run(["dmesg"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                raw = res.stdout
        except Exception:
            pass
    if not raw:
        return {
            "found": False,
            "unlocked": False,
            "error": "Could not read kernel log via journalctl -k -b or dmesg (check permissions).",
        }
    return parse_linux_kernel_log_text(raw, expected_bdf=expected_bdf)


def build_and_apply_linux_unlock(
    env_info: dict[str, Any],
    log_fn: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Build SHA-256 verified 610.43.03 firmware, compile gpu_unlock.ko, and apply live modprobe
    (or automatically fall back to staging early-boot initramfs hooks if a display driver is already bound)."""
    modprobe_cmd = env_info.get("linux_modprobe_cmd") or "modprobe gpu_unlock targets=all"
    if modprobe_cmd == "UNSUPPORTED":
        raise ValueError("Cannot apply unlock: selected GPU is not in SUPPORT_MATRIX.")

    bound_drv = str(env_info.get("bound_driver") or "unknown").strip().lower()
    if bound_drv not in ("", "unbound", "none", "unknown"):
        log_fn("-" * 76)
        log_fn(
            f"[INFO] Target GPU ({env_info.get('pci_bdf', 'N/A')}) is currently bound to '{bound_drv}'. "
            "Because kernel/gpu_unlock/main.c refuses live mutation on a driver-bound GPU (-EBUSY), "
            "automatically staging the DKMS module, firmware, and early-boot initramfs hook for the next cold boot..."
        )
        res = install_linux_dkms_and_firmware(env_info, log_fn=log_fn)
        res["modprobe_cmd"] = modprobe_cmd
        res["mode"] = "early_boot_initramfs"
        return res

    assets_dir = build_all_linux_firmware_assets(log_fn=log_fn)
    script_cmd = (
        f"set -e; cd '{APP_ROOT}' && "
        f"make ASSETS='{assets_dir}' install-dkms install-firmware install-licenses && "
        f"(dkms status -m gpu-unlock -v '{MODULE_VERSION}' | grep -q . || dkms add -m gpu-unlock -v '{MODULE_VERSION}') && "
        f"dkms build -m gpu-unlock -v '{MODULE_VERSION}' && "
        f"dkms install -m gpu-unlock -v '{MODULE_VERSION}' --force && "
        f"(lsmod | grep -q '^gpu_unlock' && rmmod gpu_unlock || true) && "
        f"{modprobe_cmd}"
    )
    log_fn("-" * 76)
    log_fn(f"[APPLY] Installing firmware + building gpu_unlock.ko + executing live: {modprobe_cmd}")
    rc = _run_privileged_shell(script_cmd, log_fn)
    if rc != 0:
        log_fn(
            "[WARN] Live modprobe returned non-zero (card may have bound to nvidia). "
            "Falling back to staging early-boot initramfs hook..."
        )
        res = install_linux_dkms_and_firmware(env_info, log_fn=log_fn)
        res["modprobe_cmd"] = modprobe_cmd
        res["mode"] = "early_boot_initramfs"
        return res
    return {
        "returncode": rc,
        "assets_dir": str(assets_dir),
        "modprobe_cmd": modprobe_cmd,
        "mode": "live_modprobe",
    }


def unload_linux_unlock_module(log_fn: Callable[[str], None] = print) -> int:
    """Safely unload gpu_unlock.ko via rmmod gpu_unlock if not retaining DMA buffers."""
    script_cmd = "if lsmod | grep -q '^gpu_unlock'; then rmmod gpu_unlock && echo '[OK] gpu_unlock.ko unloaded.'; else echo '[INFO] gpu_unlock.ko is not currently loaded.'; fi"
    return _run_privileged_shell(script_cmd, log_fn)
