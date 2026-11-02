# SPDX-License-Identifier: GPL-2.0-only
"""Launch hash-pinned SM89 cubin MMA probes through the CUDA Driver API.

The GPU must be idle during benchmarking; this runner checks every
output cell against an all-ones reference.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess
import time

BLOCKS = 1056
THREADS = 256
WARPS = BLOCKS * THREADS // 32
CHAINS = 8
MODES = (
    ("f16_f32", "bench_f16_f32", 16, False),
    ("tf32", "bench_tf32", 8, False),
    ("u4_s32", "bench_u4", 64, True),
)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cubin", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--expect-uuid", required=True)
    parser.add_argument("--expect-power-limit", type=float, required=True)
    parser.add_argument("--iters", type=int, default=20000)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    actual_sha = digest(args.cubin)
    if actual_sha != args.sha256.lower():
        raise SystemExit(f"cubin sha256 mismatch: {actual_sha}")

    smi = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,pci.bus_id,driver_version,pstate,clocks.current.sm,clocks.current.memory,power.draw,power.limit,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    ).strip().splitlines()
    if len(smi) != 1:
        raise SystemExit(f"expected exactly one GPU, got {len(smi)}")
    fields = [part.strip() for part in smi[0].split(",")]
    if fields[1] != args.expect_uuid:
        raise SystemExit(f"unexpected GPU UUID: {fields[1]}")
    if abs(float(fields[9]) - args.expect_power_limit) > 0.5:
        raise SystemExit(f"unexpected power limit: {fields[9]}")

    cuda = C.CDLL("libcuda.so.1")

    def check(status, step):
        if status != 0:
            err = C.c_char_p()
            cuda.cuGetErrorString(status, C.byref(err))
            msg = err.value.decode("utf-8", "replace") if err.value else "unknown"
            raise RuntimeError(f"{step} failed: {status} ({msg})")

    check(cuda.cuInit(0), "cuInit")
    dev = C.c_int()
    check(cuda.cuDeviceGet(C.byref(dev), 0), "cuDeviceGet")
    ctx = C.c_void_p()
    check(cuda.cuCtxCreate_v2(C.byref(ctx), 0, dev.value), "cuCtxCreate")
    mod = C.c_void_p()
    check(cuda.cuModuleLoadData(C.byref(mod), args.cubin.read_bytes()), "cuModuleLoadData")

    cells = WARPS * CHAINS * 4
    nbytes = cells * 4
    d_out = C.c_uint64()
    check(cuda.cuMemAlloc_v2(C.byref(d_out), C.c_size_t(nbytes)), "cuMemAlloc")
    host = (C.c_float * cells)()

    results = {}
    try:
        for mode, symbol, k_dim, is_int in MODES:
            fn = C.c_void_p()
            check(cuda.cuModuleGetFunction(C.byref(fn), mod, symbol.encode()), f"get {symbol}")
            expected = float(k_dim * (args.iters + 1))
            ops = 2.0 * WARPS * CHAINS * 16.0 * 8.0 * float(k_dim) * float(args.iters)

            def launch():
                out_arg = C.c_uint64(d_out.value)
                it_arg = C.c_int(args.iters)
                params = (C.c_void_p * 2)(
                    C.cast(C.byref(out_arg), C.c_void_p),
                    C.cast(C.byref(it_arg), C.c_void_p),
                )
                check(
                    cuda.cuLaunchKernel(
                        fn,
                        BLOCKS, 1, 1,
                        THREADS, 1, 1,
                        0, None,
                        params, None,
                    ),
                    f"launch {symbol}",
                )

            check(cuda.cuMemsetD32_v2(d_out, 0, C.c_size_t(cells)), "memset warmup")
            launch()
            check(cuda.cuCtxSynchronize(), f"sync warmup {symbol}")
            check(cuda.cuMemcpyDtoH_v2(host, d_out, C.c_size_t(nbytes)), "dtoh warmup")
            mismatches = sum(1 for value in host if value != expected)
            if mismatches:
                raise RuntimeError(f"{mode} warmup mismatch count {mismatches}, first={host[0]} expected={expected}")

            reps = []
            for _ in range(args.reps):
                check(cuda.cuMemsetD32_v2(d_out, 0, C.c_size_t(cells)), "memset timed")
                start = C.c_void_p()
                stop = C.c_void_p()
                check(cuda.cuEventCreate(C.byref(start), 0), "event start")
                check(cuda.cuEventCreate(C.byref(stop), 0), "event stop")
                check(cuda.cuEventRecord(start, None), "record start")
                launch()
                check(cuda.cuEventRecord(stop, None), "record stop")
                check(cuda.cuEventSynchronize(stop), f"sync {symbol}")
                ms = C.c_float()
                check(cuda.cuEventElapsedTime(C.byref(ms), start, stop), "elapsed")
                cuda.cuEventDestroy_v2(start)
                cuda.cuEventDestroy_v2(stop)
                check(cuda.cuMemcpyDtoH_v2(host, d_out, C.c_size_t(nbytes)), "dtoh timed")
                mismatches = sum(1 for value in host if value != expected)
                rate = ops / (float(ms.value) * 1e-3) / 1e12
                reps.append(
                    {
                        "ms": round(float(ms.value), 6),
                        "rate": round(rate, 4),
                        "unit": "TOP/s" if is_int else "TF/s",
                        "mismatches": mismatches,
                        "sample0": float(host[0]),
                        "expected": expected,
                    }
                )
            results[mode] = {
                "symbol": symbol,
                "k": k_dim,
                "unit": "TOP/s" if is_int else "TF/s",
                "best_rate": max(item["rate"] for item in reps),
                "repetitions": reps,
            }
    finally:
        cuda.cuMemFree_v2(d_out)
        cuda.cuModuleUnload(mod)
        cuda.cuCtxDestroy_v2(ctx)

    after_smi = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=pstate,clocks.current.sm,clocks.current.memory,power.draw,power.limit,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    ).strip()
    payload = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cubin_sha256": actual_sha,
        "gpu": {
            "name": fields[2],
            "pci_bus_id": fields[3],
            "driver_version": fields[4],
            "power_limit_w": float(fields[9]),
            "after_smi": after_smi,
        },
        "launch": {"blocks": BLOCKS, "threads": THREADS, "warps": WARPS, "chains": CHAINS, "iters": args.iters, "reps": args.reps},
        "results": results,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
