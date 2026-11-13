# Git Repository Description & README (EN + RU)

## Part 1 — English Version (Ready for GitHub)

### Short GitHub Repository Description ("About" field)

> Pre-driver FMLA32 Tensor Core unlocker and PTX benchmark console for GeForce RTX 40-series (Ada), RTX 30-series (Ampere), and RTX 20-series (Turing) on Windows 10/11 (UEFI USB) and Linux (`gpu_unlock.ko`). Automatic hardware profiling, pre-flight VBIOS ROM validation, and zero VBIOS flash modification.

### Full `README.md` (English)

# GPU-Tensor-Unlock-Universal

**Version: 1.3.2**

Consumer GeForce GPUs of the Ada Lovelace (`RTX 40xx`), Ampere (`RTX 30xx`), and Turing (`RTX 20xx`) generations carry the full physical Tensor Core execution units on silicon, but stock VBIOS firmware sets the `FMLA32` speed-select override (`0x0082381c` `SS0` / `0x00823820` `SS1` on Ada/Ampere, or `0x00409664` `SS0` / `0x0040966c` `SS1` on Turing) to half rate (`1`). Because of this fuse setting, matrix multiply-accumulate instructions that accumulate into 32-bit floating-point registers (`FP16 -> FP32`, `BF16 -> FP32`, `TF32 -> FP32`, and `FP8 E4M3 -> FP32`) run at half the issue rate of `FP16 -> FP16` or workstation RTX cards.

**GPU-Tensor-Unlock-Universal** removes this limit in volatile GPU registers before the operating system display driver binds (`BOOTX64.EFI` pre-boot on Windows 10/11, or `gpu_unlock.ko` on Linux), restoring full `2.00x` `FMLA32` throughput until the next cold power-off. The SPI flash chip (VBIOS ROM) is never written or modified.

#### Why This Project Was Built

Upstream research repositories proved that the V67 SEC2 Booter chain works on Turing, Ampere, and Ada, but they were released as low-level research snapshots rather than a unified tool:

* **Hardcoded single-card profiles**: Public Windows UEFI forks were configured for a single board (`RTX 4090` or `RTX 4080`). Adapting them to another card required manually looking up PCI Device and Subsystem IDs, bus numbers, VRAM windows, and Windows EFI System Partition GUIDs, editing C headers (`local_profile.h`) by hand, and compiling the EFI binary from the command line.

* **OS and architecture fragmentation**: Linux kernel modules (`gpu-unlock` for Ampere/Turing, `gpu-unlock-ada` for Ada) and Windows UEFI loaders lived in separate repositories with different build flows and no graphical console.

* **No built-in verification or benchmark**: Checking whether the unlock actually took effect required building external CUDA tools (`mmapeak`) separately, and stock `mmapeak` builds used compile-time all-zero fragments that allowed the compiler to collapse tile calculations.

* **Late VBIOS ROM validation on UEFI**: Earlier UEFI loaders disconnected the display driver before verifying whether the card's `FWSEC-FRTS` descriptor and `DMEMMAPPER` table in VBIOS PROM matched the expected layout.

**GPU-Tensor-Unlock-Universal** brings Windows and Linux support, Ada (`AD10x`), Ampere (`GA10x`), and Turing (`TU10x`) payload chains, automatic hardware profiling, and an integrated PTX benchmark into one self-contained package.

#### Key Features

1. **Native Desktop Consoles for Windows and Linux (`Windows_Launch_UI.bat` & `Linux_Launch_UI.sh`)**

   * **Windows 10 / 11 (`Windows_Launch_UI.bat`)**: Detects the host GPU, USB/SD removable drives, and Windows ESP GUID via zero-Admin Win32 kernel IOCTLs (`IOCTL_STORAGE_QUERY_PROPERTY`, `IOCTL_DISK_GET_DRIVE_LAYOUT_EX`) with `AUTO` UEFI ESP discovery fallback, compiles a board-matched `BOOTX64.EFI`, and stages a bootable FAT32 USB drive with a 30-second manual confirmation prompt (`Press U`).

   * **Linux (`./Linux_Launch_UI.sh`)**: Builds and verifies the pinned `610.43.03` firmware assets, stages `gpu_unlock.ko` via DKMS + early-boot `initramfs` hooks (or executes live `modprobe` for unbound secondary GPUs), parses transaction stages from `dmesg`, and reads hardware SM issue-rate dividers directly through `/dev/nvidiactl` (`ioctl 0x20801230`) without requiring a CUDA context.

   * **Multi-language Console UI & One-Click Markdown Report**: Supports instant switching between English (`EN`), Russian (`RU`), Chinese (`ZH`), and Hindi (`HI`), and includes a **`COPY MARKDOWN REPORT`** button in Section `[05]` for instant GitHub Issues diagnostics export.

2. **Multi-Source Hardware Auto-Detection & Profile Lock**

   * Cross-verifies GPU identity across `NVML` (`nvml.dll` / `libnvidia-ml.so.1`), `CUDA Driver API` (`nvcuda.dll` / `libcuda.so.1`), and OS PCI enumerators (Windows `pci.sys` via `Get-PnpDevice` or Linux `/sys/bus/pci/devices/*` + `lspci -Dnn`).

   * Enforces a strict `PCI Device ID -> Silicon Die -> PMC_BOOT_0` mapping in both host profile generation and UEFI C checks (`GuValidArchChip`), locking hardware fields in the UI so a mismatched chip profile cannot be built accidentally.

   * Includes a **Live CLI Verification** button that displays the exact `nvidia-smi` / `lspci` / PowerShell command and prints the raw system output directly in the console.

3. **Pre-Flight VBIOS ROM Validation & Safe Handoff**

   * Before disconnecting UEFI GOP (`DisconnectController`), the pre-flight check reads `NV_PROM_DATA` (`BAR0 + 0x300000` up to 1 MiB), validates the ROM expansion chain, `BIT` checksum, `Falcon Ucode Descriptor` (`V3` RSA-3K on Ada/Ampere or `V2` AES-128 on Turing; `ucode_id = 9`, `engine_mask = 0x400`), `DMEMMAPPER v3` (`"DMAP"`), and live fuse version (`0x8241c0`), and runs a dry-run `FRTS` patch in host RAM.

   * Latches the SHA-256 digest of the verified `FWSEC` span on pre-flight and re-verifies it before enabling Bus Master or launching GSP.

   * Retains all DMA buffers with Bus Master disabled if any post-start stage fails before post-FLR quiescence is confirmed, ensuring the GPU can never DMA into freed host memory.

4. **Integrated CUDA PTX JIT Benchmark (`tensor_benchmark.py`)**

   * Measures up to 7 PTX kernels (`FP16 -> FP16`, `FP16 -> FP32`, `BF16 -> FP32`, `TF32 -> FP32`, `FP8 E4M3 -> FP32`, `INT8 -> INT32`, and `Scalar FP32 FFMA`) across `sm_89` (Ada), `sm_86` (Ampere), and `sm_75` (Turing) with runtime-randomized inputs.

   * Verifies both the loop execution signature and finite non-zero IEEE-754 accumulators on every run, and saves `BEFORE (STOCK)` and `AFTER (UNLOCKED)` baselines per GPU UUID for side-by-side speedup comparison.

   * Includes one-click VBIOS maximum power limit adjustment via NVML with hardware readback verification.

5. **Offline Sanitizer & Kernel Test Suites**

   * **Windows UEFI (`python3 windows/uefi/run_self_test.py`)**: Compiles and runs 43 core transaction scenarios and 64 UEFI application/topology scenarios against simulated PCI/MMIO/DMA hardware under `gcc -fsanitize=address,undefined`.

   * **Linux Kernel & Tooling (`python3 -m unittest discover -s tests -v`)**: Runs unit and C kernel tests covering `unlock_610.c`, `main.c`, `prep_610.c`, `vbios_610.c`, `layout_610.c`, `gfw_eval.c`, `read_sm_rates.py`, and `sysfs`/`lspci` auto-detection.

#### Measured Results (Hardware-Tested Baselines)

| GPU Model | PCI ID / Die | `FP16 -> FP16` (FMLA16) | `FP16 -> FP32` Stock | `FP16 -> FP32` Unlocked | `BF16 -> FP32` Unlocked | Gain | Verification Source & Test Bench |
| ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| **GeForce RTX 4070 Ti** | `10de:2782` (`AD104`) | 172.8 TF/s | 86.4 TF/s | **172.8 TF/s** | **172.7 TF/s** | **2.00x** | **[Author Tested — MindAllik]** Win 11 UEFI, Palit `1569:f294`, 300 W ([`rtx4070ti-report`](docs/rtx4070ti-report.md)) |
| **GeForce RTX 4090** | `10de:2684` (`AD102`) | ~331.6 TF/s | 165.6 TF/s | **331.6 TF/s** | **330.6 TF/s** | **2.00x** | **[Upstream Report — elias-gaeros]** Linux 7.2.4, 450 W ([`rtx4090-report`](docs/rtx4090-register-report.md)) |
| **GeForce RTX 4070 Ti SUPER** | `10de:2705` (`AD103`) | ~190.0 TF/s | 95.0 TF/s | **189.9 TF/s** | **189.7 TF/s** | **2.00x** | **[Upstream Report — JustAResearcher]** Linux 5.15, 240 W ([`ada-2705-report`](docs/ada-2705-report.md)) |

*Note: These figures represent register-resident Tensor Core instruction issue rates (`mma.sync.aligned`). Real-world GEMM or inference speedups depend on memory bandwidth, power limits, and kernel utilization.*

#### Supported Hardware Matrix

* **Author Hardware-Tested**: GeForce RTX 4070 Ti (`10de:2782`, `AD104` — Palit `1569:f294`, Windows 11 UEFI, 300 W).

* **Upstream Hardware-Tested**: GeForce RTX 4090 (`10de:2684`, `AD102`), GeForce RTX 4070 Ti SUPER (`10de:2705`, `AD103`), GeForce RTX 3090 (`10de:2204`, `GA102`), GeForce RTX 3080 (`10de:2206`, `GA102`), GeForce RTX 3060 12GB (`10de:2504`, `GA106`).

* **Experimental Opt-In (Simulated Desktop Profiles)** (validated offline under ASan/UBSan; require explicit single-card BDF selection and family opt-in flag on Linux):
  * **Ada Lovelace (`AD102..AD107`)**: RTX 4090 D (`2685`), RTX 4080 SUPER (`2702`), RTX 4080 (`2704`), RTX 4070 SUPER (`2783`), RTX 4070 (`2786`/`2709`), RTX 4060 Ti (`2803`/`2805`/`27b0`), RTX 4060 (`2882`).
  * **Ampere (`GA102..GA107`)**: RTX 3090 Ti (`2203`), RTX 3080 Ti 12GB/20GB (`2208`/`2205`), RTX 3080 12GB/LHR (`220a`/`2216`), RTX 3070 Ti (`2482`/`2207`), RTX 3070 (`2484`/`2488`), RTX 3060 Ti (`2486`/`2489`/`24c9`/`2414`), RTX 3060 (`2503`/`2487`), RTX 3050 (`2507`/`2582`/`2584`), CMP 90HX/70HX (`220d`/`248a`).
  * **Turing (`TU102/TU104/TU106`)**: RTX 2080 Ti (`1e04`/`1e07`), TITAN RTX (`1e02`), RTX 2080 SUPER (`1e81`), RTX 2080 (`1e82`/`1e87`), RTX 2070 SUPER (`1e84`), RTX 2070 (`1f02`/`1f07`), RTX 2060 SUPER (`1f06`/`1f47`), RTX 2060 12GB (`1f03`), RTX 2060 6GB (`1f08`), CMP 50HX (`1e09`), CMP 40HX (`1f0b`).

#### Credits & Upstream Acknowledgements

This project builds upon the research, payloads, and loader code published by the following repositories and authors:

* [**TOTORONG/AD103_win_unlocker**](https://huggingface.co/TOTORONG/AD103_win_unlocker) (revision `51df9c17ec89eb8486df52cc9079dde4bd1f9974`) — AD102 4-PLM SEC2 payload construction, debug-booter analysis, and the foundational Windows UEFI application framework.

* [**Zagitta/gpu-unlock**](https://github.com/Zagitta/gpu-unlock), [**elias-gaeros/gpu-unlock**](https://github.com/elias-gaeros/gpu-unlock) (commit `4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc`), and [**JustAResearcher/gpu-unlock-ada**](https://github.com/JustAResearcher/gpu-unlock-ada) (commit `4e7fefcc4923f9e083d5324dc75a7d2f906af77f`) — pre-driver Linux kernel module architecture (`unlock_610.c`), WPR2/FLR handoff logic, AD102/AD103/TU102 integration, and the `/dev/nvidiactl` RM issue-rate getter (`tools/read_sm_rates.py`).

* [**KohakuBlueleaf/KohakUnlock**](https://github.com/KohakuBlueleaf/KohakUnlock) and [**KohakuBlueleaf/mmapeak**](https://github.com/KohakuBlueleaf/mmapeak) — Windows/UEFI pre-flight check hardening, cold-state register classification (`GuClassifyColdState`), and runtime-randomized `mmapeak` verification methodology.

* [**impacifist/Windows-GPU-UNLOCK**](https://github.com/impacifist/Windows-GPU-UNLOCK) and [**Goldlionren/gpu-unlock-4080s**](https://github.com/Goldlionren/gpu-unlock-4080s) — reference implementation for direct UEFI $\rightarrow$ Windows Boot Manager handoff without intermediate reboot and local Secure Boot `db` signing policy.

* **Jon Pry** (*"A Canary in the Crypto Mine"*, DOI `10.5281/zenodo.20916112`), [**WildFlash1st/cmp90hx-unlock**](https://github.com/WildFlash1st/cmp90hx-unlock), [**xrip/cmp50hx-unlock**](https://github.com/xrip/cmp50hx-unlock), [**PZH1gdmu/CMP40HX-Unlock**](https://github.com/PZH1gdmu/CMP40HX-Unlock), [**Consensus-Protocol/cmp170hx**](https://github.com/Consensus-Protocol/cmp170hx), **Nouveau**, and [**envytools**](https://github.com/envytools/envytools) — foundational research on the V67 Booter vulnerability, PLM register models, and Falcon/GSP processor documentation.

#### License

Source code in this repository is licensed under **GPL-2.0-only** (see `LICENSE`, `NOTICE.md`, and `licenses/`). No proprietary NVIDIA firmware binaries are distributed in this repository; pinned `610.43.03` firmware inputs are fetched directly over HTTPS and verified by SHA-256 on the user's machine during build.

## Часть 2 — Русская версия (перевод английского описания для вашей оценки)

### Краткое описание для шапки GitHub (поле «About»)

> Разблокировщик селекторов FMLA32 тензорных ядер и консоль PTX-бенчмарка для GeForce RTX 40-й (Ada), RTX 30-й (Ampere) и RTX 20-й (Turing) серий на Windows 10/11 (UEFI USB) и Linux (`gpu_unlock.ko`). Автоматическое профилирование железа, предпроверка VBIOS ROM до старта и работа без модификации флеша VBIOS.

### Полный текст `README.md` (Перевод на русский)

# GPU-Tensor-Unlock-Universal

**Version: 1.3.2**

В пользовательских видеокартах GeForce поколений Ada Lovelace (`RTX 40xx`), Ampere (`RTX 30xx`) и Turing (`RTX 20xx`) физически распаяны полноценные тензорные блоки, однако в стоковом VBIOS регистр селектора скорости `FMLA32` (`0x0082381c` `SS0` / `0x00823820` `SS1` на Ada/Ampere или `0x00409664` `SS0` / `0x0040966c` `SS1` на Turing) выставлен в режим половинной частоты (`1`). Из-за этого матричные инструкции с накоплением результата в 32-битные регистры `FP32` (`FP16 -> FP32`, `BF16 -> FP32`, `TF32 -> FP32` и `FP8 E4M3 -> FP32`) исполняются вдвое медленнее, чем `FP16 -> FP16` или аналогичные инструкции на профессиональных картах RTX.

**GPU-Tensor-Unlock-Universal** снимает это ограничение в энергозависимых регистрах GPU до инициализации основного видеодрайвера ОС (через предзагрузчик `BOOTX64.EFI` на Windows 10/11 или ядерный модуль `gpu_unlock.ko` на Linux), возвращая полную `2.00x` пропускную способность `FMLA32` до следующего полного отключения питания. Физическая микросхема SPI-флеша (VBIOS ROM) никогда не перезаписывается и не затрагивается.

#### Зачем был создан этот проект

Исследовательские репозитории доказали работоспособность цепочки V67 SEC2 Booter на архитектурах Turing, Ampere и Ada, однако они публиковались как низкоуровневые наработки под конкретные стенды, а не как готовый универсальный инструмент:

* **Жёсткая привязка к одной видеокарте**: публичные форки под Windows UEFI были настроены под одну конкретную плату (`RTX 4090` или `RTX 4080`). Чтобы запустить их на другой карте, требовалось вручную искать PCI Device и Subsystem ID, номер шины, границы VRAM и GUID раздела Windows EFI, вручную прописывать их в C-заголовки (`local_profile.h`) и компилировать EFI-бинарник из командной строки.

* **Разрозненность по ОС и архитектурам**: ядерные модули под Linux (`gpu-unlock` для Ampere/Turing, `gpu-unlock-ada` для Ada) и UEFI-загрузчики под Windows находились в разных репозиториях с разными процессами сборки и без графического интерфейса.

* **Отсутствие встроенного бенчмарка и верификации**: чтобы проверить, сработала ли разблокировка на самом деле, приходилось отдельно собирать сторонние CUDA-утилиты (`mmapeak`), причём оригинальный `mmapeak` использовал нулевые входные константы на этапе компиляции, что позволяло компилятору схлопывать матричные вычисления.

* **Отсутствие ранней проверки VBIOS ROM до отключения экрана в UEFI**: прежние загрузчики отключали видеодрайвер UEFI GOP до проверки того, совместимы ли дескриптор `FWSEC-FRTS` и таблица `DMEMMAPPER` в VBIOS конкретной карты с патчером.

**GPU-Tensor-Unlock-Universal** объединяет поддержку Windows и Linux, цепочки пейлоадов для Ada (`AD10x`), Ampere (`GA10x`) и Turing (`TU10x`), автоматическое профилирование оборудования и встроенный PTX-бенчмарк в одном автономном пакете.

#### Ключевые возможности

1. **Нативные графические консоли для Windows и Linux (`Windows_Launch_UI.bat` и `Linux_Launch_UI.sh`)**

   * **Windows 10 / 11 (`Windows_Launch_UI.bat`)**: автоматически определяет видеокарту, USB/SD-накопители и GUID системного раздела Windows ESP напрямую через ядерные Win32 IOCTL (`IOCTL_STORAGE_QUERY_PROPERTY`, `IOCTL_DISK_GET_DRIVE_LAYOUT_EX`) без прав администратора и без зависаний WMI/PowerShell (с резервным режимом `AUTO` поиска `bootmgfw.efi` в UEFI), компилирует `BOOTX64.EFI` под конкретную плату и подготавливает загрузочную FAT32-флешку с 30-секундным окном ручного подтверждения (`Press U`).

   * **Linux (`./Linux_Launch_UI.sh`)**: собирает и верифицирует по SHA-256 ассеты прошивки `610.43.03`, устанавливает `gpu_unlock.ko` через DKMS и хуки ранней загрузки `initramfs` (или выполняет живой `modprobe` для непривязанных вторичных карт), разбирает этапы транзакции из `dmesg` и считывает аппаратные делители скорости SM напрямую через `/dev/nvidiactl` (`ioctl 0x20801230`) без инициализации CUDA.

   * **Мультиязычный интерфейс и экспорт Markdown-отчета**: мгновенное переключение между русским (`RU`), английским (`EN`), китайским (`ZH`) и хинди (`HI`), а также кнопка **«СКОПИРОВАТЬ MARKDOWN-ОТЧЕТ»** (`COPY MARKDOWN REPORT`) в секции `[05]` для копирования готового шаблона диагностики в GitHub Issues.

2. **Многоуровневое автоопределение оборудования и защита профиля**

   * Перекрёстно сверяет параметры карты через `NVML` (`nvml.dll` / `libnvidia-ml.so.1`), `CUDA Driver API` (`nvcuda.dll` / `libcuda.so.1`) и системные перечислители PCI (Windows `pci.sys` через `Get-PnpDevice` или Linux `/sys/bus/pci/devices/*` + `lspci -Dnn`).

   * Жёстко связывает цепочку `PCI Device ID -> Чип -> PMC_BOOT_0` как при генерации профиля, так и внутри UEFI C-кода (`GuValidArchChip`), блокируя аппаратные поля в интерфейсе от случайного несовпадения.

   * Включает кнопку **прямой проверки в консоли**, которая показывает точную системную команду (`nvidia-smi` / `lspci` / PowerShell) и выводит необработанный ответ драйвера прямо перед пользователем.

3. **Предпроверка VBIOS ROM до старта и безопасная передача управления**

   * До отключения видеодрайвера UEFI GOP (`DisconnectController`) система считывает `NV_PROM_DATA` (`BAR0 + 0x300000` до 1 МБ), проверяет цепочку расширения ROM, контрольную сумму `BIT`, дескриптор `Falcon Ucode Descriptor` (`V3` RSA-3K на Ada/Ampere или `V2` AES-128 на Turing; `ucode_id = 9`, `engine_mask = 0x400`), `DMEMMAPPER v3` (`"DMAP"`), живую версию фьюза (`0x8241c0`) и выполняет пробный патч `FRTS` в ОЗУ.

   * Фиксирует SHA-256 проверенного среза `FWSEC` на этапе предпроверки и повторно сверяет его перед включением Bus Master и запуском GSP.

   * Удерживает выделенные DMA-буферы при сброшенном Bus Master в случае любой ошибки после старта микрокода до подтверждённого завершения `PCIe FLR`, исключая обращение GPU к освобождённой памяти хоста.

4. **Встроенный бенчмарк CUDA PTX JIT (`tensor_benchmark.py`)**

   * Замеряет до 7 PTX-ядер (`FP16 -> FP16`, `FP16 -> FP32`, `BF16 -> FP32`, `TF32 -> FP32`, `FP8 E4M3 -> FP32`, `INT8 -> INT32` и `Scalar FP32 FFMA`) на архитектурах `sm_89` (Ada), `sm_86` (Ampere) и `sm_75` (Turing) со случайной инициализацией входных данных во время выполнения.

   * Проверяет контрольную сигнатуру исполнения цикла и конечность ненулевых аккумуляторов IEEE-754 при каждом прогоне, сохраняя эталонные замеры `ДО (СТОК)` и `ПОСЛЕ (АНЛОК)` для каждого UUID видеокарты.

   * Позволяет в один клик выставить максимальный лимит мощности VBIOS через NVML с аппаратной проверкой чтения регистра.

5. **Автономные тестовые наборы с санитайзерами**

   * **Windows UEFI (`python3 windows/uefi/run_self_test.py`)**: компилирует и прогоняет 43 сценария аппаратной транзакции и 64 сценария UEFI-приложения/топологии на эмулированном PCI/MMIO/DMA под `gcc -fsanitize=address,undefined`.

   * **Ядро Linux и утилиты (`python3 -m unittest discover -s tests -v`)**: прогоняет C- и Python-тесты для `unlock_610.c`, `main.c`, `prep_610.c`, `vbios_610.c`, `layout_610.c`, `gfw_eval.c`, `read_sm_rates.py` и автоопределения через `sysfs`/`lspci`.

#### Результаты замеров (проверенные на железе ориентиры)

| Видеокарта | PCI ID / Чип | `FP16 -> FP16` (FMLA16) | `FP16 -> FP32` (Сток) | `FP16 -> FP32` (Анлок) | `BF16 -> FP32` (Анлок) | Прирост | Источник верификации и стенд |
| ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| **GeForce RTX 4070 Ti** | `10de:2782` (`AD104`) | 172.8 TF/s | 86.4 TF/s | **172.8 TF/s** | **172.7 TF/s** | **2.00x** | **[Проверено автором — MindAllik]** Win 11 UEFI, Palit `1569:f294`, 300 W ([`rtx4070ti-report`](docs/rtx4070ti-report.md)) |
| **GeForce RTX 4090** | `10de:2684` (`AD102`) | ~331.6 TF/s | 165.6 TF/s | **331.6 TF/s** | **330.6 TF/s** | **2.00x** | **[Отчёт апстрима — elias-gaeros]** Linux 7.2.4, 450 W ([`rtx4090-report`](docs/rtx4090-register-report.md)) |
| **GeForce RTX 4070 Ti SUPER** | `10de:2705` (`AD103`) | ~190.0 TF/s | 95.0 TF/s | **189.9 TF/s** | **189.7 TF/s** | **2.00x** | **[Отчёт апстрима — JustAResearcher]** Linux 5.15, 240 W ([`ada-2705-report`](docs/ada-2705-report.md)) |

*Примечание: приведены темпы выдачи инструкций (`mma.sync.aligned`) при работе из регистров. Итоговый прирост в прикладных задачах GEMM и инференсе зависит от пропускной способности памяти, лимита мощности и конкретных ядер.*

#### Матрица поддерживаемых карт

* **Проверено на физическом железе автором репозитория (`MindAllik`)**: GeForce RTX 4070 Ti (`10de:2782`, `AD104` — Palit `1569:f294`, Windows 11 UEFI, 300 W).

* **Проверено на физическом железе в отчётах апстримов**: GeForce RTX 4090 (`10de:2684`, `AD102`), GeForce RTX 4070 Ti SUPER (`10de:2705`, `AD103`), GeForce RTX 3090 (`10de:2204`, `GA102`), GeForce RTX 3080 (`10de:2206`, `GA102`), GeForce RTX 3060 12GB (`10de:2504`, `GA106`).

* **Архитектурно поддерживаемые / симулированные профили (`Experimental Opt-In`)** (прошли офлайн-проверку под ASan/UBSan; в Linux требуют явного выбора одиночного BDF и флага семейства):
  * **Ada Lovelace (`AD102..AD107`)**: RTX 4090 D (`2685`), RTX 4080 SUPER (`2702`), RTX 4080 (`2704`), RTX 4070 SUPER (`2783`), RTX 4070 (`2786`/`2709`), RTX 4060 Ti (`2803`/`2805`/`27b0`), RTX 4060 (`2882`).
  * **Ampere (`GA102..GA107`)**: RTX 3090 Ti (`2203`), RTX 3080 Ti 12GB/20GB (`2208`/`2205`), RTX 3080 12GB/LHR (`220a`/`2216`), RTX 3070 Ti (`2482`/`2207`), RTX 3070 (`2484`/`2488`), RTX 3060 Ti (`2486`/`2489`/`24c9`/`2414`), RTX 3060 (`2503`/`2487`), RTX 3050 (`2507`/`2582`/`2584`), CMP 90HX/70HX (`220d`/`248a`).
  * **Turing (`TU102/TU104/TU106`)**: RTX 2080 Ti (`1e04`/`1e07`), TITAN RTX (`1e02`), RTX 2080 SUPER (`1e81`), RTX 2080 (`1e82`/`1e87`), RTX 2070 SUPER (`1e84`), RTX 2070 (`1f02`/`1f07`), RTX 2060 SUPER (`1f06`/`1f47`), RTX 2060 12GB (`1f03`), RTX 2060 6GB (`1f08`), CMP 50HX (`1e09`), CMP 40HX (`1f0b`).

#### Благодарности и использованные наработки (Upstream Credits)

Проект опирается на исследования, пейлоады и код загрузчиков, опубликованные авторами следующих репозиториев:

* [**TOTORONG/AD103_win_unlocker**](https://huggingface.co/TOTORONG/AD103_win_unlocker) (ревизия `51df9c17ec89eb8486df52cc9079dde4bd1f9974`) — генератор 4-PLM SEC2-пейлоада для AD102, анализ отладочного booter-образа и базовый каркас UEFI-приложения под Windows.

* [**Zagitta/gpu-unlock**](https://github.com/Zagitta/gpu-unlock), [**elias-gaeros/gpu-unlock**](https://github.com/elias-gaeros/gpu-unlock) (коммит `4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc`) и [**JustAResearcher/gpu-unlock-ada**](https://github.com/JustAResearcher/gpu-unlock-ada) (коммит `4e7fefcc4923f9e083d5324dc75a7d2f906af77f`) — архитектура преддрайверного ядерного модуля Linux (`unlock_610.c`), логика передачи управления через WPR2/FLR, интеграция AD102/AD103/TU102 и утилита чтения селекторов через `/dev/nvidiactl` (`tools/read_sm_rates.py`).

* [**KohakuBlueleaf/KohakUnlock**](https://github.com/KohakuBlueleaf/KohakUnlock) и [**KohakuBlueleaf/mmapeak**](https://github.com/KohakuBlueleaf/mmapeak) — ужесточение предпроверок безопасности в Windows/UEFI, классификация холодного состояния регистров (`GuClassifyColdState`) и методика верификации на рандомизированном `mmapeak`.

* [**impacifist/Windows-GPU-UNLOCK**](https://github.com/impacifist/Windows-GPU-UNLOCK) и [**Goldlionren/gpu-unlock-4080s**](https://github.com/Goldlionren/gpu-unlock-4080s) — референсная реализация прямой передачи управления UEFI $\rightarrow$ Windows Boot Manager без промежуточного сброса и политика локальной подписи Secure Boot `db`.

* **Jon Pry** (*"A Canary in the Crypto Mine"*, DOI `10.5281/zenodo.20916112`), [**WildFlash1st/cmp90hx-unlock**](https://github.com/WildFlash1st/cmp90hx-unlock), [**xrip/cmp50hx-unlock**](https://github.com/xrip/cmp50hx-unlock), [**PZH1gdmu/CMP40HX-Unlock**](https://github.com/PZH1gdmu/CMP40HX-Unlock), [**Consensus-Protocol/cmp170hx**](https://github.com/Consensus-Protocol/cmp170hx), **Nouveau** и [**envytools**](https://github.com/envytools/envytools) — фундаментальное исследование уязвимости бутера V67, модели регистров PLM и документация по процессорам Falcon/GSP.

#### Лицензия

Исходный код распространяется под лицензией **GPL-2.0-only** (см. `LICENSE`, `NOTICE.md` и папку `licenses/`). Проприетарные бинарные файлы прошивок NVIDIA в состав репозитория не входят — необходимые пакеты версии `610.43.03` скачиваются по HTTPS и проверяются по SHA-256 локально на машине пользователя во время сборки.
