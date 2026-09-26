// build_concepts_docx.js - Concepts handbook (Word) companion to
// docs/LOWLEVEL_EXECUTION_GUIDE_20260926.pdf (built by build_lowlevel_pdf.py).
// Explains every concept the PDF uses; numbers, listings and hex dumps are read
// from results/campaign_20260926/{windows,wsl2_docker,aws_g4dn}/.
//
// Needs the `docx` npm package (npm install docx). Run from the repo root:
//   node benchmark/build_concepts_docx.js [repo_root] [out.docx]
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, LevelFormat, TableOfContents, PageBreak, Footer, PageNumber,
} = require("docx");

const ROOT = process.argv[2] || path.join(__dirname, "..");
const OUT = process.argv[3] || path.join(ROOT, "docs", "CONCEPTS_HANDBOOK_20260926.docx");
const C = path.join(ROOT, "results", "campaign_20260926");
const readJ = (p) => { try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return {}; } };
const readT = (p) => { try { return fs.readFileSync(p, "utf8"); } catch { return ""; } };
const W = readJ(path.join(C, "windows", "lowlevel", "lowlevel.json"));
const L = readJ(path.join(C, "wsl2_docker", "lowlevel", "lowlevel.json"));
const A = readJ(path.join(C, "aws_g4dn", "lowlevel", "lowlevel.json"));
const SUM = readJ(path.join(C, "summary.json"));

const PAGE_W = 11906, MARGIN = 1134, CONTENT = PAGE_W - 2 * MARGIN; // A4, 2 cm margins
const MONO = "Consolas", BODY = "Arial";
const ACCENT = "0B5CAD";

// ---------------------------------------------------------------- helpers
function runs(text, base = {}) {
  // **bold**, `code`
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), font: MONO, size: 18, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}
const body = [];
const H1 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: body.length > 3, children: [new TextRun(t)] }));
const H2 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] }));
const H3 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] }));
const Pp = (t) => body.push(new Paragraph({ spacing: { after: 120 }, children: runs(t) }));
const B = (items, level = 0) => items.forEach((t) => body.push(new Paragraph({ numbering: { reference: "bullets", level }, spacing: { after: 60 }, children: runs(t) })));
const N = (items) => items.forEach((t) => body.push(new Paragraph({ numbering: { reference: "numbers", level: 0 }, spacing: { after: 60 }, children: runs(t) })));
function label(lbl, t) {
  const head = lbl ? [new TextRun({ text: lbl + " ", bold: true, color: ACCENT })] : [];
  body.push(new Paragraph({ spacing: { after: 100 }, children: [...head, ...runs(t)] }));
}
function concept(name, what, how, yours) {
  H3(name);
  if (what) label("What it is.", what);
  if (how) (Array.isArray(how) ? how : [how]).forEach((h, i) => label(i === 0 ? "How it works." : "", h));
  if (yours) label("In your runs.", yours);
}
function code(text, maxLines = 60) {
  const lines = String(text || "(not captured)").replace(/\t/g, "    ").split(/\r?\n/).slice(0, maxLines);
  lines.forEach((l, i) => body.push(new Paragraph({
    shading: { type: ShadingType.CLEAR, color: "auto", fill: "F3F5F8" },
    spacing: { before: i === 0 ? 60 : 0, after: i === lines.length - 1 ? 140 : 0, line: 240 },
    indent: { left: 120, right: 120 },
    children: [new TextRun({ text: l.length ? l : " ", font: MONO, size: 16 })],
  })));
}
function note(t) {
  body.push(new Paragraph({
    shading: { type: ShadingType.CLEAR, color: "auto", fill: "EAF3FD" },
    border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT, space: 6 } },
    spacing: { before: 80, after: 160 }, indent: { left: 160, right: 120 },
    children: runs(t),
  }));
}
const border = { style: BorderStyle.SINGLE, size: 4, color: "C9D1D9" };
const borders = { top: border, bottom: border, left: border, right: border };
function table(rows, widthsPct, monoCols = []) {
  const widths = widthsPct.map((w) => Math.floor((CONTENT * w) / 100));
  const total = widths.reduce((a, b) => a + b, 0);
  body.push(new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((r, ri) => new TableRow({
      tableHeader: ri === 0,
      children: r.map((c, ci) => new TableCell({
        borders, width: { size: widths[ci], type: WidthType.DXA },
        shading: ri === 0 ? { type: ShadingType.CLEAR, color: "auto", fill: "E4E9F0" } : (ri % 2 === 0 ? { type: ShadingType.CLEAR, color: "auto", fill: "FAFBFC" } : undefined),
        margins: { top: 50, bottom: 50, left: 90, right: 90 },
        children: [new Paragraph({ children: ri === 0 ? [new TextRun({ text: String(c), bold: true, size: 18 })]
          : monoCols.includes(ci) ? [new TextRun({ text: String(c), font: MONO, size: 16 })] : runs(String(c), { size: 18 }) })],
      })),
    })),
  }));
  body.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
}
const g = (o, ...k) => k.reduce((a, x) => (a && a[x] !== undefined ? a[x] : undefined), o);
const f = (v, d = 1) => (typeof v === "number" && isFinite(v) ? v.toFixed(d) : "-");

// ---------------------------------------------------------------- data from the runs
const bits = g(W, "bits", "values") || [];
const v0 = bits[0] || {};
const sassRaw = readT(path.join(C, "wsl2_docker", "lowlevel", "bias_relu.sass"));
const sass = sassRaw.split(/\r?\n/).filter((l) => /\/\*[0-9a-f]{4}\*\//.test(l)).map((l) => l.replace(/\s*\/\*\s*0x[0-9a-f]+\s*\*\/\s*$/, "").trim());
const ptx = readT(path.join(C, "wsl2_docker", "lowlevel", "bias_relu.ptx")).split(/\r?\n/)
  .filter((l) => l.trim() && !/^\s*(\/\/|\.loc|\.file|\$L__|\.section|\.b8|\.debug)/.test(l));
const ptxStart = Math.max(0, ptx.findIndex((l) => l.includes(".entry")));
const asm = g(L, "cpu", "dot_avx2_asm") || [];
const ttgir = readT(path.join(C, "wsl2_docker", "lowlevel", "bias_relu.ttgir")).split(/\r?\n/).filter((l) => l.includes("#blocked") || l.includes("tt.load") || l.includes("tt.store")).slice(0, 6);
const svs = (leg) => { const r = (SUM[leg] || []).find((x) => x.test === "svs_single_gpu"); return r ? r.throughput : {}; };
const thr = (leg, t) => { const r = (SUM[leg] || []).find((x) => x.test === t); if (!r) return "-"; const v = Object.values(r.throughput); return r.status === "FAIL" || !v.length ? r.status : `${Math.round(v[v.length - 1]).toLocaleString()}/s`; };

// ================================================================ CONTENT
body.push(new Paragraph({ spacing: { before: 2400, after: 200 }, children: [new TextRun({ text: "Concepts Handbook", size: 56, bold: true })] }));
body.push(new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "From Python to Silicon — every idea behind the PyTorch-Spark inference platform, from bits and x86 registers to GPU warps, PCIe and the Spark wire protocol", size: 28, color: "57606A" })] }));
body.push(new Paragraph({ spacing: { after: 400 }, children: [new TextRun({ text: "Companion to docs/LOWLEVEL_EXECUTION_GUIDE_20260926.pdf · measurements from Windows 11 native, WSL2/Docker and AWS g4dn.xlarge runs of 26 September 2026", size: 20, color: "57606A" })] }));
note("How to use this handbook: each concept is explained in three steps — **What it is** (definition), **How it works** (the mechanism, down to the hardware), and **In your runs** (the number or artefact measured on your own machines). The PDF shows the raw evidence; this handbook teaches the concepts needed to read it. Read Part 1 first, then follow any path.");
body.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }));

// ---------------------------------------------------------------- PART 0
H1("0. The big picture");
Pp("An inference request in this platform travels down a stack of layers and the answer travels back up. Each layer turns the request into a lower-level form: Python objects become bytes, bytes become JVM tasks, tasks become operator calls, operators become GPU kernel launches, launches become commands on the PCIe bus, and commands become warps of 32 threads executing 128-bit machine instructions on streaming multiprocessors.");
table([
  ["#", "Layer", "Unit of work", "Unit of data", "Key concept"],
  ["1", "Your Python code", "function call", "numpy array / tensor", "eager execution"],
  ["2", "Py4J", "text command", "object reference", "RPC over localhost TCP"],
  ["3", "Spark driver (JVM)", "job -> stage -> task", "partition", "DAG scheduling"],
  ["4", "Executor JVM", "task", "serialized closure + rows", "serialization"],
  ["5", "Python worker", "mapPartitions / UDF call", "pickle frames / Arrow batches", "process model"],
  ["6", "PyTorch ATen", "operator", "tensor (pointer, shape, strides)", "dispatcher"],
  ["7", "cuBLAS / cuDNN / oneDNN", "algorithm choice", "tiles", "GEMM, Winograd, JIT"],
  ["8", "CUDA runtime + driver", "API call -> pushbuffer entry", "kernel params, DMA descriptors", "asynchrony, launch latency"],
  ["9", "PCIe", "transaction-layer packet", "<= 256-byte payloads", "DMA, MMIO, doorbell"],
  ["10", "GPU front end", "grid -> blocks", "block -> SM assignment", "GigaThread scheduling"],
  ["11", "Streaming multiprocessor", "warp instruction", "32-bit registers", "SIMT, occupancy"],
  ["12", "Memory hierarchy", "load/store", "128-byte lines, 32-byte sectors", "coalescing, bandwidth"],
], [5, 20, 22, 26, 27]);
Pp("Single-GPU and hybrid modes skip layers 2–5: one Python process calls the CUDA driver directly. That single difference explains why those modes are 20–100× faster than Spark-distributed mode in every environment you tested.");

// ---------------------------------------------------------------- PART 1
H1("1. Foundations: bits, numbers and memory");
H2("1.1 Binary, hexadecimal and bytes");
concept("Bit, byte, word",
  "A bit is 0 or 1. A byte is 8 bits (values 0–255). CPUs and GPUs move data in words: 32-bit registers on the GPU, 64-bit general registers on x86-64, and 128/256/512-bit vector registers.",
  "Hexadecimal writes 4 bits per digit, so one byte is exactly two hex digits (0x00–0xFF). That is why memory dumps are printed in hex: `3d d2 a0 76` is four bytes = one float32.",
  "Every hex dump in the PDF (tensor storage, pickle frames, Arrow buffers, SASS encodings) is read two hex digits per byte.");
concept("Endianness",
  "The order in which the bytes of a multi-byte value are stored in memory.",
  "Little-endian (x86, NVIDIA GPUs, ARM by default) stores the least-significant byte at the lowest address. Big-endian stores the most-significant byte first. Network protocols and Java's DataOutputStream use big-endian ('network byte order').",
  `Your first EW-signal value ${v0.value !== undefined ? v0.value.toFixed(8) : ""} is ${v0.hex || "0x3dd2a076"} as a number but appears in RAM as ${(v0.hex || "0x3dd2a076").slice(2).match(/../g).reverse().join(" ")} (little-endian). The PySpark frame length prefix 00 00 86 aa is big-endian (Java convention): 0x86aa = 34,474 bytes.`);
concept("Two's complement integers",
  "The universal encoding of signed integers: the top bit has negative weight.",
  "-1 is all ones (0xFFFFFFFF for 32 bits). Adding and subtracting work identically for signed and unsigned values, which is why hardware needs only one adder.",
  "PySpark's END_OF_DATA_SECTION marker is -1 = FF FF FF FF; Arrow's IPC continuation marker is also 0xFFFFFFFF.");

H2("1.2 Floating point (IEEE-754)");
concept("float32 (single precision)",
  "32 bits: 1 sign bit, 8 exponent bits (bias 127), 23 fraction bits with an implicit leading 1. Value = (-1)^s × 1.fraction × 2^(exponent-127). Roughly 7 decimal digits, range about 1e-38 to 3e38.",
  ["Special exponents: all zeros = zero or subnormal numbers (gradual underflow); all ones = infinity or NaN.",
   "Every model input and weight in this platform is float32 unless you cast it."],
  v0.hex ? `${v0.hex}: sign ${v0.sign}, exponent ${v0.exp} (${v0.exp}-127 = ${v0.exp - 127}), fraction 0x${Number(v0.mantissa).toString(16)} → 1.${Number(v0.mantissa).toString(16)}h × 2^${v0.exp - 127} = ${Number(v0.value).toFixed(8)}.` : null);
concept("float16 and bfloat16",
  "Two 16-bit formats. fp16 = 1 sign, 5 exponent, 10 fraction bits (range ±65,504). bf16 = 1 sign, 8 exponent, 7 fraction bits: the same range as fp32 but only ~3 significant digits.",
  "bf16 is simply the top 16 bits of an fp32, so conversion is a truncation with rounding; it rarely overflows. fp16 keeps more precision but overflows above 65,504. Tensor Cores consume fp16/bf16 and accumulate in fp32.",
  bits.length ? `Value ${bits[0].value.toFixed(8)} became ${bits[0].fp16.toFixed(6)} in fp16 and ${bits[0].bf16.toFixed(6)} in bf16 — bf16 loses more precision.` : null);
concept("Rounding, FMA and determinism",
  "Every floating-point operation rounds to the nearest representable value. A fused multiply-add (FMA) computes a×b+c with a single rounding.",
  "Because rounding happens after each step, (a+b)+c can differ from a+(b+c). Parallel reductions on GPUs and different SIMD widths on CPUs therefore give bit-slightly-different results — which is why CPU and GPU predictions differ in the last digits.",
  "Every x86 `vfmadd231ps` and GPU `FFMA` in the listings is one FMA: 2 floating-point operations (FLOP) with one rounding.");

H2("1.3 Memory, pointers and layout");
concept("Virtual memory and pages",
  "Each process sees a private virtual address space. The OS maps virtual pages (usually 4 KB) to physical RAM frames through page tables; the MMU translates on every access (cached in the TLB).",
  "A page can be moved or swapped out by the OS at any time — unless it is pinned (page-locked). DMA devices such as the GPU copy engine work on physical addresses, so they need pinned pages.",
  "This is exactly why pageable host->device copies are slower than pinned ones (Part 5).");
concept("Alignment",
  "An address is N-byte aligned if it is a multiple of N.",
  "Vector loads are fastest when aligned to their width (32 B for AVX2, 64 B for AVX-512 and for one cache line); GPU 128-bit loads require 16-byte alignment. Allocators return aligned blocks: PyTorch uses 64 B on CPU and at least 256 B on GPU.",
  "The numpy-created signal batch was not 64-byte aligned; tensors that PyTorch allocates are.");
concept("Tensor = pointer + shape + strides + dtype",
  "A tensor does not own an 'array'; it describes a view into a storage buffer: a start pointer, sizes per dimension, a stride per dimension (elements to skip), and an element type.",
  "Element [i,j,k,l] is at pointer + (i·s0 + j·s1 + k·s2 + l·s3)·elementsize. Transpose, slicing and reshape usually just change strides (no copy). `torch.from_numpy` shares the numpy buffer (zero copy).",
  "EW batch [4,128] has strides [128,1]. An image [1,3,224,224] in NCHW has strides (150528, 50176, 224, 1); in channels_last (NHWC), (150528, 1, 672, 3).");
concept("Memory formats: NCHW, NHWC and blocked layouts",
  "Ways of ordering a 4-D image tensor in memory: N = batch, C = channels, H = height, W = width.",
  "NCHW stores whole channel planes one after another; NHWC stores all channels of one pixel together (better for Tensor Cores). CPU libraries use blocked layouts such as nChw8c / aBcd8b, where channels are grouped in blocks of 8 or 16 so that one SIMD register holds 8 (AVX2) or 16 (AVX-512) channels of one pixel.",
  "oneDNN chose `Acdb8a / aBcd8b` on your laptop (AVX2, 8 floats per YMM register) and `Acdb16a / aBcd16b` on AWS (AVX-512, 16 floats per ZMM register).");

// ---------------------------------------------------------------- PART 2
H1("2. Spark and the JVM");
H2("2.1 Spark architecture");
concept("Driver, master, worker, executor",
  "The **driver** runs your program and the scheduler. The **master** (standalone cluster manager) tracks workers. A **worker** is a daemon on each machine that launches **executors** — JVM processes that run tasks and cache data.",
  ["In local[N] mode, driver and executor live in one JVM with N task threads — no master or workers.",
   "In standalone mode (your AWS run: spark://10.0.0.240:7077) the driver asks the master for executors; the master tells workers to start them; executors register back with the driver."],
  "Windows and WSL2 used local[2]; AWS used a master container plus a GPU-worker container with one 4-core executor.");
concept("Job, stage, task, partition",
  "An action (collect, count) creates a **job**. The DAG scheduler splits it at shuffle boundaries into **stages**. Each stage runs one **task per partition**. A partition is a slice of the dataset.",
  "Tasks within a stage are independent and run in parallel, limited by the number of task slots = executor cores / spark.task.cpus.",
  "The platform's distributed inference is one stage (parallelize → mapPartitions → collect). Each task loads all 10 models, so partitions multiply model-loading cost (Phase 2).");
concept("Task slots, spark.task.cpus and memory accounting",
  "Concurrency = executor cores ÷ spark.task.cpus. This platform sets spark.task.cpus = 2.",
  ["local[2] → 1 concurrent task; a 4-core executor → 2 concurrent tasks.",
   "`-m 4g` on a worker and spark.executor.memory are bookkeeping for the JVM heap. Python workers, the CUDA context and model weights live outside the heap and are not counted — the reason the laptop ran out of real RAM while Spark thought it had plenty."],
  "local[4] (2 concurrent tasks × 10 models each) exhausted the 8 GB laptop; local[2] worked.");

H2("2.2 PySpark internals");
concept("Py4J (Python ↔ JVM bridge)",
  "PySpark is a Python client of a JVM. Py4J connects them with a localhost TCP socket.",
  "Each call such as sc.parallelize becomes a small text command (call, object id, method name, arguments, end). The JVM runs it by reflection and replies with a value or an object reference. Bulk data is not sent through Py4J: parallelize writes pickled data to a temporary file, and collect results return over a separate authenticated socket.",
  `Windows run: gateway port ${g(W, "spark", "py4j_java_port") || "-"}, driver Python PID ${g(W, "spark", "driver_python_pid") || "-"}, JVM PID ${g(W, "spark", "jvm_pid") || "-"}. On Windows, the 'connection forcibly closed' errors are Py4J noticing that the JVM died.`);
concept("Serialization: pickle, cloudpickle and framing",
  "Serialization turns objects into bytes. Python's pickle is a small stack-machine language: opcodes such as PROTO, FRAME, SHORT_BINUNICODE, STACK_GLOBAL and BYTEARRAY8 rebuild the object when replayed.",
  ["cloudpickle can also serialize functions and lambdas by value — that is how your mapPartitions function (and the model weights it references) reach executors.",
   "On the JVM↔worker socket every record batch is framed as [4-byte big-endian length][pickle bytes]; -1 ends the data."],
  `One partition of 64 × 128 float32 (32,768 raw bytes) became ${g(W, "spark", "pickle_frame_bytes") || 34478} bytes on the wire (≈5% overhead): the frame header, the name numpy._core.numeric._frombuffer, and a 512-byte BYTEARRAY8 per row.`);
code(`00 00 86 aa             frame length (big-endian) = 34,474 bytes
80 05                   PROTO 5
95 9f 86 00 00 ...      FRAME + 8-byte little-endian size
5d 94 28                EMPTY_LIST, MEMOIZE, MARK
8c 13 numpy._core.numeric  8c 0b _frombuffer  94 93   -> STACK_GLOBAL
28 96 00 02 00 00 00 00 00 00   MARK, BYTEARRAY8 len 0x200 = 512 bytes (one row)
6a 0c b9 be ...         the float32 values themselves`);
concept("Apache Arrow and pandas_udf",
  "Arrow is a columnar in-memory format: each column is a set of contiguous buffers — a validity bitmap (1 bit per value, 1 = not null) and a data buffer — aligned to 8 or 64 bytes.",
  ["The Arrow IPC stream is: 0xFFFFFFFF continuation marker, a 4-byte metadata length, a FlatBuffer message (Schema or RecordBatch), then the body buffers.",
   "With pandas_udf the JVM converts rows to Arrow record batches; the Python side maps them to pandas without creating one Python object per row — far cheaper for wide numeric data."],
  "Column [1.5, null, -2.25, 3.0]: validity bitmap 0x0d (bits 1,0,1,1 read LSB-first) and data 0000c03f 00000000 000010c0 00004040. The engine=udf runs return real per-sample predictions (2.7 MB logs) instead of counts.");
concept("Python worker process model: fork vs spawn",
  "Each concurrent Python task runs in a separate Python process connected to the executor JVM by a local socket.",
  ["Linux: the JVM starts one `pyspark.daemon`, which fork()s a worker per task. fork copies the address space copy-on-write, so the child starts instantly with the parent's modules already imported. With spark.python.worker.reuse = true, workers survive between tasks.",
   "Windows has no fork(): the JVM spawns `python -m pyspark.worker` directly, and every worker pays interpreter start-up plus `import torch` (1–3 s)."],
  `AWS: 4 tasks ran in PIDs with one common parent (the daemon). Windows: parent PID = the JVM itself. The same 200k-row job took ${f(g(W, "spark", "udf_vs_rdd_s", "rdd_pickle"), 2)} s (RDD) on Windows vs ${f(g(A, "spark", "udf_vs_rdd_s", "rdd_pickle"), 2)} s on AWS.`);
concept("Task metrics and the event log",
  "Spark records per-task timing: executorDeserializeTime (unpacking the task), executorRunTime (wall time in the task thread), executorCpuTime (CPU time of that JVM thread only), jvmGCTime and resultSize. The event log writes one JSON line per scheduler event (TaskStart, TaskEnd, StageCompleted …).",
  "Run time much larger than CPU time means the JVM thread was blocked, here on the socket to the Python worker, which in turn waited for the GPU.",
  "An AWS GPU task showed about 9.4 s of run time but only about 73 ms of JVM CPU time: the real work happened in Python and on the GPU, invisible to the JVM's CPU counter.");

// ---------------------------------------------------------------- PART 3
H1("3. PyTorch: from Python call to kernel");
concept("Eager execution",
  "PyTorch runs each operator immediately when Python calls it (no graph compilation unless you use torch.compile).",
  "Every layer of forward() is an operator call that crosses the Python → C++ boundary, goes through the dispatcher and returns a new tensor. On a GPU the call returns as soon as the kernel is queued — the GPU runs asynchronously.",
  "A 3-layer MLP on 256 signals is about 20 kernel launches; ResNet18 on 8 images is about 100–110.");
concept("ATen and the dispatcher",
  "ATen is PyTorch's C++ tensor library. The dispatcher chooses the implementation of an operator from dispatch keys (device CPU/CUDA, dtype, autograd, autocast…).",
  "aten::linear → aten::t (transpose view) → aten::addmm → the CUDA implementation → cuBLAS → cudaLaunchKernel. Each step costs CPU time: microseconds per operator.",
  "Measured chain for the first Linear layer: about 0.2 ms on the AWS Xeon, about 2.3 ms on the Windows laptop (profiler on). For tiny models, this CPU overhead exceeds the GPU work.");
concept("CUDA streams and asynchrony",
  "A stream is an ordered queue of GPU work. Work in different streams may overlap.",
  "cudaLaunchKernel and cudaMemcpyAsync only enqueue; synchronize waits. The platform's single_gpu mode runs each model on its own stream so small kernels from different models fill the GPU concurrently.",
  `Parallel streams: ${Math.round(svs("aws_g4dn").single_gpu_parallel_streams || 0).toLocaleString()} samples/s on the T4, ${Math.round(svs("wsl2_docker").single_gpu_parallel_streams || 0).toLocaleString()} on the GTX 1650 under WSL2, ${Math.round(svs("windows").single_gpu_parallel_streams || 0).toLocaleString()} on the same GPU under Windows.`);
concept("cuBLAS and GEMM tiling",
  "GEMM = general matrix multiply C = αAB + βC. Linear layers are GEMMs; convolutions are usually turned into GEMMs.",
  ["Each thread block computes one output tile (e.g. 128×32) and loops over K, staging tiles of A and B through shared memory and keeping the partial C tile in registers, so every loaded value is reused many times.",
   "Kernel names encode the choice: volta_sgemm_128x32_sliced1x4_tn = single-precision, 128×32 tile, K sliced across 4 warps, A transposed / B not ('tn')."],
  "ew_classifier used volta_sgemm_128x32_*, volta_sgemm_32x32_sliced1x4_tn, volta_sgemm_128x64_tn and cublasLt::splitKreduce_kernel.");
concept("Split-K",
  "Splitting the K (inner) dimension of a GEMM across several blocks, then summing the partial results with a second 'reduce' kernel.",
  "Used when M×N is too small to occupy every SM but K is large — typical for small batches of an MLP.",
  "The splitKreduce_kernel entries in your ew_classifier traces.");
concept("Convolution algorithms: implicit GEMM, im2col, Winograd",
  "cuDNN offers several algorithms for the same convolution and picks the fastest for the shape and GPU.",
  ["im2col copies image patches into a matrix and runs one GEMM; implicit GEMM computes the same addresses on the fly without the copy.",
   "Winograd transforms 3×3 convolutions into a domain that needs about 2.25× fewer multiplications (F(2×2,3×3)) at the cost of transforms: generateWinogradTilesKernel pre-transforms the filters, winogradForwardData/Filter transform the inputs."],
  "ResNet18 used scudnn_128x64_relu (implicit GEMM with fused ReLU) for the stem and scudnn_winograd_128x128_ldg1_ldg4_relu for the 3×3 layers.");
concept("Kernel fusion",
  "Combining several operations into one kernel so intermediate results stay in registers instead of going to DRAM and back.",
  "cuDNN fuses bias + ReLU into convolution epilogues ('relu' in the name). torch.compile (TorchInductor) fuses element-wise chains automatically and generates Triton kernels for them.",
  "Inductor compiled ew_classifier into 4 fused Triton kernels (batch-norm + addmm-bias + ReLU) plus 6 cuBLAS mm/addmm calls.");
concept("Profiling: Kineto, CUPTI and correlation IDs",
  "torch.profiler uses Kineto, which uses NVIDIA's CUPTI to record every CUDA API call on the CPU and every kernel/memcpy on the GPU.",
  "Each cudaLaunchKernel gets a correlation ID that CUPTI also attaches to the GPU-side kernel record, so you can tell which CPU call launched which kernel. CUPTI also reports grid, block, registers per thread, shared memory and estimated occupancy.",
  "trace_resnet18.json and trace_ew_classifier.json in each environment's lowlevel folder; open them at ui.perfetto.dev.");

// ---------------------------------------------------------------- PART 4
H1("4. The CPU: x86 ISA, registers and SIMD");
concept("ISA (instruction set architecture)",
  "The contract between software and a processor: the instructions, registers, data types and memory model. x86-64 is the ISA of your i5-9300H and the AWS Xeon 8259CL.",
  "Extensions add instructions over time: SSE (128-bit), AVX/AVX2 (256-bit), FMA3, AVX-512 (512-bit + mask registers), VNNI (int8 dot products). Software checks what exists with the CPUID instruction.",
  "Laptop: AVX2 + FMA3. AWS Xeon: AVX-512F/DQ/CD/BW/VL + AVX512_VNNI.");
concept("Registers",
  "The CPU's fastest storage, inside the core, named by instructions.",
  ["16 general-purpose 64-bit registers (rax, rbx, rcx, rdx, rsi, rdi, rbp, rsp, r8–r15); their lower 32 bits are eax, esi, edx…",
   "Vector registers: 16 XMM (128-bit) → extended to YMM (256-bit, AVX) → 32 ZMM (512-bit, AVX-512) plus 8 opmask registers k0–k7.",
   "FLAGS holds the results of comparisons used by conditional jumps; RIP is the instruction pointer.",
   "Calling convention (System V on Linux): arguments in rdi, rsi, rdx, rcx…; float return value in xmm0."],
  "In the dot-product listing, a = rdi, b = rsi (copied to rcx), n = edx; the result comes back in xmm0.");
concept("SIMD and FMA throughput",
  "Single Instruction, Multiple Data: one instruction operates on every lane of a vector register.",
  "A YMM register holds 8 float32; `vfmadd231ps` performs 8 FMAs = 16 FLOP. A Skylake-class core has 2 FMA ports → 32 FLOP per cycle per core with AVX2 (64 with AVX-512 on two 512-bit ports).",
  "Your 4-core laptop at ~4 GHz: about 4 × 32 × 4e9 ≈ 0.5 TFLOPS fp32 peak — roughly 1/8 of the GTX 1650.");
concept("Runtime ISA dispatch and JIT code generation",
  "Libraries ship several versions of hot kernels and pick one at run time; oneDNN goes further and generates machine code at run time (JIT, using the Xbyak assembler) specialised to the exact shape and ISA.",
  "torch.backends.cpu.get_cpu_capability() reports the ATen level chosen. ONEDNN_VERBOSE=1 prints each primitive with its implementation (jit:avx2, jit:avx512_core, brg…), memory formats and time.",
  "ResNet stem conv (64×3×7×7): jit:avx2 on the laptop vs jit:avx512_core on AWS, with blocked formats of 8 vs 16 channels.");
H2("4.1 The dot-product loop, instruction by instruction");
Pp("Source: `float dot(const float* a, const float* b, int n){ float s=0; for(int i=0;i<n;i++) s+=a[i]*b[i]; return s; }` compiled with `gcc -O3 -mavx2 -mfma -ffast-math` inside the WSL2 container. This is the inner loop of every Linear layer.");
code(asm.slice(0, 32).join("\n"));
table([
  ["Instruction", "Meaning"],
  ["endbr64", "Control-flow-enforcement landing pad (security feature; no work)"],
  ["testl %edx,%edx / jle", "if n <= 0 return 0"],
  ["vxorps %xmm0,%xmm0,%xmm0", "zero the accumulator (x XOR x = 0; clears the whole YMM)"],
  ["shrl $3 / salq $5", "n/8 iterations × 32 bytes = byte length of the vector part"],
  ["vmovups (%rdi,%rax),%ymm3", "load 8 floats of a (32 bytes, unaligned allowed)"],
  ["vfmadd231ps (%rcx,%rax),%ymm3,%ymm0", "ymm0 += ymm3 × 8 floats of b from memory: 8 FMAs, one instruction"],
  ["addq $32,%rax / cmpq / jne", "advance 32 bytes, loop until done — 4 instructions per 16 FLOP"],
  ["vextractf128, vmovhlps, vshufps + vaddps", "horizontal reduction: fold 8 lanes into 1 float"],
  ["vzeroupper", "clear upper YMM halves before returning (avoids AVX-SSE transition penalty)"],
  ["xmm / scalar tail", "handle the n mod 8 leftover elements"],
], [42, 58], [0]);
note("Production GEMM kernels (MKL, oneDNN) use the same instructions but keep a tile of 12–24 accumulator registers and reuse every loaded value many times, so they approach the 32 FLOP/cycle limit instead of being limited by loads.");
concept("Caches and memory bandwidth (CPU)",
  "L1 (32–48 KB per core, ~4 cycles), L2 (256 KB–2 MB per core, ~12 cycles), L3 (shared, several MB, ~40 cycles), then DRAM (~80–100 ns). Data moves in 64-byte cache lines.",
  "A kernel is memory-bound if it performs few FLOPs per byte loaded (a dot product: 2 FLOP per 8 bytes) and compute-bound if it reuses data from registers/cache (a well-tiled GEMM).",
  "AWS Xeon 8259CL: 35.8 MB L3; laptop i5-9300H: 8 MB L3.");

// ---------------------------------------------------------------- PART 5
H1("5. The bus and the driver");
concept("PCI Express (PCIe)",
  "The point-to-point serial bus connecting the CPU's root complex to the GPU. Bandwidth = lanes × per-lane rate.",
  ["Gen3 runs 8 GT/s per lane with 128b/130b encoding → 0.985 GB/s per lane per direction. x16 = 15.75 GB/s; x8 = 7.88 GB/s. Gen4 doubles, Gen5 doubles again.",
   "Data travels in Transaction Layer Packets (TLPs) with ~20–24 bytes of header per ≤256-byte payload, so ~80–85% of line rate is the practical maximum."],
  `Laptop GTX 1650: Gen3 x16 (15.76 GB/s theoretical, ${f(g(W, "bus", "copies", 3, "h2d_pinned"), 2)} GB/s measured pinned at 4 MB). AWS T4: Gen3 x8 (7.88 GB/s theoretical, ${f(g(A, "bus", "copies", 6, "h2d_pinned"), 2)} GB/s measured).`);
concept("DMA, MMIO and the doorbell",
  "DMA (direct memory access) lets a device read/write host RAM without the CPU. MMIO (memory-mapped I/O) lets the CPU write device registers as if they were memory.",
  "The GPU's copy engines are DMA engines. To start work, the driver writes commands into memory the GPU can read, then performs one MMIO write — the doorbell — telling the GPU where the new commands end.",
  "Every kernel launch in the traces ends in such a doorbell write.");
concept("Pageable vs pinned (page-locked) memory",
  "Pageable memory is ordinary malloc/numpy memory the OS may move; pinned memory is locked to physical frames.",
  "The DMA engine needs fixed physical addresses. For pageable memory the driver first copies (with the CPU) into its own pinned staging buffer, chunk by chunk, then DMAs — two copies and CPU-bound. Pinned memory is DMA'd directly. torch: tensor.pin_memory() and .to('cuda', non_blocking=True).",
  `64 MB host→device: pageable ${f(g(W, "bus", "copies", 5, "h2d_pageable"), 2)} vs pinned ${f(g(W, "bus", "copies", 5, "h2d_pinned"), 2)} GB/s on Windows; ${f(g(A, "bus", "copies", 5, "h2d_pageable"), 2)} vs ${f(g(A, "bus", "copies", 5, "h2d_pinned"), 2)} on AWS. The platform's inputs are pageable numpy arrays, so inference pays the lower rate.`);
concept("Pushbuffer and kernel launch",
  "A ring buffer of GPU commands ('methods') in memory visible to the GPU. A launch writes: grid and block dimensions, shared-memory size, the address of the kernel's machine code, and a pointer to its parameters.",
  "cudaLaunchKernel's CPU cost = argument marshalling + writing the pushbuffer + (eventually) the doorbell. The GPU's host interface fetches commands by DMA, and the scheduler distributes blocks to SMs.",
  null);
concept("Driver models: Linux, WDDM and WSL2",
  "How the OS sits between the CUDA user-mode driver and the hardware.",
  ["Linux: the NVIDIA kernel driver; user space writes pushbuffers and doorbells almost directly.",
   "Windows WDDM (display driver model): every GPU submission goes through the Windows graphics kernel (dxgkrnl) and its scheduler, because the GPU also drives the display; submissions may be batched. (TCC mode avoids this but is only for datacentre cards.)",
   "WSL2: the Linux guest sees a paravirtualised /dev/dxg device that forwards to the same Windows host driver."],
  `Launch cost: ${f(g(W, "bus", "launch_enqueue_us"))} µs on Windows native, ${f(g(L, "bus", "launch_enqueue_us"))} µs in WSL2, ${f(g(A, "bus", "launch_enqueue_us"))} µs on AWS Linux. This is why the same GTX 1650 ran parallel CUDA streams about 5× faster under WSL2 than natively on Windows.`);
concept("Commit charge vs overcommit",
  "Rules for how much memory processes may reserve.",
  "Windows charges every committed page against RAM + pagefile at reservation time and refuses when the commit limit is reached. Linux overcommits: it grants reservations and only fails (OOM killer) when pages are actually touched and memory is exhausted.",
  "The Windows JVM crashed with 'The paging file is too small for this operation' (errno 1455) while committing a 64 MB heap region.");

// ---------------------------------------------------------------- PART 6
H1("6. The GPU");
table([
  ["Property", "GTX 1650 (laptop)", "Tesla T4 (AWS)"],
  ["Architecture / compute capability", "Turing TU117, sm_75", "Turing TU104, sm_75"],
  ["Streaming multiprocessors (SMs)", String(g(W, "gpu", "props", "multi_processor_count") || 16), String(g(A, "gpu", "props", "multi_processor_count") || 40)],
  ["FP32 lanes ('CUDA cores')", String(g(W, "gpu", "theoretical", "cuda_cores") || 1024), String(g(A, "gpu", "theoretical", "cuda_cores") || 2560)],
  ["Tensor Cores", "none", "320"],
  ["32-bit registers per SM", "65,536", "65,536"],
  ["Max threads per SM", "1,024 (32 warps)", "1,024 (32 warps)"],
  ["Shared memory per SM", "64 KB", "64 KB"],
  ["L2 cache", "1 MB", "4 MB"],
  ["Memory", "4 GB GDDR5, 128-bit, 128 GB/s", "16 GB GDDR6, 256-bit, 320 GB/s"],
  ["Measured DRAM copy", `${f(g(W, "bus", "d2d_gbps"))} GB/s`, `${f(g(A, "bus", "d2d_gbps"))} GB/s`],
  ["FP32 GEMM measured", `${f(g(W, "bus", "gemm_tflops", "torch.float32"), 2)} TFLOPS`, `${f(g(A, "bus", "gemm_tflops", "torch.float32"), 2)} TFLOPS`],
  ["FP16 GEMM measured", `${f(g(W, "bus", "gemm_tflops", "torch.float16"), 2)} TFLOPS`, `${f(g(A, "bus", "gemm_tflops", "torch.float16"), 2)} TFLOPS`],
], [40, 30, 30]);
concept("SIMT: grids, blocks, warps and threads",
  "Single Instruction, Multiple Threads. A kernel launch creates a **grid** of **blocks**; each block has up to 1,024 **threads**; the hardware groups threads into **warps** of 32 that execute one instruction together.",
  ["Each thread has its own registers and can branch; if threads of a warp diverge, the warp executes both paths with inactive lanes masked (predication).",
   "Blocks are independent and can run in any order on any SM; threads inside a block can share memory and synchronise (__syncthreads / BAR)."],
  "Triton's bias_relu: grid = 16 blocks, 128 threads (4 warps) each; every thread handles 8 floats.");
concept("Streaming multiprocessor (SM)",
  "The GPU's core. A Turing SM has 4 processing blocks, each with a warp scheduler, 16 FP32 lanes, 16 INT32 lanes, a 16K-register file slice, load/store units and (TU104 only) 2 Tensor Cores; plus 64 KB of shared memory/L1 per SM.",
  "Each cycle, each scheduler picks one ready warp and issues one instruction for it. A 32-thread FP32 instruction occupies a 16-lane block for 2 cycles. FP32 and INT32 can issue concurrently.",
  null);
concept("Latency hiding and occupancy",
  "GPUs hide latency (~4 cycles for an FFMA, hundreds for a DRAM load) by switching between many resident warps rather than using big caches or out-of-order execution. **Occupancy** = resident warps ÷ maximum warps per SM.",
  ["Resident blocks per SM = min(register limit, thread limit, shared-memory limit, 16 block slots).",
   "Registers are allocated per warp in chunks of 256: regs/warp = ceil(regs_per_thread × 32 / 256) × 256."],
  "volta_sgemm_128x32_sliced1x4_tn: 134 regs × 32 = 4,288 → 4,352 per warp × 8 warps = 34,816 per block; 65,536 / 34,816 = 1 block = 8 of 32 warps = 25% — exactly CUPTI's figure. Low occupancy is deliberate: registers hold the output tile.");
note("Occupancy is not efficiency. A GEMM at 25% occupancy with high register reuse can be near peak; an element-wise kernel at 100% occupancy is still limited by DRAM bandwidth.");
concept("Memory hierarchy and coalescing",
  "Registers (per thread) → shared memory/L1 (per SM, ~30 cycles) → L2 (whole GPU) → DRAM (GDDR5/6, hundreds of cycles).",
  "Global memory is accessed in 32-byte sectors of 128-byte lines. If the 32 threads of a warp access 32 consecutive floats, the requests **coalesce** into four 32-byte sectors (128 bytes). With 128-bit loads (LDG.E.128) each thread fetches 4 floats, so one warp instruction moves 512 bytes in four full lines.",
  "The bias_relu kernel's two LDG.E.128 per operand per thread are perfectly coalesced.");
concept("Tensor Cores",
  "Matrix units in Volta and later GPUs (Turing TU102/104/106, not TU117) that execute a small matrix multiply-accumulate per instruction.",
  "On Turing, HMMA.1688 multiplies a 16×8 fp16 tile by an 8×8 tile and accumulates in fp16/fp32 for a whole warp. cuBLAS routes fp16/bf16 GEMMs to Tensor Core kernels automatically.",
  `FP16 GEMM: ${f(g(A, "bus", "gemm_tflops", "torch.float16"), 1)} TFLOPS on the T4 (Tensor Cores) vs ${f(g(W, "bus", "gemm_tflops", "torch.float16"), 2)} on the GTX 1650 (no Tensor Cores — slower than its own FP32).`);
concept("Peak FLOPS and the roofline",
  "Peak FP32 = SMs × FP32 lanes per SM × 2 (FMA) × clock. Peak bandwidth = memory clock × data rate × bus width / 8.",
  "Arithmetic intensity = FLOP per byte moved. If intensity × bandwidth < peak FLOPS, the kernel is memory-bound (roofline model). GEMM and convolution are compute-bound; ReLU, add and batch-norm in inference are memory-bound.",
  `GTX 1650: 16 × 64 × 2 × 2.1 GHz = 4.3 TFLOPS peak, ${f(g(W, "bus", "gemm_tflops", "torch.float32"), 2)} measured. T4: 40 × 64 × 2 × 1.59 GHz = 8.1 TFLOPS peak, ${f(g(A, "bus", "gemm_tflops", "torch.float32"), 2)} measured.`);

// ---------------------------------------------------------------- PART 7
H1("7. Compilation: from Python to GPU machine code");
concept("The compilation pipeline",
  "Triton (and TorchInductor, which generates Triton) lowers code through several intermediate representations.",
  ["**TTIR** (Triton IR): tensor-level operations such as tt.load, tt.store, arith.addf — no notion of threads.",
   "**TTGIR** (Triton GPU IR): adds a layout saying how each tensor is spread over threads and warps, e.g. #blocked<{sizePerThread=[4], threadsPerWarp=[32], warpsPerCTA=[4]}>.",
   "**LLVM IR** (NVPTX target): scalar SSA code with GPU intrinsics.",
   "**PTX**: NVIDIA's virtual ISA — portable across GPU generations, unlimited virtual registers.",
   "**SASS**: the real machine code of one architecture (sm_75 here), produced by ptxas, packaged in a cubin."],
  "All five stages of bias_relu are saved in results/campaign_20260926/wsl2_docker/lowlevel/bias_relu.{ttir,ttgir,llir,ptx,cubin,sass}.");
code(ttgir.join("\n") || "(layout lines)", 8);
concept("PTX",
  "A documented, stable virtual instruction set. The driver can JIT-compile PTX for GPUs that did not exist when the code was built (that is how old binaries run on new GPUs).",
  ["Typed virtual registers: %r (32-bit int), %rd (64-bit), %f (float), %p (predicate).",
   "Special registers: %tid.x (threadIdx), %ctaid.x (blockIdx).",
   "State spaces: .param (kernel arguments), .global (DRAM), .shared, .local.",
   "Predication: @%p1 ld.global.v4.b32 {…} executes only where %p1 is true — this is the bounds mask."],
  "The bias_relu PTX (first lines below).");
code(ptx.slice(ptxStart, ptxStart + 26).join("\n"));
concept("SASS and its encoding",
  "The native instruction set of an NVIDIA GPU generation. On Volta/Turing/Ampere every instruction is a 128-bit word.",
  ["The low bits encode the opcode and operands; the high bits contain **compiler-set scheduling control**: stall count (cycles before the next instruction may issue), yield hint, and which of 6 scoreboard barriers the instruction sets or waits on.",
   "The hardware does not track most dependencies itself — ptxas schedules them. Variable-latency results (loads, S2R) signal a scoreboard; the consumer waits on it."],
  "cuobjdump -res-usage: REG:26 STACK:0 SHARED:0 LOCAL:0 — 26 registers per thread, no spills.");
code(sass.slice(0, 52).join("\n"));
table([
  ["SASS", "What the SM does"],
  ["S2R R0, SR_TID.X / SR_CTAID.X", "read threadIdx / blockIdx from special registers (variable latency → scoreboard)"],
  ["CS2R R12, SRZ", "zero a register pair fast — initialises the masked-out load targets to 0"],
  ["IMAD.SHL / LOP3.LUT 0x1fc", "lane offset = (tid × 4) & 508 — which 4 floats this thread owns"],
  ["IMAD R0, R3, 0x400, R0", "offs = blockIdx × 1024 + lane offset"],
  ["SHF / SGXT / LEA.HI / LOP3 0xffffffc0", "offs % 64 without division: power-of-two modulo via shift, sign fix-up and mask (~63)"],
  ["ISETP.GE.AND P0, PT, R0, c[0x0][0x178]", "predicate P0 = offs >= n (c[0x0][0x178] is kernel argument n in constant bank 0)"],
  ["IMAD.WIDE R2, R0, 4, c[0x0][0x160]", "64-bit address = x_ptr + offs × 4"],
  ["@!P0 LDG.E.128.SYS R12, [R2]", "load 4 floats (128 bits) into R12–R15 only where in bounds"],
  ["FADD R12, R20, R12", "x + bias"],
  ["FMNMX R12, RZ, R12, !PT", "max(0, value) = ReLU (RZ is the always-zero register)"],
  ["@!P0 STG.E.128.SYS [R4], R12", "store 4 results"],
  ["@P1 EXIT / EXIT / BRA self / NOP", "end of the thread; branch-to-self and NOPs pad the code"],
], [42, 58], [0]);
concept("Uniform registers, constant banks and kernel parameters",
  "Turing added a uniform datapath: UR registers hold values identical for the whole warp. Kernel arguments are placed by the driver in constant bank 0 (c[0x0][0x160] onward); the stack pointer comes from c[0x0][0x28].",
  "Reading constants is broadcast to all lanes at no extra cost, so the compiler uses c[0x0][…] operands directly in IMAD and ISETP.",
  null);
concept("cubin, fatbin, JIT and name mangling",
  "A cubin holds SASS for one architecture; a fatbin bundles cubins for several architectures plus PTX. At load time the driver picks matching SASS or JIT-compiles PTX (and caches it).",
  "C++ kernel names are mangled (Itanium ABI): _ZN2at6native29vectorized_elementwise_kernelILi4E… = at::native::vectorized_elementwise_kernel<4, …>. Linux CUPTI demangles; Windows traces showed raw mangled names.",
  "The 'sm_120 kernel error' in the repo history was exactly a missing-SASS-for-this-architecture problem, fixed by a newer torch wheel.");

// ---------------------------------------------------------------- PART 8
H1("8. The platform's execution modes");
table([
  ["Mode / option", "Path through the stack", "Strength", "Cost"],
  ["single_gpu (Mode 2)", "one Python process → all 10 models on one GPU, one CUDA stream per model", "no Spark overhead; streams overlap small kernels", "limited to one GPU's memory"],
  ["hybrid (Mode 3)", "memory-aware placement: models that fit in VRAM on GPU, rest on CPU (oneDNN)", "runs when VRAM is short", "CPU models are slower"],
  ["distributed (Mode 1)", "Spark RDD: parallelize → mapPartitions (each task loads 10 models) → collect", "scales across machines", "per-task model load, serialization, Python workers"],
  ["cluster_benchmark --device-mode cpu_only / gpu_only / hybrid", "same Spark path; the executor chooses CPU, forces CUDA, or uses CUDA if present", "one knob for mixed clusters", "as above"],
  ["submit_job --engine rdd", "cluster_engine mapPartitions; returns counts", "small result", "no per-sample output"],
  ["submit_job --engine udf", "pandas_udf over Arrow; returns one prediction per sample", "real predictions, columnar transport", "larger results, JVM↔Arrow conversion"],
  ["submit_pipeline_job --execution-mode service / cluster / auto", "service: HTTP to the kitchen server; cluster: run the pipeline in executors", "choose where heavy deps live", "network hop vs dependency isolation"],
], [22, 38, 20, 20]);
Pp("Throughput in your runs (samples per second, Spark distributed unless noted):");
table([
  ["Test", "Windows native", "WSL2 / Docker", "AWS g4dn (T4)"],
  ...["p1_modes_small", "p1_dist_large", "p2_partitions_2", "p2_partitions_16", "p3_tiny", "p3_xlarge", "p4_batch_16", "p4_batch_512",
    "p7_cpu_only_medium", "p7_gpu_only_medium", "p7_hybrid_medium", "eng_rdd_gpu_only", "eng_udf_gpu_only"].map((t) => [t, thr("windows", t), thr("wsl2_docker", t), thr("aws_g4dn", t)]),
  ["single GPU, parallel streams", `${Math.round(svs("windows").single_gpu_parallel_streams || 0).toLocaleString()}/s`, `${Math.round(svs("wsl2_docker").single_gpu_parallel_streams || 0).toLocaleString()}/s`, `${Math.round(svs("aws_g4dn").single_gpu_parallel_streams || 0).toLocaleString()}/s`],
], [34, 22, 22, 22], [0]);

// ---------------------------------------------------------------- PART 9
H1("9. What each test phase teaches");
table([
  ["Phase", "Varies", "Concept it demonstrates"],
  ["1 Mode comparison", "single_gpu vs hybrid vs distributed", "fixed per-task overhead (process start, model load, serialization) vs resident models on CUDA streams"],
  ["2 Partition scaling", "2 → 16 partitions", "one partition = one task = one full model load; parallelism capped by task slots"],
  ["3 Data size", "tiny → xlarge", "amortising fixed overhead: throughput grows ~10–15× with data size"],
  ["4 Batch size", "16 → 512", "fewer launches per sample; bigger GEMM tiles; flattens once launch overhead is amortised"],
  ["5 Worker scaling", "number of workers", "horizontal scaling; duplicated model loads per executor (not runnable on the 8 GB laptop)"],
  ["6/7/10 Device modes", "cpu_only / gpu_only / hybrid", "oneDNN AVX2/AVX-512 JIT code vs cuBLAS/cuDNN SASS"],
  ["8 GPU batch", "32 → 512 on GPU", "launch amortisation and VRAM limits"],
  ["Engines", "rdd vs udf", "pickle row streaming + counts vs Arrow columnar batches + per-sample predictions"],
  ["Spark vs single GPU", "no Spark at all", "upper bound of the hardware; the cost of the Spark layers"],
], [18, 24, 58]);

// ---------------------------------------------------------------- PART 10
H1("10. Failure modes, explained at the lowest level");
concept("Host out-of-memory in the torch CPU allocator",
  "`DefaultCPUAllocator: not enough memory: you tried to allocate 589824 bytes` means malloc/VirtualAlloc failed for one tensor.",
  "589,824 B = 128 × 128 × 3 × 3 × 4 bytes (one ResNet conv weight). With local[4], two concurrent Python workers each held all 10 models plus a CUDA context on an 8 GB host that also ran a 4 GB WSL2 VM.",
  "Fixed by local[2] (one concurrent task).");
concept("Windows commit limit",
  "`os::commit_memory … The paging file is too small (errno 1455)`.",
  "The JVM's G1 heap committed a new 64 MB region; Windows refused because RAM + pagefile commit was exhausted. The JVM aborted (hs_err_pid*.log, replay_pid*.log), and Py4J lost its socket ('connection forcibly closed').",
  "results/campaign_20260926/windows/jvm_crash/.");
concept("CUDA context poisoning",
  "`fatal: Memory allocation failure` followed by `CUDA error: unknown error`.",
  "The CUDA driver needs host memory to load or JIT-compile kernel images (cuDNN/cuBLAS load modules lazily). When that fails, the context is left in an error state and every later call reports cudaErrorUnknown; the process must restart.",
  null);
concept("GPU out of memory",
  "`CUDA error: out of memory` — cudaMalloc could not reserve VRAM for activations or cuDNN workspace.",
  "Under WDDM the Windows desktop compositor also holds part of the 4 GB, and PyTorch's caching allocator keeps freed blocks reserved.",
  "p8_gpu_batch_128 on Windows.");
concept("Truncated model bytes",
  "`unexpected pos X vs Y (inline_container.cc)` — torch.load read a zip container that ended early.",
  "The serialized model state shipped to the worker was cut off when the JVM or worker died mid-transfer.",
  null);
concept("VM thrashing and orchestration races",
  "The WSL2 multi-container cluster stalled at (0 + 2) / 4 with Docker API 500 errors: executors were OOM-killed inside the 3.75 GB VM and relaunched repeatedly. The first AWS run failed because SSM executed the script before cloud-init had written BUCKET into /etc/environment.",
  "Fixes: one container with local[2]; `cloud-init status --wait` plus passing BUCKET explicitly.",
  null);

// ---------------------------------------------------------------- PART 11
H1("11. Tools used to see all this");
table([
  ["Tool", "Shows", "Command / where"],
  ["nvidia-smi -q", "PCIe generation and width, clocks, power, memory", "nvidia-smi-q.txt (AWS)"],
  ["torch.cuda.get_device_properties", "SMs, registers per SM, L2, warp size, bus width", "lowlevel.json → gpu.props"],
  ["torch.profiler (Kineto + CUPTI)", "every CPU op, CUDA API call, kernel, memcpy; grid/block/registers/occupancy", "trace_*.json → ui.perfetto.dev"],
  ["ONEDNN_VERBOSE=1", "CPU primitive, ISA path, memory formats, time", "lowlevel.log section 1"],
  ["gcc -S", "x86 assembly of C code", "lowlevel.json → cpu.dot_avx2_asm"],
  ["Triton compiled.asm", "TTIR, TTGIR, LLVM IR, PTX, cubin", "lowlevel/bias_relu.*"],
  ["cuobjdump -sass / -res-usage", "SASS disassembly, registers/stack/shared per kernel", "bias_relu.sass"],
  ["TORCH_LOGS=output_code", "Inductor-generated Triton and call sequence", "inductor_ew_classifier_output_code.txt"],
  ["Spark REST API /api/v1", "stage and task metrics while the app runs", "lowlevel.log section 7"],
  ["Spark event log", "JSON line per scheduler event, per-task metrics", "spark-events/ (Linux legs)"],
  ["summarize_campaign.py", "status and throughput of every run, independent of exit code", "results/campaign_20260926/summary.md"],
], [30, 40, 30], [0]);
Pp("Regenerate everything: `LEG=windows bash benchmark/run_campaign.sh`, `python benchmark/lowlevel_trace.py --out <dir>`, `.\\deploy\\run_aws_campaign.ps1`, `python benchmark/summarize_campaign.py results/campaign_20260926`, `python benchmark/build_lowlevel_pdf.py`.");

// ---------------------------------------------------------------- GLOSSARY
H1("Glossary");
table([
  ["Term", "Meaning"],
  ["ALU / FMA pipe", "execution units that perform integer / floating-point arithmetic"],
  ["Arithmetic intensity", "FLOPs per byte moved; decides memory- vs compute-bound"],
  ["Block (CTA)", "group of up to 1,024 GPU threads scheduled on one SM"],
  ["Coalescing", "merging a warp's memory accesses into few 32-byte sectors"],
  ["Compute capability", "GPU architecture version (7.5 = Turing)"],
  ["Copy engine", "GPU DMA unit that moves data over PCIe"],
  ["cubin / fatbin", "GPU binary for one / several architectures"],
  ["DAG scheduler", "Spark component that splits a job into stages"],
  ["Doorbell", "MMIO register write that tells the GPU new commands are ready"],
  ["Executor", "Spark JVM process that runs tasks"],
  ["FLOP / TFLOPS", "floating-point operation / 10^12 per second"],
  ["GEMM", "general matrix multiply"],
  ["HMMA", "Tensor Core matrix multiply-accumulate instruction"],
  ["Kernel", "a function that runs on the GPU as a grid of threads"],
  ["MMIO", "memory-mapped I/O: device registers accessed like memory"],
  ["Occupancy", "resident warps ÷ max warps per SM"],
  ["Pinned memory", "page-locked host memory that the GPU can DMA directly"],
  ["Predicate", "1-bit register that enables or disables an instruction per lane"],
  ["PTX", "NVIDIA's virtual GPU ISA"],
  ["Py4J", "Python ↔ JVM RPC bridge used by PySpark"],
  ["SASS", "native GPU machine code"],
  ["Scoreboard", "barrier that tracks completion of variable-latency instructions"],
  ["SIMD / SIMT", "one instruction on many data lanes / many threads"],
  ["SM", "streaming multiprocessor, the GPU's core"],
  ["Spill", "a register value stored to (slow) local memory because registers ran out"],
  ["Stride", "elements to skip to move one step along a tensor dimension"],
  ["Task slot", "executor cores ÷ spark.task.cpus"],
  ["TLP", "PCIe transaction-layer packet"],
  ["Warp", "32 GPU threads executing in lockstep"],
  ["WDDM", "Windows display driver model (adds OS scheduling to GPU submissions)"],
  ["Winograd", "convolution algorithm that trades multiplications for transforms"],
  ["YMM / ZMM", "256-bit / 512-bit x86 vector registers"],
], [26, 74]);

// ---------------------------------------------------------------- document
const doc = new Document({
  creator: "pytorch-spark-inference-platform", title: "Concepts Handbook — From Python to Silicon",
  styles: {
    default: { document: { run: { font: BODY, size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 34, bold: true, font: BODY, color: "1B1F24" }, paragraph: { spacing: { before: 240, after: 180 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, font: BODY, color: ACCENT }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1, keepNext: true } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 22, bold: true, font: BODY, color: "1B1F24" }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2, keepNext: true } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } },
                                      { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1000, hanging: 270 } } } }] },
    { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: 16838 }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "Concepts Handbook — From Python to Silicon    ", size: 16, color: "57606A" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "57606A" })] })] }) },
    children: body,
  }],
});
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT, buf.length, "bytes"); });
