# GeForce RTX 4070 Ti (AD104, 10de:2782) Validation Report & Universal Console

This report documents hardware-validated Ada Lovelace support for
**NVIDIA GeForce RTX 4070 Ti (`10de:2782`, AD104, 60 SMs, 12 GiB GDDR6X)**
alongside support for RTX 4090 (`10de:2684`, AD102), RTX 4070 Ti SUPER
(`10de:2705`, AD103), Ampere (`GA10x`), and Turing (`TU10x`) cards, together
with the native Windows 10/11 (`Windows_Launch_UI.bat`) and Linux
(`Linux_Launch_UI.sh`) desktop consoles.

## Architectural Basis

1. **Shared AD102-Family Booter & GSP Boot Assets**:
   In NVIDIA's `610.43.03` open kernel module HAL (`ChipHal`), `AD104` routes to
   the exact same `kgspGetBinArchiveBooterLoadUcode_AD102` (`booter_load_ad102.bin`,
   56,832 bytes, `patch_loc = 32,272`) and `kgspGetBinArchiveGspRmBoot_AD102`
   (`gsp_boot_ad102.bin`, 36,864 bytes) archives as `AD102` and `AD103`, using the
   shared `.fwsignature_ad10x` section in `gsp_ga10x.bin`.
2. **Identical SEC2 DMEM Stack & Four-PLM V67 Payload**:
   Because `SEC2` authenticates and decrypts the identical `AD102` production
   booter image on `AD104`, the call frame at the signature DMA transfer
   (`SP = 0xFF30`, saved canary `0xFF4C`, return slot `0xFF50`, global canary
   `0x5F50`) and the four-PLM ROP gadget chain (`v67-ad102-610.43.03-four-plm.bin`,
   SHA-256 `44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb`)
   operate without modification.
3. **12 GiB GDDR6X WPR2 Layout Verification**:
   On 12 GiB `AD104` boards (`usable_fb ≈ 0x2ff400000`), `gpu_unlock_layout()`
   places `FRTS` (`1 MiB`), `GSP boot`, `GSP image`, `88 MiB heap`, `WPR meta`,
   and `non-WPR` entirely within the top 256 MiB pre-scrubbed region.

## Kernel Parameters & Safety Gates

Like the `AD103` (`10de:2705`) target, the `AD104` (`10de:2782`) Linux kernel
path is strictly opt-in and never triggered by `gpu_unlock.targets=all` or
multi-card lists. To enable it for a single card at boot on Linux:

```text
gpu_unlock.targets=0000:01:00.0 gpu_unlock.ad104_experimental=1
```

Replace `0000:01:00.0` with the exact PCI address printed by
`python3 tools/print_boot_option.py` or `lspci -Dnn | grep -i nvidia`. On
Windows 10/11, `Windows_Launch_UI.bat` automatically detects the board and
compiles a profile-locked `BOOTX64.EFI` USB loader.

## Measured Performance & Verification Gates

Hardware validation was performed by the repository author (**MindAllik**) on the
following test bench:

- **Board**: Palit GeForce RTX 4070 Ti (`PCI ID 10de:2782`, `Subsystem ID 1569:f294`, `AD104`, 60 SMs, 12 GiB GDDR6X, VBIOS `95.04.31.00.36`).
- **Environment**: Windows 11 x64 (`BOOTX64.EFI` pre-boot via FAT32 USB), 300 W power limit.
- **Register gates**: `SEC2_MAILBOX0 = 0x67b00001`, `SEC2_CPUCTL = 0x10` (HALT),
  `WPR_CFG PLM = 0xfffff0ff`, `WPR PLM = 0xffffffff`, `FEAT_OVR_PLM = 0xffffffff`,
  `SS0 = 0x88888888`, `SS1 = 0x8`, and `FEAT_READOUT_1 = 0x00000000` both before
  and after PCIe FLR.
- **Measured Throughput (`tensor_benchmark.py` register-resident PTX `mma.sync`)**:
  - `FP16 -> FP16` (`FMLA16` control): **172.8 TF/s**
  - `FP16 -> FP32` (`FMLA32`): **86.4 TF/s** (Stock) $\rightarrow$ **172.8 TF/s** (Unlocked, **2.00x**)
  - `BF16 -> FP32` (`FMLA32`): **172.7 TF/s** (Unlocked, **2.00x**)
