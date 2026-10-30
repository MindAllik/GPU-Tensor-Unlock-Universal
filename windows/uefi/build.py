#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib, json, subprocess

p = argparse.ArgumentParser()
p.add_argument('--enable-experiment', action='store_true')
p.add_argument('--clang', default='clang', help='Path or name of clang compiler executable')
p.add_argument('--linker', default='lld-link', help='Path or name of lld-link executable')
p.add_argument('--profile-dir', type=Path, default=None,
               help='Optional directory containing generated local_profile.h and prom_profile.h')
p.add_argument('--build-dir', type=Path, default=None,
               help='Optional output directory for object files and BOOTX64.EFI')
a = p.parse_args()

root = Path(__file__).resolve().parent / 'source'
profile_dir = a.profile_dir.resolve() if a.profile_dir else (root / 'unlock')
local_prof = profile_dir / 'local_profile.h'
if a.enable_experiment and '0,0,0,{0,0,0,0,0,0,0,0}' in local_prof.read_text():
    p.error('Set reviewed local Windows ESP GUID in local_profile.h first')

out = a.build_dir.resolve() if a.build_dir else (root / 'build')
out.mkdir(parents=True, exist_ok=True)

names = [
    'app', 'app_io', 'ownership', 'format', 'runtime', 'sha256',
    'checks', 'port', 'compat', 'vendor/unlock_610', 'vendor/prep_610',
    'vendor/layout_610', 'vendor/vbios_610', 'vendor/gfw_eval'
]
flags = [
    '--target=x86_64-pc-windows-msvc', '-c', '-std=c11', '-ffreestanding',
    '-fno-builtin', '-fno-stack-protector', '-mno-red-zone', '-fshort-wchar',
    '-Os', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
    '-D__KERNEL__', '-DGU_UEFI_PORT', '-DGU_TARGET_PCI_ID=GU_BOARD_ID',
]
if a.profile_dir:
    flags += [f'-I{profile_dir}']
flags += [
    '-Iunlock', '-Iunlock/compat',
    '-Ideps/edk2/MdePkg/Include', '-Ideps/edk2/MdePkg/Include/X64'
]
if a.enable_experiment:
    flags += ['-DKOH_ENABLE_EXPERIMENT=1']

objects = []
for name in names:
    obj = out / (name.replace('/', '_') + '.obj')
    subprocess.run([a.clang, *flags, f'unlock/{name}.c', '-o', str(obj)], cwd=root, check=True)
    objects.append(str(obj))

efi_out = out / 'BOOTX64.EFI'
subprocess.run([
    a.linker, '/subsystem:efi_application', '/nodefaultlib',
    '/entry:EfiMain', *objects, f'/out:{efi_out}'
], cwd=root, check=True)

efi_bytes = efi_out.read_bytes()
print(json.dumps({
    'path': str(efi_out),
    'size': len(efi_bytes),
    'sha256': hashlib.sha256(efi_bytes).hexdigest(),
}))
