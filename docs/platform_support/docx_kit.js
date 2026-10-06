// docx_kit.js - small helpers shared by the Word builders in docs/platform_support/:
// headings, paragraphs with **bold** / `code`, bullets, numbered lists, notes, code blocks,
// tables and diagram images, collected into one A4 portrait document.
//   const kit = require("./docx_kit")();  kit.H1("..."); ...; kit.write(outPath, title);
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, LevelFormat, TableOfContents, Footer, PageNumber, ImageRun,
} = require("docx");

const PW = 11906, PH = 16838, M = 1000, CW = PW - 2 * M;
const MONO = "Consolas", BODY = "Arial", ACCENT = "0B5CAD";
const DIAG = path.join(__dirname, "..", "diagrams", "png");

module.exports = function kit() {
  const body = [];
  let numInstance = 0;
  const bd = { style: BorderStyle.SINGLE, size: 4, color: "C9D1D9" };

  function runs(text, base = {}) {
    const out = []; const re = /(\*\*[^*]+\*\*|`[^`]+`)/g; let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
      const t = m[0];
      out.push(t.startsWith("**") ? new TextRun({ text: t.slice(2, -2), bold: true, ...base })
        : new TextRun({ text: t.slice(1, -1), font: MONO, size: 18, ...base }));
      last = m.index + t.length;
    }
    if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
    return out;
  }
  const k = {
    body, CW,
    title(t, sub) {
      body.push(new Paragraph({ spacing: { before: 900, after: 200 }, children: [new TextRun({ text: t, size: 52, bold: true })] }));
      body.push(new Paragraph({ spacing: { after: 300 }, children: [new TextRun({ text: sub, size: 26, color: "57606A" })] }));
    },
    toc() { body.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" })); },
    H1: (t, br = false) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: br, children: [new TextRun(t)] })),
    H2: (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] })),
    P: (t) => body.push(new Paragraph({ spacing: { after: 120 }, children: runs(t) })),
    B: (items) => items.forEach((t) => body.push(new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 60 }, children: runs(t) }))),
    N(items) {
      numInstance++; const inst = numInstance;
      items.forEach((t) => body.push(new Paragraph({ numbering: { reference: "numbers", level: 0, instance: inst }, spacing: { after: 60 }, children: runs(t) })));
    },
    note(t, fill = "EAF3FD", bar = ACCENT) {
      body.push(new Paragraph({ shading: { type: ShadingType.CLEAR, color: "auto", fill }, border: { left: { style: BorderStyle.SINGLE, size: 18, color: bar, space: 6 } },
        spacing: { before: 80, after: 160 }, indent: { left: 160, right: 120 }, children: runs(t) }));
    },
    warn(t) { k.note(t, "FFF4E5", "D97706"); },
    code(text) {
      const lines = String(text).split("\n");
      lines.forEach((l, i) => body.push(new Paragraph({ shading: { type: ShadingType.CLEAR, color: "auto", fill: "F3F5F8" },
        spacing: { before: i === 0 ? 60 : 0, after: i === lines.length - 1 ? 140 : 0, line: 240 }, indent: { left: 100, right: 100 },
        children: [new TextRun({ text: l || " ", font: MONO, size: 16 })] })));
    },
    table(rows, pct, fs_ = 17) {
      const w = pct.map((p) => Math.floor((CW * p) / 100)); const tot = w.reduce((a, b) => a + b, 0);
      body.push(new Table({ width: { size: tot, type: WidthType.DXA }, columnWidths: w, rows: rows.map((r, ri) => new TableRow({
        tableHeader: ri === 0, children: r.map((c, ci) => new TableCell({ borders: { top: bd, bottom: bd, left: bd, right: bd },
          width: { size: w[ci], type: WidthType.DXA }, margins: { top: 40, bottom: 40, left: 80, right: 80 },
          shading: ri === 0 ? { type: ShadingType.CLEAR, color: "auto", fill: "E4E9F0" } : (ri % 2 === 0 ? { type: ShadingType.CLEAR, color: "auto", fill: "FAFBFC" } : undefined),
          children: String(c).split("\n").map((line) => new Paragraph({ children: ri === 0 ? [new TextRun({ text: line, bold: true, size: fs_ })] : runs(line, { size: fs_ }) })) })) })) }));
      body.push(new Paragraph({ spacing: { after: 100 }, children: [] }));
    },
    img(key, caption, maxW = 640) {
      const p = path.join(DIAG, `${key}.png`);
      const b = fs.readFileSync(p); const w = b.readUInt32BE(16), h = b.readUInt32BE(20);
      const W = Math.min(maxW, w / 2), H = (h * W) / w;
      body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 60, after: 40 }, children: [new ImageRun({ type: "png", data: b,
        transformation: { width: Math.round(W), height: Math.round(H) }, altText: { title: key, description: caption || key, name: key } })] }));
      if (caption) body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 150 }, children: [new TextRun({ text: caption, italics: true, size: 16, color: "57606A" })] }));
    },
    write(out, title) {
      const doc = new Document({
        creator: "pytorch-spark-inference-platform", title,
        styles: {
          default: { document: { run: { font: BODY, size: 20 } } },
          paragraphStyles: [
            { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 30, bold: true, font: BODY, color: "1B1F24" },
              paragraph: { keepNext: true, keepLines: true, spacing: { before: 300, after: 140 }, outlineLevel: 0 } },
            { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 24, bold: true, font: BODY, color: ACCENT },
              paragraph: { keepNext: true, keepLines: true, spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
          ],
        },
        numbering: { config: [
          { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
          { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
        ] },
        sections: [{
          properties: { page: { size: { width: PW, height: PH }, margin: { top: M, right: M, bottom: M, left: M } } },
          footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [
            new TextRun({ text: `${title}    `, size: 16, color: "57606A" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "57606A" })] })] }) },
          children: body,
        }],
      });
      return Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(out, buf); console.log("wrote", out, buf.length, "bytes"); });
    },
  };
  return k;
};
