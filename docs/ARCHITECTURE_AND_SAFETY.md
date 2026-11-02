# Technical Architecture & Hardware Safety Guarantees (Windows 10/11 & Linux)

## 1. Windows 10 / 11 Pre-Driver UEFI Unlock Architecture (`Windows_Launch_UI.bat`)

Both Windows 10 and Windows 11 load the NVIDIA kernel-mode display driver (`nvlddmkm.sys`) early during OS boot, which initializes `WPR2` (Write Protected Region 2) and boots GSP-RM. Once `WPR2` is active, running `FWSEC-FRTS` or `PCIe FLR` from under the Windows driver is unsafe.

To solve this cleanly on Windows 10 and Windows 11, `BOOTX64.EFI` executes the entire unlock transaction **inside UEFI Boot Services** before the Windows kernel starts:

1. **Read-Only Preflight Gates (`EfiMain` in `windows/uefi/source/unlock/app.c`)**:
   - **`secure-boot` & `watchdog`**: Verifies UEFI boot policy and disables the UEFI watchdog timer.
   - **`target` & `config-recheck` (`FindTarget` / `GuCheckConfig` in `checks.c`)**: Enumerates `EFI_PCI_IO_PROTOCOL` handles across all root bridges, filtering candidates by full `Segment:Bus:Device.Function` (`GU_BOARD_SEGMENT`, `GU_BOARD_BUS`, `GU_BOARD_DEVICE`, `GU_BOARD_FUNCTION`), `GU_BOARD_ID`, and `GU_BOARD_SUBSYSTEM` before counting matches. Verifies PCI Express Capability FLR support (`PCI_EXP_DEVCAP_FLR`) and Power State `D0`.
   - **`display` & `ownership` (`DisplayCheck` / `ownership.c`)**: Snapshots all active `EFI_GRAPHICS_OUTPUT_PROTOCOL` (GOP) handles (including Intel/AMD iGPUs and secondary NVIDIA GPUs on non-target handles), records `InitialTargetMatched` active target display children, and supports both `requires_driver_release` (bound GOP driver) and `already_exclusive` (headless/unbound controller) ownership modes.
   - **`bar0` (`BarCheck`)**: Verifies that `BAR0` is a 16 MiB (`0x1000000`) non-translated MMIO aperture matching the PCI configuration registers.
   - **`cold-state` (`ColdCheck` & `GuClassifyColdState`)**: Verifies `PMC_BOOT_0` (`BAR0 + 0x0` == `GU_BOARD_CHIP` by default under `GU_ALLOW_ARCH_CHIP_FAMILY=0`), confirms GFW boot completion (`gpu_unlock_gfw_assess`), and classifies `(FEAT_PLM, SS0, SS1, WPR2_HI)` into `GU_COLD_OK`, `GU_COLD_ALREADY_MODIFIED`, `GU_COLD_PARTIALLY_MODIFIED`, `GU_COLD_INITIALIZED_WPR`, `GU_COLD_UNREADABLE`, or `GU_COLD_UNKNOWN_PROFILE_STATE`. Only `GU_COLD_OK` with `VRAM` (`0x1183a4`, or `0x100ce0` fallback on Turing) inside `[GU_VRAM_MIN_MIB..GU_VRAM_MAX_MIB]` proceeds.
   - **`prom` (`PromCheck` — Separated `OptionRomPolicy` + `PromPolicy` + `PreparedTransaction`)**:
     - Under `GU_UEFI_ROM_SHA256 = "AUTO"`, logs `PciIo->RomImage` / `RomSize` diagnostically without failing when the motherboard firmware omits or resizes the cached PCI Option ROM.
     - Reads `NV_PROM_DATA` (`BAR0 + 0x300000`, up to `1,048,576` bytes), validates the ROM expansion chain (`0xaa55` / `0x4e56` / `0xbb77`), `BIT` table checksum, `Falcon Ucode Descriptor` (`V3` RSA-3K on Ada/Ampere or `V2` AES-128 on Turing; `ucode_id = 9`, `engine_mask = 0x400`), live fuse version (`0x8241c0`), and `DMEMMAPPER v3` (`"DMAP"` signature `0x50414d44`), and performs a dry-run `gpu_unlock_fwsec_patch_frts` on a temporary RAM buffer **before** `DisconnectController`.
     - Latches the SHA-256 digest and byte length of the verified `FWSEC` span (`[0, fw.image_off + fw.image_size)`) so `unlock_transaction_fwsec()` can verify that the exact same bytes are consumed during execution.
   - **`assets` (`GuLoadAssets` in `app_io.c`)**: Loads all 5 pinned NVIDIA `610.43.03` firmware binaries from `\GPU-UNLOCK\ASSETS\` and verifies each file's exact byte size and SHA-256 hash.
   - **`windows-preload` (`PreloadWindows` in `handoff.inc`)**: Locates the Windows 10 / 11 EFI System Partition (`KOH_WINDOWS_ESP_GUID` and optional `KOH_WINDOWS_ESP_PART`) and preloads `\EFI\Microsoft\Boot\bootmgfw.efi` into memory via `LoadImage` before touching the GPU.

2. **Manual Confirmation (30-Second Window) & UEFI GOP Disconnect**:
   - By default (`KOH_UNATTENDED_AUTOFIRE = 0`, `KOH_AUTOCONFIRM_MS = 30000`), `Arm()` gives the user **30 seconds** to press **`U`**; if no key is pressed within 30 seconds (or if `Esc` is pressed), it returns `EFI_TIMEOUT` / `EFI_ABORTED` without disconnecting GOP or writing to the GPU.
   - Once confirmed, `BOOTX64.EFI` disconnects the UEFI GOP driver (`DisconnectController`), claims exclusive ownership of `EFI_PCI_IO_PROTOCOL`, restores memory/IO decode if cleared, and re-verifies `ConfigCheck`, `BarCheck`, `ColdCheck`, and `PromCheck`.

3. **Hardware Transaction (`unlock_610.c`)**:
   - **Layout Calculation (`unlock_transaction_layout`)**: Reads actual usable VRAM (`0x1183a4`, or `0x100ce0` fallback when `0x1183a4` is protected on Turing) and places the 1 MiB `FRTS` region and `WPR` metadata in the top 256 MiB of framebuffer memory.
   - **`FWSEC-FRTS` on GSP Falcon (`0x110000`)**: Verifies the live PROM span against the preflight-latched SHA-256 (`Gu.verify_prom_span`), stages `FWSEC` into DMA memory, patches the `FRTS` offset, copies the fuse-matched RSA-3K signature (for V3 descriptors), and launches GSP to initialize `WPR2`.
   - **`Booter` + `V67` Payload on SEC2 Falcon (`0x840000`)**:
     - **Ada Lovelace (`GU_ARCH_ADA == 1`)**: Publishes `v67-ad102-610.43.03-four-plm.bin` and launches `booter_load_ad102.bin` once on SEC2. Enforces the **3 required PLM gates** (`WPR_CFG` `0x1fa7cc` $\rightarrow$ `0xfffff0ff`, `WPR` `0x1fa7c4` $\rightarrow$ `0xffffffff`, and `FEAT_OVR_PLM` `0x823804` $\rightarrow$ `0xffffffff`; index 1 `FBPA` `0x9a0148` is logged diagnostically as non-fatal per upstream `KohakUnlock`), completion marker `0x67b00001` in `FALCON_MAILBOX0` (`0x840040`), `DEBUGINFO == 0xda550000`, and `CPUCTL.HALTED` (`work->sec2_halt_verified`).
     - **Ampere (`GU_ARCH_ADA == 0`, `GU_ARCH_TURING == 0`)**: Publishes `v67-ga102-610.43.03.bin` and launches `booter_load_ga102.bin` on SEC2. Verifies `FEAT_OVR_PLM == 0xffffffff` (`0x823804`) while keeping `work->quiesced = false` and retaining all DMA buffers until post-FLR reset completes.
     - **Turing (`GU_ARCH_TURING == 1`)**: Publishes `v67-tu102-610.43.03.bin` and launches `booter_load_tu102.bin` on SEC2. Verifies `WPR_CFG` (`0x1fa7cc == 0xfffff0ff`) and Turing `FEAT_OVR_PLM` (`0x409650 == 0xffffffff`), completion marker `0x67b00001`, and SEC2 halt.
   - **Stock Signature Restoration & Selector Writes**: Restores the stock `.fwsignature_ad10x` / `.fwsignature_ga10x` / `.fwsignature_tu10x` pointer in `WPR` metadata, then writes `0x88888888` to `SS0` (`0x82381c` on Ada/Ampere or `0x409664` on Turing) and `0x8` to `SS1` (`0x823820` on Ada/Ampere or `0x40966c` on Turing).
   - **`PCIe FLR` & Quiescence Verification (`unlock_transaction_reset`)**: Clears Bus Master Enable (`BME = 0`), triggers `PCIe FLR`, restores PCI BARs and command bits, waits for GFW boot completion and GSP halt, pulses and releases SEC2 engine reset (`0x8403c0`), and verifies `WPR2_HI == 0` and `SS0 == 0x88888888` / `SS1 == 0x8` before setting `work->quiesced = true` and freeing DMA buffers.

4. **UEFI GOP Reconnect & Windows Handoff (`RestoreDisplayForWindows`)**:
   - Releases exclusive protocol lock, calls `ConnectController` to rebind the UEFI GOP driver, verifies that `DisplayCheck()` recovers all `InitialTargetMatched` target displays, verifies `POST-GOP` selectors (`VerifySelectors`: checking `0x823818 == 0` on Ada and skipping the unverified `0x823818` read on Ampere and Turing), logs `HANDOFF_STATE stage=handoff_prepared` and `FINAL status=0x0 ...`, closes all file handles (`GuIoClose`), and calls `StartImage(WindowsImage)`.

## 2. Linux Kernel Module & RM Selector Architecture (`./Linux_Launch_UI.sh`)

On Linux, no USB flash drive or UEFI boot replacement is required:

1. **Multi-Source GPU Auto-Detection (`core_detector.py` + `linux_backend.py`)**:
   - Queries Linux kernel `sysfs` (`/sys/bus/pci/devices/<BDF>/{vendor,device,subsystem_vendor,subsystem_device,class,driver}`), filtering for PCI class `0x03xxxx` (VGA `0x0300` and 3D `0x0302` controllers while ignoring `.1` HDMI audio functions).
   - Cross-verifies with `lspci -Dnn`, `libnvidia-ml.so.1` (`NVML`), `nvidia-smi` CLI (normalizing 8-digit domains `00000000:01:00.0` to standard 4-digit kernel BDF `0000:01:00.0`), and `libcuda.so.1` (`sm_89` / `sm_86` / `sm_75`).
2. **Kernel Module (`kernel/gpu_unlock/main.c` & `unlock_610.c`)**:
   - Loads SHA-256 verified firmware assets from `/usr/lib/firmware/gpu-unlock/610.43.03/`, executes the identical `FWSEC-FRTS` $\rightarrow$ `Booter + V67` $\rightarrow$ `SS0 = 0x88888888 / SS1 = 0x8` $\rightarrow$ `pcie_flr()` transaction, and hands the card off cleanly with `WPR2_HI == 0` and `GSP` halted.
   - Experimental Ada and Turing targets require an explicit single PCI BDF address plus their family parameter (`ad103_experimental=1`, `ad104_experimental=1`, `ada_experimental=1`, or `turing_experimental=1`).
3. **Direct Hardware Selector Verification via `/dev/nvidiactl` (`tools/read_sm_rates.py`)**:
   - Issues `NV2080_CTRL_CMD_GR_GET_SM_ISSUE_RATE_MODIFIER` (`0x20801230`) directly to `/dev/nvidiactl` without mapping BARs or starting CUDA, reading back the 9 hardware rate modifiers (`fmla32 = 0` for unlocked full speed vs `1` for stock half speed).

## 3. Verification & Sanitizer Test Suites

- **Zero VBIOS Flash Modification**: The SPI flash controller (`NV_PMGR_ROM`) is never accessed on either OS. All writes target volatile MMIO registers and host RAM, resetting on cold power-off.
- **Windows UEFI Self-Test Suite (`windows/uefi/run_self_test.py`)**: Run `python3 windows/uefi/run_self_test.py` to execute all **43 core transaction scenarios** and **56 UEFI application/topology scenarios** under GCC `-fsanitize=address,undefined`.
- **Linux Kernel & Cross-Platform Test Suite (`tests/`)**: Run `python3 -m unittest discover -s tests -v` to execute all unit and C kernel tests (`test_main.c`, `test_ad102_kernel.c`, `test_unlock_adapter.c`, `test_prep_610.c`, `test_vbios_610.c`, `test_layout_610.c`, `test_gfw_eval.c`, `test_packaging.py`, `test_firmware.py`, `test_sm_rates.py`, `test_print_boot_option.py`, and `test_linux_integration.py`).
