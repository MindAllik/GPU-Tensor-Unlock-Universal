#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Live CUDA Driver API PTX JIT Tensor Core Benchmark (Before vs. After Comparison)
Supports NVIDIA Ada Lovelace (sm_89) and Ampere (sm_86) on Windows 10 / 11."""

from __future__ import annotations

import ctypes
import json
import math
import os
import statistics
import struct
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

APP_ROOT = Path(__file__).resolve().parent
HISTORY_FILE = APP_ROOT / "benchmark_history.json"
HISTORY_SCHEMA_VERSION = 2
ITER_SIGNATURE_MAGIC = 0x67B05A5A


class CudaBenchmarkError(RuntimeError):
    """Raised when a CUDA Driver API call, device identity check, or numerical verification fails."""


def _check_cu(result: int, op: str) -> None:
    if int(result) != 0:
        raise CudaBenchmarkError(f"CUDA Driver API error in {op}: CUresult={int(result)}")


def _load_nvcuda() -> ctypes.CDLL | None:
    candidates = [r"C:\Windows\System32\nvcuda.dll", "nvcuda.dll", "libcuda.so.1"]
    for name in candidates:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


def _build_ptx_kernel(
    sm_target: str,
    func_name: str,
    body_inst: str,
    regs_decl: str,
    init_regs: str,
    epilogue_inst: str,
    ptx_version: str = "8.0",
    unroll: int = 32,
) -> bytes:
    """Build PTX kernel with 2 independent MMA accumulator chains per warp and deterministic dual-word writeback:
    - out[tid]      = non-zero accumulator result %r10
    - out[tid + 32] = iteration signature (%r2 ^ 0x67b05a5a)
    """
    unrolled = "\n    ".join([body_inst] * unroll)
    ptx = f"""
.version {ptx_version}
.target {sm_target}
.address_size 64

.visible .entry {func_name}(
    .param .u64 out_ptr,
    .param .u32 iters
)
{{
    .reg .pred %p<3>;
    .reg .b32 %r<16>;
    .reg .b64 %rd<4>;
    {regs_decl}

    ld.param.u64 %rd1, [out_ptr];
    ld.param.u32 %r1, [iters];
    setp.eq.u32 %p2, %r1, 0;
    @%p2 bra DONE;

    {init_regs}
    mov.u32 %r2, 0;

LOOP:
    {unrolled}
    add.u32 %r2, %r2, 1;
    setp.lt.u32 %p1, %r2, %r1;
    @%p1 bra LOOP;

DONE:
    {epilogue_inst}
    mov.u32 %r3, %tid.x;
    mov.u32 %r4, %ctaid.x;
    setp.eq.u32 %p1, %r4, 0;
    @!%p1 bra EXIT;
    setp.lt.u32 %p1, %r3, 32;
    @!%p1 bra EXIT;
    mul.wide.u32 %rd2, %r3, 4;
    add.u64 %rd3, %rd1, %rd2;
    st.global.u32 [%rd3], %r10;
    xor.b32 %r11, %r2, {ITER_SIGNATURE_MAGIC:#010x};
    st.global.u32 [%rd3+128], %r11;

EXIT:
    ret;
}}
"""
    return ptx.encode("ascii") + b"\x00"


def _query_device_uuid(cuda: ctypes.CDLL, dev: ctypes.c_int) -> str | None:
    uuid_fn = getattr(cuda, "cuDeviceGetUuid_v2", None) or getattr(cuda, "cuDeviceGetUuid", None)
    if uuid_fn is None:
        return None
    raw = (ctypes.c_ubyte * 16)()
    if uuid_fn(ctypes.byref(raw), dev) != 0:
        return None
    b = bytes(raw)
    hex_s = b.hex()
    return f"GPU-{hex_s[0:8]}-{hex_s[8:12]}-{hex_s[12:16]}-{hex_s[16:20]}-{hex_s[20:32]}"


def _query_device_bdf(cuda: ctypes.CDLL, dev: ctypes.c_int) -> str:
    if hasattr(cuda, "cuDeviceGetPCIBusId"):
        buf = ctypes.create_string_buffer(32)
        if cuda.cuDeviceGetPCIBusId(buf, 32, dev) == 0 and buf.value:
            return buf.value.decode("ascii", errors="replace").strip().lower()

    def _attr(aid: int) -> int:
        v = ctypes.c_int(0)
        _check_cu(cuda.cuDeviceGetAttribute(ctypes.byref(v), aid, dev), f"cuDeviceGetAttribute({aid})")
        return v.value

    bus = _attr(33)
    dnum = _attr(34)
    dom = _attr(50)
    return f"{dom:04x}:{bus:02x}:{dnum:02x}.0"


def _resolve_target_device(
    cuda: ctypes.CDLL,
    target_bdf: str | None,
    target_uuid: str | None,
) -> tuple[ctypes.c_int, str, str]:
    """Resolve and verify the exact CUDA device matching target_bdf and/or target_uuid."""
    dev = ctypes.c_int(0)
    if target_bdf:
        if not hasattr(cuda, "cuDeviceGetByPCIBusId"):
            raise CudaBenchmarkError("CUDA library does not support cuDeviceGetByPCIBusId for explicit target_bdf")
        bdf_bytes = target_bdf.strip().encode("ascii") + b"\x00"
        _check_cu(cuda.cuDeviceGetByPCIBusId(ctypes.byref(dev), bdf_bytes), f"cuDeviceGetByPCIBusId({target_bdf})")
    else:
        _check_cu(cuda.cuDeviceGet(ctypes.byref(dev), 0), "cuDeviceGet(0)")

    actual_bdf = _query_device_bdf(cuda, dev)
    if target_bdf and target_bdf.strip().lower() != actual_bdf.lower():
        raise CudaBenchmarkError(f"Target BDF mismatch: requested {target_bdf}, resolved {actual_bdf}")

    actual_uuid = _query_device_uuid(cuda, dev)
    if target_uuid:
        if not actual_uuid:
            raise CudaBenchmarkError(
                f"Cannot verify requested target_uuid={target_uuid}: CUDA driver does not expose cuDeviceGetUuid"
            )
        if actual_uuid.lower() != target_uuid.strip().lower():
            raise CudaBenchmarkError(f"Target UUID mismatch: requested {target_uuid}, device reported {actual_uuid}")

    return dev, (actual_uuid or ""), actual_bdf


def _verify_kernel_output_buffer(host_buf: Any, iters_val: int, is_float_kernel: bool, key: str) -> None:
    """Verify both the deterministic iteration signature in words [32..63] and valid finite non-garbage accumulator values in [0..31]."""
    expected_sig = (iters_val ^ ITER_SIGNATURE_MAGIC) & 0xFFFFFFFF
    sigs = [int(host_buf[32 + i]) & 0xFFFFFFFF for i in range(32)]
    if any(s != expected_sig for s in sigs):
        raise CudaBenchmarkError(
            f"Kernel {key} failed iteration signature verification: expected {expected_sig:#010x}, got {sigs[0]:#010x}"
        )

    vals = [int(host_buf[i]) & 0xFFFFFFFF for i in range(32)]
    if all(v == 0 for v in vals) or all(v == 0x5A5A5A5A for v in vals):
        raise CudaBenchmarkError(f"Kernel {key} failed numerical accumulator verification (zero or constant pattern)")

    if is_float_kernel:
        for v in vals:
            # Subtract iters_val added in epilogue to inspect the raw IEEE-754 accumulator bits
            raw_bits = (v - iters_val) & 0xFFFFFFFF
            fval = struct.unpack("<f", struct.pack("<I", raw_bits))[0]
            if not math.isfinite(fval) or fval <= 1.0:
                raise CudaBenchmarkError(f"Kernel {key} produced non-finite or non-accumulating float value: {fval}")


def run_tensor_benchmark(
    log_fn: Callable[[str], None] = print,
    target_bdf: str | None = None,
    target_uuid: str | None = None,
) -> dict[str, Any]:
    """Run PTX JIT Tensor Core microbenchmarks with strict CUDA error checking, UUID/BDF verification, and numerical output validation."""
    cuda = _load_nvcuda()
    if cuda is None:
        raise CudaBenchmarkError("CUDA Driver API (nvcuda.dll) not found. Ensure NVIDIA display driver is installed.")

    # Both cuMemsetD32_v2 and cuMemcpyDtoH_v2 are mandatory for numerical verification
    if not hasattr(cuda, "cuMemcpyDtoH_v2") or not hasattr(cuda, "cuMemsetD32_v2"):
        raise CudaBenchmarkError("CUDA Driver API is missing required cuMemsetD32_v2 / cuMemcpyDtoH_v2 verification symbols.")

    _check_cu(cuda.cuInit(0), "cuInit(0)")
    dev, actual_uuid, actual_bdf = _resolve_target_device(cuda, target_bdf, target_uuid)

    name_buf = ctypes.create_string_buffer(128)
    _check_cu(cuda.cuDeviceGetName(name_buf, 128, dev), "cuDeviceGetName")
    gpu_name = name_buf.value.decode("utf-8", errors="replace")

    def get_attr(attr_id: int) -> int:
        val = ctypes.c_int(0)
        _check_cu(cuda.cuDeviceGetAttribute(ctypes.byref(val), attr_id, dev), f"cuDeviceGetAttribute({attr_id})")
        return val.value

    sm_count = get_attr(16)       # CU_DEVICE_ATTRIBUTE_MULTIPROCESSOR_COUNT
    cc_major = get_attr(75)       # CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MAJOR
    cc_minor = get_attr(76)       # CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MINOR
    clock_khz = get_attr(13)      # CU_DEVICE_ATTRIBUTE_CLOCK_RATE

    cc_str = f"{cc_major}{cc_minor}"
    # Explicitly restrict to supported Ampere (sm_86) and Ada Lovelace (sm_89)
    if cc_str not in ("86", "89"):
        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gpu_name": gpu_name,
            "gpu_uuid": actual_uuid,
            "pci_bdf": actual_bdf,
            "compute_capability": f"sm_{cc_str}",
            "sm_count": sm_count,
            "boost_clock_mhz": round(clock_khz / 1000.0, 1),
            "status": "UNSUPPORTED",
            "throttled": None,
            "correctness_verified": False,
            "f16_to_f32_ratio": "N/A",
            "status_text": f"UNSUPPORTED ARCHITECTURE (sm_{cc_str}; requires sm_86 or sm_89)",
            "metrics": {},
        }

    sm_target = f"sm_{cc_str}"
    ctx = ctypes.c_void_p()
    _check_cu(cuda.cuCtxCreate_v2(ctypes.byref(ctx), 0, dev), "cuCtxCreate_v2")

    out_bytes = 256
    d_out = ctypes.c_ulonglong(0)
    allocated = False
    first_cleanup_err: Exception | None = None
    try:
        _check_cu(cuda.cuMemAlloc_v2(ctypes.byref(d_out), out_bytes), "cuMemAlloc_v2")
        allocated = True

        specs = [
            (
                "f16_acc_f16",
                "FP16 -> FP16 accumulate (FMLA16)",
                "FMLA16",
                "TFLOP/s",
                "8.0",
                (
                    "mma.sync.aligned.m16n8k16.row.col.f16.f16.f16.f16 {%h0, %h1}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%h0, %h1};\n    "
                    "mma.sync.aligned.m16n8k16.row.col.f16.f16.f16.f16 {%h2, %h3}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%h2, %h3};"
                ),
                ".reg .b32 %h<4>, %a<4>, %b<2>;",
                "mov.b32 %h0, 0x3c003c00; mov.b32 %h1, 0x3c003c00; mov.b32 %h2, 0x3c003c00; mov.b32 %h3, 0x3c003c00; mov.b32 %a0, 0x38003800; mov.b32 %a1, 0x38003800; mov.b32 %a2, 0x38003800; mov.b32 %a3, 0x38003800; mov.b32 %b0, 0x38003800; mov.b32 %b1, 0x38003800;",
                "xor.b32 %r8, %h0, %h1; xor.b32 %r9, %h2, %h3; add.u32 %r10, %r8, %r9; add.u32 %r10, %r10, %r2;",
                8192,
                True,
                False,
            ),
            (
                "f16_acc_f32",
                "FP16 -> FP32 accumulate (FMLA32)",
                "FMLA32",
                "TFLOP/s",
                "8.0",
                (
                    "mma.sync.aligned.m16n8k16.row.col.f32.f16.f16.f32 {%f0, %f1, %f2, %f3}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%f0, %f1, %f2, %f3};\n    "
                    "mma.sync.aligned.m16n8k16.row.col.f32.f16.f16.f32 {%f4, %f5, %f6, %f7}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%f4, %f5, %f6, %f7};"
                ),
                ".reg .f32 %f<8>; .reg .b32 %a<4>, %b<2>;",
                "mov.f32 %f0, 0f3f800000; mov.f32 %f1, 0f3f800000; mov.f32 %f2, 0f3f800000; mov.f32 %f3, 0f3f800000; mov.f32 %f4, 0f3f800000; mov.f32 %f5, 0f3f800000; mov.f32 %f6, 0f3f800000; mov.f32 %f7, 0f3f800000; mov.b32 %a0, 0x38003800; mov.b32 %a1, 0x38003800; mov.b32 %a2, 0x38003800; mov.b32 %a3, 0x38003800; mov.b32 %b0, 0x38003800; mov.b32 %b1, 0x38003800;",
                "add.f32 %f0, %f0, %f4; mov.b32 %r10, %f0; add.u32 %r10, %r10, %r2;",
                8192,
                True,
                True,
            ),
            (
                "bf16_acc_f32",
                "BF16 -> FP32 accumulate (FMLA32)",
                "FMLA32",
                "TFLOP/s",
                "8.0",
                (
                    "mma.sync.aligned.m16n8k16.row.col.f32.bf16.bf16.f32 {%f0, %f1, %f2, %f3}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%f0, %f1, %f2, %f3};\n    "
                    "mma.sync.aligned.m16n8k16.row.col.f32.bf16.bf16.f32 {%f4, %f5, %f6, %f7}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%f4, %f5, %f6, %f7};"
                ),
                ".reg .f32 %f<8>; .reg .b32 %a<4>, %b<2>;",
                "mov.f32 %f0, 0f3f800000; mov.f32 %f1, 0f3f800000; mov.f32 %f2, 0f3f800000; mov.f32 %f3, 0f3f800000; mov.f32 %f4, 0f3f800000; mov.f32 %f5, 0f3f800000; mov.f32 %f6, 0f3f800000; mov.f32 %f7, 0f3f800000; mov.b32 %a0, 0x3f003f00; mov.b32 %a1, 0x3f003f00; mov.b32 %a2, 0x3f003f00; mov.b32 %a3, 0x3f003f00; mov.b32 %b0, 0x3f003f00; mov.b32 %b1, 0x3f003f00;",
                "add.f32 %f0, %f0, %f4; mov.b32 %r10, %f0; add.u32 %r10, %r10, %r2;",
                8192,
                False,
                True,
            ),
            (
                "tf32_acc_f32",
                "TF32 -> FP32 accumulate (FMLA32)",
                "FMLA32",
                "TFLOP/s",
                "8.0",
                (
                    "mma.sync.aligned.m16n8k8.row.col.f32.tf32.tf32.f32 {%f0, %f1, %f2, %f3}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%f0, %f1, %f2, %f3};\n    "
                    "mma.sync.aligned.m16n8k8.row.col.f32.tf32.tf32.f32 {%f4, %f5, %f6, %f7}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%f4, %f5, %f6, %f7};"
                ),
                ".reg .f32 %f<8>; .reg .b32 %a<4>, %b<2>;",
                "mov.f32 %f0, 0f3f800000; mov.f32 %f1, 0f3f800000; mov.f32 %f2, 0f3f800000; mov.f32 %f3, 0f3f800000; mov.f32 %f4, 0f3f800000; mov.f32 %f5, 0f3f800000; mov.f32 %f6, 0f3f800000; mov.f32 %f7, 0f3f800000; mov.b32 %a0, 0x3f000000; mov.b32 %a1, 0x3f000000; mov.b32 %a2, 0x3f000000; mov.b32 %a3, 0x3f000000; mov.b32 %b0, 0x3f000000; mov.b32 %b1, 0x3f000000;",
                "add.f32 %f0, %f0, %f4; mov.b32 %r10, %f0; add.u32 %r10, %r10, %r2;",
                4096,
                False,
                True,
            ),
            (
                "fp8_e4m3_acc_f32",
                "FP8 (E4M3) -> FP32 accumulate (FMLA32)",
                "FMLA32",
                "TFLOP/s",
                "8.4",
                (
                    "mma.sync.aligned.m16n8k32.row.col.f32.e4m3.e4m3.f32 {%f0, %f1, %f2, %f3}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%f0, %f1, %f2, %f3};\n    "
                    "mma.sync.aligned.m16n8k32.row.col.f32.e4m3.e4m3.f32 {%f4, %f5, %f6, %f7}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%f4, %f5, %f6, %f7};"
                ),
                ".reg .f32 %f<8>; .reg .b32 %a<4>, %b<2>;",
                "mov.f32 %f0, 0f3f800000; mov.f32 %f1, 0f3f800000; mov.f32 %f2, 0f3f800000; mov.f32 %f3, 0f3f800000; mov.f32 %f4, 0f3f800000; mov.f32 %f5, 0f3f800000; mov.f32 %f6, 0f3f800000; mov.f32 %f7, 0f3f800000; mov.b32 %a0, 0x38383838; mov.b32 %a1, 0x38383838; mov.b32 %a2, 0x38383838; mov.b32 %a3, 0x38383838; mov.b32 %b0, 0x38383838; mov.b32 %b1, 0x38383838;",
                "add.f32 %f0, %f0, %f4; mov.b32 %r10, %f0; add.u32 %r10, %r10, %r2;",
                16384,
                False,
                True,
            ),
            (
                "s8_acc_s32",
                "INT8 -> INT32 accumulate (IMLA1)",
                "IMLA1",
                "TOP/s",
                "8.0",
                (
                    "mma.sync.aligned.m16n8k32.row.col.s32.s8.s8.s32 {%s0, %s1, %s2, %s3}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%s0, %s1, %s2, %s3};\n    "
                    "mma.sync.aligned.m16n8k32.row.col.s32.s8.s8.s32 {%s4, %s5, %s6, %s7}, {%a0, %a1, %a2, %a3}, {%b0, %b1}, {%s4, %s5, %s6, %s7};"
                ),
                ".reg .s32 %s<8>; .reg .b32 %a<4>, %b<2>;",
                "mov.s32 %s0, 1; mov.s32 %s1, 1; mov.s32 %s2, 1; mov.s32 %s3, 1; mov.s32 %s4, 1; mov.s32 %s5, 1; mov.s32 %s6, 1; mov.s32 %s7, 1; mov.b32 %a0, 0x01010101; mov.b32 %a1, 0x01010101; mov.b32 %a2, 0x01010101; mov.b32 %a3, 0x01010101; mov.b32 %b0, 0x01010101; mov.b32 %b1, 0x01010101;",
                "add.s32 %s0, %s0, %s4; mov.b32 %r10, %s0; add.u32 %r10, %r10, %r2;",
                16384,
                False,
                False,
            ),
            (
                "scalar_ffma_f32",
                "Scalar FP32 FMA (CUDA Cores, FFMA)",
                "FFMA",
                "TFLOP/s",
                "8.0",
                "fma.rn.f32 %f0, %f0, %f1, %f2; fma.rn.f32 %f3, %f3, %f1, %f2; fma.rn.f32 %f4, %f4, %f1, %f2; fma.rn.f32 %f5, %f5, %f1, %f2;",
                ".reg .f32 %f<8>;",
                "mov.f32 %f0, 0f3f800000; mov.f32 %f1, 0f3f800000; mov.f32 %f2, 0f3dcccccd; mov.f32 %f3, 0f3f800000; mov.f32 %f4, 0f3f800000; mov.f32 %f5, 0f3f800000;",
                "add.f32 %f0, %f0, %f3; add.f32 %f4, %f4, %f5; add.f32 %f0, %f0, %f4; mov.b32 %r10, %f0; add.u32 %r10, %r10, %r2;",
                256,
                False,
                True,
            ),
        ]

        grid_x = max(1, sm_count * 8)
        block_x = 256
        warps_total = (grid_x * block_x) // 32
        unroll = 32
        iters_val = 20000

        results: dict[str, Any] = {}
        all_verified = True

        for key, label, fuse, unit, ptx_ver, inst, regs, init_r, epilogue, ops_per_inst, required, is_float in specs:
            if key.startswith("fp8_") and cc_str != "89":
                results[key] = {
                    "label": label,
                    "fuse": fuse,
                    "unit": unit,
                    "status": "UNSUPPORTED_ARCH",
                    "best": None,
                    "median": None,
                    "stdev": None,
                    "runs": [],
                }
                continue

            ptx_bytes = _build_ptx_kernel(
                sm_target, f"bench_{key}", inst, regs, init_r, epilogue, ptx_version=ptx_ver, unroll=unroll
            )
            mod = ctypes.c_void_p()
            err = cuda.cuModuleLoadData(ctypes.byref(mod), ptx_bytes)
            if err != 0:
                if required:
                    raise CudaBenchmarkError(f"Required kernel {key} failed PTX JIT load: CUresult={err}")
                results[key] = {
                    "label": label,
                    "fuse": fuse,
                    "unit": unit,
                    "status": f"SKIPPED_JIT_ERR_{err}",
                    "best": None,
                    "median": None,
                    "stdev": None,
                    "runs": [],
                }
                continue

            try:
                func = ctypes.c_void_p()
                _check_cu(cuda.cuModuleGetFunction(ctypes.byref(func), mod, f"bench_{key}".encode("ascii")), f"cuModuleGetFunction({key})")
                _check_cu(cuda.cuMemsetD32_v2(d_out, 0, out_bytes // 4), f"cuMemsetD32_v2(warmup:{key})")

                arg_ptr = ctypes.c_ulonglong(d_out.value)
                arg_iters = ctypes.c_uint(iters_val)
                kernel_params = (ctypes.c_void_p * 2)(
                    ctypes.cast(ctypes.byref(arg_ptr), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(arg_iters), ctypes.c_void_p),
                )

                # Warmup launch + output verification
                _check_cu(
                    cuda.cuLaunchKernel(func, grid_x, 1, 1, block_x, 1, 1, 0, None, kernel_params, None),
                    f"cuLaunchKernel(warmup:{key})",
                )
                _check_cu(cuda.cuCtxSynchronize(), f"cuCtxSynchronize(warmup:{key})")

                host_buf = (ctypes.c_uint32 * (out_bytes // 4))()
                _check_cu(cuda.cuMemcpyDtoH_v2(ctypes.byref(host_buf), d_out, out_bytes), f"cuMemcpyDtoH_v2(warmup:{key})")
                _verify_kernel_output_buffer(host_buf, iters_val, is_float, key)

                runs: list[float] = []
                total_ops = float(warps_total) * float(iters_val) * float(unroll) * float(ops_per_inst)
                use_events = all(hasattr(cuda, fn) for fn in ("cuEventCreate", "cuEventRecord", "cuEventSynchronize", "cuEventElapsedTime", "cuEventDestroy_v2"))

                # Clear buffer before timed runs so post-timed verification proves timed runs executed
                _check_cu(cuda.cuMemsetD32_v2(d_out, 0, out_bytes // 4), f"cuMemsetD32_v2(timed:{key})")

                for _ in range(5):
                    if use_events:
                        ev_start = ctypes.c_void_p()
                        ev_stop = ctypes.c_void_p()
                        _check_cu(cuda.cuEventCreate(ctypes.byref(ev_start), 0), "cuEventCreate(start)")
                        try:
                            _check_cu(cuda.cuEventCreate(ctypes.byref(ev_stop), 0), "cuEventCreate(stop)")
                            try:
                                _check_cu(cuda.cuEventRecord(ev_start, None), "cuEventRecord(start)")
                                _check_cu(
                                    cuda.cuLaunchKernel(func, grid_x, 1, 1, block_x, 1, 1, 0, None, kernel_params, None),
                                    f"cuLaunchKernel({key})",
                                )
                                _check_cu(cuda.cuEventRecord(ev_stop, None), "cuEventRecord(stop)")
                                _check_cu(cuda.cuEventSynchronize(ev_stop), "cuEventSynchronize(stop)")
                                ms = ctypes.c_float(0.0)
                                _check_cu(cuda.cuEventElapsedTime(ctypes.byref(ms), ev_start, ev_stop), "cuEventElapsedTime")
                                dt = max(float(ms.value) / 1000.0, 1e-9)
                            finally:
                                _check_cu(cuda.cuEventDestroy_v2(ev_stop), "cuEventDestroy_v2(stop)")
                        finally:
                            _check_cu(cuda.cuEventDestroy_v2(ev_start), "cuEventDestroy_v2(start)")
                    else:
                        t0 = time.perf_counter()
                        _check_cu(
                            cuda.cuLaunchKernel(func, grid_x, 1, 1, block_x, 1, 1, 0, None, kernel_params, None),
                            f"cuLaunchKernel({key})",
                        )
                        _check_cu(cuda.cuCtxSynchronize(), f"cuCtxSynchronize({key})")
                        dt = max(time.perf_counter() - t0, 1e-9)

                    runs.append(round((total_ops / dt) / 1e12, 2))

                # Verify output buffer AGAIN after the timed runs!
                host_buf_post = (ctypes.c_uint32 * (out_bytes // 4))()
                _check_cu(cuda.cuMemcpyDtoH_v2(ctypes.byref(host_buf_post), d_out, out_bytes), f"cuMemcpyDtoH_v2(timed:{key})")
                _verify_kernel_output_buffer(host_buf_post, iters_val, is_float, key)

                best = max(runs)
                med = round(statistics.median(runs), 2)
                stdev = round(statistics.pstdev(runs), 3) if len(runs) > 1 else 0.0
                results[key] = {
                    "label": label,
                    "fuse": fuse,
                    "unit": unit,
                    "status": "OK",
                    "correctness_verified": True,
                    "best": best,
                    "median": med,
                    "stdev": stdev,
                    "runs": runs,
                }
                log_fn(f"[BENCH] {label}: median={med:.2f} {unit} (best={best:.2f}, stdev={stdev:.2f})")
            finally:
                rc_u = cuda.cuModuleUnload(mod)
                if rc_u != 0 and first_cleanup_err is None:
                    first_cleanup_err = CudaBenchmarkError(f"cuModuleUnload failed: CUresult={rc_u}")

        f16_16 = (results.get("f16_acc_f16") or {}).get("median") or (results.get("f16_acc_f16") or {}).get("best") or 0.0
        f16_32 = (results.get("f16_acc_f32") or {}).get("median") or (results.get("f16_acc_f32") or {}).get("best") or 0.0

        if f16_16 <= 0.0 or f16_32 <= 0.0 or not all_verified:
            status_code = "INSUFFICIENT_DATA"
            throttled: bool | None = None
            ratio_str = "N/A"
            status_text = "INSUFFICIENT DATA / UNVERIFIED (Cannot determine FMLA32 state)"
        else:
            ratio = round(f16_16 / f16_32, 2)
            ratio_str = f"{ratio:.2f}x"
            if ratio >= 1.55:
                status_code = "MEASURED_THROTTLED"
                throttled = True
                status_text = "MEASURED_THROTTLED (Stock Half-Rate FMLA32)"
            elif 0.85 <= ratio <= 1.25:
                status_code = "MEASURED_UNLOCKED"
                throttled = False
                status_text = "MEASURED_UNLOCKED (Full-Rate 2x FMLA32)"
            else:
                status_code = "MEASURED_INCONCLUSIVE"
                throttled = None
                status_text = f"MEASURED_INCONCLUSIVE (Ratio={ratio:.2f}x outside canonical stock/unlocked bands)"

        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gpu_name": gpu_name,
            "gpu_uuid": actual_uuid,
            "pci_bdf": actual_bdf,
            "compute_capability": sm_target,
            "sm_count": sm_count,
            "boost_clock_mhz": round(clock_khz / 1000.0, 1),
            "status": status_code,
            "throttled": throttled,
            "correctness_verified": all_verified,
            "f16_to_f32_ratio": ratio_str,
            "status_text": status_text,
            "metrics": results,
        }
    finally:
        if allocated and d_out.value:
            rc_f = cuda.cuMemFree_v2(d_out)
            if rc_f != 0 and first_cleanup_err is None:
                first_cleanup_err = CudaBenchmarkError(f"cuMemFree_v2 failed: CUresult={rc_f}")
        rc_c = cuda.cuCtxDestroy_v2(ctx)
        if rc_c != 0 and first_cleanup_err is None:
            first_cleanup_err = CudaBenchmarkError(f"cuCtxDestroy_v2 failed: CUresult={rc_c}")
        if first_cleanup_err is not None:
            raise first_cleanup_err


def _default_history() -> dict[str, Any]:
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "before": None,
        "after": None,
        "baselines_by_uuid": {},
        "runs": [],
    }


def _valid_snapshot(snap: Any) -> bool:
    """Strictly validate a non-null benchmark snapshot dict."""
    if not isinstance(snap, dict):
        return False
    metrics = snap.get("metrics")
    if not isinstance(metrics, dict) or len(metrics) == 0:
        return False
    identity = str(snap.get("gpu_uuid") or snap.get("pci_bdf") or "").strip()
    if not identity:
        return False
    has_numeric = False
    for k, v in metrics.items():
        if not isinstance(k, str) or not isinstance(v, dict):
            return False
        for num_field in ("best", "median", "stdev"):
            val = v.get(num_field)
            if val is not None:
                if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(val):
                    return False
                has_numeric = True
    return has_numeric


def _valid_optional_snapshot(snap: Any) -> bool:
    return snap is None or _valid_snapshot(snap)


def _quarantine_corrupt_history(path: Path) -> None:
    try:
        ts = int(time.time())
        quarantine = path.with_name(f"{path.stem}.corrupt_{ts}{path.suffix}")
        os.replace(path, quarantine)
    except OSError:
        pass


def load_benchmark_history(history_path: Path | None = None) -> dict[str, Any]:
    path = history_path or HISTORY_FILE
    if not path.exists():
        return _default_history()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _quarantine_corrupt_history(path)
        return _default_history()

    if not isinstance(raw, dict):
        _quarantine_corrupt_history(path)
        return _default_history()

    schema_ver = raw.get("schema_version", 1)
    if schema_ver not in (1, HISTORY_SCHEMA_VERSION):
        _quarantine_corrupt_history(path)
        return _default_history()

    before = raw.get("before")
    after = raw.get("after")
    runs = raw.get("runs", [])
    baselines = raw.get("baselines_by_uuid", {})
    if (
        not _valid_optional_snapshot(before)
        or not _valid_optional_snapshot(after)
        or not isinstance(runs, list)
        or not isinstance(baselines, dict)
    ):
        _quarantine_corrupt_history(path)
        return _default_history()

    clean_baselines: dict[str, dict[str, Any]] = {}
    for uid, pair in baselines.items():
        if not isinstance(uid, str) or not uid.strip() or not isinstance(pair, dict):
            _quarantine_corrupt_history(path)
            return _default_history()
        b_s = pair.get("before")
        a_s = pair.get("after")
        if not _valid_optional_snapshot(b_s) or not _valid_optional_snapshot(a_s):
            _quarantine_corrupt_history(path)
            return _default_history()
        clean_baselines[uid] = {"before": b_s, "after": a_s}

    if any(not _valid_snapshot(r) for r in runs):
        _quarantine_corrupt_history(path)
        return _default_history()

    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "before": before,
        "after": after,
        "baselines_by_uuid": clean_baselines,
        "runs": runs[-50:],
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(serialized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def record_benchmark_run(data: dict[str, Any], history_path: Path | None = None) -> dict[str, Any]:
    """Record a completed measurement into runs history without overwriting existing baselines."""
    if not _valid_snapshot(data):
        raise ValueError("Refusing to record invalid or unverified benchmark snapshot")
    path = history_path or HISTORY_FILE
    hist = load_benchmark_history(path)
    hist["runs"].append(data)
    hist["runs"] = hist["runs"][-50:]
    uuid_key = str(data.get("gpu_uuid") or data.get("pci_bdf")).strip()
    per_gpu = hist["baselines_by_uuid"].setdefault(uuid_key, {"before": None, "after": None})
    if data.get("status") == "MEASURED_THROTTLED":
        if hist["before"] is None:
            hist["before"] = data
        if per_gpu.get("before") is None:
            per_gpu["before"] = data
    elif data.get("status") == "MEASURED_UNLOCKED":
        if hist["after"] is None:
            hist["after"] = data
        if per_gpu.get("after") is None:
            per_gpu["after"] = data
    _atomic_write_json(path, hist)
    return hist


def save_benchmark_slot(
    slot: str,
    data: dict[str, Any],
    overwrite: bool = True,
    history_path: Path | None = None,
) -> dict[str, Any]:
    if slot not in ("before", "after"):
        raise ValueError(f"Invalid benchmark slot: {slot}")
    if not _valid_snapshot(data):
        raise ValueError("Invalid benchmark snapshot payload: requires non-empty finite metrics and GPU UUID/BDF")
    path = history_path or HISTORY_FILE
    hist = load_benchmark_history(path)
    if hist.get(slot) is not None and not overwrite:
        return hist
    hist[slot] = data
    uuid_key = str(data.get("gpu_uuid") or data.get("pci_bdf")).strip()
    per_gpu = hist["baselines_by_uuid"].setdefault(uuid_key, {"before": None, "after": None})
    per_gpu[slot] = data
    _atomic_write_json(path, hist)
    return hist


if __name__ == "__main__":
    out = run_tensor_benchmark()
    print(json.dumps(out, indent=2))
