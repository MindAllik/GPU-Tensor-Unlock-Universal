# GPU-Tensor-Unlock-Universal

**Pre-driver `FMLA32` Tensor Core unlocker and PTX benchmark console for GeForce RTX 40-series (Ada Lovelace) and RTX 30-series (Ampere) on Windows 10/11 (UEFI USB) and Linux (`gpu_unlock.ko`).**

Consumer GeForce GPUs of the Ada Lovelace (`RTX 40xx`) and Ampere (`RTX 30xx`) generations carry the full physical Tensor Core execution units on silicon, but stock VBIOS firmware sets the `FMLA32` speed-select override (`0x0082381c` `SS0` / `0x00823820` `SS1`) to half rate (`1`). Because of this fuse setting, matrix multiply-accumulate instructions that accumulate into 32-bit floating-point registers (`FP16 -> FP32`, `BF16 -> FP32`, `TF32 -> FP32`, and `FP8 E4M3 -> FP32`) run at half the issue rate of `FP16 -> FP16` or workstation RTX cards.

**GPU-Tensor-Unlock-Universal** removes this limit in volatile GPU registers before the operating system display driver binds (`BOOTX64.EFI` pre-boot on Windows 10/11, or `gpu_unlock.ko` on Linux), restoring full `2.00x` `FMLA32` throughput until the next cold power-off. The SPI flash chip (VBIOS ROM) is never written or modified.

## Why This Project Was Built

Upstream research repositories proved that the V67 SEC2 Booter chain works on Ampere and Ada, but they were released as low-level research snapshots rather than a unified tool:
- **Hardcoded single-card profiles**: Public Windows UEFI forks were configured for a single board (`RTX 4090` or `RTX 4080`). Adapting them to another card required manually looking up PCI Device and Subsystem IDs, bus numbers, VRAM windows, and Windows EFI System Partition GUIDs, editing C headers (`local_profile.h`) by hand, and compiling the EFI binary from the command line.
- **OS and architecture fragmentation**: Linux kernel modules (`gpu-unlock` for Ampere, `gpu-unlock-ada` for Ada) and Windows UEFI loaders lived in separate repositories with different build flows and no graphical console.
- **No built-in verification or benchmark**: Checking whether the unlock actually took effect required building external CUDA tools (`mmapeak`) separately, and stock `mmapeak` builds used compile-time all-zero fragments that allowed the compiler to collapse tile calculations.
- **Late VBIOS ROM validation on UEFI**: Earlier UEFI loaders disconnected the display driver before verifying whether the card's `FWSEC-FRTS` descriptor and `DMEMMAPPER` table in VBIOS PROM matched the expected layout.

**GPU-Tensor-Unlock-Universal** brings Windows and Linux support, Ada (`AD10x`) and Ampere (`GA10x`) payload chains, automatic hardware profiling, and an integrated PTX benchmark into one self-contained package.

## Key Features

1. **Native Desktop Consoles for Windows and Linux (`Windows_Launch_UI.bat` & `Linux_Launch_UI.sh`)**
   - **Windows 10 / 11 (`Windows_Launch_UI.bat`)**: Detects the host GPU and Windows ESP GUID automatically, compiles a board-matched `BOOTX64.EFI`, and stages a bootable FAT32 USB drive with a 30-second manual confirmation prompt (`Press U`).
   - **Linux (`./Linux_Launch_UI.sh`)**: Builds and verifies the pinned `610.43.03` firmware assets, compiles and loads `gpu_unlock.ko` via DKMS and `modprobe`, parses transaction stages from `dmesg`, and reads hardware SM issue-rate dividers directly through `/dev/nvidiactl` (`ioctl 0x20801230`) without requiring a CUDA context.
   - **Cross-OS Protection & Multi-Language UI**: Prevents running the Windows launcher on Linux/Wine or the Linux launcher on Windows, and supports instant switching between English (`EN`), Russian (`RU`), Chinese (`ZH`), and Hindi (`HI`).

2. **Multi-Source Hardware Auto-Detection & Profile Lock**
   - Cross-verifies GPU identity across `NVML` (`nvml.dll` / `libnvidia-ml.so.1`), `CUDA Driver API` (`nvcuda.dll` / `libcuda.so.1`), and OS PCI enumerators (Windows `pci.sys` via `Get-PnpDevice` or Linux `/sys/bus/pci/devices/*` + `lspci -Dnn`).
   - Enforces a strict `PCI Device ID -> Silicon Die -> PMC_BOOT_0` mapping in both host profile generation and UEFI C checks (`GuValidArchChip`), locking hardware fields in the UI so a mismatched chip profile cannot be built accidentally.
   - Includes a **Live CLI Verification** button that displays the exact `nvidia-smi` / `lspci` / PowerShell command and prints the raw system output directly in the console.

3. **Pre-Flight VBIOS ROM Validation & Safe Handoff**
   - Before disconnecting UEFI GOP (`DisconnectController`), the pre-flight check reads `NV_PROM_DATA` (`BAR0 + 0x300000` up to 1 MiB), validates the ROM expansion chain, `BIT` checksum, `Falcon Ucode Descriptor V3` (`ucode_id = 9`, `engine_mask = 0x400`), `DMEMMAPPER v3` (`"DMAP"`), and live fuse version (`0x8241c0`), and runs a dry-run `FRTS` patch in host RAM.
   - Latches the SHA-256 digest of the verified `FWSEC` span on pre-flight and re-verifies it before enabling Bus Master or launching GSP.
   - Retains all DMA buffers with Bus Master disabled if any post-start stage fails before post-FLR quiescence is confirmed, ensuring the GPU can never DMA into freed host memory.

4. **Integrated CUDA PTX JIT Benchmark (`tensor_benchmark.py`)**
   - Measures 7 PTX kernels (`FP16 -> FP16`, `FP16 -> FP32`, `BF16 -> FP32`, `TF32 -> FP32`, `FP8 E4M3 -> FP32`, `INT8 -> INT32`, and `Scalar FP32 FFMA`) with runtime-randomized inputs.
   - Verifies both the loop execution signature and finite non-zero IEEE-754 accumulators on every run, and saves `BEFORE (STOCK)` and `AFTER (UNLOCKED)` baselines per GPU UUID for side-by-side speedup comparison.
   - Includes one-click VBIOS maximum power limit adjustment via NVML with hardware readback verification.

5. **Offline Sanitizer & Kernel Test Suites**
   - **Windows UEFI (`python3 windows/uefi/run_self_test.py`)**: Compiles and runs 43 core transaction scenarios and 56 UEFI application/topology scenarios against simulated PCI/MMIO/DMA hardware under `gcc -fsanitize=address,undefined`.
   - **Linux Kernel & Tooling (`python3 -m unittest discover -s tests -v`)**: Runs 33 unit and C kernel tests covering `unlock_610.c`, `main.c`, `prep_610.c`, `vbios_610.c`, `layout_610.c`, `gfw_eval.c`, `read_sm_rates.py`, and `sysfs`/`lspci` auto-detection.

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
2. In Section `[01]`, verify your automatically detected GPU (`sysfs` `/sys/bus/pci/devices/*` + `lspci -Dnn` + `NVML` + `CUDA`) and inspect the generated **Module Load Command** (e.g. `modprobe gpu_unlock targets=0000:01:00.0 ad104_experimental=1` for RTX 4070 Ti `10de:2782`, or `modprobe gpu_unlock targets=0000:01:00.0` for RTX 4090 / RTX 3090).
3. In Section `[02]`, verify that `linux-headers`, `dkms` + C compiler (`gcc`/`clang`), and `zstd` are installed (or click **`INSTALL BUILD DEPENDENCIES (LINUX-HEADERS + DKMS + ZSTD)`**).
4. In Section `[03]`, click **`>> BUILD & APPLY UNLOCK NOW (MODPROBE GPU_UNLOCK) <<`**.
5. Verify the unlock in Sections `[03]` & `[04]`:
   - Click **`CHECK DMESG / KERNEL LOG`** to confirm `marker=0x67b00001`, `SS0=88888888 SS1=00000008`, and `gpu_unlock: unlocked`.
   - Click **`PROBE SM RATES (/dev/nvidiactl)`** to query NVIDIA RM ioctl `0x20801230` (`tools/read_sm_rates.py`) and confirm `fmla32 = 0 [FULL (1/1)]`.
   - Click **`RUN LIVE TENSOR BENCHMARK`** to measure the `2.00x` `FMLA32` TFLOP/s speedup.

## Measured Results (Hardware-Tested Baselines)

| GPU Model | PCI ID / Die | `FP16 -> FP16` (FMLA16) | `FP16 -> FP32` Stock | `FP16 -> FP32` Unlocked | `BF16 -> FP32` Unlocked | Gain |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| **GeForce RTX 4090** | `10de:2684` (`AD102`) | ~331.6 TF/s | 165.6 TF/s | **331.6 TF/s** | **330.6 TF/s** | **2.00x** |
| **GeForce RTX 4070 Ti SUPER** | `10de:2705` (`AD103`) | ~190.0 TF/s | 95.0 TF/s | **189.9 TF/s** | **189.7 TF/s** | **2.00x** |
| **GeForce RTX 4070 Ti** | `10de:2782` (`AD104`) | 172.8 TF/s | 86.4 TF/s | **172.8 TF/s** | **172.7 TF/s** | **2.00x** |

*Note: These figures represent register-resident Tensor Core instruction issue rates (`mma.sync.aligned.m16n8k16`). Real-world GEMM or inference speedups depend on memory bandwidth, power limits, and kernel utilization.*

## Supported Hardware Matrix

| Family | `PMC_BOOT_0` | Status | Desktop Models | Linux Module Load Command (`gpu_unlock.ko`) |
| :--- | :--- | :--- | :--- | :--- |
| **Ada (`AD102`)** | `0x192000a1` | `hardware_tested` | GeForce RTX 4090 (`10de:2684`) | `modprobe gpu_unlock targets=<BDF>` |
| **Ada (`AD104`)** | `0x194000a1` | `hardware_tested` / `exp` | GeForce RTX 4070 Ti (`10de:2782`), 4070 SUPER, 4070, 4060 Ti (`AD104`) | `modprobe gpu_unlock targets=<BDF> ad104_experimental=1` |
| **Ada (`AD103`)** | `0x193000a1` | `hardware_tested` / `exp` | GeForce RTX 4070 Ti SUPER (`10de:2705`), 4080 SUPER, 4080, 4070 (`AD103`) | `modprobe gpu_unlock targets=<BDF> ad103_experimental=1` |
| **Ada (`AD102/106/107`)** | `0x192..0x197` | `experimental` | GeForce RTX 4090 D, 4060 Ti (8/16 GB), 4060 | `modprobe gpu_unlock targets=<BDF> ada_experimental=1` |
| **Ampere (`GA102..106`)** | `0x172..0x176` | `hardware_tested` / `exp` | GeForce RTX 3090 Ti, 3090, 3080 Ti, 3080, 3070 Ti, 3070, 3060 Ti, 3060 | `modprobe gpu_unlock targets=<BDF>` (or `all`) |

Detailed architecture and safety guarantees are documented in [`docs/ARCHITECTURE_AND_SAFETY.md`](docs/ARCHITECTURE_AND_SAFETY.md) and [`QUICKSTART.md`](QUICKSTART.md).

## Credits & Upstream Acknowledgements

This project builds upon the research, payloads, and loader code published by the following repositories:
- **[TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)** — AD102 4-PLM SEC2 payload construction, debug-booter analysis, and the foundational Windows UEFI application.
- **[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)** & **[JustAResearcher/gpu-unlock-ada](https://github.com/JustAResearcher/gpu-unlock-ada)** — Linux pre-driver kernel module (`unlock_610.c`), WPR2/FLR handoff logic, and the `/dev/nvidiactl` RM issue-rate getter (`read_sm_rates.py`).
- **[KohakuBlueleaf/KohakUnlock](https://github.com/KohakuBlueleaf/KohakUnlock)** — Windows/UEFI pre-flight hardening, cold-state register classification, and runtime-randomized `mmapeak` verification methodology.
- **[WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock)**, **[xrip/cmp50hx-unlock](https://github.com/xrip/cmp50hx-unlock)**, **Nouveau**, and **[envytools](https://github.com/envytools/envytools)** — GA102 V67 Booter ROP research and Falcon engine documentation.

## License

Source code in this repository is licensed under **GPL-2.0-only** (see [`LICENSE`](LICENSE) and [`licenses/`](licenses/)). No proprietary NVIDIA firmware binaries are distributed in this repository; pinned `610.43.03` firmware inputs are fetched directly over HTTPS and verified by SHA-256 on the user's machine during build.
