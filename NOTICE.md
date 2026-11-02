# Licensing and Provenance

The source work in **GPU-Tensor-Unlock-Universal** is licensed under **GPL-2.0-only** ([`LICENSE`](LICENSE)), except for retained third-party license texts under [`licenses/`](licenses/) and [`windows/uefi/source/LICENSES/`](windows/uefi/source/LICENSES/). Documentation authored for this repository is also licensed under **GPL-2.0-only**. External NVIDIA firmware retains its own separate terms (see [`firmware/NOTICE.md`](firmware/NOTICE.md)); no license to proprietary firmware is implied.

## 1. Repository Structure and Original Contributions (`MindAllik`)

The top-level cross-platform orchestration, hardware auto-detection, benchmark engine, and desktop graphical consoles were authored for **GPU-Tensor-Unlock-Universal** (`MindAllik`) under **GPL-2.0-only**:

- **`core_detector.py`**: Multi-source hardware auto-detection across `NVML`, `CUDA Driver API`, Windows `pci.sys`, and Linux `sysfs`/`lspci`, strict `PCI ID -> Silicon Die -> PMC_BOOT_0` profile locking, dynamic `local_profile.h` / `prom_profile.h` code generation, and bootable USB staging.
- **`linux_backend.py`**: Linux DKMS build automation, SHA-256 verified `610.43.03` asset preparation, early-boot `initramfs` hook installation (`mkinitcpio` / `dracut` / `initramfs-tools`), live `modprobe` orchestration, and `journalctl`/`dmesg` transaction parser.
- **`gpu_unlock_ui.py` & `Windows_Launch_UI.bat`**: Native desktop GUI console and launcher for Windows 10/11.
- **`linux_unlock_ui.py` & `Linux_Launch_UI.sh`**: Native desktop GUI console and launcher for Linux.
- **`tensor_benchmark.py`**: Integrated 7-kernel CUDA PTX JIT benchmark (`FP16 -> FP16`, `FP16 -> FP32`, `BF16 -> FP32`, `TF32 -> FP32`, `FP8 E4M3 -> FP32`, `INT8 -> INT32`, `Scalar FP32 FFMA`) across `sm_89` (Ada), `sm_86` (Ampere), and `sm_75` (Turing) with runtime-randomized non-zero inputs and accumulator verification.
- **`i18n_strings.py`**: Localization tables for English (`EN`), Russian (`RU`), Chinese (`ZH`), and Hindi (`HI`).

Hardware validation performed by the repository author (`MindAllik`) was conducted on a **Palit GeForce RTX 4070 Ti** (`10de:2782`, Subsystem `1569:f294`, `AD104`, 12 GiB GDDR6X, VBIOS `95.04.31.00.36`, Windows 11 x64, 300 W power limit); see [`docs/rtx4070ti-report.md`](docs/rtx4070ti-report.md).

## 2. Linux Kernel Module and Firmware Generators (`kernel/gpu_unlock/`, `firmware/`, `tools/`)

The pre-driver Linux kernel module in [`kernel/gpu_unlock/`](kernel/gpu_unlock/) (`main.c`, `unlock_610.c`, `prep_610.c`, `vbios_610.c`, `layout_610.c`, `gfw_eval.c`, `arch_610.h`) and the firmware extraction/generation scripts in [`firmware/`](firmware/) (`fetch_artifacts.py`, `extract_boot_assets.py`, `generate_v67.py`) and [`tools/`](tools/) (`print_boot_option.py`, `read_sm_rates.py`) derive from:

- **[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)** (commit `a9b0c75bb79b0c9fac6be68feade78d0b8715395` and `main` branch `recipes.c`): Ampere (`GA10x`) and Turing (`TU10x`) pre-driver kernel module architecture, WPR2 layout calculation, FWSEC-FRTS V2/V3 execution, `tu102_v67` 6-write payload recipe (`0x00409650` PLM / `0x00409664` SS0 / `0x0040966c` SS1), and PCIe FLR handoff.
- **[elias-gaeros/gpu-unlock](https://github.com/elias-gaeros/gpu-unlock)** (commit `4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc`): Initial RTX 4090 (`AD102`, `10de:2684`) Linux kernel integration, four-PLM verification gates, and the RTX 4090 hardware experiment report ([`docs/rtx4090-register-report.md`](docs/rtx4090-register-report.md)).
- **[JustAResearcher/gpu-unlock-ada](https://github.com/JustAResearcher/gpu-unlock-ada)** (commit `4e7fefcc4923f9e083d5324dc75a7d2f906af77f`): Guarded `AD103` (`10de:2705`, RTX 4070 Ti SUPER) integration, `/dev/nvidiactl` issue-rate reader (`tools/read_sm_rates.py`), SM89 benchmark probes (`diagnostics/bench/`), and the RTX 4070 Ti SUPER report ([`docs/ada-2705-report.md`](docs/ada-2705-report.md)).

## 3. Windows UEFI Pre-Boot Application (`windows/uefi/`)

The UEFI application in [`windows/uefi/`](windows/uefi/) (`app.c`, `app_io.c`, `checks.c`, `ownership.c`, `port.c`, `handoff.inc`, and the shared transaction core under `windows/uefi/source/unlock/vendor/`) derives from:

- **[TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)** (revision `51df9c17ec89eb8486df52cc9079dde4bd1f9974`): AD102 4-PLM SEC2 payload construction, debug-booter analysis, and the foundational GPL-2.0-only UEFI application. EDK2 headers retain `BSD-2-Clause-Patent`; individual MIT/NVIDIA notices are preserved under [`windows/uefi/source/LICENSES/`](windows/uefi/source/LICENSES/). No upstream CC-BY-NC narrative documents or disassembly excerpts are copied.
- **[KohakuBlueleaf/KohakUnlock](https://github.com/KohakuBlueleaf/KohakUnlock)** and **[KohakuBlueleaf/mmapeak](https://github.com/KohakuBlueleaf/mmapeak)** (commit `cb43e95423be799eeb038cce0dfca1ba1c5572a8`, derived from `ReinForce-II/mmapeak`): Workstation PCI/GOP enumeration hardening, inactive display child handling, cold-state register classification (`GuClassifyColdState`), two-phase pre-flight VBIOS `PROM` verification before `DisconnectController`, and runtime-randomized `mmapeak` verification methodology ([`docs/ADA-WINDOWS.md`](docs/ADA-WINDOWS.md)).
- **[impacifist/Windows-GPU-UNLOCK](https://github.com/impacifist/Windows-GPU-UNLOCK)** and **[Goldlionren/gpu-unlock-4080s](https://github.com/Goldlionren/gpu-unlock-4080s)**: Reference implementation for direct UEFI $\rightarrow$ Windows Boot Manager (`bootmgfw.efi`) handoff without an intermediate reboot and local Secure Boot `db` signing policy.

## 4. Foundational V67 Booter, PLM, and Falcon Research

- **Jon Pry** (*"A Canary in the Crypto Mine"*, DOI `10.5281/zenodo.20916112`), **[WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock)** (commit `76940ae583281daa2b883518a2e89b56c11d3a46`), **[xrip/cmp50hx-unlock](https://github.com/xrip/cmp50hx-unlock)**, **[PZH1gdmu/CMP40HX-Unlock](https://github.com/PZH1gdmu/CMP40HX-Unlock)**, **[Consensus-Protocol/cmp170hx](https://github.com/Consensus-Protocol/cmp170hx)**, **[NVIDIA/open-gpu-kernel-modules](https://github.com/NVIDIA/open-gpu-kernel-modules)**, **Nouveau**, and **[envytools](https://github.com/envytools/envytools)**: Foundational research on the SEC2 Booter V67 stack canary vulnerability, Privilege Level Mask (`PLM`) register models, and Falcon/GSP boot interfaces. Full MIT license texts are retained in [`licenses/CMP40HX-MIT.txt`](licenses/CMP40HX-MIT.txt) and [`licenses/NVIDIA-MIT.txt`](licenses/NVIDIA-MIT.txt).

## 5. Publication Boundary

- **Excluded**: Proprietary NVIDIA firmware binaries, ROM/PROM dumps, decrypted firmware images, signing keys, and precompiled kernel/EFI binaries.
- **Included**: GPL-2.0-only source code, register constants, SHA-256 input manifests, and deterministic local asset generators. Pinned `610.43.03` firmware inputs must be obtained independently on the user's machine under their applicable terms.
