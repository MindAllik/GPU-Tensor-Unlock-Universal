# Windows UEFI Pre-Boot Application (`windows/uefi/`)

GPL-2.0-only UEFI application derived from `TOTORONG/AD103_win_unlocker`
(revision `51df9c17ec89eb8486df52cc9079dde4bd1f9974`) and
`KohakuBlueleaf/KohakUnlock`. Component licenses are retained in
`source/LICENSES` and `source/deps/edk2/License.txt`; upstream notices accompany it.

Supports automatic board profile generation from `Windows_Launch_UI.bat`
(`core_detector.py`) as well as standalone command-line builds for Ada Lovelace
(`AD10x`) and Ampere (`GA10x`). Adaptations cover workstation enumeration/BARs,
inactive GOP children, full preflight logging, two-phase `PromCheck` before GOP
disconnect, strict selectors and effective readout, and Secure Boot policy.

## Build

Python 3, `clang`, `lld-link`:

```sh
python3 build.py --clang /path/to/clang --linker /path/to/lld-link
```

Default standalone EFI returns `EFI_UNSUPPORTED` before hardware access. For an
execution build, `Windows_Launch_UI.bat` (or manual editing of
`source/unlock/local_profile.h` and `source/unlock/prom_profile.h`) supplies the
board profile and Windows ESP GUID initializer and invokes `build.py --enable-experiment`.
Output: `source/build/BOOTX64.EFI`. Firmware hashes and names are pinned in `app_io.c`.

Offline sanitizer self-test suite (`43` core transaction scenarios + `63` UEFI
application/topology scenarios under `gcc -fsanitize=address,undefined`):

```sh
python3 run_self_test.py
```

CPU-only private-fixture runner:

```sh
python3 test_host.py --prom /private/normalized-prom.bin --assets /private/assets --pci-config /private/pci-config.bin
```

[Results](../../docs/ADA-WINDOWS.md) · [Architecture & Safety](../../docs/ARCHITECTURE_AND_SAFETY.md) · [Provenance](../../NOTICE.md)
