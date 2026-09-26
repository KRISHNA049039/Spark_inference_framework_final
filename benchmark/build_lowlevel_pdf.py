"""
build_lowlevel_pdf.py - Build docs/LOWLEVEL_EXECUTION_GUIDE_20260926.pdf from the
campaign outputs: results/campaign_<stamp>/{windows,wsl2_docker,aws_g4dn}/...

Every number, table, hex dump and instruction listing in the PDF is read from
those files (lowlevel/lowlevel.json, *.log, spark-events/, lowlevel/bias_relu.*),
so re-running the campaign and this script regenerates the document.

  python benchmark/build_lowlevel_pdf.py [results/campaign_20260926] [out.pdf]
"""
import glob
import html
import json
import math
import os
import re
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from summarize_campaign import parse as parse_log  # noqa: E402

ROOT = sys.argv[1] if len(sys.argv) > 1 else "results/campaign_20260926"
OUT = sys.argv[2] if len(sys.argv) > 2 else "docs/LOWLEVEL_EXECUTION_GUIDE_20260926.pdf"
LEGS = [("windows", "Windows 11 native"), ("wsl2_docker", "WSL2 / Docker (Linux)"), ("aws_g4dn", "AWS g4dn.xlarge")]

# ------------------------------------------------------------------ fonts/styles
FONT_DIR = "C:/Windows/Fonts"
try:
    pdfmetrics.registerFont(TTFont("Body", os.path.join(FONT_DIR, "arial.ttf")))
    pdfmetrics.registerFont(TTFont("Body-Bold", os.path.join(FONT_DIR, "arialbd.ttf")))
    pdfmetrics.registerFont(TTFont("Body-Italic", os.path.join(FONT_DIR, "ariali.ttf")))
    pdfmetrics.registerFont(TTFont("Mono", os.path.join(FONT_DIR, "consola.ttf")))
    pdfmetrics.registerFont(TTFont("Mono-Bold", os.path.join(FONT_DIR, "consolab.ttf")))
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-Bold")
    registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")
    BODY, BOLD, MONO = "Body", "Body-Bold", "Mono"
except Exception:
    BODY, BOLD, MONO = "Helvetica", "Helvetica-Bold", "Courier"

INK = colors.HexColor("#1b1f24")
MUTED = colors.HexColor("#57606a")
ACCENT = colors.HexColor("#0b5cad")
RULE = colors.HexColor("#d0d7de")
CODEBG = colors.HexColor("#f6f8fa")
HEADBG = colors.HexColor("#eaeef2")
LEGCOL = {"windows": colors.HexColor("#0b5cad"), "wsl2_docker": colors.HexColor("#d97706"),
          "aws_g4dn": colors.HexColor("#15803d")}

ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", fontName=BOLD, fontSize=24, leading=29, textColor=INK, spaceAfter=6),
    "sub": ParagraphStyle("s", fontName=BODY, fontSize=12, leading=16, textColor=MUTED, spaceAfter=18),
    "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=17, leading=21, textColor=INK, spaceBefore=6, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=12.5, leading=16, textColor=ACCENT, spaceBefore=10, spaceAfter=5, keepWithNext=1),
    "h3": ParagraphStyle("h3", fontName=BOLD, fontSize=10.5, leading=14, textColor=INK, spaceBefore=6, spaceAfter=3, keepWithNext=1),
    "p": ParagraphStyle("p", fontName=BODY, fontSize=9.6, leading=13.4, textColor=INK, spaceAfter=5),
    "small": ParagraphStyle("sm", fontName=BODY, fontSize=8.2, leading=11, textColor=MUTED, spaceAfter=4),
    "cell": ParagraphStyle("c", fontName=BODY, fontSize=7.9, leading=10, textColor=INK),
    "cellb": ParagraphStyle("cb", fontName=BOLD, fontSize=7.9, leading=10, textColor=INK),
    "cellm": ParagraphStyle("cm", fontName=MONO, fontSize=7.2, leading=9, textColor=INK),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=7.1, leading=8.9, textColor=INK),
    "callout": ParagraphStyle("co", fontName=BODY, fontSize=9.2, leading=12.8, textColor=INK, backColor=colors.HexColor("#eef6ff"),
                              borderColor=colors.HexColor("#b6d4f5"), borderWidth=0.6, borderPadding=6,
                              spaceBefore=4, spaceAfter=9),
}


def P(t, st="p"):
    return Paragraph(t, S[st])


def esc(t):
    return html.escape(str(t), quote=False)


def code(text, max_lines=80, width=118):
    lines = []
    for l in str(text).splitlines()[:max_lines]:
        l = l.replace("\t", "    ")
        while len(l) > width:
            lines.append(l[:width])
            l = "    " + l[width:]
        lines.append(l)
    pre = Preformatted("\n".join(lines) or "(empty)", S["code"])
    t = Table([[pre]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODEBG), ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def table(rows, widths, header=True, mono_cols=(), zebra=True, font_size=None):
    data = []
    for i, r in enumerate(rows):
        row = []
        for j, c in enumerate(r):
            if isinstance(c, (Paragraph, Table, Drawing)):
                row.append(c)
                continue
            st = "cellb" if (header and i == 0) else ("cellm" if j in mono_cols else "cell")
            row.append(Paragraph(esc(c) if not str(c).startswith("<") else str(c), S[st]))
        data.append(row)
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.3, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
             ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), HEADBG))
    if zebra:
        for i in range(1 if header else 0, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fbfcfd")))
    t.setStyle(TableStyle(style))
    return t


# ------------------------------------------------------------------ data
def load_json(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


LL = {leg: load_json(os.path.join(ROOT, leg, "lowlevel", "lowlevel.json")) for leg, _ in LEGS}
LEGS = [(l, n) for l, n in LEGS if os.path.isdir(os.path.join(ROOT, l))]
LEGNAME = dict(LEGS)


def g(leg, *path, default=None):
    d = LL.get(leg, {})
    for k in path:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return default
    return d


def logs_for(leg):
    d = os.path.join(ROOT, leg)
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "*.log"))):
        name = os.path.basename(f)[:-4]
        if name[:2] in ("p1", "p2", "p3", "p4", "p7", "p8", "en", "sv"):
            out[name] = parse_log(f)
    return out


RUNS = {leg: logs_for(leg) for leg, _ in LEGS}


def read(p, default=""):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        return default


def first_leg_with(*path):
    for leg, _ in LEGS:
        if g(leg, *path) not in (None, {}, []):
            return leg
    return None


# ------------------------------------------------------------------ explanations
SASS_DOC = [
    (r"^S2R\b", "Special-register -> general register read (e.g. SR_TID.X = threadIdx.x, SR_CTAID.X = blockIdx.x). Goes through a slow, variable-latency path, so the scheduler tracks it with a scoreboard barrier."),
    (r"^S2UR\b", "Special register -> *uniform* register (one value shared by the whole warp; Turing+ uniform datapath)."),
    (r"^ULDC", "Load a constant-bank value (kernel parameter or driver constant) into a uniform register. c[0x0][0x160]+ are this kernel's arguments."),
    (r"^MOV\b", "Register move. Often materialises a constant-bank value (a kernel parameter) into a per-thread register."),
    (r"^IMAD\.WIDE", "32x32 -> 64-bit integer multiply-add: pointer arithmetic base + index*4 (sizeof(float)) into a 64-bit address register pair Rn:Rn+1."),
    (r"^IMAD\.SHL|^IMAD\.MOV|^IMAD\.IADD|^IMAD\b", "Integer multiply-add on the FMA-capable integer pipe; the compiler also uses it as a MOV/SHIFT/ADD because that pipe is otherwise idle."),
    (r"^LEA", "Load-effective-address: (a << shift) + b in one instruction, used for index*16 byte offsets."),
    (r"^IADD3", "Three-input integer add."),
    (r"^LOP3", "Arbitrary 3-input bitwise function selected by an 8-bit truth-table immediate (0xc0 = a AND b). With 0x1fc it masks lane offsets; with 0xffffffc0 (= ~63) it rounds down to a multiple of 64 for offs % 64."),
    (r"^SHF|^SHL|^SHR", "Funnel/logical shift."),
    (r"^ISETP", "Integer compare -> writes a 1-bit predicate register P0..P6 (used for the `mask = offs < n` bounds check)."),
    (r"^FSETP", "Floating-point compare -> predicate register."),
    (r"^SGXT", "Sign-extend a bit-field: part of the signed `offs % 64` trick (fix-up for negative offsets)."),
    (r"^LEA\.HI", "(a >> (32-shift)) + b: rounding correction so the signed modulo by 64 is exact."),
    (r"^IABS|^I2F|^F2I|^MUFU\.RCP|^IMAD\.HI", "Integer division/modulo expansion for a non-power-of-two divisor: reciprocal (MUFU.RCP) + multiply-high + fix-up (the GPU has no integer divider)."),
    (r"^LDG\.E\.128", "Global-memory LOAD of 128 bits (4 x fp32) per thread in one instruction: a warp issues 32 x 16 B = 512 B, i.e. four fully-coalesced 128-byte L2 sectors-lines."),
    (r"^LDG", "Global-memory load into registers (goes L1 -> L2 -> DRAM)."),
    (r"^STG\.E\.128", "Global-memory STORE of 128 bits per thread (4 floats) - the vectorised write of y."),
    (r"^STG", "Global-memory store."),
    (r"^FADD", "fp32 add on the FMA pipe (x + b)."),
    (r"^FMNMX", "fp32 min/max; with predicate !PT it is max(x, 0.0) = the ReLU."),
    (r"^FFMA", "Fused multiply-add a*b+c, one rounding. The basic unit behind all GEMM/conv FLOPs (2 FLOP)."),
    (r"^FMUL", "fp32 multiply."),
    (r"^SEL", "Select between two registers by predicate."),
    (r"^BRA", "Branch. `BRA` to itself after EXIT is the standard end-of-kernel padding trap."),
    (r"^EXIT", "Thread (warp) exits; @P0 EXIT = early-out for threads whose predicate says they are out of range."),
    (r"^NOP", "Padding so the instruction stream stays aligned to 128-bit bundles / cache lines."),
    (r"^BAR", "Block-wide barrier (__syncthreads)."),
    (r"^CS2R", "Fast read of a special register pair (e.g. SRZ = zero, clock)."),
    (r"^SHFL", "Warp shuffle: exchange registers between lanes without shared memory."),
]
PTX_DOC = [
    (r"\.entry", "Kernel entry point; .param lines are the kernel arguments (pointers and n) placed in constant bank 0 by the driver."),
    (r"\.reg", "Declares virtual registers (unlimited in PTX; ptxas later allocates the physical 32-bit registers per thread)."),
    (r"ld\.param", "Load a kernel argument."),
    (r"%ctaid", "Block index (blockIdx) = Triton program_id(0)."),
    (r"%tid", "Thread index inside the block (threadIdx)."),
    (r"mad\.lo|mul\.lo|shl\.b32", "Integer index arithmetic: offs = pid*BLOCK + lane offsets."),
    (r"setp", "Compare -> predicate (%p) for the mask."),
    (r"mul\.wide|add\.s64", "64-bit address computation base + 4*index."),
    (r"ld\.global\.v4|ld\.global", "Vector load from global memory (v4 = 4 x 32 bit = 128-bit access), guarded by @%p predicate."),
    (r"rem\.s32|div", "offs % C for the broadcast bias index."),
    (r"add\.f32", "fp32 add."),
    (r"max\.f32", "ReLU = max(x, 0)."),
    (r"st\.global", "Store results back to global memory."),
    (r"ret", "Return."),
]
X86_DOC = [
    (r"vfmadd\d+ps", "FMA3 packed single: 8 (ymm) or 16 (zmm) fp32 multiply-adds in one instruction, one rounding."),
    (r"vfmadd\d+ss", "FMA scalar (leftover tail element)."),
    (r"vmulps", "Packed multiply."),
    (r"vaddps", "Packed add (horizontal reduction of partial sums)."),
    (r"vmovups|vmovaps|vmovss", "Vector load/store (u = unaligned allowed)."),
    (r"vxorps", "x ^ x = 0: the idiom for zeroing an accumulator register."),
    (r"vextractf128|vextractf32x4|vpermilps|vshufps|vhaddps|vmovhlps|vunpckhps", "Horizontal reduction: fold the 8 lanes of the accumulator into 1 float."),
    (r"endbr64", "Intel CET landing pad: marks a legal indirect-branch target (security, no-op otherwise)."),
    (r"\bsal|\bshl", "Shift left: n/8 iterations x 32 bytes = byte length of the vector part."),
    (r"vzeroupper", "Clear upper YMM halves before returning to SSE code (avoids AVX-SSE transition penalty)."),
    (r"\bcmp|\btest", "Compare -> sets FLAGS."),
    (r"\bj[a-z]+", "Conditional jump on FLAGS (loop back-edge / tail handling)."),
    (r"\badd|\blea|\bsub|\bshr|\bsar|\band", "Integer loop-counter / pointer arithmetic."),
    (r"\bxor", "xor reg,reg = zero the register (loop index i = 0)."),
    (r"\bmov", "Integer move (copy n, pointers)."),
    (r"\bret", "Return; the result is in xmm0 per the SysV ABI."),
]


def annotate(lines, doc, key=lambda l: l):
    rows = []
    for l in lines:
        k = key(l)
        exp = next((d for pat, d in doc if re.search(pat, k)), "")
        rows.append((l, exp))
    return rows


def sass_mnemonic(line):
    m = re.search(r"\*/\s+(@!?U?P\w+\s+)?([A-Z0-9_.]+)", line)
    return (m.group(2) if m else "").strip()


# ------------------------------------------------------------------ charts
def bar_chart(categories, series, names, title, ylab, width=170, height=62, fmt="%.1f", colorlist=None):
    d = Drawing(width * mm, height * mm)
    bc = VerticalBarChart()
    bc.x, bc.y = 16 * mm, 16 * mm
    bc.width, bc.height = (width - 24) * mm, (height - 26) * mm
    bc.data = series
    bc.categoryAxis.categoryNames = categories
    bc.categoryAxis.labels.fontName = BODY
    bc.categoryAxis.labels.fontSize = 6.5
    bc.categoryAxis.labels.angle = 0
    bc.valueAxis.labels.fontName = BODY
    bc.valueAxis.labels.fontSize = 6.5
    bc.valueAxis.valueMin = 0
    mx = max([max(s) for s in series if s] + [1])
    bc.valueAxis.valueMax = mx * 1.12
    bc.barLabels.fontName = BODY
    bc.barLabels.fontSize = 5.5
    bc.barLabelFormat = fmt
    bc.barLabels.nudge = 5
    bc.groupSpacing = 6
    bc.barSpacing = 1
    cl = colorlist or [colors.HexColor(c) for c in ("#0b5cad", "#d97706", "#15803d", "#7c3aed")]
    for i in range(len(series)):
        bc.bars[i].fillColor = cl[i % len(cl)]
        bc.bars[i].strokeColor = None
    d.add(bc)
    lg = Legend()
    lg.alignment = "right"
    lg.columnMaximum = 1
    lg.x, lg.y = 18 * mm, 4 * mm
    lg.fontName, lg.fontSize = BODY, 7
    lg.colorNamePairs = [(cl[i % len(cl)], names[i]) for i in range(len(series))]
    lg.dx = lg.dy = 6
    d.add(lg)
    d.add(String(16 * mm, (height - 6) * mm, title, fontName=BOLD, fontSize=8.5, fillColor=INK))
    return d


def stack_diagram():
    layers = [
        ("Python driver", "your code: run_benchmark.py / cluster_benchmark.py / submit_job.py", "#e8f1fb"),
        ("Py4J socket", "text commands over localhost TCP to the JVM", "#e8f1fb"),
        ("Spark driver JVM", "DAGScheduler -> stages -> tasks; TaskScheduler assigns to executors", "#fdf1e3"),
        ("RPC / Netty", "task = serialized closure + partition bytes to executor JVM", "#fdf1e3"),
        ("Executor JVM", "PythonRunner opens a socket to a python worker (fork on Linux, spawn on Windows)", "#fdf1e3"),
        ("Python worker", "unpickle partition (or Arrow batches) -> numpy -> torch.from_numpy (zero-copy)", "#e9f7ee"),
        ("PyTorch / ATen", "dispatcher: aten::linear -> aten::addmm -> CUDA kernel choice", "#e9f7ee"),
        ("cuBLAS / cuDNN", "pick a pre-compiled SASS kernel (volta_sgemm_128x32..., winograd...)", "#e9f7ee"),
        ("CUDA runtime/driver", "cudaMemcpyAsync / cudaLaunchKernel -> command in pushbuffer, doorbell write", "#f3eefe"),
        ("PCIe", "DMA of data (pageable->staging->device or pinned direct); doorbell MMIO write", "#f3eefe"),
        ("GPU front-end", "host interface + copy engines + GigaThread scheduler hand blocks to SMs", "#fdecec"),
        ("SM / warp", "4 schedulers issue 1 instr/clk per warp of 32 threads; registers, shared mem, L1", "#fdecec"),
        ("L2 / DRAM", "128-byte sectors over a 128-bit GDDR5/GDDR6 bus", "#fdecec"),
    ]
    h = 7.2 * mm
    d = Drawing(174 * mm, (len(layers) * (h + 1.6 * mm)) + 4 * mm)
    y = d.height - h - 2 * mm
    for name, desc, col in layers:
        d.add(Rect(0, y, 40 * mm, h, fillColor=colors.HexColor(col), strokeColor=RULE, strokeWidth=0.5))
        d.add(String(2 * mm, y + 2.4 * mm, name, fontName=BOLD, fontSize=7.8, fillColor=INK))
        d.add(Rect(41 * mm, y, 133 * mm, h, fillColor=colors.white, strokeColor=RULE, strokeWidth=0.5))
        d.add(String(43 * mm, y + 2.4 * mm, desc, fontName=BODY, fontSize=7.4, fillColor=INK))
        y -= h + 1.6 * mm
    return d


# ------------------------------------------------------------------ occupancy
def occupancy(regs, threads, smem, regs_sm=65536, max_warps=32, max_blocks=16, smem_sm=65536):
    warps = math.ceil(threads / 32)
    rpw = math.ceil(regs * 32 / 256) * 256
    by_regs = regs_sm // (rpw * warps) if regs else max_blocks
    by_thr = max_warps // warps
    by_smem = smem_sm // smem if smem else max_blocks
    blocks = max(0, min(by_regs, by_thr, by_smem, max_blocks))
    limiter = min((by_regs, "registers"), (by_thr, "threads"), (by_smem, "shared memory"), (max_blocks, "block slots"))[1]
    return warps, rpw, by_regs, by_thr, by_smem, blocks, blocks * warps, 100 * blocks * warps / max_warps, limiter


def demangle(name):
    """Readable form of an Itanium-mangled CUDA kernel name (Windows CUPTI
    reports them mangled): _ZN2at6native29vectorized_elementwise_kernelILi4E...
    -> at::native::vectorized_elementwise_kernel<4, ...>."""
    if not name.startswith("_Z"):
        return re.sub(r"^void ", "", name)
    i, parts = (3 if name.startswith("_ZN") else 2), []
    while i < len(name) and name[i].isdigit():
        j = i
        while j < len(name) and name[j].isdigit():
            j += 1
        n = int(name[i:j])
        parts.append(name[j:j + n])
        i = j + n
    out = "::".join(parts) or name
    tmpl = re.match(r"ILi(\d+)E", name[i:])
    if name[i:i + 1] == "I":
        out += f"<{tmpl.group(1)}, ...>" if tmpl else "<...>"
    return out


def fmt_dims(v):
    try:
        return "x".join(str(int(x)) for x in v)
    except Exception:
        return str(v)


def f2(v, spec=".1f", unit=""):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "-"
        return format(v, spec) + unit
    except Exception:
        return "-"


def dims(v):
    try:
        return int(v[0]) * int(v[1]) * int(v[2])
    except Exception:
        return 0


# ================================================================== document
story = []
A = story.append

A(Spacer(1, 30 * mm))
A(P("From Python to Silicon", "title"))
A(P("How every inference in the PyTorch-Spark platform is turned into bytes, JVM tasks, CUDA calls, "
    "PCIe transfers, warps, registers and machine instructions, measured on three environments "
    "(Windows 11 native, WSL2/Docker Linux, AWS g4dn.xlarge) on 26 Sep 2026.", "sub"))
meta_rows = [["Environment", "Host", "OS", "Python / torch / CUDA", "GPU", "CPU ISA used"]]
for leg, name in LEGS:
    m = g(leg, "meta", default={})
    meta_rows.append([name, m.get("host", "-"), (m.get("os", "-") or "-")[:38],
                      f"{m.get('python', '-')} / {m.get('torch', '-')} / {m.get('cuda', '-')}",
                      g(leg, "gpu", "props", "name", default="-"), g(leg, "cpu", "torch_cpu_capability", default="-")])
A(table(meta_rows, [30, 26, 38, 34, 26, 20]))
A(Spacer(1, 6 * mm))
A(P("How to read this document: chapters follow one inference request downward through the stack. "
    "Each chapter shows (1) what the layer does, (2) the exact artefact captured on your runs - a hex dump, "
    "a log line, a kernel table or an instruction listing - and (3) a line-by-line decoding of it. "
    "Chapter 12 then maps every benchmark test (Phases 1-10) to the low-level effect that dominated it. "
    "All sources are in results/campaign_20260926/; the generator is benchmark/build_lowlevel_pdf.py.", "callout"))
toc = ["1. The stack in one picture", "2. Bits: how a sample is stored", "3. Spark driver <-> JVM (Py4J)",
       "4. Shipping data to workers: pickle frames and Arrow IPC", "5. Python worker processes and task metrics",
       "6. PyTorch dispatch: from aten::linear to cudaLaunchKernel", "7. The CPU path: x86 ISA, SIMD registers, oneDNN JIT",
       "8. Crossing the bus: CUDA driver, launch latency, PCIe DMA", "9. The GPU: SMs, warps, registers, occupancy",
       "10. Every kernel your models launch", "11. Machine code: Triton -> TTIR -> LLVM -> PTX -> SASS",
       "12. Test results for all modes and what dominated each", "13. Failures, root-caused to the byte",
       "14. Reproduce / file index"]
A(P("<b>Contents</b>", "h3"))
for t in toc:
    A(P(t, "small"))
A(PageBreak())

# ---------------------------------------------------------------- 1
A(P("1. The stack in one picture", "h1"))
A(P("A distributed-mode inference (Mode 1 / cluster_benchmark / submit_job) crosses every layer below, top to bottom, "
    "then the results travel back up. Single-GPU and hybrid modes skip the Spark layers (rows 2-5): the Python process "
    "talks to the CUDA driver directly. That one difference explains most of the throughput gaps in chapter 12."))
A(stack_diagram())
A(Spacer(1, 3 * mm))
A(P("What moves at each layer and in what unit:", "h3"))
A(table([["Layer", "Unit of work", "Unit of data", "Measured on your runs (see chapter)"],
         ["Spark scheduler", "job -> stage -> task (1 per partition)", "partition", "task deserialize / run / GC ms (5)"],
         ["Python worker", "one process per concurrent task", "pickled row or Arrow record batch", "34,478 B frame for 64x128 fp32 (4)"],
         ["ATen", "operator (aten::addmm)", "tensor (ptr, sizes, strides, dtype)", "dispatch chain us (6)"],
         ["CUDA driver", "API call -> pushbuffer command", "kernel params (<=4 KB) / DMA descriptor", "launch 14-86 us (8)"],
         ["PCIe", "TLP packets, 128b/130b coded lanes", "256 B max payload per TLP", "GB/s pinned vs pageable (8)"],
         ["GPU", "grid -> blocks -> warps of 32 threads", "32-bit registers, 128 B cache lines", "regs/thread, occupancy (9, 10)"],
         ["SM core", "one SASS instruction per warp per issue", "128-bit instruction words", "listing (11)"]],
        [30, 44, 46, 54]))
A(PageBreak())

# ---------------------------------------------------------------- 2
A(P("2. Bits: how a sample is stored", "h1"))
bl = first_leg_with("bits", "values")
A(P("The EW-signal models take a float32 vector of 128 values per sample; images are float32 tensors of 3x224x224; "
    "detection inputs 3x640x640. Everything below is from the real generator (data/signal_generator.py) on your run."))
if bl:
    b = LL[bl]["bits"]
    A(P(f"Batch of 4 EW signals: shape {b['shape']}, dtype {b['dtype']}, stride {b['stride']} elements, "
        f"{b['nbytes']} bytes, element size {b['element_size']} B. data_ptr % 64 = {b['ptr_mod_64']} "
        f"({'cache-line aligned' if b['ptr_mod_64'] == 0 else 'not 64-byte aligned - numpy allocator; PyTorch-allocated tensors are 64 B aligned on CPU and 256 B+ on GPU'})."))
    A(P("2.1 IEEE-754 single precision, decoded", "h2"))
    A(P("A float32 is 32 bits: bit 31 = sign, bits 30-23 = biased exponent (bias 127), bits 22-0 = fraction with an implicit leading 1. "
        "value = (-1)^s x 1.f x 2^(e-127). fp16 keeps 5 exponent / 10 fraction bits; bf16 keeps fp32's 8 exponent bits but only 7 fraction bits "
        "(so it rounds more coarsely but never overflows where fp32 would not)."))
    rows = [["value", "hex (memory order reversed)", "s", "exponent (bin / dec)", "fraction (23 bits)", "fp16", "bf16"]]
    for v in b["values"]:
        rows.append([f"{v['value']:+.8f}", v["hex"], v["sign"], f"{v['exp']:08b} / {v['exp']}", f"{v['mantissa']:023b}",
                     f"{v['fp16']:+.6f}", f"{v['bf16']:+.6f}"])
    A(table(rows, [21, 22, 5, 26, 44, 20, 20], mono_cols=(1, 3, 4)))
    v0 = b["values"][0]
    A(P(f"Worked example: {v0['hex']} -> sign {v0['sign']}, exponent {v0['exp']} - 127 = {v0['exp'] - 127}, "
        f"fraction 0x{v0['mantissa']:06x}/2^23 = {v0['mantissa'] / 2 ** 23:.8f}, so value = 1.{v0['mantissa']:06x}h x 2^{v0['exp'] - 127} = "
        f"{(1 + v0['mantissa'] / 2 ** 23) * 2 ** (v0['exp'] - 127):.8f}. x86 and NVIDIA GPUs are little-endian, so in memory the four "
        f"bytes appear lowest first: {' '.join(v0['hex'][2:][i:i + 2] for i in (6, 4, 2, 0))}.", "callout"))
    A(P("2.2 The raw bytes of the tensor", "h2"))
    A(P("First 64 bytes of the storage as they sit in RAM (and later on the PCIe bus and in GPU DRAM - the bytes are never converted, only copied):"))
    raw = read(os.path.join(ROOT, bl, "lowlevel.log"))
    m = re.search(r"First 64 bytes.*?\n((?:\s+[0-9a-f]{4}\s+.*\n){1,4})", raw)
    if m:
        A(code(m.group(1)))
    A(P("2.3 Layout: strides", "h2"))
    s = b.get("image_strides", {})
    A(P(f"An image batch [1,3,224,224] in default NCHW layout has strides {tuple(s.get('nchw', []))}: moving one channel skips 50,176 floats, "
        f"one row 224, one pixel 1. The same tensor in channels_last (NHWC) has strides {tuple(s.get('channels_last', []))}: the 3 colour values of a pixel are adjacent. "
        "cuDNN and oneDNN reorder into their own blocked layouts (e.g. oneDNN's aBcd8b / aBcd16b in chapter 7 = channels grouped in blocks of 8 or 16 to match one SIMD register)."))
A(PageBreak())

# ---------------------------------------------------------------- 3
A(P("3. Spark driver <-> JVM (Py4J)", "h1"))
A(P("PySpark is a thin client. The Python driver starts a JVM (spark-submit) and talks to it through Py4J: a localhost TCP socket carrying "
    "line-oriented text commands. sc.parallelize(...), rdd.mapPartitions(...).collect() each become a command such as "
    "<font name='Mono'>c\\no12\\ncollectAndServe\\nro34\\ne\\n</font> (call, object id, method, argument refs, end); the JVM runs it by reflection and replies "
    "<font name='Mono'>yro35</font> (success, object reference). Large data does not go through Py4J - collect() results come back over a separate "
    "authenticated local socket, and parallelize() writes the pickled data to a temp file the JVM reads."))
rows = [["", *[n for _, n in LEGS]]]
for key, lab in [("pyspark", "PySpark version"), ("master", "master URL"), ("driver_python_pid", "driver Python PID"),
                 ("jvm_pid", "driver JVM PID"), ("py4j_java_port", "Py4J gateway port (JVM listens)"), ("jvm_version", "JVM"),
                 ("jvm_max_heap_mb", "driver JVM max heap (MB)")]:
    rows.append([lab, *[str(g(leg, "spark", key, default="-")) for leg, _ in LEGS]])
A(table(rows, [44] + [130 / len(LEGS)] * len(LEGS)))
A(P("The ephemeral port changes every run; the JVM PID is the parent of every Python worker on Windows (next chapter), because there "
    "the JVM spawns workers itself.", "small"))

# ---------------------------------------------------------------- 4
A(P("4. Shipping data to workers: pickle frames and Arrow IPC", "h1"))
A(P("4.1 RDD path (Mode 1 / cluster_engine rdd): framed pickle", "h2"))
A(P("For RDD operations the executor JVM streams each partition to the Python worker over a local socket as a sequence of frames: "
    "a 4-byte big-endian length followed by that many bytes of pickle (protocol 5), batched 1024 records per frame by BatchedSerializer; "
    "a length of -1 (0xFFFFFFFF) ends the data section. The closure itself (your mapPartitions function and everything it references - "
    "in this platform the serialized model state_dicts) is sent the same way, cloudpickled, once per task."))
pl = first_leg_with("spark", "pickle_frame_bytes")
if pl:
    sp = LL[pl]["spark"]
    raw = read(os.path.join(ROOT, pl, "lowlevel.log"))
    m = re.search(r"as PySpark ships it:\n.*\n.*\n((?:\s+[0-9a-f]{4}\s+.*\n){1,6})", raw)
    A(P(f"Captured: one partition of 64 EW-signal rows (64 x 128 x 4 = {sp['pickle_raw_bytes']:,} raw bytes) serializes to "
        f"{sp['pickle_frame_bytes']:,} bytes on the wire ({100 * (sp['pickle_frame_bytes'] - sp['pickle_raw_bytes']) / sp['pickle_raw_bytes']:.1f}% overhead):"))
    if m:
        A(code(m.group(1)))
    A(table([["bytes", "meaning"],
             ["00 00 86 aa", "frame length, big-endian int32 = 0x86aa = 34,474 bytes of pickle follow"],
             ["80 05", "PROTO 5 - pickle protocol version 5"],
             ["95 9f 86 00 00 00 00 00 00", "FRAME opcode + 8-byte little-endian frame size (0x869f)"],
             ["5d 94 28", "EMPTY_LIST, MEMOIZE, MARK - start of the batch list"],
             ["8c 13 'numpy._core.numeric'", "SHORT_BINUNICODE: module name (19 chars)"],
             ["8c 0b '_frombuffer' 94 93", "SHORT_BINUNICODE function name, MEMOIZE, STACK_GLOBAL -> numpy._core.numeric._frombuffer"],
             ["28 96 00 02 00 00 00 00 00 00", "MARK, BYTEARRAY8 with 8-byte length 0x200 = 512 bytes = 128 floats (one row)"],
             ["6a 0c b9 be ...", "the 128 little-endian float32 values themselves (e.g. be b9 0c 6a = -0.3614...)"]],
            [52, 122], mono_cols=(0,)))
    A(P("So each row costs ~27 bytes of pickle metadata (module/function names are memoized after the first row) plus a Python "
        "object allocation on each side - fine for 5K signals, visible for images (3x224x224 = 602,112 bytes per sample).", "small"))
A(P("4.2 pandas_udf path (engine=udf): Arrow IPC", "h2"))
A(P("With engine=udf the JVM converts rows to Apache Arrow record batches (columnar, spark.sql.execution.arrow.maxRecordsPerBatch rows each) and "
    "writes them in the Arrow IPC streaming format; the worker maps them to pandas without per-row Python objects."))
if pl:
    raw = read(os.path.join(ROOT, pl, "lowlevel.log"))
    m = re.search(r"(validity bitmap.*\n.*data buffer.*\n.*IPC stream.*\n(?:\s+[0-9a-f]{4}\s+.*\n){1,6})", raw)
    if m:
        A(code(m.group(1)))
    A(table([["bytes", "meaning"],
             ["ff ff ff ff", "continuation marker (IPC format >= 0.15)"],
             ["70 00 00 00", "metadata length = 112 bytes of FlatBuffer follow"],
             ["10 00 00 00 ... 0a 00 0c 00 ...", "FlatBuffer Message{version=V5, header=Schema}: a vtable of little-endian uint16 field offsets, then the table"],
             ["... 01 03 ...", "Type = FloatingPoint, precision = SINGLE (the float32 column 'x')"],
             ["(later) RecordBatch message", "length=4, nodes=[{length 4, null_count 1}], buffers=[validity @0 len 1, data @8 len 16]"],
             ["0d 00 00 00 00 00 00 00", "validity bitmap, LSB first: 1 0 1 1 = 0x0d (element 1 is null), padded to 8 bytes"],
             ["00 00 c0 3f | 00 00 00 00 | 00 00 10 c0 | 00 00 40 40", "1.5 | (null slot) | -2.25 | 3.0 as little-endian IEEE-754"]],
            [60, 114], mono_cols=(0,)))
rows = [["", *[n for _, n in LEGS]]]
rows.append(["200k rows x2, pandas_udf (Arrow)", *[f2(g(l, 'spark', 'udf_vs_rdd_s', 'pandas_udf_arrow'), ".2f", " s") for l, _ in LEGS]])
rows.append(["200k rows x2, RDD map (pickle)", *[f2(g(l, 'spark', 'udf_vs_rdd_s', 'rdd_pickle'), ".2f", " s") for l, _ in LEGS]])
A(table(rows, [60] + [114 / len(LEGS)] * len(LEGS)))
A(P("On Linux the pickle path wins for this trivial function (workers are forked and reused, and Arrow adds JVM-side conversion); on Windows "
    "every task pays a full Python process start, so the path with fewer round trips (Arrow) wins. With real models the per-sample cost of "
    "pickling large arrays dominates and Arrow/UDF returns per-sample predictions - see eng_* tests in chapter 12.", "small"))
A(PageBreak())

# ---------------------------------------------------------------- 5
A(P("5. Python worker processes and task metrics", "h1"))
A(P("Each Spark task that runs Python code needs a Python process. On Linux the executor JVM starts one "
    "<font name='Mono'>python -m pyspark.daemon</font> which fork()s a worker per concurrent task (copy-on-write: the new process "
    "shares the parent's already-imported modules). With spark.python.worker.reuse=true (set by this platform) the worker survives for the "
    "next task. Windows has no fork(), so the JVM launches <font name='Mono'>python -m pyspark.worker</font> directly and every worker pays "
    "a full interpreter start plus 'import torch' (~1-3 s)."))
for leg, name in LEGS:
    ws = g(leg, "spark", "workers", default=[])
    if ws:
        A(P(f"<b>{name}</b> - the 4 tasks of a probe job ran in:", "p"))
        A(table([["pid", "ppid (parent)", "host", "rows", "compute us"]] +
                [[w["pid"], w["ppid"], w["host"], w["n"], f"{w['compute_us']:.0f}"] for w in ws], [25, 30, 60, 20, 25]))
        ppids = {w["ppid"] for w in ws}
        jvm = g(leg, "spark", "jvm_pid")
        A(P(f"Parent PID(s) {sorted(ppids)}; driver JVM PID {jvm}. "
            + ("All workers share one parent = forked from pyspark.daemon." if len(ppids) == 1 and jvm not in ppids else
               "Parent is the JVM itself - workers are spawned, not forked." if jvm in ppids else ""), "small"))
A(P("5.1 Stage metrics (Spark REST API) of the same probe jobs", "h2"))
A(P("executorRunTime is wall time of the task thread in the executor JVM; executorCpuTime is CPU time of that JVM thread only. "
    "Python work happens in another process, so it shows up as run time without CPU time - the gap is time the JVM spent "
    "blocked on the Python socket (and on the GPU, for inference tasks)."))
for leg, name in LEGS:
    st = g(leg, "spark", "stages", default=[])
    if st:
        A(P(f"<b>{name}</b>", "p"))
        A(table([["stage", "tasks", "run ms", "JVM cpu ms", "deserialize ms", "result ser ms", "GC ms", "records in"]] +
                [[s["stage"], s["tasks"], s["run_ms"], f"{s['cpu_ms']:.0f}", s["deser_ms"], s["result_ser_ms"], s["gc_ms"], s["in_rec"]] for s in st],
                [14, 14, 22, 24, 26, 24, 18, 24]))
A(P("5.2 One real inference task, from the Spark event log", "h2"))
evleg = next((l for l, _ in LEGS if glob.glob(os.path.join(ROOT, l, "spark-events", "app-*"))), None)
if evleg:
    evs = sorted(glob.glob(os.path.join(ROOT, evleg, "spark-events", "app-*")))
    pick = None
    for f in evs:
        ev = [json.loads(l) for l in open(f, encoding="utf-8")]
        nm = next((e.get("App Name") for e in ev if e["Event"] == "SparkListenerApplicationStart"), "")
        if "gpu_only" in nm:
            pick = (f, nm, ev)
            break
    if pick:
        f, nm, ev = pick
        tasks = [e for e in ev if e["Event"] == "SparkListenerTaskEnd"]
        A(P(f"{LEGNAME[evleg]}, application <font name='Mono'>{esc(nm)}</font> ({os.path.basename(f)}), "
            f"{len(tasks)} tasks. The event log is a JSON line per listener event: "
            + ", ".join(sorted({e['Event'].replace('SparkListener', '') for e in ev})) + "."))
        rows = [["task", "executor@host", "locality", "wall ms", "deser ms", "deser CPU ms", "run ms", "run CPU ms", "GC ms", "result B"]]
        for t in tasks:
            ti, tm = t["Task Info"], t["Task Metrics"]
            rows.append([ti["Task ID"], f"{ti['Executor ID']}@{ti['Host']}", ti["Locality"], ti["Finish Time"] - ti["Launch Time"],
                         tm["Executor Deserialize Time"], f"{tm['Executor Deserialize CPU Time'] / 1e6:.0f}", tm["Executor Run Time"],
                         f"{tm['Executor CPU Time'] / 1e6:.0f}", tm["JVM GC Time"], tm["Result Size"]])
        A(table(rows, [10, 28, 22, 15, 15, 18, 15, 18, 12, 17]))
        A(P("Read it as: deserialize = JVM unpacks the task closure (includes the serialized model weights shipped by the driver); "
            "run = the JVM waits while the Python worker loads 10 models, copies data host->device, runs kernels and returns counts; "
            "run CPU (JVM) stays tiny because the JVM thread is just blocked on a socket read. Result size is small because this "
            "platform returns counts/timings, not predictions, from each partition.", "callout"))
A(PageBreak())

# ---------------------------------------------------------------- 6
A(P("6. PyTorch dispatch: from aten::linear to cudaLaunchKernel", "h1"))
A(P("Calling model(x) runs Python forward() code which calls torch operators. Each operator goes through the ATen dispatcher "
    "(a table keyed by device/dtype/autograd 'dispatch keys'), lands in the CUDA implementation, which asks cuBLAS/cuDNN for a kernel, "
    "fills a small parameter block, and calls cudaLaunchKernel. The CUPTI 'correlation id' links the CPU-side launch call to the GPU-side kernel. "
    "Below: the first Linear layer of ew_classifier and the first Conv of ResNet18, with host-side timestamps relative to the operator start."))
for leg, name in LEGS:
    raw = read(os.path.join(ROOT, leg, "lowlevel.log"))
    for mm_ in re.finditer(r"(Dispatch chain inside the first aten::\w+.*?\n(?:\s+\+.*\n)+\s+-> GPU kernels.*\n)", raw):
        A(P(f"<b>{name}</b>", "p"))
        A(code(mm_.group(1), width=125))
A(P("Note the dispatch overhead is paid on the CPU for every operator, every batch: ~0.2 ms per Linear on the AWS Xeon, ~2.3 ms on the "
    "Windows laptop (profiler overhead included). With a small MLP on 256 samples this CPU overhead is larger than the GPU work - "
    "which is why the tiny signal models reach only a few thousand samples/s even on a GPU, and why batching matters (Phase 4/8).", "small"))

# ---------------------------------------------------------------- 7
A(P("7. The CPU path: x86 ISA, SIMD registers, oneDNN JIT", "h1"))
A(P("In cpu_only mode, and for any model the hybrid planner places on CPU, the same aten::linear/aten::conv2d calls go to oneDNN (for conv) "
    "and MKL/oneDNN GEMM (for linear). These libraries contain several copies of each kernel for different instruction sets and pick one at "
    "run time using CPUID; oneDNN additionally JIT-generates x86 machine code (Xbyak) specialised to the exact shape."))
rows = [["", *[n for _, n in LEGS]]]
for key, lab in [("processor", "CPU"), ("logical_cpus", "logical CPUs"), ("torch_cpu_capability", "ATen SIMD dispatch"),
                 ("torch_threads", "intra-op threads")]:
    rows.append([lab, *[str(g(l, "cpu", key, default="-")) for l, _ in LEGS]])
rows.append(["SIMD flags (Linux)", *[", ".join(g(l, "cpu", "simd_flags", default=[]) or ["(Windows: not exposed)"]) for l, _ in LEGS]])
A(table(rows, [34] + [140 / len(LEGS)] * len(LEGS)))
A(table([["ISA", "registers", "width", "fp32 per register", "FMA FLOP / instr", "where"],
         ["SSE4.2", "16 x XMM", "128 bit", "4", "- (no FMA)", "baseline"],
         ["AVX2 + FMA3", "16 x YMM", "256 bit", "8", "16", "i5-9300H laptop (Windows & WSL2)"],
         ["AVX-512 + VNNI", "32 x ZMM + 8 mask k0-k7", "512 bit", "16", "32 (int8 VNNI: 64 MAC)", "Xeon 8259CL on AWS"]],
        [26, 36, 16, 26, 30, 40]))
A(P("7.1 oneDNN verbose log, decoded", "h2"))
for leg, name in LEGS:
    lines = [l for l in g(leg, "cpu", "onednn_verbose", default=[]) if ",exec," in l]
    if lines:
        A(P(f"<b>{name}</b>", "p"))
        A(code("\n".join(lines), width=125))
A(table([["field", "meaning"],
         ["primitive,exec,cpu", "a primitive executed on the CPU engine"],
         ["convolution,jit:avx2 / jit:avx512_core", "implementation: JIT-generated code for the AVX2 or AVX-512 ISA (Xbyak emits the machine code at run time)"],
         ["reorder,jit:uni / jit:blk", "layout conversion kernels (weights to blocked layout, output back to plain)"],
         ["src:f32::blocked:abcd", "source tensor fp32 in plain NCHW (a=N, b=C, c=H, d=W)"],
         ["wei ... Acdb8a / Acdb16a", "weights blocked by 8 or 16 output channels innermost = exactly one YMM (8 fp32) or ZMM (16 fp32) register"],
         ["dst ... aBcd8b / aBcd16b", "output channels in blocks of 8/16 so one vector FMA updates 8/16 output channels at once"],
         ["64x3x7x7, 8x64x112x112", "problem shape (ResNet stem conv 7x7, 64 filters) - last number = execution time in ms"]],
        [52, 122], mono_cols=(0,)))
A(P("The block size in the layout tag (8 on your laptop, 16 on AWS) is the SIMD width showing through: the same PyTorch call produces a "
    "different memory layout and different machine code on each CPU.", "callout"))
asm_leg = first_leg_with("cpu", "dot_avx2_asm")
A(P("7.2 The inner loop of every Linear layer, as x86 machine instructions", "h2"))
A(P("A Linear layer is a matrix multiply, whose core is a dot product s += a[i]*b[i]. Compiled with gcc -O3 -mavx2 -mfma -ffast-math, "
    "the loop becomes vectorised FMA instructions operating on YMM registers:"))
if asm_leg:
    asm = g(asm_leg, "cpu", "dot_avx2_asm", default=[])
    rows = [["instruction", "what the CPU does"]] + [[l.strip(), e] for l, e in annotate(asm[:46], X86_DOC)]
    A(table(rows, [70, 104], mono_cols=(0,)))
    A(P("The hot loop is the four instructions vmovups / vfmadd231ps / addq $32 / jne: each iteration loads 8 floats of a (32 bytes, one YMM), "
        "multiplies them by 8 floats of b straight from memory and accumulates into ymm0 - 16 FLOP per iteration. After the loop the 8 partial "
        "sums in ymm0 are folded (vextractf128, vmovhlps, vshufps + vaddps) into one float, then a 4-wide (xmm) and scalar tail handle n % 8. "
        "MKL/oneDNN's real GEMM kernels are the same idea unrolled over a register tile: 12+ YMM accumulators, each loaded value reused many times.", "callout"))
else:
    A(P("(not captured - requires gcc in the Linux leg)", "small"))
A(PageBreak())

# ---------------------------------------------------------------- 8
A(P("8. Crossing the bus: CUDA driver, launch latency, PCIe DMA", "h1"))
A(P("A kernel launch does not 'call' the GPU. The CUDA driver writes a command (method + kernel parameters, grid/block sizes, "
    "shared-memory size, the address of the SASS code) into a pushbuffer - a ring buffer in pinned host memory the GPU can read - and then "
    "writes a doorbell register on the GPU through a PCIe memory-mapped (MMIO) write. The GPU's host interface fetches the commands by DMA "
    "over PCIe and hands blocks to SMs. On Windows the WDDM display-driver model inserts the OS graphics kernel (dxgkrnl) and a scheduling "
    "queue between the CUDA user-mode driver and the hardware; WSL2 goes through a paravirtualized /dev/dxg into the same Windows host driver; "
    "Linux on AWS uses the native NVIDIA kernel driver directly."))
rows = [["", *[n for _, n in LEGS]]]
rows.append(["kernel launch, CPU enqueue (us)", *[f2(g(l, 'bus', 'launch_enqueue_us')) for l, _ in LEGS]])
rows.append(["launch + sync round trip (us)", *[f2(g(l, 'bus', 'launch_roundtrip_us')) for l, _ in LEGS]])
rows.append(["PCIe link", *[(f"Gen{g(l, 'gpu', 'nvidia_smi', 'pcie_gen_cur')} x{g(l, 'gpu', 'nvidia_smi', 'pcie_width_cur')}" if g(l, 'gpu', 'nvidia_smi', 'pcie_gen_cur') else "-") for l, _ in LEGS]])
rows.append(["PCIe theoretical per direction", *[f2(g(l, 'gpu', 'theoretical', 'pcie_gbps_theoretical'), ".2f", " GB/s") for l, _ in LEGS]])
A(table(rows, [56] + [118 / len(LEGS)] * len(LEGS)))
A(P("PCIe arithmetic: Gen3 = 8 GT/s per lane with 128b/130b line coding -> 8 x 128/130 / 8 = 0.985 GB/s per lane per direction. "
    "x16 = 15.75 GB/s, x8 = 7.88 GB/s. Real transfers also carry TLP headers (~20-24 B per <=256 B payload), so ~80-85% of line rate is the practical ceiling.", "small"))
A(P("8.1 Host <-> device copy bandwidth", "h2"))
for leg, name in LEGS:
    cp = g(leg, "bus", "copies", default=[])
    if cp:
        A(P(f"<b>{name}</b> (GB/s)", "p"))
        A(table([["size", "H2D pageable", "H2D pinned", "D2H pageable", "D2H pinned"]] +
                [[f"{c['MB']:g} MB", f"{c['h2d_pageable']:.2f}", f"{c['h2d_pinned']:.2f}", f"{c['d2h_pageable']:.2f}", f"{c['d2h_pinned']:.2f}"] for c in cp],
                [30, 34, 34, 34, 34]))
BLEGS = [(l, n) for l, n in LEGS if g(l, "bus", "copies")]
cats = [n for _, n in BLEGS]
ser = [[g(l, "bus", "copies")[-2].get(k, 0) for l, _ in BLEGS]
       for k in ("h2d_pageable", "h2d_pinned", "d2h_pageable", "d2h_pinned")]
A(bar_chart(cats, ser, ["H2D pageable", "H2D pinned", "D2H pageable", "D2H pinned"], "64 MB copy bandwidth (GB/s)", "GB/s"))
A(P("Pageable memory: the driver cannot DMA from pages the OS may move or swap, so it copies your buffer (with the CPU) into a pinned "
    "staging buffer in chunks and DMAs those - two copies, CPU-bound. Pinned (page-locked) memory is DMA'd directly by the GPU copy engine. "
    "In this platform the inputs are created by numpy (pageable) and moved with .to(device), so every inference pays the pageable rate "
    "(visible in the kernel traces as 'Memcpy HtoD (Pageable -> Device)').", "callout"))
A(P("8.2 Device memory and compute ceilings", "h2"))
rows = [["", *[n for _, n in LEGS]]]
rows.append(["DRAM, measured D2D copy (GB/s)", *[f2(g(l, 'bus', 'd2d_gbps')) for l, _ in LEGS]])
dram_spec = []
for l, _ in LEGS:
    nm = str(g(l, "gpu", "props", "name", default=""))
    dram_spec.append("320 (GDDR6, 256-bit eff.)" if "T4" in nm else "128 (GDDR5 8 Gbps x 128-bit)" if "1650" in nm else "-")
rows.append(["DRAM spec (GB/s)", *dram_spec])
rows.append(["FP32 peak (TFLOPS) = SMs x 64 x 2 x clock", *[f2(g(l, 'gpu', 'theoretical', 'fp32_tflops_theoretical'), ".2f") for l, _ in LEGS]])
rows.append(["SGEMM 2048^3 fp32 measured", *[f2(g(l, 'bus', 'gemm_tflops', 'torch.float32'), ".2f") for l, _ in LEGS]])
rows.append(["HGEMM 2048^3 fp16 measured", *[f2(g(l, 'bus', 'gemm_tflops', 'torch.float16'), ".2f") for l, _ in LEGS]])
A(table(rows, [66] + [108 / len(LEGS)] * len(LEGS)))
A(P("Why fp16 is 4.5x slower than fp32 on the GTX 1650 but 6x faster on the T4: both are Turing (sm_75), but the TU117 chip in the GTX 1650 "
    "has no Tensor Cores, so fp16 matrix multiply falls back to generic kernels; the T4 (TU104) has 320 Tensor Cores that execute "
    "HMMA.1688 instructions (a 16x8x8 fp16 matrix multiply-accumulate per warp per instruction). Note on DRAM: the tracer's naive "
    "formula (clock x 2 x bus width) is right for GDDR5 but undercounts GDDR6, which moves 2 bits per pin per reported clock edge pair; "
    "the T4's measured 231 GB/s (72% of 320) proves the spec figure.", "small"))
A(PageBreak())

# ---------------------------------------------------------------- 9
A(P("9. The GPU: SMs, warps, registers, occupancy", "h1"))
rows = [["property", *[n for _, n in LEGS]]]
for key, lab in [("name", "GPU"), ("major", "compute capability major"), ("minor", "minor"), ("multi_processor_count", "SMs"),
                 ("warp_size", "threads per warp"), ("max_threads_per_multi_processor", "max threads per SM"),
                 ("regs_per_multiprocessor", "32-bit registers per SM"), ("shared_memory_per_multiprocessor", "shared memory per SM (B)"),
                 ("L2_cache_size", "L2 cache (B)"), ("memory_bus_width", "memory bus (bits)"), ("total_memory", "VRAM (B)")]:
    rows.append([lab, *[str(g(l, "gpu", "props", key, default="-")) for l, _ in LEGS]])
rows.append(["FP32 lanes ('CUDA cores')", *[str(g(l, "gpu", "theoretical", "cuda_cores", default="-")) for l, _ in LEGS]])
rows.append(["max SM clock (MHz)", *[str(g(l, "gpu", "nvidia_smi", "sm_clock_max_mhz", default="-")) for l, _ in LEGS]])
A(table(rows, [52] + [122 / len(LEGS)] * len(LEGS)))
A(P("A Turing SM has 4 processing blocks. Each has a warp scheduler that can issue one instruction per clock for one of its warps, "
    "16 FP32 lanes, 16 INT32 lanes, a 16K x 32-bit register file slice, and (on TU104 only) 2 Tensor Cores. A warp of 32 threads executes "
    "one instruction for all 32 threads together (SIMT); an FP32 instruction therefore takes 2 clocks on a 16-lane block. "
    "Latency (~4 clocks for FFMA, hundreds for DRAM loads) is hidden by switching between resident warps - so the number of warps that "
    "fit on an SM (occupancy) matters."))
A(P("9.1 Occupancy, computed by hand for your kernels", "h2"))
A(P("Resident blocks per SM = min(register limit, thread limit, shared-memory limit, 16 block slots). Registers are allocated per warp in "
    "chunks of 256: regs/warp = ceil(regs_per_thread x 32 / 256) x 256. The results below reproduce CUPTI's 'est. achieved occupancy' column."))
occ_rows = [["kernel (leg)", "regs/thr", "thr/blk", "smem B", "regs/warp", "blk by regs", "blk by thr", "blk by smem", "blocks", "warps", "occ %", "CUPTI %", "limit"]]
seen = set()
for leg, name in LEGS:
    for mname in ("resnet18", "ew_classifier"):
        for k in g(leg, "kernels", mname, "kernels", default=[]):
            short = re.sub(r"^_Z\w*?(\d+)", "", k["name"])[:40]
            base = demangle(k["name"]).split("(")[0][:48]
            if base in seen or not k.get("regs"):
                continue
            if not any(x in k["name"] for x in ("sgemm", "scudnn", "winograd", "bn_fw", "vectorized_elementwise", "max_pool")):
                continue
            seen.add(base)
            w, rpw, br, bt, bs, blocks, warps, occ, lim = occupancy(int(k["regs"]), dims(k["block"]), int(k.get("smem") or 0))
            occ_rows.append([f"{base} ({leg.split('_')[0]})", k["regs"], dims(k["block"]), k.get("smem"), rpw, br, bt, bs, blocks,
                             warps, f"{occ:.0f}", k.get("occupancy"), lim])
            if len(occ_rows) > 14:
                break
A(table(occ_rows[:15], [46, 11, 11, 13, 13, 11, 11, 12, 11, 10, 10, 11, 14], mono_cols=(0,)))
A(P("Example: volta_sgemm_128x32_sliced1x4_tn uses 134 registers/thread and 256 threads. 134 x 32 = 4288 -> 4352 registers per warp x 8 warps "
    "= 34,816 registers per block; 65,536 / 34,816 = 1 block per SM = 8 of 32 warps = 25%. CUPTI reports exactly 25%. Low occupancy is a "
    "deliberate trade here: GEMM kernels keep a 128x32 output tile in registers to reuse every loaded value many times.", "callout"))
A(P("9.2 Reading kernel names", "h2"))
A(table([["name fragment", "meaning"],
         ["volta_sgemm_128x32_sliced1x4_tn", "cuBLAS single-precision GEMM from the Volta-era kernel family (runs on Turing), each block computes a 128x32 tile of C, K dimension sliced 1x4 across warps, A transposed / B not ('tn')"],
         ["cublasLt::splitKreduce_kernel", "the K dimension was split across blocks; this kernel sums the partial results (used when M x N is small but K is large)"],
         ["scudnn_winograd_128x128_ldg1_ldg4_relu_tile148t_nt", "cuDNN fp32 convolution with the Winograd transform (fewer multiplies for 3x3 filters), 128x128 tile, 1- and 4-wide global loads, ReLU fused into the epilogue"],
         ["scudnn_128x64_relu_xregs_large_nn", "implicit-GEMM convolution (im2col done on the fly), 128x64 tile, extra registers, 'large' variant"],
         ["winograd::generateWinogradTilesKernel", "pre-transforms the filter weights into the Winograd domain"],
         ["bn_fw_inf_1C11_kernel_NCHW", "BatchNorm forward in inference mode (per-channel scale+shift), NCHW layout"],
         ["vectorized_elementwise_kernel<4, ...>", "ATen's generic pointwise kernel; <4> = each thread handles 4 elements with 128-bit vector loads (ReLU, add, etc.)"],
         ["max_pool_forward_nchw", "ATen max-pool, one thread per output element"],
         ["computeOffsetsKernel (cask)", "cuDNN helper that precomputes address offsets for the implicit-GEMM kernel"]],
        [66, 108], mono_cols=(0,)))
A(PageBreak())

# ---------------------------------------------------------------- 10
A(P("10. Every kernel your models launch", "h1"))
A(P("Captured with torch.profiler (Kineto + CUPTI activity API): ew_classifier on a batch of 256 signals and ResNet18 on 8 images, "
    "including the input copy host->device and the result copy device->host. grid and block are the CUDA launch dimensions; "
    "regs = registers per thread from the cubin; smem = static+dynamic shared memory per block; occ = CUPTI's estimated occupancy."))
for mname in ("ew_classifier", "resnet18"):
    for leg, name in LEGS:
        ks = g(leg, "kernels", mname, "kernels", default=[])
        if not ks:
            continue
        mc = g(leg, "kernels", mname, "memcpy", default=[])
        tot = sum((k.get("dur_us") or 0) for k in ks)
        A(P(f"10.{1 if mname == 'ew_classifier' else 2} {mname} - {name}: {len(ks)} kernels, {tot:,.0f} us of GPU time", "h3"))
        rows = [["#", "us", "grid", "block", "regs", "smem", "occ", "kernel"]]
        for i, k in enumerate(ks[:26 if mname == "ew_classifier" else 24]):
            nm = demangle(k["name"])
            rows.append([i, f"{k.get('dur_us') or 0:.1f}", fmt_dims(k.get("grid")), fmt_dims(k.get("block")), k.get("regs"),
                         k.get("smem"), k.get("occupancy"), nm[:84]])
        for c in mc:
            rows.append(["", f"{c.get('dur') or 0:.1f}", "", "", "", "", "",
                         f"{c['name']}  {c.get('bytes', '')} B @ {c.get('memory bandwidth (GB/s)', 0) or 0:.2f} GB/s"])
        A(table(rows, [6, 11, 16, 14, 9, 11, 8, 99], mono_cols=(2, 3, 7)))
        rc = g(leg, "kernels", mname, "runtime_calls", default={})
        A(P("CPU-side CUDA API calls: " + ", ".join(f"{k} x{v}" for k, v in rc.items()), "small"))
A(P("Observe: (1) a 3-layer MLP on 256 samples = 20 launches but only ~0.1 ms of GPU work on the T4 - launch/dispatch overhead dominates; "
    "(2) ResNet18 is ~100 kernels, dominated by Winograd and implicit-GEMM convolutions; (3) the input copy for 8 images (4.8 MB) takes "
    "longer than several convolutions - the PCIe bus is a first-class cost for the image and detection models.", "callout"))
A(PageBreak())

# ---------------------------------------------------------------- 11
A(P("11. Machine code: Triton -> TTIR -> LLVM -> PTX -> SASS", "h1"))
A(P("cuBLAS/cuDNN kernels are shipped as pre-compiled binaries, so to see a kernel's complete life we compile one ourselves - a fused "
    "bias-add + ReLU, the same epilogue every Linear/Conv layer of these models ends with - using Triton (bundled with PyTorch on Linux):"))
A(code('''@triton.jit
def bias_relu(x_ptr, b_ptr, y_ptr, n, C: tl.constexpr, BLOCK: tl.constexpr):
    pid  = tl.program_id(0)                       # blockIdx.x
    offs = pid * BLOCK + tl.arange(0, BLOCK)     # this block's 1024 element indices
    mask = offs < n                              # bounds check -> predicate registers
    x = tl.load(x_ptr + offs, mask=mask)         # global -> registers (LDG)
    b = tl.load(b_ptr + offs % C, mask=mask)     # broadcast bias (offs mod 64)
    y = tl.maximum(x + b, 0.0)                   # FADD + FMNMX
    tl.store(y_ptr + offs, y, mask=mask)         # registers -> global (STG)
grid = (n // 1024,)   n = 16384, C = 64'''))
sl = next((l for l, _ in LEGS if os.path.exists(os.path.join(ROOT, l, "lowlevel", "bias_relu.sass"))), None)
if sl:
    sd = LL[sl].get("sass", {})
    d = os.path.join(ROOT, sl, "lowlevel")
    A(P(f"Captured on {LEGNAME[sl]}: {sd.get('n_regs')} registers/thread, {sd.get('n_spills')} spills, {sd.get('shared')} B shared memory, "
        f"num_warps = {sd.get('num_warps')} (= {(sd.get('num_warps') or 0) * 32} threads per block, each thread owns "
        f"{1024 // max(1, (sd.get('num_warps') or 4) * 32)} elements)."))
    A(P("11.1 Triton IR (TTIR) - target-independent, tensor-level", "h2"))
    A(code(read(os.path.join(d, "bias_relu.ttir")), max_lines=40))
    A(P("11.2 Triton GPU IR (TTGIR) - adds a layout: how the 1024-element tensor is distributed over threads", "h2"))
    tg = read(os.path.join(d, "bias_relu.ttgir"))
    A(code(tg, max_lines=30))
    A(P("The #blocked layout line is the key decision: sizePerThread=[4] means each thread holds 4 consecutive floats (-> one 128-bit load), "
        "threadsPerWarp=[32], warpsPerCTA=[num_warps]. 4 x 32 x warps x repetitions = 1024 elements.", "small"))
    A(P("11.3 LLVM IR (NVPTX target)", "h2"))
    A(code(read(os.path.join(d, "bias_relu.llir")), max_lines=55))
    A(PageBreak())
    A(P("11.4 PTX - NVIDIA's virtual ISA (what the driver can still re-compile for any future GPU)", "h2"))
    ptx = read(os.path.join(d, "bias_relu.ptx"))
    body = [l for l in ptx.splitlines() if l.strip() and not l.strip().startswith(("//", ".loc", ".file", "$L__", ".section", "}"))
            and not re.match(r"^\s*\.b8|^\s*\.debug", l)]
    start = next((i for i, l in enumerate(body) if ".entry" in l), 0)
    body = body[start:start + 70]
    rows = [["PTX", "meaning"]] + [[l.strip()[:70], e] for l, e in annotate(body, PTX_DOC)]
    A(table(rows, [96, 78], mono_cols=(0,)))
    A(PageBreak())
    A(P("11.5 SASS - the real sm_75 machine code (cuobjdump -sass)", "h2"))
    A(P("ptxas turns PTX into SASS: it allocates physical registers, schedules instructions, and encodes each as a 128-bit word. "
        "The /*0080*/ column is the byte offset (16 bytes per instruction); the hex column is the encoding, whose top bits hold the "
        "compiler-set scheduling control: stall cycles, yield hint, and which of the 6 scoreboard barriers the instruction sets or waits on "
        "(this is how a load's result is waited for without hardware interlocks)."))
    sass = [l for l in read(os.path.join(d, "bias_relu.sass")).splitlines() if re.search(r"/\*[0-9a-f]{4}\*/", l)]
    rows = [["offset", "instruction", "encoding (hex, 2 x 64 bit)", "what the SM does"]]
    raw_sass = read(os.path.join(d, "bias_relu.sass")).splitlines()
    for l in sass[:70]:
        mo = re.search(r"/\*([0-9a-f]{4})\*/\s+(.*?);\s*/\*\s*(0x[0-9a-f]+)\s*\*/", l)
        if not mo:
            continue
        idx = raw_sass.index(l) if l in raw_sass else -1
        hi = ""
        if 0 <= idx + 1 < len(raw_sass):
            h2 = re.search(r"/\*\s*(0x[0-9a-f]+)\s*\*/", raw_sass[idx + 1])
            hi = h2.group(1) if h2 else ""
        instr = mo.group(2).strip()
        mn = sass_mnemonic(l)
        exp = next((dsc for pat, dsc in SASS_DOC if re.search(pat, mn)), "")
        if instr.startswith("@"):
            exp = f"Predicated on {instr.split()[0]}: only lanes whose predicate is true execute. " + exp
        rows.append([mo.group(1), instr[:52], f"{mo.group(3)}\n{hi}", exp])
    A(table(rows, [11, 52, 36, 75], mono_cols=(0, 1, 2)))
    ru = sd.get("res_usage", "")
    if ru:
        A(P("cuobjdump -res-usage (resource summary the driver uses to compute occupancy at launch):", "small"))
        A(code(ru, max_lines=6))
    A(P("Trace one element through the hardware: S2R reads threadIdx/blockIdx; IMAD/LEA build the byte address; ISETP computes the mask "
        "predicate; LDG.E.128 fetches 4 floats per thread (a warp's 32 requests coalesce into 4 x 128-byte transactions from L2/DRAM); "
        "offs % 64 costs no division at all - C is a constexpr power of two, so ptxas emits SHF/SGXT/LEA.HI/LOP3 (shift, sign-fix, mask with ~63); "
    "a non-power-of-two C would have produced a MUFU.RCP + IMAD.HI reciprocal sequence because the GPU has no integer divider. FADD adds the bias, "
        "FMNMX clamps at zero, STG.E.128 writes 16 bytes per thread; EXIT ends the warp. Everything a Linear/Conv epilogue does in these "
        "models is this sequence, just fused into the cuBLAS/cuDNN kernel.", "callout"))
    ind = read(os.path.join(d, "inductor_ew_classifier_output_code.txt"))
    if ind:
        A(P("11.6 torch.compile of the repo's own ew_classifier (TorchInductor)", "h2"))
        A(P("Inductor traces the model, keeps the matrix multiplies as cuBLAS calls (extern_kernels.mm/addmm) and fuses everything between them "
            "(bias, batch-norm, ReLU) into generated Triton kernels. Excerpt of the generated code:"))
        seg = []
        grab = False
        for l in ind.splitlines():
            if "@triton.jit" in l:
                grab = True
            if grab:
                seg.append(l)
            if grab and len(seg) > 26:
                break
        calls = [l.strip() for l in ind.splitlines() if "extern_kernels." in l][:8]
        A(code("\n".join(seg) + "\n...\n# host-side call sequence:\n" + "\n".join(calls), max_lines=45))
else:
    A(P("(SASS listing not captured: Triton needs a C compiler to build its launcher; run the Linux leg with gcc installed.)", "small"))
A(PageBreak())

# ---------------------------------------------------------------- 12
A(P("12. Test results for all modes and what dominated each", "h1"))
A(P("Every run log was parsed for status independent of the exit code (several scripts catch Spark exceptions and still exit 0). "
    "Throughput = total samples processed by all models / wall time. Configuration per environment: Windows and WSL2 = one laptop, Spark local[2] "
    "(one concurrent task: spark.task.cpus=2), 4 GB GTX 1650; AWS = Spark standalone master + worker containers on one g4dn.xlarge, executor with "
    "4 cores (2 concurrent tasks), 16 GB T4."))
tests = sorted({t for r in RUNS.values() for t in r})
PH = {"p1": "Phase 1 - mode comparison", "p2": "Phase 2 - partition scaling", "p3": "Phase 3 - data size", "p4": "Phase 4 - batch size",
      "p7": "Phase 6/7/10 - cluster engine device modes", "p8": "Phase 8 - GPU batch size", "en": "Engines - RDD vs pandas UDF (example_mlp)",
      "sv": "Spark vs single GPU"}
for pfx, title in PH.items():
    ts = [t for t in tests if t.startswith(pfx)]
    if not ts:
        continue
    A(P(title, "h2"))
    rows = [["test", *[n for _, n in LEGS]]]
    for t in ts:
        cells = []
        for leg, _ in LEGS:
            r = RUNS[leg].get(t)
            if not r:
                cells.append("-")
                continue
            thr = "; ".join(f"{k.split()[0].replace('single_gpu_', '')} {v:,.0f}/s" for k, v in r["throughput"].items())
            s = r["status"] + (" - " + r["reason"] if r["reason"] else "")
            cells.append(f"<b>{esc(s)}</b><br/>{esc(thr)}" + (f"<br/>{r['elapsed_s']:.1f} s" if r.get("elapsed_s") else ""))
        rows.append([t, *cells])
    A(table(rows, [30] + [144 / len(LEGS)] * len(LEGS)))


def val(leg, t, key="Spark distributed"):
    r = RUNS.get(leg, {}).get(t)
    if not r:
        return 0
    return r["throughput"].get(key) or next(iter(r["throughput"].values()), 0) if r["status"] != "FAIL" else 0


sel = [t for t in ("p3_tiny", "p3_medium", "p3_xlarge", "p7_cpu_only_medium", "p7_gpu_only_medium", "p7_hybrid_medium") if any(t in RUNS[l] for l, _ in LEGS)]
if sel:
    A(bar_chart([t.replace("p7_", "").replace("p3_", "size_") for t in sel], [[val(l, t) for t in sel] for l, _ in LEGS],
                [n for _, n in LEGS], "Spark distributed throughput (samples/s)", "samples/s", fmt="%.0f",
                colorlist=[LEGCOL[l] for l, _ in LEGS]))
A(P("12.1 What each test is really measuring at the low level", "h2"))
A(table([["test / phase", "dominant low-level effect", "evidence in your data"],
         ["P1 single_gpu vs distributed", "Single-GPU mode keeps models resident and launches kernels on CUDA streams from one process; distributed pays per task: Python worker start (spawn on Windows), cloudpickle of 10 models' weights, model re-construction, first-call cuDNN autotune/JIT, H2D of pageable data.",
          "Mode 1 is 10-100x slower than Mode 2 on every leg; event log shows run time >> JVM CPU time"],
         ["P2 partitions", "Each partition = one task = one full model load. More partitions multiply fixed overhead; parallelism is capped at 1 (laptop) or 2 (AWS) concurrent tasks.",
          "Windows: falls monotonically 2 -> 16 (process spawn per task); WSL2 noisy (342-538/s); AWS peaks at 4 (= 2 task slots x 2 waves), falls at 16"],
         ["P3 data size", "Fixed per-task overhead is amortised by more samples; throughput rises with size until the GPU (or pageable PCIe copy) becomes the limit.",
          "tiny -> xlarge: ~10-15x on every leg"],
         ["P4 / P8 batch size", "Larger batches = fewer kernel launches and larger GEMM tiles per launch. Once launch overhead is amortised the effect flattens; memory ceiling on 4 GB VRAM.",
          "flat on T4 (1.6K/s at 32..512); p8 batch 128 failed on the laptop (VRAM/commit)"],
         ["P7 cpu_only vs gpu_only vs hybrid", "cpu_only = oneDNN AVX2/AVX-512 JIT code; gpu_only = cuBLAS/cuDNN SASS; hybrid = GPU if present. Image/detection models dominate compute.",
          "gpu_only ~1.6x cpu_only on T4 at medium load; laptop gains less (launch latency + contention)"],
         ["Engines rdd vs udf", "RDD returns counts only (small result, pickle stream); UDF ships Arrow batches and returns one prediction row per sample (much larger result, JVM<->Python Arrow conversion both ways).",
          "RDD ~2x UDF throughput on every leg; UDF logs are 2.7 MB (real predictions)"],
         ["svs_single_gpu", "Same models, no Spark: pure CUDA streams. Upper bound for this hardware.",
          "T4 58.8K/s; same GTX 1650: 20.6K/s under WSL2/Linux vs 3.8K/s on Windows native (WDDM launch cost)"]],
        [30, 88, 56]))
A(PageBreak())

# ---------------------------------------------------------------- 13
A(P("13. Failures, root-caused to the byte", "h1"))
fails = []
for leg, name in LEGS:
    for t, r in RUNS[leg].items():
        if r["status"] != "OK":
            fails.append([name, t, r["status"], r["reason"] or "see log"])
    for f in glob.glob(os.path.join(ROOT, leg, "*_stalled_*.txt")):
        fails.append([name, os.path.basename(f).split("_spark")[0], "PARTIAL",
                      "Spark half stalled (VM out of memory); single-GPU half re-run with --local"])
if fails:
    A(table([["environment", "test", "status", "root cause"]] + fails, [34, 40, 18, 82]))
A(P("How each failure happens at the lowest level:", "h3"))
A(table([["symptom in log", "mechanism"],
         ["DefaultCPUAllocator: not enough memory: you tried to allocate 589824 bytes", "torch's CPU allocator asked the OS for one 128x128x3x3 fp32 ResNet conv weight (128*128*9*4 = 589,824 B; the other failure, 9,437,184 B = 512x512x3x3) and the OS refused: with local[4] four Python workers each held 10 models (~1+ GB each) on an 8 GB host with a 4 GB WSL2 VM resident."],
         ["os::commit_memory ... 'The paging file is too small' (errno 1455)", "Windows commits every reserved page against RAM+pagefile at reservation time (Linux overcommits). The JVM's G1 heap tried to commit a 64 MB region; the system commit limit was exhausted, the JVM aborted (hs_err_pid*.log), Py4J lost its socket -> 'connection forcibly closed'."],
         ["fatal: Memory allocation failure / CUDA error: unknown error", "The CUDA driver JIT (or cuDNN/cuBLAS lazy module load) needed host memory to load/compile kernel images and failed; the context is then poisoned and the next kernel returns cudaErrorUnknown."],
         ["CUDA error: out of memory", "cudaMalloc for activations/workspace exceeded the 4 GB VRAM (minus what the Windows desktop compositor holds under WDDM)."],
         ["unexpected pos X vs Y (inline_container.cc)", "torch.load read a truncated serialized model (zip container) - the bytes shipped to the worker were cut short when the JVM/worker died mid-transfer."],
         ["WSL2 cluster: stage stuck (0 + 2) / 4, Docker API 500", "executor processes were OOM-killed inside the 3.75 GB WSL2 VM and relaunched repeatedly; the VM itself became unresponsive. Fixed by running one container with local[2]."],
         ["AWS first attempt: bucket name \"\"", "SSM ran the script before cloud-init had written BUCKET into /etc/environment (race); fixed by passing BUCKET explicitly and 'cloud-init status --wait'."]],
        [62, 112], mono_cols=(0,)))
A(P("Take-away: on an 8 GB laptop the Spark distributed modes are memory-bound, not compute-bound - each concurrent task holds its own copy "
    "of all 10 models plus a CUDA context (~300-500 MB host RSS). On AWS (16 GB host, 16 GB VRAM) every test passed.", "callout"))

# ---------------------------------------------------------------- 14
A(P("14. Reproduce / file index", "h1"))
A(code(r'''# Windows native leg (Spark local[2])
LEG=windows bash benchmark/run_campaign.sh
python benchmark/lowlevel_trace.py --out results/campaign_20260926/windows/lowlevel

# WSL2 / Docker leg (one GPU container, Linux)
docker run -d --name wsl-leg --gpus all -e SPARK_MASTER_URL=local[2] -v <repo>/results:/app/results ... multi-model-inference:latest sleep infinity
docker exec -e LEG=wsl2_docker wsl-leg bash benchmark/run_campaign.sh
docker exec wsl-leg bash -c "apt-get install -y gcc && python benchmark/lowlevel_trace.py --out results/campaign_20260926/wsl2_docker/lowlevel"

# AWS leg (deploys GpuBenchmarkStack g4dn.xlarge, runs everything, downloads, destroys)
.\deploy\run_aws_campaign.ps1

# Summaries and this PDF
python benchmark/summarize_campaign.py results/campaign_20260926
python benchmark/build_lowlevel_pdf.py results/campaign_20260926 docs/LOWLEVEL_EXECUTION_GUIDE_20260926.pdf

# Concepts handbook (Word) - needs `npm install docx`
node benchmark/build_concepts_docx.js'''))
A(table([["path", "contents"],
         ["results/campaign_20260926/<leg>/*.log", "full stdout/stderr of every test"],
         ["results/campaign_20260926/<leg>/summary.tsv", "exit code and wall seconds per test"],
         ["results/campaign_20260926/<leg>/lowlevel.log", "human-readable low-level trace (chapters 2-11)"],
         ["results/campaign_20260926/<leg>/lowlevel/lowlevel.json", "all trace measurements (this PDF's data source)"],
         ["results/campaign_20260926/<leg>/lowlevel/trace_*.json", "Chrome/Perfetto timelines: open in ui.perfetto.dev"],
         ["results/campaign_20260926/<leg>/lowlevel/bias_relu.{ttir,ttgir,llir,ptx,cubin,sass}", "every compilation stage of the chapter-11 kernel"],
         ["results/campaign_20260926/<leg>/spark-events/", "Spark event logs (Linux legs) - load in the Spark History Server"],
         ["results/campaign_20260926/aws_g4dn/spark-worker-work/", "executor stdout/stderr per application"],
         ["results/campaign_20260926/windows/jvm_crash/", "hs_err_pid*.log / replay_pid*.log from the JVM commit-limit crashes"],
         ["results/campaign_20260926/summary.md|json", "cross-environment status/throughput table"]],
        [86, 88], mono_cols=(0,)))


def on_page(canv, doc):
    canv.saveState()
    canv.setFont(BODY, 7.5)
    canv.setFillColor(MUTED)
    canv.drawString(18 * mm, 10 * mm, "From Python to Silicon - pytorch-spark-inference-platform low-level execution guide")
    canv.drawRightString(192 * mm, 10 * mm, f"{doc.page}")
    canv.setStrokeColor(RULE)
    canv.line(18 * mm, 13 * mm, 192 * mm, 13 * mm)
    canv.restoreState()


os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                        title="From Python to Silicon", author="pytorch-spark-inference-platform",
                        subject="Low-level execution guide: bits, ISA, registers, GPU, buses, Spark wire protocol")
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print("wrote", OUT)
