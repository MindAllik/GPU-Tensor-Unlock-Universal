#!/usr/bin/env python3
"""Self-contained ASan + UBSan verification suite for windows/uefi (M-13).
Generates synthetic PROM, PCI config, and firmware fixtures on the fly and executes
all 43 core transaction scenarios and 64 UEFI app/topology scenarios under GCC -fsanitize=address,undefined."""

from pathlib import Path
import hashlib, re, shutil, struct, subprocess, sys, tempfile

UEFI_ROOT = Path(__file__).resolve().parent
REPO_ROOT = UEFI_ROOT.parent.parent
sys.path.insert(0, str(REPO_ROOT))
import core_detector


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="gpu_unlock_selftest_") as tmpd:
        work = Path(tmpd)
        fix = work / "fixtures"
        assets = fix / "assets"
        fix.mkdir(parents=True)
        assets.mkdir(parents=True)

        # 1. Synthetic 1 MiB PROM fixture with BIT, Falcon Ucode Descriptor V3, and DMEMMAPPER v3 ("DMAP")
        prom = bytearray(1048576)
        struct.pack_into("<H", prom, 0x0, 0xAA55)
        struct.pack_into("<H", prom, 0x18, 0x20)
        struct.pack_into("<4s", prom, 0x20, b"PCIR")
        struct.pack_into("<H", prom, 0x20 + 0x0A, 0x18)
        struct.pack_into("<H", prom, 0x20 + 0x10, 0x24A00 // 512)
        prom[0x20 + 0x14] = 0x00
        prom[0x20 + 0x15] = 0x80

        prom[0x100:0x106] = b"\xff\xb8BIT\x00"
        prom[0x108] = 12
        prom[0x109] = 6
        prom[0x10A] = 1
        prom[0x10B] = (256 - (sum(prom[0x100:0x10B]) & 0xFF)) & 0xFF
        prom[0x10C] = 0x70
        prom[0x10D] = 2
        struct.pack_into("<H", prom, 0x10E, 4)
        struct.pack_into("<H", prom, 0x110, 0x200)
        struct.pack_into("<I", prom, 0x200, 0x300)
        prom[0x300:0x304] = bytes([1, 6, 6, 1])
        prom[0x306] = 0x85
        struct.pack_into("<I", prom, 0x308, 0x45154)

        desc_off = 0x45154
        desc_size = 44 + 768
        hdr = (desc_size << 16) | (3 << 8) | 1
        image_size = 0x10300
        imem_size = 0xF500
        dmem_size = 0xE00
        pkc_off = 0xB24
        interface_off = 0xCEC
        struct.pack_into(
            "<9IHBBH",
            prom,
            desc_off,
            hdr,
            image_size,
            pkc_off,
            interface_off,
            0,
            imem_size,
            0,
            0,
            dmem_size,
            0x400,
            9,
            2,
            0x0003,
        )
        for i in range(384):
            prom[0x45180 + i] = (0xA0 + i) & 0xFF
            prom[0x45180 + 0x180 + i] = (0x55 + i) & 0xFF

        dmem_base = desc_off + desc_size + imem_size
        prom[dmem_base + interface_off : dmem_base + interface_off + 4] = bytes([1, 4, 8, 2])
        struct.pack_into("<II", prom, dmem_base + interface_off + 4, 1, 0)
        struct.pack_into("<II", prom, dmem_base + interface_off + 12, 4, 0xD00)
        struct.pack_into("<IHHII", prom, dmem_base + 0xD00, 0x50414D44, 3, 64, 0xD40, 44)
        (fix / "prom.bin").write_bytes(prom)

        # 2. Synthetic 256-byte PCI configuration space
        pci_cfg = bytearray(256)
        struct.pack_into("<I", pci_cfg, 0x00, 0x278210DE)
        struct.pack_into("<I", pci_cfg, 0x04, 0x00100003)
        struct.pack_into("<I", pci_cfg, 0x08, 0x030000A1)
        struct.pack_into("<I", pci_cfg, 0x0C, 0x00800010)
        struct.pack_into("<I", pci_cfg, 0x10, 0x80000000)
        struct.pack_into("<I", pci_cfg, 0x14, 0x0000000C)
        struct.pack_into("<I", pci_cfg, 0x18, 0x00000060)
        struct.pack_into("<I", pci_cfg, 0x1C, 0x0000000C)
        struct.pack_into("<I", pci_cfg, 0x20, 0x00000064)
        struct.pack_into("<I", pci_cfg, 0x24, 0x00005001)
        struct.pack_into("<I", pci_cfg, 0x2C, 0xF2941569)
        struct.pack_into("<I", pci_cfg, 0x30, 0x85000000)
        pci_cfg[0x34] = 0x60
        pci_cfg[0x3C] = 0xFF
        struct.pack_into("<I", pci_cfg, 0x60, 0x48036801)
        struct.pack_into("<I", pci_cfg, 0x64, 0x00000008)
        struct.pack_into("<I", pci_cfg, 0x68, 0x00807805)
        struct.pack_into("<I", pci_cfg, 0x78, 0x0012C810)
        struct.pack_into("<I", pci_cfg, 0x7C, 0x112C8DE1)
        struct.pack_into("<I", pci_cfg, 0x80, 0x00092930)
        struct.pack_into("<I", pci_cfg, 0xC8, 0x00050011)
        (fix / "pci.bin").write_bytes(pci_cfg)

        # 3. Synthetic firmware assets
        booter_ad = bytearray(57672)
        struct.pack_into(
            "<II14III",
            booter_ad,
            0,
            0x314C5442,
            1,
            0,
            256,
            32256,
            24576,
            1,
            256,
            32000,
            256,
            0,
            32272,
            3,
            1,
            2,
            768,
            56832,
            768,
        )
        (assets / "booter_load_ad102.bin").write_bytes(booter_ad)
        (assets / "v67-ad102-610.43.03-four-plm.bin").write_bytes(core_detector.build_v67_payload(True))

        gsp_size = 84277400
        fwimage_off = 0x40
        fwimage_size = 0x5053000
        sig_ad_off = fwimage_off + fwimage_size
        sig_ga_off = sig_ad_off + 4096
        shstr_off = sig_ga_off + 4096
        shstr = b"\x00.shstrtab\x00.fwimage\x00.fwsignature_ad10x\x00.fwsignature_ga10x\x00"
        shstr_size = len(shstr)
        shoff = (shstr_off + shstr_size + 7) & ~7

        gsp = bytearray(gsp_size)
        gsp[0:4] = b"\x7fELF"
        gsp[4] = 2
        gsp[5] = 1
        gsp[6] = 1
        struct.pack_into("<I", gsp, 20, 1)
        struct.pack_into("<Q", gsp, 40, shoff)
        struct.pack_into("<H", gsp, 52, 64)
        struct.pack_into("<H", gsp, 58, 64)
        struct.pack_into("<H", gsp, 60, 5)
        struct.pack_into("<H", gsp, 62, 1)
        gsp[shstr_off : shstr_off + shstr_size] = shstr

        def pack_shdr(idx: int, name_off: int, off: int, size: int) -> None:
            base = shoff + idx * 64
            struct.pack_into("<I", gsp, base + 0, name_off)
            struct.pack_into("<Q", gsp, base + 24, off)
            struct.pack_into("<Q", gsp, base + 32, size)

        pack_shdr(0, 0, 0, 0)
        pack_shdr(1, shstr.index(b".shstrtab"), shstr_off, shstr_size)
        pack_shdr(2, shstr.index(b".fwimage"), fwimage_off, fwimage_size)
        pack_shdr(3, shstr.index(b".fwsignature_ad10x"), sig_ad_off, 4096)
        pack_shdr(4, shstr.index(b".fwsignature_ga10x"), sig_ga_off, 4096)
        (assets / "gsp_ga10x.bin").write_bytes(gsp)

        (assets / "gsp_boot_ad102.bin").write_bytes(bytearray(36864))
        desc_ad = bytearray(84)
        struct.pack_into("<I", desc_ad, 0, 5)
        for r_idx in (1, 3, 8, 10, 12):
            struct.pack_into("<II", desc_ad, r_idx * 4, 0x100, 0x100)
        struct.pack_into("<I", desc_ad, 56, 1)
        struct.pack_into("<I", desc_ad, 76, 36864)
        (assets / "gsp_boot_desc_ad102.bin").write_bytes(desc_ad)

        src = work / "src"
        shutil.copytree(UEFI_ROOT / "source", src)
        app_io_path = src / "unlock/app_io.c"
        app_io_txt = app_io_path.read_text()
        for fname in (
            "booter_load_ad102.bin",
            "v67-ad102-610.43.03-four-plm.bin",
            "gsp_ga10x.bin",
            "gsp_boot_ad102.bin",
            "gsp_boot_desc_ad102.bin",
        ):
            h = hashlib.sha256((assets / fname).read_bytes()).hexdigest()
            app_io_txt = re.sub(
                rf'(\{{[^}}]*{re.escape(fname)}[^}}]*,\s*\")[0-9a-f]{{64}}(\"\}})',
                rf"\g<1>{h}\g<2>",
                app_io_txt,
            )
        app_io_path.write_text(app_io_txt)

        asan_flags = [
            "-std=c11",
            "-fshort-wchar",
            "-O1",
            "-g",
            "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-unused-parameter",
            "-Wno-unused-function",
            "-Wno-misleading-indentation",
            "-Wno-format",
            "-D__KERNEL__",
            "-DGU_UEFI_PORT",
            "-DKOH_ENABLE_EXPERIMENT=1",
            "-DGU_TARGET_PCI_ID=GU_BOARD_ID",
            "-Iunlock",
            "-Iunlock/compat",
            "-Ideps/edk2/MdePkg/Include",
            "-Ideps/edk2/MdePkg/Include/X64",
        ]
        core_srcs = [
            "port",
            "compat",
            "vendor/unlock_610",
            "vendor/prep_610",
            "vendor/layout_610",
            "vendor/vbios_610",
            "vendor/gfw_eval",
        ]
        app_srcs = ["app", "app_io", "ownership", "format", "sha256", "checks"] + core_srcs

        core_exe = work / "core_asan"
        subprocess.run(
            ["gcc", *asan_flags, "unlock/tests/test_ad102_transaction.c", *[f"unlock/{s}.c" for s in core_srcs], "-o", str(core_exe)],
            cwd=src,
            check=True,
        )
        r_core = subprocess.run([str(core_exe), str(fix / "prom.bin"), str(assets)], cwd=src, capture_output=True, text=True, check=True)
        print(r_core.stdout.splitlines()[-1])

        app_exe = work / "app_asan"
        subprocess.run(
            ["gcc", *asan_flags, "unlock/tests/test_ad103_app.c", *[f"unlock/{s}.c" for s in app_srcs], "-o", str(app_exe)],
            cwd=src,
            check=True,
        )
        r_app = subprocess.run(
            [str(app_exe), str(fix / "prom.bin"), str(assets), str(fix / "pci.bin")],
            cwd=src,
            capture_output=True,
            text=True,
            check=True,
        )
        print(r_app.stdout.splitlines()[-1])

        # 4. Cross-generation profile & AD103 cold-state (SS0=0, SS1=0) + AIB PCI capability verification
        probe_c = work / "probe_multi_gen.c"
        probe_c.write_text("""
#include "port.h"
#include "checks.h"
int puts(const char *s);
void abort(void);
#define CHECK_TRUE(cond) do { if (!(cond)) abort(); } while (0)

int main(void) {
    /* Verify external --profile-dir header overrode default 0x278210de with RTX 4080 0x270410de */
    CHECK_TRUE(GU_BOARD_ID == 0x270410deU);
    CHECK_TRUE(GU_BOARD_SUBSYSTEM == 0x268819daU);
    CHECK_TRUE(GU_BOARD_CHIP == 0x193000a1U);

    /* Verify GuValidArchChip accepts exact chip, foundry strap bits 31:29 (0xa0000000), and same-family steppings */
    CHECK_TRUE(GuValidArchChip(0x193000a1U));
    CHECK_TRUE(GuValidArchChip(0xb93000a1U));
    CHECK_TRUE(GuValidArchChip(0x193001a2U));
    CHECK_TRUE(!GuValidArchChip(0x172000a1U));
    CHECK_TRUE(!GuValidArchChip(0xb72000a1U));
    CHECK_TRUE(!GuValidArchChip(0xbadf5040U));

    /* Verify GuClassifyColdState accepts AD103 cold state (SS0=0, SS1=0, PLM=0xffffff8f, WPR2_HI=0) */
    CHECK_TRUE(GuClassifyColdState(0xffffff8fU, 0x0U, 0x0U, 0x0U) == GU_COLD_OK);
    CHECK_TRUE(GuClassifyColdState(0x0004cb8fU, 0x0U, 0x0U, 0x0U) == GU_COLD_OK);
    CHECK_TRUE(GuClassifyColdState(0xffffff8fU, 0x31322012U, 0x7U, 0x0U) == GU_COLD_OK);
    CHECK_TRUE(GuClassifyColdState(0xffffffffU, 0x88888888U, 0x8U, 0x0U) == GU_COLD_ALREADY_MODIFIED);
    CHECK_TRUE(GuClassifyColdState(0xffffff8fU, 0x88888888U, 0x0U, 0x0U) == GU_COLD_PARTIALLY_MODIFIED);
    CHECK_TRUE(GuClassifyColdState(0xffffffffU, 0x0U, 0x0U, 0x0U) == GU_COLD_UNKNOWN_PROFILE_STATE);

    /* Verify GuCheckConfig accepts AIB VPD (0x03) and compact PCIe v2 capability layouts */
    UINT32 cfg[64] = {0};
    GU_CAPS caps = {0};
    cfg[0x00 / 4] = 0x270410deU;
    cfg[0x04 / 4] = 0x00100003U;
    cfg[0x08 / 4] = 0x030000a1U;
    cfg[0x0c / 4] = 0x00800010U;
    cfg[0x2c / 4] = 0x268819daU;
    cfg[0x34 / 4] = 0x60U;
    cfg[0x60 / 4] = 0x48036801U; /* PM at 0x60 -> next 0x68 */
    cfg[0x64 / 4] = 0x00000008U;
    cfg[0x68 / 4] = 0x00807805U; /* MSI at 0x68 -> next 0x78 */
    cfg[0x78 / 4] = 0x0012a410U; /* PCIe v2 at 0x78 -> compact next at 0xa4 (+0x2c) */
    cfg[0x7c / 4] = 0x112c8de1U;
    cfg[0xa4 / 4] = 0x0000c803U; /* VPD (0x03) at 0xa4 -> next 0xc8 */
    cfg[0xc8 / 4] = 0x00050011U; /* MSI-X at 0xc8 -> end 0x00 */
    CHECK_TRUE(GuCheckConfig(cfg, 0, 1, 0, 0, &caps));
    CHECK_TRUE(caps.pm == 0x60 && caps.msi == 0x68 && caps.pcie == 0x78 && caps.msix == 0xc8);

    puts("Multi-generation RTX 4080 (AD103) profile, cold-state SS0=0/SS1=0, and AIB PCI capability checks PASS");
    return 0;
}
""")
        prof_4080 = work / "prof_4080"
        prof_4080.mkdir()
        (prof_4080 / "local_profile.h").write_text("""#pragma once
#define GU_BOARD_ID 0x270410deU
#define GU_BOARD_SUBSYSTEM 0x268819daU
#define GU_BOARD_CHIP 0x193000a1U
#define GU_BOARD_SEGMENT 0U
#define GU_BOARD_BUS 0x01U
#define GU_BOARD_DEVICE 0U
#define GU_BOARD_FUNCTION 0U
#define GU_BOARD_CLASS_REV 0x030000a1U
#define GU_VRAM_MIN_MIB 0x3bf0U
#define GU_VRAM_MAX_MIB 0x4400U
#define GU_ARCH_ADA 1
#define GU_ARCH_TURING 0
#define GU_EXPECTED_COLD_PLM 0xffffff8fU
#define GU_EXPECTED_POST_FLR_PLM 0xffffffffU
#define KOH_WINDOWS_ESP_GUID 0xc70266a8U,0x85cfU,0x45d9U,{0x8d,0x4c,0x6b,0xa5,0x74,0x21,0xf5,0x5a}
#define KOH_WINDOWS_ESP_PART 1U
#define KOH_PAYLOAD_ESP_GUID 0xc70266a9U,0x85cfU,0x45d9U,{0x8d,0x4c,0x6b,0xa5,0x74,0x21,0xf5,0x5a}
#define KOH_AUTOCONFIRM_MS 30000
#define KOH_UNATTENDED_AUTOFIRE 0
""")
        src_4080 = work / "src_4080"
        shutil.copytree(src, src_4080)
        shutil.copy2(prof_4080 / "local_profile.h", src_4080 / "unlock" / "local_profile.h")
        probe_exe = work / "probe_4080_asan"
        subprocess.run(
            ["gcc", f"-I{prof_4080}", *asan_flags, str(probe_c), "unlock/checks.c", "-o", str(probe_exe)],
            cwd=src_4080,
            check=True,
        )
        r_probe = subprocess.run([str(probe_exe)], cwd=src_4080, capture_output=True, text=True, check=True)
        print(r_probe.stdout.strip())

        # 5. Ampere GA102 (RTX 3090 0x220410de / RTX 3080 Ti 20GB 0x220510de) NV_PMC_BOOT_0=0xb72000a1U check
        probe_3090_c = work / "probe_3090.c"
        probe_3090_c.write_text("""
#include "port.h"
int puts(const char *s);
void abort(void);
#define CHECK_TRUE(cond) do { if (!(cond)) abort(); } while (0)
int main(void) {
    CHECK_TRUE(GU_ARCH_ADA == 0);
    CHECK_TRUE(GU_BOARD_CHIP == 0x172000a1U);
    CHECK_TRUE(GuValidArchChip(0x172000a1U));
    CHECK_TRUE(GuValidArchChip(0xb72000a1U));
    CHECK_TRUE(GuValidArchChip(0xb73000a1U));
    CHECK_TRUE(GuValidArchChip(0xb74000a1U));
    CHECK_TRUE(GuValidArchChip(0xb76000a1U));
    CHECK_TRUE(GuValidArchChip(0xb77000a1U));
    CHECK_TRUE(!GuValidArchChip(0x192000a1U));
    CHECK_TRUE(!GuValidArchChip(0x162000a1U));
    puts("Ampere GA10x NV_PMC_BOOT_0 (0xb72000a1 / Samsung 8N strap bits 31:29) validation PASS");
    return 0;
}
""")
        prof_3090 = work / "prof_3090"
        prof_3090.mkdir()
        (prof_3090 / "local_profile.h").write_text("""#pragma once
#define GU_BOARD_ID 0x220410deU
#define GU_BOARD_SUBSYSTEM 0x136a196eU
#define GU_BOARD_CHIP 0x172000a1U
#define GU_ARCH_ADA 0
#define GU_ARCH_TURING 0
""")
        src_3090 = work / "src_3090"
        shutil.copytree(src, src_3090)
        shutil.copy2(prof_3090 / "local_profile.h", src_3090 / "unlock" / "local_profile.h")
        probe_3090_exe = work / "probe_3090_asan"
        subprocess.run(
            ["gcc", f"-I{prof_3090}", *asan_flags, str(probe_3090_c), "-o", str(probe_3090_exe)],
            cwd=src_3090,
            check=True,
        )
        r_3090 = subprocess.run([str(probe_3090_exe)], cwd=src_3090, capture_output=True, text=True, check=True)
        print(r_3090.stdout.strip())

        # 6. Laptop / Mobile GPU (AD106M RTX 4070 Laptop 0x282010de, 3D controller 0x030200a1, GU_IS_MOBILE_GPU=1)
        probe_laptop_c = work / "probe_laptop.c"
        probe_laptop_c.write_text("""
#include "port.h"
int puts(const char *s);
void abort(void);
#define CHECK_TRUE(cond) do { if (!(cond)) abort(); } while (0)
int main(void) {
    CHECK_TRUE(GU_IS_MOBILE_GPU == 1);
    CHECK_TRUE(GuValidArchChip(0x196000a1U));
    CHECK_TRUE(GuValidArchChip(0xb96000a1U));
    puts("Laptop / Mobile GPU (AD106M 0x282010de, GU_IS_MOBILE_GPU=1) validation PASS");
    return 0;
}
""")
        prof_laptop = work / "prof_laptop"
        prof_laptop.mkdir()
        (prof_laptop / "local_profile.h").write_text("""#pragma once
#define GU_BOARD_ID 0x282010deU
#define GU_BOARD_SUBSYSTEM 0x1e331043U
#define GU_BOARD_CHIP 0x196000a1U
#define GU_ARCH_ADA 1
#define GU_ARCH_TURING 0
#define GU_IS_MOBILE_GPU 1
""")
        src_laptop = work / "src_laptop"
        shutil.copytree(src, src_laptop)
        shutil.copy2(prof_laptop / "local_profile.h", src_laptop / "unlock" / "local_profile.h")
        probe_laptop_exe = work / "probe_laptop_asan"
        subprocess.run(
            ["gcc", f"-I{prof_laptop}", *asan_flags, str(probe_laptop_c), "-o", str(probe_laptop_exe)],
            cwd=src_laptop,
            check=True,
        )
        r_laptop = subprocess.run([str(probe_laptop_exe)], cwd=src_laptop, capture_output=True, text=True, check=True)
        print(r_laptop.stdout.strip())
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
