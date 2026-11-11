# GPU-Tensor-Unlock-Universal: Quick Start Guide

This guide covers both supported operating systems and execution modes in **GPU-Tensor-Unlock-Universal**:

1. **Windows 10 / 11 (`Windows_Launch_UI.bat` — Pre-Boot UEFI Application)**:
   Builds a board-matched `BOOTX64.EFI` loader onto a **FAT32** USB flash drive with automatic Windows EFI System Partition (ESP) GUID detection and a **30-second** manual confirmation prompt (`Press U`). The UEFI loader validates VBIOS `PROM` integrity before disconnecting UEFI GOP, executes `FWSEC-FRTS` and `SEC2 Booter + V67`, applies `SS0 = 0x88888888` / `SS1 = 0x8`, performs `PCIe FLR`, reconnects GOP, and hands control directly to Windows Boot Manager (`bootmgfw.efi`).
2. **Linux (`./Linux_Launch_UI.sh` & `make install` — Pre-Driver Kernel Module `gpu_unlock.ko`)**:
   Builds SHA-256 verified `610.43.03` firmware assets and installs `gpu_unlock.ko` via **DKMS** and an **early-boot initramfs hook** (`mkinitcpio`, `dracut`, or `initramfs-tools`) so the unlock transaction runs before `nvidia.ko` binds to the primary GPU. For secondary compute GPUs that are not bound to any host driver (`bound_driver = unbound`), the module can also be triggered live via `modprobe gpu_unlock`.

All register overrides are volatile and reside in GPU MMIO space until the next cold power-off. The SPI flash ROM (`NV_PMGR_ROM`) is never modified.

## 1. Quick Start on Windows 10 / 11 (`Windows_Launch_UI.bat`)

1. **Clone the repository and launch the Windows console**:
   ```powershell
   git clone https://github.com/MindAllik/GPU-Tensor-Unlock-Universal.git
   cd GPU-Tensor-Unlock-Universal
   .\Windows_Launch_UI.bat
   ```
2. **Verify hardware and build toolchain**:
   - In Section `[01]`, click **`RUN LIVE CLI VERIFICATION (SHOW RAW NUMBERS)`** to inspect the raw `nvidia-smi` and `pci.sys` hardware queries and confirm your card's `PCI ID`, `Subsystem ID`, `PCI BDF`, and `PMC_BOOT_0` profile lock.
   - In Section `[02]`, verify that **LLVM (`clang` / `lld-link`)** and **Python `zstandard`** are installed. If either is missing, click **`INSTALL MISSING DEPENDENCIES (LLVM + ZSTD)`**.
3. **Record your stock baseline**:
   - In Section `[04]`, click **`RUN LIVE TENSOR BENCHMARK`**, wait for the PTX kernels to finish, and click **`SAVE AS 'BEFORE' (STOCK)`**.
4. **Build and write the bootable FAT32 USB drive**:
   - Insert a **FAT32**-formatted USB flash drive, select it in Section `[03]`, and click **`>> BUILD & WRITE BOOTABLE USB <<`**.
   - The builder downloads and SHA-256 verifies the pinned `610.43.03` firmware inputs (caching them locally in `~/.cache/gpu-tensor-unlock`), compiles `BOOTX64.EFI` for your exact board profile, and writes `EFI/Boot/BOOTX64.EFI` and `GPU-UNLOCK/ASSETS/` to the USB drive.
5. **Prepare BitLocker and Secure Boot**:
   - If BitLocker is enabled on `C:`, suspend protection for one reboot from an Administrator PowerShell prompt before changing BIOS settings:
     ```powershell
     Suspend-BitLocker -MountPoint "C:" -RebootCount 1
     ```
   - Disable **Secure Boot** in your motherboard BIOS, or sign `BOOTX64.EFI` with a local key and enroll its public certificate in the UEFI `db` signature database.
6. **Cold shutdown and USB pre-boot execution**:
   - Click **`GRACEFUL COLD SHUTDOWN FOR USB BOOT`** (`shutdown /s /t 5`) and wait 5–10 seconds after the system powers off completely.
   - Power on the PC, open the BIOS One-Time Boot Menu (`F11` / `F12` / `F8`), and boot from the USB flash drive.
   - At the `BOOTX64.EFI` prompt, press **`U`** once within **30 seconds**. The loader executes the pre-driver unlock transaction, reconnects the display, writes `GPU-UNLOCK/RUNxx/REPORT.TXT`, and boots directly into Windows 10/11.
7. **Verify the unlock and measure the speedup**:
   - Launch **`Windows_Launch_UI.bat`**, click **`READ USB REPORT.TXT`** in Section `[03]` to inspect the stage-by-stage register readbacks (`SS0=0x88888888`, `SS1=0x8`), and run **`RUN LIVE TENSOR BENCHMARK`** $\rightarrow$ **`SAVE AS 'AFTER' (UNLOCKED)`** to confirm the `2.00x` `FMLA32` throughput gain.

## 2. Quick Start on Linux (`./Linux_Launch_UI.sh` and CLI `make install`)

### Option A: Desktop GUI Console (`./Linux_Launch_UI.sh`)

1. Clone the repository and launch the graphical console:
   ```sh
   git clone https://github.com/MindAllik/GPU-Tensor-Unlock-Universal.git
   cd GPU-Tensor-Unlock-Universal
   ./Linux_Launch_UI.sh
   ```
2. In Section `[02]`, click **`INSTALL BUILD DEPENDENCIES (LINUX-HEADERS + DKMS + ZSTD)`** if kernel headers, DKMS, or `zstd` are missing.
3. In Section `[03]`, click **`>> BUILD & APPLY UNLOCK NOW (MODPROBE GPU_UNLOCK) <<`**:
   - **Unbound secondary GPU (`bound_driver = unbound`)**: Compiles and loads `gpu_unlock.ko` immediately via `modprobe` and unlocks the card without rebooting.
   - **Primary display GPU (`bound_driver = nvidia`)**: Because `kernel/gpu_unlock/main.c` refuses to touch a PCI device while `nvidia.ko` is already bound (`-EBUSY`), the console automatically stages the DKMS module, firmware assets, and early-boot `initramfs` hook, and prints the exact kernel command-line parameter to add to your bootloader for the next cold boot.

### Option B: Terminal CLI Build (`make install`)

1. Install your distribution's kernel headers, C compiler (`gcc`/`clang`), `dkms`, `python3`, and `zstd`, then run:
   ```sh
   git clone https://github.com/MindAllik/GPU-Tensor-Unlock-Universal.git
   cd GPU-Tensor-Unlock-Universal
   make install
   ```
   `make install` selects the native package path for Debian/Ubuntu (`make install-deb`), Arch Linux (`make install-arch`), or Fedora/RHEL (`make install-rpm`), downloads the SHA-256 pinned `610.43.03` inputs, generates the firmware locally, and registers the DKMS module and `initramfs` hook.
2. **Determine your exact kernel boot parameter**:
   Run `python3 tools/print_boot_option.py` or `lspci -Dnn | grep -i nvidia` to find your GPU's full PCI address (for example `0000:01:00.0`) and PCI ID:
   - **GeForce RTX 4090 (`10de:2684`, `AD102`) and supported RTX 30-series (`GA102`–`GA106`)**:
     ```text
     gpu_unlock.targets=0000:01:00.0
     ```
     *(On Ampere-only setups, `gpu_unlock.targets=all` is also accepted; never use `targets=all` for Ada or Turing cards.)*
   - **GeForce RTX 4070 Ti (`10de:2782`, `AD104`)**:
     ```text
     gpu_unlock.targets=0000:01:00.0 gpu_unlock.ad104_experimental=1
     ```
   - **GeForce RTX 4070 Ti SUPER (`10de:2705`, `AD103`)**:
     ```text
     gpu_unlock.targets=0000:01:00.0 gpu_unlock.ad103_experimental=1
     ```
   - **Other experimental desktop Ada chips (`AD102`/`AD106`/`AD107`)**:
     ```text
     gpu_unlock.targets=0000:01:00.0 gpu_unlock.ada_experimental=1
     ```
   - **Experimental desktop Turing (`TU102`/`TU104`/`TU106` — RTX 20-series / TITAN RTX / CMP 40HX / CMP 50HX)**:
     ```text
     gpu_unlock.targets=0000:01:00.0 gpu_unlock.turing_experimental=1
     ```
   *Note: Hardware-validated `AD104` (`10de:2782`), `AD103` (`10de:2705`), and experimental Turing targets intentionally retain the single-BDF requirement and `ad104_experimental=1` / `ad103_experimental=1` / `turing_experimental=1` module flags in `gpu_unlock.ko` so a wildcard `targets=all` configuration on a multi-GPU host cannot accidentally trigger an Ada or Turing transaction on an unintended card.*
3. **Add the parameter to your bootloader and perform a cold power-off**:
   - **Debian / Ubuntu (GRUB2)**: Append the options to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`, then run `sudo update-grub`.
   - **Arch Linux (GRUB2)**: Append the options to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`, then run `sudo grub-mkconfig -o /boot/grub/grub.cfg`.
   - **Fedora / RHEL (`grubby`)**: Run `sudo grubby --update-kernel=ALL --args="gpu_unlock.targets=0000:01:00.0 ..."`.
   - **systemd-boot**: Append the options to the `options` line of your active loader entry in `/boot/loader/entries/*.conf` (keeping a separate stock fallback entry).
   - Shut down the PC, cut AC power for 15–30 seconds, power on, and verify the unlock after login:
     ```sh
     journalctl -k -b --no-pager | grep -E 'gpu_unlock: unlocked|gpu_unlock: unlock failed|post-FLR SEC2'
     python3 tools/read_sm_rates.py --expect-uuid <GPU_UUID>
     ```

## 3. Laptop / Mobile GPU Notes (MUX / Optimus & Linux Runtime D3)

- **Windows 10 / 11 UEFI (`BOOTX64.EFI`)**:
  - Supports both MUXed (`dGPU-only` / `Ultimate` mode, PCI class `0x0300`) and MUXless / Advanced Optimus laptops (`3D controller`, PCI class `0x0302`, `targetGops == 0`).
  - Automatically wakes the dGPU from `D1..D3hot` to `D0`, enables PCI Memory Space Decode (`PCI_COMMAND |= 0x0002`), and enables Upstream PCI-to-PCI Root Port Bus Master (`GuEnsureUpstreamBridgeMaster`) during the SEC2/GSP DMA transaction.
  - If your laptop BIOS powers off the dGPU rail (`D3cold`, `BAR0 = 0xffffffff`) or skips VBIOS OptionROM pre-initialization (`GFW_PLM` closed) in hybrid mode, switch the laptop MUX to **dGPU / Ultimate mode** in BIOS or OEM software (or connect an external monitor to the dGPU port) and cold-boot.
- **Linux (`gpu_unlock.ko`)**:
  - Disable NVIDIA Runtime D3 (`RTD3`) so the driver does not power off the dGPU into `D3cold` after ~15 seconds of idle and reset `SS0`/`SS1` back to stock half-rate:
    ```sh
    echo "options nvidia NVreg_DynamicPowerManagement=0x00" | sudo tee /etc/modprobe.d/nvidia-runtimepm.conf
    ```
  - Rebuild your `initramfs` (`sudo mkinitcpio -P`, `sudo update-initramfs -u`, or `sudo dracut --regenerate-all --force`) and perform a cold power-off.

## 4. Rollback

- **Windows 10 / 11**: Shut down the PC (cold power-off), remove the USB flash drive, and boot normally from your system SSD. All GPU registers return to factory defaults on power-off. Re-enable Secure Boot and BitLocker if you disabled or suspended them.
- **Linux**: Remove the `gpu_unlock.*` parameters from your bootloader configuration (`GRUB2`, `grubby`, or `systemd-boot`), update the bootloader config, and perform a cold power-off. If a firmware transaction failed and retained DMA pages (`retained=true`), perform a full AC power-off rather than attempting to force-unload `gpu_unlock.ko`.

For architecture details, safety gates, and provenance, see [`docs/ARCHITECTURE_AND_SAFETY.md`](docs/ARCHITECTURE_AND_SAFETY.md), [`docs/SAFETY.md`](docs/SAFETY.md), [`NOTICE.md`](NOTICE.md), and [`firmware/NOTICE.md`](firmware/NOTICE.md).
