#ifndef GU_PROM_PROFILE_H
#define GU_PROM_PROFILE_H
/* Separated OptionRomPolicy and PromPolicy:
 * - GU_UEFI_ROM_SHA256: "AUTO" treats EFI_PCI_IO_PROTOCOL.RomImage as optional
 *   diagnostic data; a 64-hex digest enforces exact byte length and SHA-256.
 * - GU_PROM_VIEW_SHA256: "AUTO" validates the live BAR0+0x300000 ROM chain up to
 *   GU_PROM_MAX_BYTES (1 MiB), verifies BIT + Falcon Ucode Descriptor V3 +
 *   DMEMMAPPER v3 ("DMAP") + fuse signature before GOP disconnect, and binds the
 *   verified span digest to unlock_transaction_fwsec(). */
#define GU_PROM_BAR_OFFSET 0x300000U
#define GU_PROM_VIEW_BYTES 0xd6c00U
#define GU_PROM_MAX_BYTES 0x100000U
#define GU_UEFI_ROM_BYTES 0x24a00U
#define GU_PROM_VIEW_SHA256 "AUTO"
#define GU_UEFI_ROM_SHA256 "AUTO"
#endif
