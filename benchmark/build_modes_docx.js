// build_modes_docx.js - "Spark distributed inference: execution modes, worker-level
// statistics and a Triton architecture" (Word, A4 landscape).
//
// Reads results/modes_20260926/<run>/modes_summary.json (analyze_modes_stats.py),
// its charts/ and gantt/ PNGs, the Triton configs and docs/diagrams/png/*.png.
// Needs the `docx` npm package (npm install docx).
//
//   node benchmark/build_modes_docx.js [run_dir] [out.docx]
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, LevelFormat, TableOfContents, Footer, PageNumber, ImageRun, PageOrientation,
} = require("docx");

const REPO = path.join(__dirname, "..");
// one or more result dirs, comma-separated; the first is the primary run
const RUN_DIRS = (process.argv[2] || path.join(REPO, "results", "modes_20260926", "aws_2node")).split(",");
const RUN = RUN_DIRS[0];
const TEXT = process.argv[4] || "modes_doc_text.js";
const OUT = process.argv[3] || path.join(REPO, "docs", "SPARK_INFERENCE_MODES_AND_TRITON_ARCHITECTURE_20260926.docx");
const DIAG = path.join(REPO, "docs", "diagrams", "png");
const S = RUN_DIRS.flatMap((d) => JSON.parse(fs.readFileSync(path.join(d, "modes_summary.json"), "utf8"))
  .map((s) => ({ ...s, run: path.basename(d), runDir: d })));
const readT = (p) => { try { return fs.readFileSync(p, "utf8"); } catch { return ""; } };
const RES = readT(path.join(RUN, "results.jsonl")).split(/\r?\n/).filter(Boolean).map((l) => JSON.parse(l));

// A4 landscape, 1.5 cm margins
const PW = 16838, PH = 11906, M = 850, CW = PW - 2 * M;
const MONO = "Consolas", BODY = "Arial", ACCENT = "0B5CAD";

// ------------------------------------------------------------------ helpers
function runs(text, base = {}) {
  const out = []; const re = /(\*\*[^*]+\*\*|`[^`]+`)/g; let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    out.push(t.startsWith("**") ? new TextRun({ text: t.slice(2, -2), bold: true, ...base })
      : new TextRun({ text: t.slice(1, -1), font: MONO, size: 17, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}
const body = [];
const H1 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(t)] }));
const H2 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] }));
const H3 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] }));
const P = (t) => body.push(new Paragraph({ spacing: { after: 110 }, children: runs(t) }));
const B = (items) => items.forEach((t) => body.push(new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 50 }, children: runs(t) })));
let numInstance = 0;  // each numbered list restarts at 1
const N = (items) => { numInstance++; const inst = numInstance;
  items.forEach((t) => body.push(new Paragraph({ numbering: { reference: "numbers", level: 0, instance: inst }, spacing: { after: 50 }, children: runs(t) }))); };
function note(t, fill = "EAF3FD", bar = ACCENT) {
  body.push(new Paragraph({ shading: { type: ShadingType.CLEAR, color: "auto", fill }, border: { left: { style: BorderStyle.SINGLE, size: 18, color: bar, space: 6 } },
    spacing: { before: 80, after: 160 }, indent: { left: 160, right: 120 }, children: runs(t) }));
}
function code(text, max = 60) {
  const lines = String(text || "(not captured)").replace(/\t/g, "    ").split(/\r?\n/).slice(0, max);
  lines.forEach((l, i) => body.push(new Paragraph({ shading: { type: ShadingType.CLEAR, color: "auto", fill: "F3F5F8" },
    spacing: { before: i === 0 ? 60 : 0, after: i === lines.length - 1 ? 140 : 0, line: 235 }, indent: { left: 120, right: 120 },
    children: [new TextRun({ text: l.length ? l : " ", font: MONO, size: 15 })] })));
}
const bd = { style: BorderStyle.SINGLE, size: 4, color: "C9D1D9" };
function table(rows, pct, mono = []) {
  const w = pct.map((p) => Math.floor((CW * p) / 100)); const tot = w.reduce((a, b) => a + b, 0);
  body.push(new Table({ width: { size: tot, type: WidthType.DXA }, columnWidths: w, rows: rows.map((r, ri) => new TableRow({
    tableHeader: ri === 0, children: r.map((c, ci) => new TableCell({ borders: { top: bd, bottom: bd, left: bd, right: bd },
      width: { size: w[ci], type: WidthType.DXA }, margins: { top: 40, bottom: 40, left: 80, right: 80 },
      shading: ri === 0 ? { type: ShadingType.CLEAR, color: "auto", fill: "E4E9F0" } : (ri % 2 === 0 ? { type: ShadingType.CLEAR, color: "auto", fill: "FAFBFC" } : undefined),
      children: [new Paragraph({ children: ri === 0 ? [new TextRun({ text: String(c), bold: true, size: 17 })]
        : mono.includes(ci) ? [new TextRun({ text: String(c), font: MONO, size: 15 })] : runs(String(c), { size: 17 }) })] })) })) }));
  body.push(new Paragraph({ spacing: { after: 100 }, children: [] }));
}
function pngSize(p) { const b = fs.readFileSync(p); return [b.readUInt32BE(16), b.readUInt32BE(20)]; }
function img(p, maxW = 980, caption = "") {
  if (!fs.existsSync(p)) { P(`(image not available: ${path.basename(p)})`); return; }
  const [w, h] = pngSize(p); let W = Math.min(maxW, w / 2); let Hh = (h * W) / w;
  if (Hh > 455) { Hh = 455; W = (w * Hh) / h; }
  body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 60, after: caption ? 40 : 140 },
    children: [new ImageRun({ type: "png", data: fs.readFileSync(p), transformation: { width: Math.round(W), height: Math.round(Hh) },
      altText: { title: path.basename(p), description: caption || path.basename(p), name: path.basename(p) } })] }));
  if (caption) body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 }, children: [new TextRun({ text: caption, italics: true, size: 16, color: "57606A" })] }));
}

// ------------------------------------------------------------------ data helpers
const get = (model, mode, run) => S.find((s) => s.model === model && s.mode === mode && (!run || s.run === run));
const MODELS = [...new Set(S.filter((s) => s.run === path.basename(RUN)).map((s) => s.model).filter((m) => m && m !== "platform10"))];
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "-" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
const mb = (b) => fmt((b || 0) / 1e6, 1);
const thr = (s) => (s && !s.error && s.throughput ? `${fmt(s.throughput, 0)}/s` : s ? `failed (${s.error || "?"})` : "not run");
function inferStage(s) { const st = s.stages || []; return st.filter((x) => /UDF|map \(Python\)/.test(x.kind || "")).pop() || st[st.length - 1] || {}; }
function workersLine(s) {
  return (s.executors || []).map((e) => `${e.host} (${e.device}): ${e.tasks || 0} tasks`).join("; ") || "-";
}
function loadsLine(s) {
  const L = s.model_loads || []; if (!L.length) return s.mode && s.mode.startsWith("udf") ? "per task (not instrumented)" : "-";
  const byDev = {}; L.forEach((l) => { byDev[l.device] = (byDev[l.device] || 0) + 1; });
  const avg = L.reduce((a, l) => a + l.secs, 0) / L.length;
  return `${L.length} (${Object.entries(byDev).map(([k, v]) => `${v} ${k}`).join(", ")}), avg ${fmt(avg, 2)} s`;
}
function statRows(mode, models = MODELS, run) {
  const cols = models.map((m) => get(m, mode, run));
  const r = (label, f) => [label, ...cols.map((s) => (s ? f(s) : "not run"))];
  const sum = (s, k) => (s.tasks || []).reduce((a, t) => a + (t[k] || 0), 0);
  return [
    ["metric", ...models],
    r("throughput (samples/s)", (s) => thr(s)),
    r("wall time of the job", (s) => `${fmt(s.wall_s, 2)} s`),
    r("samples x batch size x partitions", (s) => `${fmt(s.samples, 0)} x ${s.batch_size} x ${s.partitions}`),
    r("jobs / stages / tasks", (s) => `${(s.jobs || []).length} / ${(s.stages || []).length} / ${(s.tasks || []).length}`),
    r("stages", (s) => (s.stages || []).map((x) => `s${x.id}: ${x.kind} (${x.tasks} tasks, ${fmt(x.duration_ms / 1000, 2)} s)`).join("; ")),
    r("tasks per worker (device)", (s) => workersLine(s)),
    r("inference task min / median / max", (s) => { const st = inferStage(s); return `${fmt(st.task_ms_min / 1000, 2)} / ${fmt(st.task_ms_median / 1000, 2)} / ${fmt(st.task_ms_max / 1000, 2)} s`; }),
    r("sum deserialize / run / JVM CPU / GC", (s) => `${fmt(sum(s, "deser_ms") / 1000, 2)} / ${fmt(sum(s, "run_ms") / 1000, 2)} / ${fmt(sum(s, "cpu_ms") / 1000, 2)} / ${fmt(sum(s, "gc_ms") / 1000, 2)} s`),
    r("shuffle write / read (remote)", (s) => `${mb(sum(s, "shuffle_write_bytes"))} / ${mb(sum(s, "shuffle_read_bytes"))} (${mb(sum(s, "shuffle_remote_bytes"))}) MB`),
    r("task results to driver", (s) => `${mb(sum(s, "result_bytes"))} MB`),
    r("model loads", (s) => loadsLine(s)),
    r("GPU SM util avg / max", (s) => (s.gpu_util ? `${fmt(s.gpu_util.avg, 0)} % / ${fmt(s.gpu_util.max, 0)} %` : "-")),
    r("GPU memory used max", (s) => (s.gpu_fb_mb ? `${fmt(s.gpu_fb_mb.max, 0)} MB` : "-")),
  ];
}
function execTable(s) {
  if (!s || !(s.executors || []).length) return;
  table([["executor", "host", "device", "cores", "tasks", "busy s", "run s", "JVM CPU s", "GC s", "longest task s", "shuffle read MB", "results MB"],
    ...s.executors.map((e) => [e.id, e.host, e.device, e.cores, e.tasks || 0, fmt((e.busy_ms || 0) / 1000, 2), fmt((e.run_ms || 0) / 1000, 2),
      fmt((e.cpu_ms || 0) / 1000, 2), fmt((e.gc_ms || 0) / 1000, 2), fmt((e.max_task_ms || 0) / 1000, 2), mb(e.shuffle_read_bytes), mb(e.result_bytes)])],
  [9, 13, 7, 6, 6, 8, 8, 9, 7, 10, 9, 8]);
}
function gantt(model, mode, cap, run) {
  const s = get(model, mode, run); const dir = s ? s.runDir : RUN;
  img(path.join(dir, "gantt", `modes-${model}-${mode}.png`), 960, cap);
}
const EXTRA = require("./" + TEXT);

module.exports = { body, H1, H2, H3, P, B, N, note, code, table, img, get, fmt, thr, mb, statRows, execTable, gantt, MODELS, S, RES, RUN, RUN_DIRS, DIAG, REPO, readT, inferStage };

// ------------------------------------------------------------------ content
EXTRA.build(module.exports);

const doc = new Document({
  creator: "pytorch-spark-inference-platform", title: "Spark distributed inference - execution modes and Triton architecture",
  styles: { default: { document: { run: { font: BODY, size: 19 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 32, bold: true, font: BODY, color: "1B1F24" }, paragraph: { spacing: { before: 120, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 25, bold: true, font: BODY, color: ACCENT }, paragraph: { spacing: { before: 220, after: 110 }, outlineLevel: 1, keepNext: true } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 21, bold: true, font: BODY, color: "1B1F24" }, paragraph: { spacing: { before: 160, after: 70 }, outlineLevel: 2, keepNext: true } }] },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 500, hanging: 260 } } } }] },
    { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 500, hanging: 300 } } } }] }] },
  sections: [{ properties: { page: { size: { width: PH, height: PW, orientation: PageOrientation.LANDSCAPE }, margin: { top: M, bottom: M, left: M, right: M } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [
      new TextRun({ text: "Spark distributed inference - execution modes and Triton architecture    ", size: 15, color: "57606A" }),
      new TextRun({ children: [PageNumber.CURRENT], size: 15, color: "57606A" })] })] }) },
    children: body }],
});
Packer.toBuffer(doc).then((buf) => { fs.mkdirSync(path.dirname(OUT), { recursive: true }); fs.writeFileSync(OUT, buf); console.log("wrote", OUT, buf.length); });
