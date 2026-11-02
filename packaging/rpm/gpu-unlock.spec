%global nv 610.43.03
%{!?pkg_version: %global pkg_version %(sed -n 's/^\\*\\*Version: \\([0-9.]*\\)\\*\\*$/\\1/p' README.md 2>/dev/null)}

Name: gpu-unlock
Version: %{pkg_version}
Release: 1%{?dist}
Summary: Pre-driver Tensor Core unlocker for GeForce RTX 20 (Turing), RTX 30 (Ampere), and RTX 40 (Ada) series
URL: https://github.com/MindAllik/GPU-Tensor-Unlock-Universal
License: GPL-2.0-only
BuildArch: noarch
Source0: gpu-unlock-%{version}.tar.xz
Source1: https://download.nvidia.com/XFree86/NVIDIA-kernel-module-source/NVIDIA-kernel-module-source-%{nv}.tar.xz
Source2: https://archive.cachyos.org/archive/cachyos-v3/nvidia-utils-%{nv}-1-x86_64_v3.pkg.tar.zst
# NVIDIA inputs stay out of the source RPM (it becomes a .nosrc.rpm).
NoSource: 1
NoSource: 2
BuildRequires: make
BuildRequires: gcc
BuildRequires: python3
BuildRequires: zstd

%description
Kernel module that unlocks GeForce RTX 20/30/40 FP32-accumulate tensor throughput
before the unmodified NVIDIA driver binds, opted in on the kernel command line.

%package dkms
Summary: GeForce RTX 20/30/40 tensor unlock kernel source
Requires: dkms
Requires(post): dkms
Requires(preun): dkms
Requires: gpu-unlock-firmware = %{version}-%{release}

%description dkms
DKMS source for gpu_unlock, loaded ahead of nvidia on every boot. It does
nothing unless gpu_unlock.targets= is on the kernel command line.

%package firmware
Summary: Locally generated pinned NVIDIA firmware for GPU unlock
License: LicenseRef-NVIDIA AND GPL-2.0-only

%description firmware
Firmware assets generated locally from verified upstream inputs.

%prep
sha256sum -c - <<EOF
7e118923c7a23edc36114d63273a46e3e04e9af98695a42203e7ac2dfe9fc1dc  %{SOURCE1}
e17e7c92eeffa178b0fe1f40eb17a47095f8fc3ce4a77bf115cf5bd5a4df86e9  %{SOURCE2}
EOF
%autosetup
test "$(sed -n 's/^\*\*Version: \([0-9.]*\)\*\*$/\1/p' README.md)" = "%{version}"

%build
%make_build INPUTS=%{_sourcedir} ASSETS="$PWD/assets" firmware

%check
make test ASSETS="$PWD/assets"

%install
make DESTDIR=%{buildroot} ASSETS="$PWD/assets" \
    install-dkms install-firmware install-dracut

%files dkms
%license licenses/GPL-2.0.txt licenses/CMP40HX-MIT.txt licenses/NVIDIA-MIT.txt
%doc %{_docdir}/gpu-unlock
%{_usrsrc}/gpu-unlock-%{version}
%{_prefix}/lib/dracut/dracut.conf.d/gpu-unlock.conf

%files firmware
%license %{_defaultlicensedir}/gpu-unlock-firmware
%{_prefix}/lib/firmware/gpu-unlock

%post dkms
for d in /var/lib/dkms/gpu-unlock/[0-9]*; do
    [ -d "$d" ] && [ "${d##*/}" != %{version} ] &&
        dkms remove -m gpu-unlock -v "${d##*/}" --all || :
done
dkms add -m gpu-unlock -v %{version} --rpm_safe_upgrade || :

%preun dkms
if [ -d /var/lib/dkms/gpu-unlock/%{version} ]; then
    dkms remove -m gpu-unlock -v %{version} --all --rpm_safe_upgrade || :
fi

%posttrans dkms
kernels=
for b in /lib/modules/*/build; do
    [ -d "$b" ] || continue
    k=${b%/build}; k=${k##*/}
    dkms build -m gpu-unlock -v %{version} -k "$k" --force && kernels="$kernels -k $k"
done
[ -n "$kernels" ] && dkms install -m gpu-unlock -v %{version} $kernels --force || :
if command -v dracut >/dev/null &&
    ! grep -qs '^post_transaction=.*dracut' /etc/dkms/framework.conf \
        /etc/dkms/framework.conf.d/*.conf; then
    for d in /lib/modules/*/; do
        k=${d%/}; k=${k##*/}
        modinfo -k "$k" gpu_unlock >/dev/null 2>&1 &&
            dracut --force --kver "$k" || :
    done
fi

%postun dkms
if [ "$1" -eq 0 ]; then
    for l in /lib/modules/*/weak-updates/gpu_unlock.ko*; do
        [ -L "$l" ] || continue
        rm -f "$l"
        k=${l%/weak-updates/*}; depmod -a "${k##*/}" || :
    done
    if command -v lsinitrd >/dev/null; then
        for d in /lib/modules/*/; do
            k=${d%/}; k=${k##*/}
            lsinitrd --kver "$k" 2>/dev/null | grep -q gpu_unlock &&
                dracut --force --kver "$k" || :
        done
    fi
fi

%changelog
* Sat Oct 31 2026 MindAllik <MindAllik@users.noreply.github.com> - %{version}-1
- Add RTX 20-series (Turing), RTX 30-series (Ampere), and RTX 40-series (Ada) support.
