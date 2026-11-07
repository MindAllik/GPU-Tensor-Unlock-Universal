/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef GPU_UNLOCK_ARCH_610_H
#define GPU_UNLOCK_ARCH_610_H

enum gpu_unlock_booter_arch {
	GU_BOOTER_GA10X = 0,
	GU_BOOTER_AD10X = 1,
	GU_BOOTER_TU10X = 2,
};

/* Exact experimental AD103 and AD104 targets; other Ada/Turing PCI IDs require their family flag. */
#define GU_AD103_RTX_4070_TI_SUPER 0x2705u
#define GU_AD104_RTX_4070_TI       0x2782u

static inline int gu_is_ad103_exp_id(unsigned short dev)
{
	return dev == 0x2702u || dev == 0x2703u || dev == 0x2704u ||
	       dev == 0x2705u || dev == 0x2709u;
}

static inline int gu_is_ad104_exp_id(unsigned short dev)
{
	return dev == 0x2782u || dev == 0x2783u || dev == 0x2786u ||
	       dev == 0x2788u || dev == 0x27b0u || dev == 0x27b2u;
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

static inline int gu_is_turing_exp_id(unsigned short dev)
{
	/* TU102: TITAN RTX, RTX 2080 Ti, CMP 50HX */
	if (dev == 0x1e02u || dev == 0x1e03u || dev == 0x1e04u ||
	    dev == 0x1e07u || dev == 0x1e09u || dev == 0x1e2du || dev == 0x1e2eu)
		return 1;
	/* TU104: RTX 2080 SUPER, RTX 2080, RTX 2070 SUPER, RTX 2060 KO */
	if (dev == 0x1e81u || dev == 0x1e82u || dev == 0x1e84u ||
	    dev == 0x1e87u || dev == 0x1e89u || dev == 0x1ec2u || dev == 0x1ec7u)
		return 1;
	/* TU106: RTX 2070, RTX 2060 SUPER, RTX 2060 12GB/6GB, CMP 40HX */
	if (dev == 0x1f02u || dev == 0x1f03u || dev == 0x1f06u ||
	    dev == 0x1f07u || dev == 0x1f08u || dev == 0x1f0au ||
	    dev == 0x1f0bu || dev == 0x1f42u || dev == 0x1f47u)
		return 1;
	return 0;
}

static inline int gu_is_any_turing_id(unsigned short dev)
{
	return gu_is_turing_exp_id(dev);
}

#endif
