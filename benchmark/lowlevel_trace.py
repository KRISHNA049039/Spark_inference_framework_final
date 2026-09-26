"""
lowlevel_trace.py - Show what this platform does at the hardware / wire level.

Runs on Windows-native python AND inside the Linux (WSL2/Docker) image, so the
two legs can be compared line by line. Sections:

  1. cpu      - x86 ISA the PyTorch/oneDNN CPU kernels dispatch to (AVX2/FMA),
                oneDNN JIT verbose log of a real conv, optional gcc -S of an
                FMA dot product (Linux only)
  2. bits     - IEEE-754 bit fields of real EW-signal inputs, fp16/bf16
                rounding, tensor storage/stride/alignment + hex dump
  3. gpu      - SM count, registers/SM, warp size, L2, clocks, PCIe link,
                theoretical FP32 FLOPS and DRAM bandwidth
  4. bus      - host<->device copy bandwidth (pageable vs pinned) vs PCIe
                theoretical, device DRAM bandwidth, kernel-launch latency,
                measured SGEMM FLOPS
  5. kernels  - torch.profiler/CUPTI trace of ResNet18 + ew_classifier:
                every CUDA kernel with grid, block, registers/thread, shared
                memory, occupancy, and the CPU op -> cudaLaunchKernel chain
  6. sass     - (Linux + Triton only) a Triton kernel lowered through
                TTIR -> TTGIR -> LLVM IR -> PTX -> SASS, with register count
  7. spark    - Py4J socket, JVM/python-worker process tree, the exact bytes
                PySpark pickles per partition, the Arrow IPC buffer layout a
                pandas UDF ships, and per-task metrics from a real job

Usage:
  python benchmark/lowlevel_trace.py --out results/campaign_20260926/windows/lowlevel
  python benchmark/lowlevel_trace.py --sections gpu,bus
"""

import argparse
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch

RESULTS = {}


def banner(title):
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


def hexdump(b, width=16, limit=128):
    b = bytes(b[:limit])
    lines = []
    for i in range(0, len(b), width):
        chunk = b[i:i + width]
        hx = " ".join(f"{x:02x}" for x in chunk)
        asc = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
        lines.append(f"    {i:04x}  {hx:<{width * 3}} {asc}")
    return "\n".join(lines)


def sh(cmd, env=None, timeout=300):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True,
                           env=env, timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except Exception as e:
        return -1, str(e)


def cuda_time(fn, iters=20, warmup=3):
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    s.record()
    for _ in range(iters):
        fn()
    e.record()
    torch.cuda.synchronize()
    return s.elapsed_time(e) / iters / 1000.0  # seconds per iter


# --------------------------------------------------------------------------- 1
def section_cpu(out):
    banner("1. CPU - ISA dispatch, SIMD registers, oneDNN JIT")
    info = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "torch_cpu_capability": torch.backends.cpu.get_cpu_capability(),
        "mkldnn_available": torch.backends.mkldnn.is_available(),
        "torch_threads": torch.get_num_threads(),
    }
    if os.path.exists("/proc/cpuinfo"):
        flags = next((l.split(":", 1)[1].split() for l in open("/proc/cpuinfo") if l.startswith("flags")), [])
        info["simd_flags"] = [f for f in flags if f.startswith(("sse", "ssse", "avx", "fma", "f16c", "amx", "vnni"))]
    for k, v in info.items():
        print(f"  {k:24s}: {v}")
    print("""
  What this means:
    torch_cpu_capability=AVX2 -> ATen's vectorized CPU kernels are compiled several
    times (DEFAULT/AVX2/AVX512) and the AVX2 copy is picked at runtime via CPUID.
    AVX2 = 16 x 256-bit YMM registers; one YMM holds 8 x fp32. With FMA3 a single
    VFMADD231PS does 8 multiply-adds -> 16 FLOP/instruction, 2 ports -> 32 FLOP/cycle/core.""")

    # oneDNN verbose: run conv in a subprocess so the C library's stdout is captured
    code = ("import torch;x=torch.randn(8,3,224,224);w=torch.nn.Conv2d(3,64,7,2,3);"
            "torch.nn.functional.relu(w(x));import torch.nn as nn;nn.Linear(128,256)(torch.randn(64,128))")
    env = dict(os.environ, ONEDNN_VERBOSE="1", DNNL_VERBOSE="1")
    rc, log = sh([sys.executable, "-c", code], env=env)
    lines = [l for l in log.splitlines() if l.startswith(("onednn_verbose", "dnnl_verbose"))]
    print(f"\n  oneDNN verbose ({len(lines)} lines) - the 'jit:avx2' / 'brg' field is the x86 code path chosen:")
    for l in lines[:12]:
        print("    " + l[:220])
    info["onednn_verbose"] = lines[:40]

    # Real x86 instructions: compile an fp32 dot product and show the AVX2 FMA loop
    cc = shutil.which("gcc") or shutil.which("cc")
    if cc and platform.system() == "Linux":
        src = ("float dot(const float* a, const float* b, int n){float s=0;"
               "for(int i=0;i<n;i++) s+=a[i]*b[i]; return s;}\n")
        d = tempfile.mkdtemp()
        open(os.path.join(d, "dot.c"), "w").write(src)
        rc, _ = sh([cc, "-O3", "-mavx2", "-mfma", "-ffast-math", "-S", "-o", os.path.join(d, "dot.s"),
                    os.path.join(d, "dot.c")])
        if rc == 0:
            asm = [l for l in open(os.path.join(d, "dot.s")).read().splitlines()
                   if l.startswith("\t") and not l.startswith("\t.")]
            print("\n  gcc -O3 -mavx2 -mfma of `s += a[i]*b[i]` (the inner loop of every Linear layer):")
            for l in asm[:40]:
                print("   " + l)
            info["dot_avx2_asm"] = asm
    else:
        print("\n  (no gcc here - x86 asm listing is produced in the Linux leg)")
    RESULTS["cpu"] = info


# --------------------------------------------------------------------------- 2
def fbits(x):
    u = struct.unpack("<I", struct.pack("<f", float(x)))[0]
    s, e, m = u >> 31, (u >> 23) & 0xFF, u & 0x7FFFFF
    return u, s, e, m


def section_bits(out):
    banner("2. BITS - how one input sample is stored")
    from data.signal_generator import generate_ew_signals
    try:
        sig = generate_ew_signals(4)
        x = torch.as_tensor(sig[0] if isinstance(sig, tuple) else sig, dtype=torch.float32)
    except Exception:
        x = torch.randn(4, 128)
    info = {"shape": list(x.shape), "dtype": str(x.dtype), "stride": list(x.stride()),
            "element_size": x.element_size(), "nbytes": x.nelement() * x.element_size(),
            "data_ptr": hex(x.data_ptr()), "ptr_mod_64": x.data_ptr() % 64}
    print(f"  EW signal batch: shape={info['shape']} stride={info['stride']} "
          f"({info['nbytes']} bytes, data_ptr={info['data_ptr']}, 64B-aligned={info['ptr_mod_64'] == 0})")
    print("\n  IEEE-754 fp32 = [1 sign][8 exponent, bias 127][23 mantissa]:")
    rows = []
    for v in x.flatten()[:6].tolist():
        u, s, e, m = fbits(v)
        val = (-1) ** s * (1 + m / 2 ** 23) * 2.0 ** (e - 127) if e else 0.0
        h = torch.tensor([v]).half().float().item()
        bf = torch.tensor([v]).bfloat16().float().item()
        rows.append({"value": v, "hex": f"0x{u:08x}", "sign": s, "exp": e, "mantissa": m, "fp16": h, "bf16": bf})
        print(f"    {v:+.8f}  0x{u:08x}  {s} {e:08b} {m:023b}  = (-1)^{s}*1.{m:06x}h*2^({e}-127)"
              f"  | fp16 {h:+.6f}  bf16 {bf:+.6f}")
    info["values"] = rows
    raw = x.numpy().tobytes()
    print("\n  First 64 bytes of the tensor's storage (little-endian, 4 bytes per fp32):")
    print(hexdump(raw, limit=64))
    img = torch.randn(1, 3, 224, 224)
    cl = img.contiguous(memory_format=torch.channels_last)
    print(f"\n  Image tensor NCHW stride={img.stride()}  channels_last stride={cl.stride()}"
          "\n    NCHW: all 50176 R pixels, then G, then B.  NHWC: R,G,B of pixel 0, then pixel 1...")
    info["image_strides"] = {"nchw": list(img.stride()), "channels_last": list(cl.stride())}
    RESULTS["bits"] = info


# --------------------------------------------------------------------------- 3
def nvsmi(q):
    rc, o = sh(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader,nounits"])
    return [v.strip() for v in o.strip().split(",")] if rc == 0 else []


def section_gpu(out):
    banner("3. GPU - streaming multiprocessors, registers, caches, clocks, bus")
    if not torch.cuda.is_available():
        print("  no CUDA device")
        return
    p = torch.cuda.get_device_properties(0)
    props = {k: getattr(p, k) for k in dir(p) if not k.startswith("_") and not callable(getattr(p, k))}
    props = {k: (str(v) if not isinstance(v, (int, float, str, bool)) else v) for k, v in props.items()}
    for k, v in props.items():
        print(f"  {k:32s}: {v}")
    q = nvsmi("pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max,"
              "clocks.max.sm,clocks.max.mem,clocks.sm,clocks.mem,power.limit,driver_version,pstate,"
              "temperature.gpu")
    keys = ["pcie_gen_cur", "pcie_gen_max", "pcie_width_cur", "pcie_width_max", "sm_clock_max_mhz",
            "mem_clock_max_mhz", "sm_clock_now_mhz", "mem_clock_now_mhz", "power_limit_w", "driver",
            "pstate", "temp_c"]
    smi = dict(zip(keys, q))
    for k, v in smi.items():
        print(f"  {k:32s}: {v}")

    cc = (p.major, p.minor)
    fp32_per_sm = {(7, 5): 64, (8, 6): 128, (8, 9): 128, (8, 0): 64, (7, 0): 64, (12, 0): 128, (9, 0): 128}.get(cc, 64)
    sms = p.multi_processor_count
    try:
        sm_mhz = float(smi.get("sm_clock_max_mhz", 0))
        mem_mhz = float(smi.get("mem_clock_max_mhz", 0))
    except ValueError:
        sm_mhz = mem_mhz = 0
    bus_bits = getattr(p, "memory_bus_width", 0) or 128
    theo = {
        "compute_capability": f"{p.major}.{p.minor}",
        "fp32_lanes_per_sm": fp32_per_sm,
        "cuda_cores": sms * fp32_per_sm,
        "fp32_tflops_theoretical": sms * fp32_per_sm * 2 * sm_mhz * 1e6 / 1e12,
        "dram_gbps_theoretical": mem_mhz * 1e6 * 2 * bus_bits / 8 / 1e9,  # DDR: 2 transfers/clock as nvidia-smi reports
        "pcie_gbps_theoretical": {1: 0.25, 2: 0.5, 3: 0.985, 4: 1.969, 5: 3.938}.get(
            int(smi.get("pcie_gen_cur", 3) or 3), 0.985) * int(smi.get("pcie_width_cur", 16) or 16),
        "memory_bus_width_bits": bus_bits,
    }
    print(f"""
  Derived:
    compute capability {theo['compute_capability']}  ->  {sms} SMs x {fp32_per_sm} FP32 lanes = {theo['cuda_cores']} 'CUDA cores'
    Each SM: 4 warp schedulers; a warp = 32 threads executing one instruction (SIMT).
    Register file per SM = {props.get('regs_per_multiprocessor', '?')} x 32-bit registers, shared by all resident threads:
      a kernel using R regs/thread can keep at most floor({props.get('regs_per_multiprocessor', 65536)}/(R*32)) warps per SM.
    FP32 peak = SMs*lanes*2(FMA)*clock = {theo['fp32_tflops_theoretical']:.2f} TFLOPS at {sm_mhz:.0f} MHz
    DRAM peak = mem_clock*2*bus/8     = {theo['dram_gbps_theoretical']:.1f} GB/s  ({bus_bits}-bit bus)
    PCIe Gen{smi.get('pcie_gen_cur')} x{smi.get('pcie_width_cur')} = {theo['pcie_gbps_theoretical']:.2f} GB/s per direction (128b/130b encoding)""")
    RESULTS["gpu"] = {"props": props, "nvidia_smi": smi, "theoretical": theo}


# --------------------------------------------------------------------------- 4
def section_bus(out):
    banner("4. BUS - PCIe copies, DRAM bandwidth, launch latency, SGEMM")
    if not torch.cuda.is_available():
        return
    dev = torch.device("cuda")
    rows = []
    print(f"  {'size':>10} {'H2D pageable':>14} {'H2D pinned':>12} {'D2H pageable':>14} {'D2H pinned':>12}   (GB/s)")
    for mb in [0.004, 0.064, 1, 4, 16, 64, 256]:
        n = int(mb * 1024 * 1024 / 4)
        h = torch.randn(n)
        hp = h.pin_memory()
        d = torch.empty(n, device=dev)
        r = {"MB": mb}
        for name, src in [("h2d_pageable", h), ("h2d_pinned", hp)]:
            t = cuda_time(lambda: d.copy_(src, non_blocking=True), iters=10)
            r[name] = n * 4 / t / 1e9
        for name, dst in [("d2h_pageable", torch.empty(n)), ("d2h_pinned", torch.empty(n).pin_memory())]:
            t = cuda_time(lambda: dst.copy_(d, non_blocking=True), iters=10)
            r[name] = n * 4 / t / 1e9
        rows.append(r)
        print(f"  {mb:>8.3f}MB {r['h2d_pageable']:>14.2f} {r['h2d_pinned']:>12.2f} "
              f"{r['d2h_pageable']:>14.2f} {r['d2h_pinned']:>12.2f}")
        del h, hp, d
    print("""
    pageable: the driver first memcpy's your buffer into its own pinned staging
      buffer (CPU does this, cache-line by cache-line), then the GPU's copy engine
      DMAs it across PCIe. pinned (page-locked): the copy engine DMAs straight
      from your physical pages -> close to PCIe line rate. Tiny copies are
      latency-bound (~10 us of driver + doorbell + DMA descriptor setup).""")

    big = torch.empty(64 * 1024 * 1024, device=dev)
    big2 = torch.empty_like(big)
    t = cuda_time(lambda: big2.copy_(big), iters=10)
    d2d = 2 * big.numel() * 4 / t / 1e9  # read + write
    print(f"  Device DRAM (D2D copy, read+write): {d2d:.1f} GB/s")
    del big, big2

    x = torch.ones(1, device=dev)
    torch.cuda.synchronize()
    n = 2000
    t0 = time.perf_counter()
    for _ in range(n):
        x.add_(1)
    t_enq = (time.perf_counter() - t0) / n
    torch.cuda.synchronize()
    t_all = (time.perf_counter() - t0) / n
    t0 = time.perf_counter()
    for _ in range(200):
        x.add_(1)
        torch.cuda.synchronize()
    t_sync = (time.perf_counter() - t0) / 200
    print(f"  Kernel launch: enqueue {t_enq * 1e6:.1f} us/launch (CPU side), "
          f"{t_all * 1e6:.1f} us/launch incl. GPU drain, {t_sync * 1e6:.1f} us round-trip with sync")

    gemm = {}
    for dt in [torch.float32, torch.float16]:
        a = torch.randn(2048, 2048, device=dev, dtype=dt)
        b = torch.randn(2048, 2048, device=dev, dtype=dt)
        t = cuda_time(lambda: a @ b, iters=10)
        gemm[str(dt)] = 2 * 2048 ** 3 / t / 1e12
        print(f"  GEMM 2048^3 {str(dt):14s}: {gemm[str(dt)]:.2f} TFLOPS")
    RESULTS["bus"] = {"copies": rows, "d2d_gbps": d2d, "launch_enqueue_us": t_enq * 1e6,
                      "launch_drain_us": t_all * 1e6, "launch_roundtrip_us": t_sync * 1e6, "gemm_tflops": gemm}


# --------------------------------------------------------------------------- 5
def section_kernels(out):
    banner("5. KERNELS - every CUDA kernel the models launch (CUPTI via torch.profiler)")
    if not torch.cuda.is_available():
        return
    from torch.profiler import profile, ProfilerActivity
    from models.image_models import ResNet18Classifier
    from models.ew_signal_model import EWSignalClassifier
    res = {}
    for name, model, inp in [
        ("ew_classifier", EWSignalClassifier(), torch.randn(256, 128)),
        ("resnet18", ResNet18Classifier(), torch.randn(8, 3, 224, 224)),
    ]:
        model = model.cuda().eval()
        inp_d = inp.cuda()
        with torch.no_grad():
            for _ in range(3):
                model(inp_d)
        torch.cuda.synchronize()
        trace = os.path.join(out, f"trace_{name}.json")
        with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA], record_shapes=True) as prof:
            with torch.no_grad():
                x = inp.cuda()           # H2D
                y = model(x)
                y.cpu()                  # D2H
            torch.cuda.synchronize()
        prof.export_chrome_trace(trace)
        ev = json.load(open(trace, encoding="utf-8"))["traceEvents"]
        kernels = [e for e in ev if e.get("cat") == "kernel"]
        memcpy = [e for e in ev if e.get("cat") in ("gpu_memcpy", "gpu_memset")]
        runtime = [e for e in ev if e.get("cat") in ("cuda_runtime", "cuda_driver")]
        print(f"\n  --- {name}: input {list(inp.shape)} -> {len(kernels)} kernels, {len(memcpy)} memcpy, "
              f"{len(runtime)} CUDA runtime calls. Chrome trace: {trace}")
        print(f"  {'us':>7} {'grid':>14} {'block':>12} {'regs':>4} {'smem':>6} {'occ%':>5}  kernel")
        klist = []
        for k in kernels:
            a = k.get("args", {})
            row = {"name": k["name"], "dur_us": k.get("dur"), "grid": a.get("grid"), "block": a.get("block"),
                   "regs": a.get("registers per thread"), "smem": a.get("shared memory"),
                   "occupancy": a.get("est. achieved occupancy %"), "blocks_per_sm": a.get("blocks per SM"),
                   "warps_per_sm": a.get("warps per SM")}
            klist.append(row)
        for r in klist[:40]:
            print(f"  {r['dur_us'] or 0:>7.1f} {str(r['grid']):>14} {str(r['block']):>12} {str(r['regs']):>4} "
                  f"{str(r['smem']):>6} {str(r['occupancy']):>5}  {r['name'][:90]}")
        for m in memcpy:
            a = m.get("args", {})
            bw = a.get("memory bandwidth (GB/s)")
            print(f"  {m.get('dur', 0):>7.1f} {'':>14} {'':>12} {'':>4} {'':>6} {'':>5}  {m['name']} "
                  f"{a.get('bytes', '')} bytes {'@ %.2f GB/s' % bw if bw else ''}")
        rt_counts = {}
        for r in runtime:
            rt_counts[r["name"]] = rt_counts.get(r["name"], 0) + 1
        print("  CUDA runtime/driver API calls (CPU side):", rt_counts)
        # CPU op -> launch chain for the first conv / addmm
        ops = [e for e in ev if e.get("cat") == "cpu_op" and e["name"] in
               ("aten::conv2d", "aten::convolution", "aten::_convolution", "aten::cudnn_convolution",
                "aten::linear", "aten::addmm")]
        if ops:
            first = ops[0]
            t0, t1 = first["ts"], first["ts"] + first["dur"]
            chain = sorted([e for e in ev if e.get("ph") == "X" and e.get("cat") in ("cpu_op", "cuda_runtime", "cuda_driver")
                            and t0 <= e["ts"] <= t1], key=lambda e: e["ts"])
            print(f"  Dispatch chain inside the first {first['name']} (host timeline):")
            for e in chain[:14]:
                print(f"    +{e['ts'] - t0:7.1f}us {e['dur']:7.1f}us  [{e['cat']}] {e['name']}")
            corr = [e.get("args", {}).get("correlation") for e in chain if e.get("cat") == "cuda_runtime"]
            linked = [k["name"][:70] for k in kernels if k.get("args", {}).get("correlation") in corr]
            print(f"    -> GPU kernels launched by it (matched by CUPTI correlation id): {linked}")
        tbl = prof.key_averages().table(sort_by="cuda_time_total", row_limit=15)
        open(os.path.join(out, f"profile_{name}.txt"), "w", encoding="utf-8").write(tbl)
        res[name] = {"kernels": klist, "memcpy": [{"name": m["name"], "dur": m.get("dur"), **m.get("args", {})} for m in memcpy],
                     "runtime_calls": rt_counts}
        del model
        torch.cuda.empty_cache()
    RESULTS["kernels"] = res


# --------------------------------------------------------------------------- 6
def section_sass(out):
    banner("6. SASS - one kernel from Python down to GPU machine code (Triton)")
    try:
        import triton
        import triton.language as tl
    except ImportError:
        print("  Triton not installed on this platform (Windows) - produced in the Linux leg.")
        return
    # @triton.jit resolves names (tl.constexpr, tl.load...) from the module globals
    globals().update(triton=triton, tl=tl)
    if not torch.cuda.is_available():
        return

    @triton.jit
    def bias_relu(x_ptr, b_ptr, y_ptr, n, C: tl.constexpr, BLOCK: tl.constexpr):
        pid = tl.program_id(0)                       # blockIdx.x
        offs = pid * BLOCK + tl.arange(0, BLOCK)     # + threadIdx-derived lane offsets
        mask = offs < n
        x = tl.load(x_ptr + offs, mask=mask)         # LDG  (global -> registers)
        b = tl.load(b_ptr + offs % C, mask=mask)
        y = tl.maximum(x + b, 0.0)                   # FADD + FMNMX
        tl.store(y_ptr + offs, y, mask=mask)         # STG  (registers -> global)

    n, C = 256 * 64, 64
    x = torch.randn(n, device="cuda")
    b = torch.randn(C, device="cuda")
    y = torch.empty_like(x)
    ck = bias_relu[(triton.cdiv(n, 1024),)](x, b, y, n, C=C, BLOCK=1024)
    assert torch.allclose(y, torch.relu(x + b.repeat(n // C)))
    info = {"n_regs": getattr(ck, "n_regs", None), "n_spills": getattr(ck, "n_spills", None),
            "shared": getattr(ck.metadata, "shared", None), "num_warps": getattr(ck.metadata, "num_warps", None)}
    print(f"  compiled: regs/thread={info['n_regs']} spills={info['n_spills']} shared={info['shared']}B "
          f"num_warps={info['num_warps']} (= {(info['num_warps'] or 0) * 32} threads/block)")
    for stage in ["ttir", "ttgir", "llir", "ptx"]:
        txt = ck.asm.get(stage, "")
        if isinstance(txt, bytes):
            txt = txt.decode()
        open(os.path.join(out, f"bias_relu.{stage}"), "w").write(txt)
        info[f"{stage}_lines"] = len(txt.splitlines())
    ptx = ck.asm["ptx"]
    body = [l for l in ptx.splitlines() if l.strip() and not l.strip().startswith(("//", ".loc", ".file", "$L__"))]
    print(f"\n  PTX (virtual ISA, {len(body)} lines; first 45 of the kernel body):")
    start = next((i for i, l in enumerate(body) if ".entry" in l), 0)
    for l in body[start:start + 45]:
        print("    " + l)
    cubin = os.path.join(out, "bias_relu.cubin")
    open(cubin, "wb").write(ck.asm["cubin"])
    tbin = os.path.join(os.path.dirname(triton.__file__), "backends", "nvidia", "bin")
    cuobjdump = os.path.join(tbin, "cuobjdump")
    rc, sass = sh([cuobjdump, "-sass", cubin])
    if rc != 0:
        rc, sass = sh([os.path.join(tbin, "nvdisasm"), "-c", cubin])
    open(os.path.join(out, "bias_relu.sass"), "w").write(sass)
    sl = [l for l in sass.splitlines() if "/*" in l and ";" in l]
    print(f"\n  SASS (real sm_{torch.cuda.get_device_capability()[0]}{torch.cuda.get_device_capability()[1]} "
          f"machine code, {len(sl)} instructions; each is 128 bits = instruction + scheduling control bits):")
    for l in sl[:60]:
        print("   " + l.rstrip())
    info["sass"] = sl
    rc, res = sh([cuobjdump, "-res-usage", cubin])
    print("\n  cuobjdump -res-usage:", res.strip()[-300:])
    info["res_usage"] = res.strip()

    # Inductor: compile the repo's own ew_classifier and keep its generated kernels
    from models.ew_signal_model import EWSignalClassifier
    code = (
        "import torch,sys;sys.path.insert(0,'.');from models.ew_signal_model import EWSignalClassifier;"
        "m=EWSignalClassifier().cuda().eval();x=torch.randn(256,128,device='cuda');"
        "c=torch.compile(m);\nwith torch.no_grad(): c(x);c(x)\nprint('ok')"
    )
    env = dict(os.environ, TORCH_LOGS="output_code")
    rc, log = sh([sys.executable, "-c", code], env=env, timeout=600)
    open(os.path.join(out, "inductor_ew_classifier_output_code.txt"), "w").write(log)
    trit = [l for l in log.splitlines() if "@triton.jit" in l or "def triton_" in l or "extern_kernels." in l]
    print(f"\n  torch.compile(ew_classifier): rc={rc}; generated {sum('def triton_' in l for l in trit)} fused "
          f"Triton kernels + {sum('extern_kernels' in l for l in trit)} cuBLAS calls "
          f"(full code: inductor_ew_classifier_output_code.txt)")
    for l in trit[:16]:
        print("    " + l.strip()[:150])
    RESULTS["sass"] = info


# --------------------------------------------------------------------------- 7
def section_spark(out):
    banner("7. SPARK - JVM <-> Python wire level")
    from pyspark.sql import SparkSession
    from pyspark.serializers import CPickleSerializer, BatchedSerializer
    import pyspark
    master = os.environ.get("SPARK_MASTER_URL") or "local[2]"
    spark = (SparkSession.builder.appName("lowlevel_trace").master(master)
             .config("spark.driver.memory", "1g").config("spark.executor.memory", "1g")
             .config("spark.sql.execution.arrow.pyspark.enabled", "true").getOrCreate())
    sc = spark.sparkContext
    gw = sc._gateway
    info = {
        "pyspark": pyspark.__version__, "master": sc.master, "app_id": sc.applicationId,
        "driver_python_pid": os.getpid(),
        "py4j_java_port": gw.gateway_parameters.port,
        "py4j_callback_port": getattr(gw.callback_server_parameters, "port", None),
        "jvm_pid": None,
    }
    try:
        info["jvm_pid"] = int(sc._jvm.java.lang.ProcessHandle.current().pid())
        info["jvm_version"] = sc._jvm.java.lang.System.getProperty("java.version")
        info["jvm_vm"] = sc._jvm.java.lang.System.getProperty("java.vm.name")
        info["jvm_max_heap_mb"] = int(sc._jvm.java.lang.Runtime.getRuntime().maxMemory()) // (1 << 20)
    except Exception as e:
        info["jvm_err"] = str(e)
    for k, v in info.items():
        print(f"  {k:22s}: {v}")
    print("""
  Driver side: this Python process talks to the JVM over a localhost TCP socket
  (Py4J). Every sc.xxx call is serialized as a text command ('c\\n<objid>\\n<method>...'),
  the JVM executes it via reflection and sends the answer back on the same socket.""")

    # What the executor's python worker looks like from the inside
    def probe(it):
        import os, socket as s, threading, time as t
        rows = list(it)
        t0 = t.perf_counter()
        _ = sum(float(v) for v in rows)
        yield {"pid": os.getpid(), "ppid": os.getppid(), "host": s.gethostname(),
               "thread": threading.current_thread().name, "n": len(rows),
               "compute_us": (t.perf_counter() - t0) * 1e6,
               "env_worker": {k: v for k, v in os.environ.items() if k.startswith(("SPARK_", "PYSPARK_", "PYTHON_WORKER"))
                              and "SECRET" not in k}}
    rdd = sc.parallelize(range(20000), 4)
    probes = rdd.mapPartitions(probe).collect()
    print("\n  Python worker processes that ran the 4 tasks:")
    for p in probes:
        print(f"    pid={p['pid']} ppid={p['ppid']} host={p['host']} rows={p['n']} compute={p['compute_us']:.0f}us")
    same_parent = len({p["ppid"] for p in probes}) == 1
    print(f"    -> {'all forked from one pyspark.daemon (ppid shared) - Linux fork() model' if same_parent and platform.system() == 'Linux' else 'workers launched per the platform model (Windows has no fork(); JVM spawns python -m pyspark.worker directly)'}")
    info["workers"] = [{k: v for k, v in p.items() if k != "env_worker"} for p in probes]
    info["worker_env_keys"] = sorted(probes[0]["env_worker"].keys()) if probes else []

    # Exact bytes on the JVM->python socket for one partition
    ser = BatchedSerializer(CPickleSerializer(), 1024)
    part = np.random.randn(64, 128).astype(np.float32)   # 64 EW signal rows
    buf = __import__("io").BytesIO()
    ser.dump_stream([part[i] for i in range(len(part))], buf)
    b = buf.getvalue()
    print(f"\n  One partition of 64 EW-signal rows (64x128 fp32 = {part.nbytes} raw bytes) as PySpark ships it:")
    print(f"    framed stream = {len(b)} bytes  (overhead {len(b) - part.nbytes} bytes = "
          f"{100 * (len(b) - part.nbytes) / part.nbytes:.1f}%)")
    print("    layout: [int32 big-endian length][pickle protocol-5 payload]... then END_OF_DATA_SECTION (-1)")
    print(hexdump(b, limit=96))
    info["pickle_frame_bytes"] = len(b)
    info["pickle_raw_bytes"] = part.nbytes

    # Arrow IPC: what a pandas UDF batch looks like
    import pyarrow as pa
    arr = pa.array([1.5, None, -2.25, 3.0], type=pa.float32())
    batch = pa.record_batch([arr], names=["x"])
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as w:
        w.write_batch(batch)
    ipc = sink.getvalue().to_pybytes()
    bufs = arr.buffers()
    print(f"\n  Arrow (pandas_udf transport): column x=[1.5, null, -2.25, 3.0] float32")
    print(f"    validity bitmap = {bufs[0].to_pybytes().hex()}  (bits LSB-first: 1,0,1,1 -> 0b1101 = 0x0d)")
    print(f"    data buffer     = {bufs[1].to_pybytes().hex()}  (4 x fp32 little-endian, null slot is garbage/zero)")
    print(f"    IPC stream {len(ipc)} bytes: 0xFFFFFFFF continuation, int32 metadata length, flatbuffer "
          "Schema, then RecordBatch message + 8-byte-aligned body buffers:")
    print(hexdump(ipc, limit=96))
    info["arrow_ipc_bytes"] = len(ipc)

    # Real job task metrics via the status/REST store
    from pyspark.sql.functions import pandas_udf
    import pandas as pd

    @pandas_udf("double")
    def times2(s: pd.Series) -> pd.Series:
        return s * 2.0

    df = spark.range(0, 200000, numPartitions=4).selectExpr("cast(id as double) as x")
    t0 = time.perf_counter()
    df.select(times2("x")).agg({"*": "count"}).collect()
    t_udf = time.perf_counter() - t0
    t0 = time.perf_counter()
    df.rdd.map(lambda r: r.x * 2.0).count()
    t_rdd = time.perf_counter() - t0
    print(f"\n  200k rows x2: pandas_udf (Arrow, columnar) {t_udf:.2f}s  vs  RDD map (pickle, row-by-row) {t_rdd:.2f}s")
    info["udf_vs_rdd_s"] = {"pandas_udf_arrow": t_udf, "rdd_pickle": t_rdd}

    try:
        import urllib.request
        ui = sc.uiWebUrl
        base = f"{ui}/api/v1/applications/{sc.applicationId}"
        stages = json.load(urllib.request.urlopen(base + "/stages", timeout=10))
        print("\n  Per-stage metrics from the Spark REST API (all times ms):")
        print(f"    {'stage':>5} {'tasks':>5} {'run':>7} {'cpu':>7} {'deser':>6} {'resSer':>6} {'gc':>5} "
              f"{'in/out rec':>12}  name")
        srows = []
        for s in sorted(stages, key=lambda s: s["stageId"]):
            r = {"stage": s["stageId"], "tasks": s["numTasks"], "run_ms": s.get("executorRunTime"),
                 "cpu_ms": (s.get("executorCpuTime") or 0) / 1e6, "deser_ms": s.get("executorDeserializeTime"),
                 "result_ser_ms": s.get("resultSerializationTime"), "gc_ms": s.get("jvmGcTime"),
                 "in_rec": s.get("inputRecords"), "out_rec": s.get("outputRecords"), "name": s["name"][:50]}
            srows.append(r)
            print(f"    {r['stage']:>5} {r['tasks']:>5} {r['run_ms']:>7} {r['cpu_ms']:>7.0f} {r['deser_ms']:>6} "
                  f"{r['result_ser_ms']:>6} {r['gc_ms']:>5} {str(r['in_rec']) + '/' + str(r['out_rec']):>12}  {r['name']}")
        info["stages"] = srows
    except Exception as e:
        print("  (REST API unavailable:", e, ")")
    spark.stop()
    RESULTS["spark"] = info


SECTIONS = {"cpu": section_cpu, "bits": section_bits, "gpu": section_gpu, "bus": section_bus,
            "kernels": section_kernels, "sass": section_sass, "spark": section_spark}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/lowlevel")
    ap.add_argument("--sections", default=",".join(SECTIONS))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    RESULTS["meta"] = {"host": socket.gethostname(), "os": platform.platform(), "python": sys.version.split()[0],
                       "torch": torch.__version__, "cuda": torch.version.cuda,
                       "cudnn": torch.backends.cudnn.version() if torch.cuda.is_available() else None,
                       "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    print(json.dumps(RESULTS["meta"], indent=2))
    for s in a.sections.split(","):
        try:
            SECTIONS[s](a.out)
        except Exception as e:
            import traceback
            traceback.print_exc()
            RESULTS[s] = {"error": repr(e)}
    with open(os.path.join(a.out, "lowlevel.json"), "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1, default=str)
    print(f"\nSaved {os.path.join(a.out, 'lowlevel.json')}")


if __name__ == "__main__":
    main()
