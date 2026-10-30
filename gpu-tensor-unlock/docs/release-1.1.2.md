# GPU Unlock 1.1.2 — RTX 4070 Ti (AD104, 10de:2782) support

This release adds an experimental, exact-device Ada Lovelace path for
**NVIDIA GeForce RTX 4070 Ti (`10de:2782`, AD104, 60 SMs, 12 GB GDDR6X)**
alongside existing support for RTX 4090 (`10de:2684`, AD102), RTX 4070 Ti SUPER
(`10de:2705`, AD103), and legacy Ampere (GA10x) cards.

## Architectural Basis

1. **Shared AD102-family Booter & GSP Boot Assets**:
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
   On 12 GB `AD104` boards (`usable_fb ≈ 0x2ff400000`), `gpu_unlock_layout()`
   places `FRTS` (`1 MiB`), `GSP boot`, `GSP image`, `88 MiB heap`, `WPR meta`,
   and `non-WPR` entirely within the top 256 MiB pre-scrubbed region.

## Kernel Parameters & Safety Gates

Like the `AD103` (`10de:2705`) target, the `AD104` (`10de:2782`) path is
strictly opt-in and never triggered by `gpu_unlock.targets=all` or multi-card
lists. To enable it for a single card at boot:

```text
gpu_unlock.targets=0000:01:00.0 gpu_unlock.ad104_experimental=1
```

Replace `0000:01:00.0` with the exact PCI address printed by
`python3 tools/print_boot_option.py` or `lspci -Dnn | grep -i nvidia`.

## Expected Performance & Verification Gates

- **Register gates**: `SEC2_MAILBOX0 = 0x67b00001`, `SEC2_CPUCTL = 0x10` (HALT),
  `WPR_CFG PLM = 0xfffff0ff`, `WPR PLM = 0xffffffff`, `FEAT_OVR_PLM = 0xffffffff`,
  `SS0 = 0x88888888`, `SS1 = 0x8`, and `FEAT_READOUT_1 = 0x00000000` both before
  and after PCIe FLR.
- **Throughput**: Full-rate `FMLA32` (`0`), doubling register-resident FP16/BF16/TF32
  with FP32 accumulation issue rates (~83.5–91.2 TF/s stock → ~167–182 TF/s
  unlocked depending on boost clock) and ~83–84% speedup on dense `8192³` cuBLAS
  FP16/BF16 (`CUBLAS_COMPUTE_32F`) GEMM under the stock 285 W TGP limit.
