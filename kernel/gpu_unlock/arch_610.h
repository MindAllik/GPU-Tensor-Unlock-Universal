/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef GPU_UNLOCK_ARCH_610_H
#define GPU_UNLOCK_ARCH_610_H

enum gpu_unlock_booter_arch {
	GU_BOOTER_GA10X = 0,
	GU_BOOTER_AD10X = 1,
};

/* Exact experimental AD103 and AD104 targets; other Ada PCI IDs require their family flag. */
#define GU_AD103_RTX_4070_TI_SUPER 0x2705u
#define GU_AD104_RTX_4070_TI       0x2782u

static inline int gu_is_ad103_exp_id(unsigned short dev)
{
	return dev == 0x2702u || dev == 0x2704u || dev == 0x2705u || dev == 0x2709u;
}

static inline int gu_is_ad104_exp_id(unsigned short dev)
{
	return dev == 0x2782u || dev == 0x2783u || dev == 0x2786u || dev == 0x27b0u;
}

static inline int gu_is_other_ada_exp_id(unsigned short dev)
{
	return dev == 0x2685u || dev == 0x2689u ||
	       dev == 0x2803u || dev == 0x2805u || dev == 0x2808u ||
	       dev == 0x2882u;
}

static inline int gu_is_any_ada_id(unsigned short dev)
{
	return dev == 0x2684u || gu_is_ad103_exp_id(dev) ||
	       gu_is_ad104_exp_id(dev) || gu_is_other_ada_exp_id(dev);
}

#endif
