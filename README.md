# GPU-Tensor-Unlock-Universal

**Version: 1.2.8**

**Pre-driver `FMLA32` Tensor Core unlocker and PTX benchmark console for GeForce RTX 40-series (Ada Lovelace), RTX 30-series (Ampere), and RTX 20-series (Turing) on Windows 10/11 (UEFI USB) and Linux (`gpu_unlock.ko`).**

Consumer GeForce GPUs of the Ada Lovelace (`RTX 40xx`), Ampere (`RTX 30xx`), and Turing (`RTX 20xx`) generations carry the full physical Tensor Core execution units on silicon, but stock VBIOS firmware sets the `FMLA32` speed-select override (`0x0082381c` `SS0` / `0x00823820` `SS1` on Ada/Ampere, or `0x00409664` `SS0` / `0x0040966c` `SS1` on Turing) to half rate (`1`). Because of this fuse setting, matrix multiply-accumulate instructions that accumulate into 32-bit floating-point registers (`FP16 -> FP32`, `BF16 -> FP32`, `TF32 -> FP32`, and `FP8 E4M3 -> FP32`) run at half the issue rate of `FP16 -> FP16` or workstation RTX cards.

**GPU-Tensor-Unlock-Universal** removes this limit in volatile GPU registers before the operating system display driver binds (`BOOTX64.EFI` pre-boot on Windows 10/11, or `gpu_unlock.ko` on Linux), restoring full `2.00x` `FMLA32` throughput until the next cold power-off. The SPI flash chip (VBIOS ROM) is never written or modified.

## Why This Project Was Built

Upstream research repositories proved that the V67 SEC2 Booter chain works on Turing, Ampere, and Ada, but they were released as low-level research snapshots rather than a unified tool:
- **Hardcoded single-card profiles**: Public Windows UEFI forks were configured for a single board (`RTX 4090` or `RTX 4080`). Adapting them to another card required manually looking up PCI Device and Subsystem IDs, bus numbers, VRAM windows, and Windows EFI System Partition GUIDs, editing C headers (`local_profile.h`) by hand, and compiling the EFI binary from the command line.
- **OS and architecture fragmentation**: Linux kernel modules (`gpu-unlock` for Ampere/Turing, `gpu-unlock-ada` for Ada) and Windows UEFI loaders lived in separate repositories with different build flows and no graphical console.
- **No built-in verification or benchmark**: Checking whether the unlock actually took effect required building external CUDA tools (`mmapeak`) separately, and stock `mmapeak` builds used compile-time all-zero fragments that allowed the compiler to collapse tile calculations.
- **Late VBIOS ROM validation on UEFI**: Earlier UEFI loaders disconnected the display driver before verifying whether the card's `FWSEC-FRTS` descriptor and `DMEMMAPPER` table in VBIOS PROM matched the expected layout.

**GPU-Tensor-Unlock-Universal** brings Windows and Linux support, Ada (`AD10x`), Ampere (`GA10x`), and Turing (`TU10x`) payload chains, automatic hardware profiling, and an integrated PTX benchmark into one self-contained package.

## Key Features

1. **Native Desktop Consoles for Windows and Linux (`Windows_Launch_UI.bat` & `Linux_Launch_UI.sh`)**
   - **Windows 10 / 11 (`Windows_Launch_UI.bat`)**: Detects the host GPU, USB/SD removable drives, and Windows ESP GUID via zero-Admin Win32 kernel IOCTLs (`IOCTL_STORAGE_QUERY_PROPERTY`, `IOCTL_DISK_GET_DRIVE_LAYOUT_EX`) with `AUTO` UEFI ESP discovery fallback, compiles a board-matched `BOOTX64.EFI`, and stages a bootable FAT32 USB drive with a 30-second manual confirmation prompt (`Press U`).
   - **Linux (`./Linux_Launch_UI.sh`)**: Builds and verifies the pinned `610.43.03` firmware assets, stages `gpu_unlock.ko` via DKMS + early-boot `initramfs` hooks (or executes live `modprobe` for unbound secondary GPUs), parses transaction stages from `dmesg`, and reads hardware SM issue-rate dividers directly through `/dev/nvidiactl` (`ioctl 0x20801230`) without requiring a CUDA context.
   - **Cross-OS Protection & Multi-Language UI**: Prevents running the Windows launcher on Linux/Wine or the Linux launcher on Windows, and supports instant switching between English (`EN`), Russian (`RU`), Chinese (`ZH`), and Hindi (`HI`).

2. **Multi-Source Hardware Auto-Detection & Profile Lock**
   - Cross-verifies GPU identity across `NVML` (`nvml.dll` / `libnvidia-ml.so.1`), `CUDA Driver API` (`nvcuda.dll` / `libcuda.so.1`), and OS PCI enumerators (Windows `pci.sys` via `Get-PnpDevice` or Linux `/sys/bus/pci/devices/*` + `lspci -Dnn`).
   - Enforces a strict `PCI Device ID -> Silicon Die -> PMC_BOOT_0` mapping in both host profile generation and UEFI C checks (`GuValidArchChip`), locking hardware fields in the UI so a mismatched chip profile cannot be built accidentally.
   - Includes a **Live CLI Verification** button that displays the exact `nvidia-smi` / `lspci` / PowerShell command and prints the raw system output directly in the console.

3. **Pre-Flight VBIOS ROM Validation & Safe Handoff**
   - Before disconnecting UEFI GOP (`DisconnectController`), the pre-flight check reads `NV_PROM_DATA` (`BAR0 + 0x300000` up to 1 MiB), validates the ROM expansion chain, `BIT` checksum, `Falcon Ucode Descriptor` (`V3` RSA-3K on Ada/Ampere or `V2` AES-128 on Turing; `ucode_id = 9`, `engine_mask = 0x400`), `DMEMMAPPER v3` (`"DMAP"`), and live fuse version (`0x8241c0`), and runs a dry-run `FRTS` patch in host RAM.
   - Latches the SHA-256 digest of the verified `FWSEC` span on pre-flight and re-verifies it before enabling Bus Master or launching GSP.
   - Retains all DMA buffers with Bus Master disabled if any post-start stage fails before post-FLR quiescence is confirmed, ensuring the GPU can never DMA into freed host memory.

4. **Integrated CUDA PTX JIT Benchmark (`tensor_benchmark.py`)**
   - Measures up to 7 PTX kernels (`FP16 -> FP16`, `FP16 -> FP32`, `BF16 -> FP32`, `TF32 -> FP32`, `FP8 E4M3 -> FP32`, `INT8 -> INT32`, and `Scalar FP32 FFMA`) across `sm_89` (Ada), `sm_86` (Ampere), and `sm_75` (Turing) with runtime-randomized inputs.
   - Verifies both the loop execution signature and finite non-zero IEEE-754 accumulators on every run, and saves `BEFORE (STOCK)` and `AFTER (UNLOCKED)` baselines per GPU UUID for side-by-side speedup comparison.
   - Includes one-click VBIOS maximum power limit adjustment via NVML with hardware readback verification.

5. **Offline Sanitizer & Kernel Test Suites**
   - **Windows UEFI (`python3 windows/uefi/run_self_test.py`)**: Compiles and runs 43 core transaction scenarios and 64 UEFI application/topology scenarios against simulated PCI/MMIO/DMA hardware under `gcc -fsanitize=address,undefined`.
   - **Linux Kernel & Tooling (`python3 -m unittest discover -s tests -v`)**: Runs unit and C kernel tests covering `unlock_610.c`, `main.c`, `prep_610.c`, `vbios_610.c`, `layout_610.c`, `gfw_eval.c`, `read_sm_rates.py`, and `sysfs`/`lspci` auto-detection.

## Quick Start — Windows 10 / 11 (`Windows_Launch_UI.bat`)

1. Extract this repository to any folder and double-click **`Windows_Launch_UI.bat`**.
2. Click **`RUN LIVE CLI VERIFICATION (SHOW RAW NUMBERS)`** in Section `[01]` to inspect the exact `nvidia-smi` and PowerShell queries and verify your GPU's raw hardware IDs.
3. If `LLVM` or `zstandard` is missing in Section `[02]`, click **`INSTALL MISSING DEPENDENCIES (LLVM + ZSTD)`**.
4. Run the benchmark before unlocking (**`RUN LIVE TENSOR BENCHMARK`** $\rightarrow$ **`SAVE AS 'BEFORE' (STOCK)`**).
5. Insert a **FAT32**-formatted USB flash drive, select it in Section `[03]`, and click **`>> BUILD & WRITE BOOTABLE USB <<`**.
6. **BitLocker & Secure Boot Note**: If BitLocker is active on `C:`, suspend BitLocker protection for 1 reboot (`Suspend-BitLocker -MountPoint "C:" -RebootCount 1`) or keep your 48-digit recovery key ready before disabling **Secure Boot** in BIOS.
7. Click **`GRACEFUL COLD SHUTDOWN FOR USB BOOT`** (`shutdown /s /t 5`), wait 5–10 seconds after power-off, turn on the PC, and boot from the USB drive via your BIOS Boot Menu (`F11` / `F12` / `F8`).
8. At the UEFI prompt, press **`U`** once within **30 seconds** to confirm and start the unlock transaction. After the transaction and GOP reconnect complete, Windows boots automatically.
9. Open **`Windows_Launch_UI.bat`** and click **`RUN LIVE TENSOR BENCHMARK`** to verify your `2.00x` `FMLA32` speedup.

## Quick Start — Linux (`./Linux_Launch_UI.sh`)

1. Run **`./Linux_Launch_UI.sh`** (or `python3 linux_unlock_ui.py`).
2. In Section `[01]`, verify your automatically detected GPU (`sysfs` `/sys/bus/pci/devices/*` + `lspci -Dnn` + `NVML` + `CUDA`) and inspect the generated **Module Load Command** (e.g. `modprobe gpu_unlock targets=0000:01:00.0 ad104_experimental=1` for RTX 4070 Ti `10de:2782`, `modprobe gpu_unlock targets=0000:01:00.0 turing_experimental=1` for RTX 2080 Ti `10de:1e07`, or `modprobe gpu_unlock targets=0000:01:00.0` for RTX 4090 / RTX 3090).
3. In Section `[02]`, verify that `linux-headers`, `dkms` + C compiler (`gcc`/`clang`), and `zstd` are installed (or click **`INSTALL BUILD DEPENDENCIES (LINUX-HEADERS + DKMS + ZSTD)`**).
4. In Section `[03]`, click **`>> BUILD & APPLY UNLOCK NOW (MODPROBE GPU_UNLOCK) <<`**:
   - **Primary GPU bound to `nvidia` (`bound_driver = nvidia`)**: Because the kernel module refuses to mutate a GPU while `nvidia.ko` is already attached (`-EBUSY`), the UI automatically installs the DKMS module, firmware assets, and early-boot `initramfs` hook, and prints the exact `gpu_unlock.targets=...` kernel parameter to add to your bootloader (`GRUB2`, `grubby`, or `systemd-boot`) for the next cold boot.
   - **Unbound secondary compute GPU (`bound_driver = unbound`)**: Compiles and loads `gpu_unlock.ko` live via `modprobe` without requiring a reboot.
5. Verify the unlock in Sections `[03]` & `[04]`:
   - Click **`CHECK DMESG / KERNEL LOG`** to confirm `marker=0x67b00001`, `SS0=88888888 SS1=00000008`, and `gpu_unlock: unlocked`.
   - Click **`PROBE SM RATES (/dev/nvidiactl)`** to query NVIDIA RM ioctl `0x20801230` (`tools/read_sm_rates.py`) and confirm `fmla32 = 0 [FULL (1/1)]`.
   - Click **`RUN LIVE TENSOR BENCHMARK`** to measure the `2.00x` `FMLA32` TFLOP/s speedup.

## Measured Results (Hardware-Tested Baselines)

| GPU Model | PCI ID / Die | `FP16 -> FP16` (FMLA16) | `FP16 -> FP32` Stock | `FP16 -> FP32` Unlocked | `BF16 -> FP32` Unlocked | Gain | Verification Source & Test Bench |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| **GeForce RTX 4070 Ti** | `10de:2782` (`AD104`) | 172.8 TF/s | 86.4 TF/s | **172.8 TF/s** | **172.7 TF/s** | **2.00x** | **[Author Tested — MindAllik]** Win 11 UEFI, Palit `1569:f294`, 300 W ([`rtx4070ti-report`](docs/rtx4070ti-report.md)) |
| **GeForce RTX 4090** | `10de:2684` (`AD102`) | ~331.6 TF/s | 165.6 TF/s | **331.6 TF/s** | **330.6 TF/s** | **2.00x** | **[Upstream Report — elias-gaeros]** Linux 7.2.4, 450 W ([`rtx4090-report`](docs/rtx4090-register-report.md)) |
| **GeForce RTX 4070 Ti SUPER** | `10de:2705` (`AD103`) | ~190.0 TF/s | 95.0 TF/s | **189.9 TF/s** | **189.7 TF/s** | **2.00x** | **[Upstream Report — JustAResearcher]** Linux 5.15, 240 W ([`ada-2705-report`](docs/ada-2705-report.md)) |

*Note: These figures represent register-resident Tensor Core instruction issue rates (`mma.sync.aligned`). Real-world GEMM or inference speedups depend on memory bandwidth, power limits, and kernel utilization.*

## Supported Hardware Matrix

| Family | `PMC_BOOT_0` | Validation Status | Models & PCI IDs | Linux Module Load Command (`gpu_unlock.ko`) |
| :--- | :--- | :--- | :--- | :--- |
| **Ada (`AD104`) — Author Bench** | `0x194000a1` | **Author Hardware-Tested** | GeForce RTX 4070 Ti (`10de:2782` — Windows 11 UEFI, Palit `1569:f294`, 300 W) | `modprobe gpu_unlock targets=<BDF> ad104_experimental=1` \* |
| **Ada (`AD102` / `AD103`) — Upstream** | `0x192000a1` / `0x193000a1` | **Upstream Hardware-Tested** | GeForce RTX 4090 (`10de:2684`), GeForce RTX 4070 Ti SUPER (`10de:2705`) | `targets=<BDF>` (`4090`) or `targets=<BDF> ad103_experimental=1` (`4070 TiS`) \* |
| **Ampere (`GA102` / `GA106`) — Upstream** | `0x172000a1` / `0x176000a1` | **Upstream Hardware-Tested** | GeForce RTX 3090 (`10de:2204`), RTX 3080 (`10de:2206`), RTX 3060 12GB (`10de:2504`) | `modprobe gpu_unlock targets=<BDF>` (or `all`) |
| **Ada (`AD102/103/104/106/107`)** | `0x192..0x197` | **Experimental Opt-In (Simulated)** | GeForce RTX 4090 D (`2685`), 4080 SUPER (`2702`), 4080 (`2704`), 4070 SUPER (`2783`), 4070 (`2786`/`2709`), 4060 Ti (`2803`/`2805`/`27b0`), 4060 (`2882`) | `targets=<BDF>` + family flag (`ad103_experimental=1`, `ad104_experimental=1`, or `ada_experimental=1`) |
| **Ampere (`GA102/103/104/106/107`)** | `0x172..0x177` (incl. `0xb72..0xb77` 8N strap) | **Experimental Opt-In (Simulated)** | GeForce RTX 3090 Ti (`2203`), 3080 Ti 12GB/20GB (`2208`/`2205`), 3080 12GB/LHR (`220a`/`2216`), 3070 Ti (`2482`/`2207`), 3070 (`2484`/`2488`), 3060 Ti (`2486`/`2489`/`24c9`/`2414`), 3060 (`2503`/`2487`), 3050 (`2507`/`2582`/`2584`), CMP 90HX/70HX (`220d`/`248a`) | `modprobe gpu_unlock targets=<BDF>` (or `all`) |
| **Turing (`TU102/104/106`)** | `0x162/164/166` | **Experimental Opt-In (Simulated)** | GeForce RTX 2080 Ti (`1e04`/`1e07`), TITAN RTX (`1e02`), 2080 SUPER (`1e81`), 2080 (`1e82`/`1e87`), 2070 SUPER (`1e84`), 2070 (`1f02`/`1f07`), 2060 SUPER (`1f06`/`1f47`), 2060 12GB (`1f03`), 2060 6GB (`1f08`), CMP 50HX (`1e09`), CMP 40HX (`1f0b`) | `modprobe gpu_unlock targets=<BDF> turing_experimental=1` \* |

*\* Note on Linux module flags: Hardware-validated `RTX 4070 Ti` (`10de:2782`), `RTX 4070 Ti SUPER` (`10de:2705`), and experimental Turing (`TU102`/`TU104`/`TU106`) targets intentionally retain a mandatory single-BDF requirement and their family opt-in module parameters (`ad104_experimental=1`, `ad103_experimental=1`, `turing_experimental=1`) in `gpu_unlock.ko` so that a wildcard `targets=all` setting on a multi-GPU machine cannot accidentally capture an Ada or Turing card without explicit per-device opt-in.*

Detailed architecture and safety guarantees are documented in [`docs/ARCHITECTURE_AND_SAFETY.md`](docs/ARCHITECTURE_AND_SAFETY.md), [`docs/SAFETY.md`](docs/SAFETY.md), and [`QUICKSTART.md`](QUICKSTART.md).

## Credits & Upstream Acknowledgements

This project builds upon the research, payloads, and loader code published by the following repositories and authors:
- **[TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)** (revision `51df9c17ec89eb8486df52cc9079dde4bd1f9974`) — AD102 4-PLM SEC2 payload construction, debug-booter analysis, and the foundational Windows UEFI application framework.
- **[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)**, **[elias-gaeros/gpu-unlock](https://github.com/elias-gaeros/gpu-unlock)** (commit `4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc`), and **[JustAResearcher/gpu-unlock-ada](https://github.com/JustAResearcher/gpu-unlock-ada)** (commit `4e7fefcc4923f9e083d5324dc75a7d2f906af77f`) — pre-driver Linux kernel module architecture (`unlock_610.c`), WPR2/FLR handoff logic, AD102/AD103/TU102 integration, and the `/dev/nvidiactl` RM issue-rate getter (`tools/read_sm_rates.py`).
- **[KohakuBlueleaf/KohakUnlock](https://github.com/KohakuBlueleaf/KohakUnlock)** and **[KohakuBlueleaf/mmapeak](https://github.com/KohakuBlueleaf/mmapeak)** — Windows/UEFI pre-flight check hardening, cold-state register classification (`GuClassifyColdState`), and runtime-randomized `mmapeak` verification methodology.
- **[impacifist/Windows-GPU-UNLOCK](https://github.com/impacifist/Windows-GPU-UNLOCK)** and **[Goldlionren/gpu-unlock-4080s](https://github.com/Goldlionren/gpu-unlock-4080s)** — reference implementation for direct UEFI $\rightarrow$ Windows Boot Manager handoff without intermediate reboot and local Secure Boot `db` signing policy.
- **Jon Pry** (*"A Canary in the Crypto Mine"*, DOI `10.5281/zenodo.20916112`), **[WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock)**, **[xrip/cmp50hx-unlock](https://github.com/xrip/cmp50hx-unlock)**, **[PZH1gdmu/CMP40HX-Unlock](https://github.com/PZH1gdmu/CMP40HX-Unlock)**, **[Consensus-Protocol/cmp170hx](https://github.com/Consensus-Protocol/cmp170hx)**, **Nouveau**, and **[envytools](https://github.com/envytools/envytools)** — foundational research on the V67 Booter vulnerability, PLM register models, and Falcon/GSP processor documentation.

## License

Source code in this repository is licensed under **GPL-2.0-only** (see [`LICENSE`](LICENSE), [`NOTICE.md`](NOTICE.md), and [`licenses/`](licenses/)). No proprietary NVIDIA firmware binaries are distributed in this repository; pinned `610.43.03` firmware inputs are fetched directly over HTTPS and verified by SHA-256 on the user's machine during build.
