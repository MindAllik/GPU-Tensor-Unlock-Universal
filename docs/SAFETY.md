# Safety Architecture and Operational Boundaries

This project executes privileged pre-driver GPU firmware transactions (`FWSEC-FRTS` on GSP Falcon and `Booter + V67` on SEC2 Falcon) to modify volatile `FMLA32` speed-select registers before the operating system display driver binds. No warranty or guarantee of hardware suitability is made. Always test with verified backups, no critical active workloads, and physical access to AC power control.

## 1. Explicit Opt-In and Target Selection Gates

- **Linux (`kernel/gpu_unlock/main.c`)**:
  - Loading `gpu_unlock.ko` without parameters performs no hardware access (`targets=` is empty by default).
  - Standard allowlisted targets (`RTX 4090` `10de:2684` and supported `GA102`–`GA106` Ampere IDs) require an explicit `gpu_unlock.targets=<PCI_BDF>` parameter (or `targets=all` for Ampere).
  - Guarded Ada Lovelace and Turing families require both a single explicit `Segment:Bus:Device.Function` (`BDF`) address and their family opt-in flag (`gpu_unlock.ad103_experimental=1` for `AD103`, `gpu_unlock.ad104_experimental=1` for `AD104`, `gpu_unlock.ada_experimental=1` for other desktop Ada chips, or `gpu_unlock.turing_experimental=1` for `TU102`/`TU104`/`TU106`). Multi-card lists and `targets=all` are rejected for experimental Ada and Turing flags.
- **Windows 10 / 11 UEFI (`windows/uefi/source/unlock/app.c`)**:
  - `BOOTX64.EFI` is compiled against the exact board profile (`PCI Device ID`, `Subsystem ID`, `Segment:Bus:Device.Function`, `Silicon Die / PMC_BOOT_0`, and `VRAM` bounds) locked in `local_profile.h`.
  - Unattended execution is disabled by default (`KOH_UNATTENDED_AUTOFIRE = 0`). At boot, `Arm()` enforces a **30-second** manual confirmation window (`KOH_AUTOCONFIRM_MS = 30000`): if the user does not press **`U`** within 30 seconds (or presses `Esc`), the loader aborts cleanly without disconnecting UEFI GOP or touching GPU registers.

## 2. Pre-Flight Integrity Checks (`-EBUSY` and Two-Phase `PromCheck`)

- **Refusal on Driver-Bound GPUs (Linux)**:
  - In `kernel/gpu_unlock/main.c` (`unlock_one`), the module locks the PCI device (`pci_dev_lock`) and checks `pdev->driver`. If `nvidia`, `nouveau`, `vfio-pci`, or any other driver is already bound, `gpu_unlock` immediately returns `-EBUSY` without mapping `BAR0` or mutating state.
- **Pre-Flight VBIOS `PROM` Validation Before GOP Disconnect (Windows UEFI)**:
  - Before calling `DisconnectController` on the UEFI display handle, `PromCheck()` reads `NV_PROM_DATA` (`BAR0 + 0x300000`, up to 1 MiB) and verifies the PCI ROM expansion headers (`0xaa55`, `0x4e56`), `BIT` table checksum, `Falcon Ucode Descriptor` (`V3` RSA-3K on Ada/Ampere or `V2` AES-128 on Turing; `ucode_id = 9`, `engine_mask = 0x400`), live fuse version (`0x008241c0`), and `DMEMMAPPER v3` (`"DMAP"` signature `0x50414d44`), followed by a dry-run `FRTS` patch in host RAM.
  - The SHA-256 hash of the verified `FWSEC` span is latched during pre-flight and re-verified before Bus Master is enabled.
- **Cold-State Gate (`GuClassifyColdState`)**:
  - Execution proceeds only when the GPU is in a verified cold state (`WPR2_HI == 0`, `FEAT_OVR_PLM == 0xffffff8f`, and `GFW_BOOT` complete). Already-initialized or partially mutated states are rejected.

## 3. Fail-Closed DMA Memory Containment (`retained` Lifecycle)

- Once Bus Master is enabled or microcode starts on GSP/SEC2 (`work->firmware_started = true`), the transaction must reach verified post-FLR quiescence (`work->quiesced = true`, confirmed by `WPR2_HI == 0`, GSP halted, SEC2 reset released, and `SS0 == 0x88888888` / `SS1 == 0x8`) before host DMA pages can be freed.
- **Clean Completion (`work->retained == false`)**:
  - When post-FLR quiescence is confirmed, Bus Master Enable is cleared (`BME = 0`), all DMA allocations are unmapped and freed, and on Linux `gpu_unlock.ko` can be unloaded normally via `rmmod gpu_unlock` (`module_exit(gpu_unlock_exit)` in `main.c`).
- **Containment on Fault (`work->retained == true`)**:
  - If any stage after microcode start fails or times out before post-FLR quiescence is verified, the cleanup path immediately clears `PCI_COMMAND_MASTER` (`BME = 0`), sets `work->retained = true`, and intentionally keeps all DMA pages pinned in RAM (and holds a module reference on Linux via `try_module_get(THIS_MODULE)`) so the GPU can never DMA into freed or reallocated host memory.
  - If a transaction enters the `retained` state, **do not force-unload the kernel module**. Perform a full AC power-off (15–30 seconds) to reset the GPU hardware state completely.

## 4. Zero VBIOS Flash Modification & System Recovery Recommendations

- **No Non-Volatile Writes**: Neither `BOOTX64.EFI` nor `gpu_unlock.ko` accesses the SPI flash controller (`NV_PMGR_ROM`). All modifications occur in volatile MMIO registers and host RAM and are cleared on cold power-off.
- **Bootloader & BitLocker Precautions**:
  - On Windows 10/11, always keep the standard Windows Boot Manager on your internal SSD as the primary BIOS boot option, using the FAT32 USB drive via the one-time BIOS Boot Menu. Suspend BitLocker (`Suspend-BitLocker -MountPoint "C:" -RebootCount 1`) or verify your 48-digit recovery key before changing Secure Boot settings.
  - On Linux, always preserve a stock bootloader entry without `gpu_unlock.*` parameters so you can boot normally from the boot menu if needed.
