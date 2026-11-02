# RTX 4090 Windows / UEFI Validation Reference

> **Reference Upstream Report**: AD102 Windows/UEFI validation report (sources: **[KohakuBlueleaf/KohakUnlock](https://github.com/KohakuBlueleaf/KohakUnlock)**, test bench: GeForce RTX 4090 `10de:2684` / `10de:167c`; canonical register-resident baseline figures from **[elias-gaeros/gpu-unlock](https://github.com/elias-gaeros/gpu-unlock)** in [`docs/rtx4090-register-report.md`](rtx4090-register-report.md)).

## Hardware Result

One RTX 4090 AD102 24 GiB, `10de:2684` / subsystem `10de:167c`, VBIOS
`95.02.18.80.EF`; ASUS Pro WS W890E-SAGE SE BIOS 0402, with two Intel Arc Pro B50s.
Windows NVIDIA 621.01, native CUDA 13.2, 450 W unchanged before/after.
`RUN03` completed one FWSEC/SEC2 transaction, required permission gates, selector
writes `SS0=0x88888888` / `SS1=8`, one FLR, cleanup, GOP reconnection and Windows
handoff. Effective speed readout remained zero after FLR and GOP reconnection.
FBPA was the known nonessential mismatch; all required gates passed.
No VBIOS flash, NVIDIA driver replacement or internal boot modification.

The EFI was locally signed, but this successful hardware boot had **Secure Boot
off**. Enabled Secure Boot is supported by policy/tests, not hardware-validated here.

## Canonical Before/After Instruction Rates (RTX 4090 `10de:2684`, 450 W)

Canonical register-resident Tensor Core and scalar instruction issue rates for
GeForce RTX 4090 (`10de:2684`, `AD102`, 128 SMs, 450 W power limit, matching the
NVIDIA Ada Architecture Whitepaper dense peak of `165.2 TF/s` Stock / `330.3 TF/s`
Full Rate and the verified samples in [`docs/evidence/rtx4090/`](evidence/rtx4090/README.md)):

| Instruction Mode | Accumulator | Stock (Locked) | Unlocked (`20k` iters) | Unlocked (`40k` iters) | Gain |
| :--- | :--- | ---: | ---: | ---: | ---: |
| **FP16 Tensor Core** | **FP32** (`FMLA32`) | 165.6 TF/s | **331.6 TF/s** | **330.8 TF/s** | **2.00x** |
| **BF16 Tensor Core** | **FP32** (`FMLA32`) | 165.5 TF/s | **330.6 TF/s** | **330.3 TF/s** | **2.00x** |
| **FP16 Tensor Core** | **FP16** (`FMLA16`) | 325.7 TF/s | 306.3 TF/s | 331.6 TF/s | **1.00x** |
| **INT8 Tensor Core** | **INT32** (`IMMA`) | 661.6 TOP/s | 661.4 TOP/s | 659.5 TOP/s | **1.00x** |
| **Integer `dp4a`** | **INT32** | 164.5 TOP/s | 164.4 TOP/s | 164.1 TOP/s | **1.00x** |
| **Scalar FP32 `ffma`** | **FP32** | 79.1 TF/s | 79.1 TF/s | 79.1 TF/s | **1.00x** |

These are dense register-resident instruction issue rates, not end-to-end GEMM,
game, or inference speedups. Finite outputs were checked; exhaustive numerical
correctness, endurance, and sleep/resume require workload-specific validation.

## MAMF Finder Application GEMM

Unlocked RTX 4090 FP16 MAMF Finder (reported by `KohakuBlueleaf/KohakUnlock`):
**243.9 TFLOPS best median** at `4096x5120x2048`; best peak `250.4 TFLOPS`, best
mean `224.2 TFLOPS`. Original measurement loop: 50 warmup + 100 measured
iterations, 125 shapes, `M/N/K` each `2048..6144` step `1024`. WSL2, PyTorch
`2.14.1+cu130`.

| Before | After (best median) |
|---:|---:|
| ~160 TFLOPS | 243.9 TFLOPS |

## Original `mmapeak` Zero-Input Issue

[ReinForce-II/mmapeak](https://github.com/ReinForce-II/mmapeak) uses compile-time
all-zero fragments. In inspected CUDA 13.2 / SM120a SASS, identical FP16/BF16 tile
computations were collapsed while FLOP accounting still counted the full tile.
That inflated results. This is a compiler/counting problem, not proof that zero
data intrinsically doubles hardware throughput, nor that every kernel/compiler
behaves identically.

The [KohakuBlueleaf/mmapeak](https://github.com/KohakuBlueleaf/mmapeak) fork uses
runtime-randomized bounded inputs and nonzero scales, correct packed formats,
unique output storage and explicit scalar FMA chains. It also removes redundant
post-MMA barriers and uses an SM-scaled launch. In **GPU-Tensor-Unlock-Universal**,
[`tensor_benchmark.py`](../tensor_benchmark.py) applies the same runtime-randomized
input principle with finite IEEE-754 accumulator verification.

## Source and Deployment Model

[`windows/uefi/`](../windows/uefi) contains the UEFI C source, offline sanitizer
tests, and retained notices.

Execution flow:
`UEFI USB -> identify/verify ROM and ownership -> preload Windows -> manual U -> release target GOP -> firmware transaction -> selectors -> FLR -> cleanup -> GOP reconnect -> Windows directly`, without a system reboot between stages.

The workstation exposed 317 PCI handles and four target display children with
only one active framebuffer. The port scans the complete UEFI handle buffer,
validates inactive-child ancestry/ownership without requiring a framebuffer,
checks all children and collects independent preflight results. Independent Intel
GOP identities/state remain checked. Actual integrity/ownership/execution faults
still block mutation or handoff; an inactive display alone does not.

FAT32 USB layout: `EFI/Boot/BOOTX64.EFI` and `GPU-UNLOCK/ASSETS/`.
Keep stock Windows Boot Manager as default. Cold-start, select USB manually, press
`U` once within 30 seconds at `READY`. Failure recovery: full power-off and boot
Windows without USB.

A USB-less layout is also supported: the EFI on the Windows ESP with the
work tree on a separate FAT32 payload partition. Identify that partition by
its GPT GUID, never by its index: partition numbers are not stable. On the
tested upstream workstation `diskpart` renumbered the payload from the planned
partition 5 to partition 4 after the `C:` shrink, and a run pinned to the stale
number failed (measured 2026-10-26). The GUID is unique and authoritative; the
index is a wildcard.

For Secure Boot enabled, sign a reviewed local EFI and append its public cert to
firmware `db` (not shim MOK), preserving existing keys. The app does not enroll keys
or override authentication. Cryptographic signing is not proof of firmware trust.

## References and Licenses

- [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker), `51df9c17ec89eb8486df52cc9079dde4bd1f9974`: immediate UEFI source and Ada payload research.
- [elias-gaeros/gpu-unlock](https://github.com/elias-gaeros/gpu-unlock), `4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc`: AD102 Linux integration and RTX 4090 baseline report.
- [JustAResearcher/gpu-unlock-ada](https://github.com/JustAResearcher/gpu-unlock-ada), `4e7fefcc4923f9e083d5324dc75a7d2f906af77f`: AD103 evidence and pinned firmware generators.
- [KohakuBlueleaf/KohakUnlock](https://github.com/KohakuBlueleaf/KohakUnlock) & [KohakuBlueleaf/mmapeak](https://github.com/KohakuBlueleaf/mmapeak): UEFI pre-flight hardening and randomized benchmark methodology.
- [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock): underlying transaction lineage.
- [impacifist/Windows-GPU-UNLOCK](https://github.com/impacifist/Windows-GPU-UNLOCK): UEFI/Windows handoff reference.
- [Goldlionren/gpu-unlock-4080s](https://github.com/Goldlionren/gpu-unlock-4080s): local signing/`db` enrollment reference.
- [NVIDIA open GPU kernel modules](https://github.com/NVIDIA/open-gpu-kernel-modules): firmware/interfaces.

GPL-derived UEFI code: GPL-2.0-only. EDK2 and per-file NVIDIA/MIT notices retain
their terms. Firmware is separately licensed and excluded. No upstream TOTORONG
CC-BY-NC narrative documents or disassembly excerpts are copied. See the retained
[`LICENSE`](../LICENSE) and [`NOTICE.md`](../NOTICE.md).
