# Ada Lovelace Linux Port Status

> **Attribution**: Summary of the Linux kernel module integration for the AD102-family four-PLM payload from **[elias-gaeros/gpu-unlock](https://github.com/elias-gaeros/gpu-unlock)** (commit `4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc`) and **[JustAResearcher/gpu-unlock-ada](https://github.com/JustAResearcher/gpu-unlock-ada)** (commit `4e7fefcc4923f9e083d5324dc75a7d2f906af77f`), building on **[TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)** (revision `51df9c17ec89eb8486df52cc9079dde4bd1f9974`).

This module integrates the published AD102-family four-PLM payload and Linux
transaction flow. Upstream forks reported physical RTX 4090 (`10de:2684`) and
RTX 4070 Ti SUPER (`10de:2705`) validation results (see
[`rtx4090-register-report.md`](rtx4090-register-report.md) and
[`ada-2705-report.md`](ada-2705-report.md)), and the repository author
(**MindAllik**) validated RTX 4070 Ti (`10de:2782`, `AD104`) on Windows 11 UEFI
(see [`rtx4070ti-report.md`](rtx4070ti-report.md)).

## Verified Integration Milestones

- NVIDIA's pinned AD102 archive is extracted and checked independently of the
  Ampere archive. Its production Booter image is 56,832 bytes, with data at
  32,256 and its signature patch at 32,272. The matching GSP boot image is
  36,864 bytes.
- `firmware/ada-610.43.03.json` pins both source files, the three stock Ada
  assets, the shared GSP, and the published four-PLM payload. The pinned GSP
  contains an Ada signature section at offset 84,267,118 with size 4,096,
  distinct from GA10x. The generated payload SHA-256 is
  `44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb`.
- The kernel carries separate GA10x and AD10x asset profiles: Booter file,
  exact geometry, GSP signature section, GSP boot image size, and payload.
  RTX 4090 `10de:2684` is selected by the standard allowlist; `AD103` (`10de:2705`),
  `AD104` (`10de:2782`), and other Ada IDs require their family opt-in flag plus
  a single exact PCI BDF address and are never selected by `targets=all`.
- The standard firmware build and locally built packages include the three pinned
  stock Ada files, the shared GSP, and the four-PLM Ada V67 image. The install
  test checks their SHA-256 hashes.
- DMA cleanup uses the validated Booter allocation length rather than an
  Ampere constant. The DRM aperture helper provides build compatibility across
  Linux kernels from 5.15 through 6.x+.

## Physical Ada RM Issue-Rate Baseline

The read-only RM getter in `tools/read_sm_rates.py` was verified on the
RTX 4070 Ti SUPER canary (`10de:2705`, driver `580.178.04`). On stock boot,
it reported:

| Field | Encoding |
| --- | ---: |
| FMLA32 | 1 (half rate) |
| IMLA2 | 1 (half rate) |
| IMLA4 | 1 (half rate) |
| IMLA0, FMLA16, DP, FFMA, IMLA1, IMLA3 | 0 (full rate) |

The query does not map BARs, write GPU registers, submit firmware, reset
the GPU, create a CUDA context, or execute a GPU kernel. It creates temporary
RM client/device/subdevice handles and closes the file descriptors on exit.

## Qualification Scope

The published four-PLM chain reproduces its pinned SHA-256 hash deterministically
in `firmware/generate_v67.py` and `core_detector.py` (`build_v67_payload`).
The `10de:2705` canary used a target-kernel build, full AC cold power, and exact
readback gates for marker `0x67b00001`, `SEC2 HALT`, required permissions,
selectors `SS0=0x88888888` / `SS1=0x8`, and effective rate `0`. The
[canary report](ada-2705-report.md) records stock-driver handoff, output
equality, and matched-binary throughput. Further cards need independent gates.

## Reproduce Stock Extraction and Host Checks

Use NVIDIA `open-gpu-kernel-modules` revision `610.43.03`
(`452cec62d827034798072827d3866d1881662b77`). Keep downloaded NVIDIA source and
derived binary assets outside Git and preserve their notices:

```sh
python3 firmware/extract_boot_assets.py /path/to/nvidia-source /tmp/ada-assets --chip ad102
GPU_UNLOCK_NVIDIA_SOURCE=/path/to/nvidia-source make test
python3 tools/read_sm_rates.py --expect-uuid GPU-EXACT-UUID
```

The last command requires the Linux NVIDIA driver and a GPU matching the
specified UUID. It is optional and not part of the offline tests. The standard
installation targets generate both pinned Ampere and Ada assets locally and
do not ship NVIDIA firmware binaries in the source archive.
