/* SPDX-License-Identifier: GPL-2.0-only */
/* Universal NVIDIA Ada Lovelace (AD10x) & Ampere (GA10x) UEFI Port */
#pragma once
#include <Uefi.h>
#include <Protocol/PciIo.h>
#include <Protocol/DevicePath.h>
#include <stddef.h>
#include "local_profile.h"

#ifndef GU_BOARD_ID
#define GU_BOARD_ID 0x278210deU
#endif
#ifndef GU_BOARD_SUBSYSTEM
#define GU_BOARD_SUBSYSTEM 0xf2941569U
#endif
#ifndef GU_BOARD_CHIP
#define GU_BOARD_CHIP 0x194000a1U
#endif
#ifndef GU_BOARD_SEGMENT
#define GU_BOARD_SEGMENT 0U
#endif
#ifndef GU_BOARD_BUS
#define GU_BOARD_BUS 0x01U
#endif
#ifndef GU_BOARD_DEVICE
#define GU_BOARD_DEVICE 0U
#endif
#ifndef GU_BOARD_FUNCTION
#define GU_BOARD_FUNCTION 0U
#endif
#ifndef GU_BOARD_CLASS_REV
#define GU_BOARD_CLASS_REV 0x030000a1U
#endif
#ifndef GU_VRAM_MIN_MIB
#define GU_VRAM_MIN_MIB 0x2ff0U
#endif
#ifndef GU_VRAM_MAX_MIB
#define GU_VRAM_MAX_MIB 0x3000U
#endif
#ifndef GU_ARCH_ADA
#define GU_ARCH_ADA 1
#endif
#ifndef GU_EXPECTED_COLD_PLM
#define GU_EXPECTED_COLD_PLM 0xffffff8fU
#endif
#ifndef GU_EXPECTED_POST_FLR_PLM
#define GU_EXPECTED_POST_FLR_PLM 0xffffffffU
#endif
#ifndef KOH_WINDOWS_ESP_PART
#define KOH_WINDOWS_ESP_PART 0U
#endif
#ifndef KOH_UNATTENDED_AUTOFIRE
#define KOH_UNATTENDED_AUTOFIRE 0
#endif

typedef enum {
  GU_COLD_OK = 0,
  GU_COLD_UNREADABLE = 1,
  GU_COLD_INITIALIZED_WPR = 2,
  GU_COLD_ALREADY_MODIFIED = 3,
  GU_COLD_PARTIALLY_MODIFIED = 4,
  GU_COLD_UNKNOWN_PROFILE_STATE = 5
} GU_COLD_STATE;

typedef struct GU_DMA GU_DMA;
struct GU_DMA {
  GU_DMA *next;
  VOID *cpu;
  VOID *mapping;
  UINT64 dma;
  UINTN bytes;
  UINTN pages;
  BOOLEAN mapped;
};
typedef struct {
  EFI_BOOT_SERVICES *bs;
  EFI_PCI_IO_PROTOCOL *pci;
  EFI_HANDLE image, handle;
  UINT64 bar_base, bar_size, ticks;
  UINT16 pm_cap, pcie_cap, msi_cap, msix_cap, saved_devctl, saved_devctl2;
  UINT8 pcie_version;
  UINT32 saved_config[64];
  BOOLEAN saved, owned, armed, display_ok, started, quiesced, fault, retained;
  BOOLEAN master_attributes_pending;
  UINT64 master_original_attributes;
  UINT16 master_original_command;
  EFI_PCI_IO_PROTOCOL *master_pci;
  EFI_STATUS master_attribute_status, master_hardware_status;
  UINT64 master_last_attributes;
  UINT16 master_last_command;
  BOOLEAN (*display_check)(VOID);
  BOOLEAN (*verify_prom_span)(const VOID *Prom, UINTN SpanBytes);
  UINT32 dma_count, mmio_writes, flrs;
  GU_DMA *allocations;
} GU_PLATFORM;
extern GU_PLATFORM Gu;

#ifndef GU_ALLOW_ARCH_CHIP_FAMILY
#define GU_ALLOW_ARCH_CHIP_FAMILY 0
#endif

static inline BOOLEAN GuValidArchChip(UINT32 Chip) {
  if (Chip == GU_BOARD_CHIP) return TRUE;
#if GU_ALLOW_ARCH_CHIP_FAMILY
#if !defined(GU_ARCH_ADA) || GU_ARCH_ADA
  UINT32 arch = (Chip >> 20) & 0xfffU;
  return (Chip & 0xffU) == 0xa1U &&
         (arch == 0x192U || arch == 0x193U || arch == 0x194U || arch == 0x196U || arch == 0x197U);
#else
  UINT32 arch = (Chip >> 20) & 0xfffU;
  return (Chip & 0xffU) == 0xa1U &&
         (arch == 0x172U || arch == 0x173U || arch == 0x174U || arch == 0x176U || arch == 0x177U);
#endif
#else
  return FALSE;
#endif
}

static inline BOOLEAN GuInaccessible32(UINT32 V) {
  return V == 0xffffffffU || (V & 0xffff0000U) == 0xbadf0000U;
}

static inline GU_COLD_STATE GuClassifyColdState(UINT32 Plm, UINT32 Ss0, UINT32 Ss1, UINT32 WprHi) {
  if (GuInaccessible32(Ss0) || Ss1 == 0xffffffffU || GuInaccessible32(WprHi) ||
      (Plm & 0xffff0000U) == 0xbadf0000U) {
    return GU_COLD_UNREADABLE;
  }
  if ((WprHi >> 4) != 0U) {
    return GU_COLD_INITIALIZED_WPR;
  }
  BOOLEAN ss0_unlocked = (Ss0 == 0x88888888U);
  BOOLEAN ss1_unlocked = (Ss1 == 8U);
  if (Plm == 0xffffffffU && ss0_unlocked && ss1_unlocked) {
    return GU_COLD_ALREADY_MODIFIED;
  }
  if (ss0_unlocked || ss1_unlocked || (Ss0 & 0x88888888U) != 0U || (Ss1 & ~7U) != 0U) {
    return GU_COLD_PARTIALLY_MODIFIED;
  }
  if (Plm != GU_EXPECTED_COLD_PLM || (Ss1 & 7U) == 0U) {
    return GU_COLD_UNKNOWN_PROFILE_STATE;
  }
  return GU_COLD_OK;
}

VOID GuInit(EFI_BOOT_SERVICES *Bs, EFI_PCI_IO_PROTOCOL *Pci);
BOOLEAN GuTargetConfig(const UINT32 *Config, UINTN Segment, UINTN Bus, UINTN Device, UINTN Function);
BOOLEAN GuSafeToReturn(VOID);
VOID *GuAlloc(size_t Bytes);
VOID GuFree(VOID *Memory);
VOID GuStarted(VOID);
VOID GuQuiesced(VOID);
EFI_STATUS GuDmaAllocate(UINTN Bytes, VOID **Cpu, UINT64 *Dma);
EFI_STATUS GuDmaFree(VOID *Cpu, UINT64 Dma);
UINT32 GuRead32(UINT32 Offset);
VOID GuWrite32(UINT32 Offset, UINT32 Value);
EFI_STATUS GuConfigRead(EFI_PCI_IO_PROTOCOL_WIDTH Width, UINT32 Offset, VOID *Value);
EFI_STATUS GuConfigWrite(EFI_PCI_IO_PROTOCOL_WIDTH Width, UINT32 Offset, VOID *Value);
VOID GuStall(UINTN Microseconds);
EFI_STATUS GuEnableMaster(VOID);
EFI_STATUS GuClearMaster(VOID);
EFI_STATUS GuSavePci(VOID);
EFI_STATUS GuFlr(VOID);
EFI_STATUS GuRestorePci(VOID);
VOID GuLog(const char *Format, ...);
VOID GuLogText(const char *Text);
VOID GuConsole(const char *Text);
BOOLEAN GuLogReady(VOID);
BOOLEAN GuVerifyPreparedPromSpan(const VOID *Prom, UINTN SpanBytes);
VOID GuCopyFromIo(VOID *Destination, const VOID *Source, size_t Bytes);
