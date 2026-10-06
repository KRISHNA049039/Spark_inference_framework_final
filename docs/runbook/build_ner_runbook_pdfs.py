"""
build_ner_runbook_pdfs.py - two PDFs for the NER pipeline on the cluster:

  docs/NER_PIPELINE_END_TO_END_PROCESS.pdf     conceptual: start -> stop, every stage
  docs/CLUSTER_RUNBOOK_MODES_AND_TESTS.pdf     operational: every cluster mode, the
                                               air-gapped HDFS / master-FS model store
                                               simulation, all tests with real outputs

Test outputs are read from results/airgap_sim_*/ (deploy/airgap_sim_tests.ps1),
so the runbook shows what actually happened on the last run.

  python docs/runbook/build_ner_runbook_pdfs.py
"""
import glob
import json
import os
import re
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIAG = os.path.join(REPO, "docs", "diagrams", "png")
FONT_DIR = "C:/Windows/Fonts"
try:
    pdfmetrics.registerFont(TTFont("Body", os.path.join(FONT_DIR, "arial.ttf")))
    pdfmetrics.registerFont(TTFont("Body-Bold", os.path.join(FONT_DIR, "arialbd.ttf")))
    pdfmetrics.registerFont(TTFont("Mono", os.path.join(FONT_DIR, "consola.ttf")))
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body", boldItalic="Body-Bold")
    BODY, BOLD, MONO = "Body", "Body-Bold", "Mono"
except Exception:
    BODY, BOLD, MONO = "Helvetica", "Helvetica-Bold", "Courier"

INK, MUTED, ACCENT, RULE = colors.HexColor("#1b1f24"), colors.HexColor("#57606a"), colors.HexColor("#0b5cad"), colors.HexColor("#d0d7de")
S = {
    "title": ParagraphStyle("t", fontName=BOLD, fontSize=22, leading=27, textColor=INK, spaceAfter=6),
    "sub": ParagraphStyle("s", fontName=BODY, fontSize=11.5, leading=15, textColor=MUTED, spaceAfter=14),
    "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=16, leading=20, textColor=INK, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=12, leading=15, textColor=ACCENT, spaceBefore=9, spaceAfter=4, keepWithNext=1),
    "h3": ParagraphStyle("h3", fontName=BOLD, fontSize=10.2, leading=13, textColor=INK, spaceBefore=6, spaceAfter=3, keepWithNext=1),
    "p": ParagraphStyle("p", fontName=BODY, fontSize=9.4, leading=13, textColor=INK, spaceAfter=5),
    "small": ParagraphStyle("sm", fontName=BODY, fontSize=8, leading=10.5, textColor=MUTED, spaceAfter=4),
    "cell": ParagraphStyle("c", fontName=BODY, fontSize=7.8, leading=9.8, textColor=INK),
    "cellb": ParagraphStyle("cb", fontName=BOLD, fontSize=7.8, leading=9.8, textColor=INK),
    "cellm": ParagraphStyle("cm", fontName=MONO, fontSize=7, leading=8.8, textColor=INK),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=7.2, leading=9, textColor=INK),
    "note": ParagraphStyle("n", fontName=BODY, fontSize=9, leading=12.5, textColor=INK, backColor=colors.HexColor("#eef6ff"),
                           borderColor=colors.HexColor("#b6d4f5"), borderWidth=0.6, borderPadding=6, spaceBefore=4, spaceAfter=9),
    "warn": ParagraphStyle("w", fontName=BODY, fontSize=9, leading=12.5, textColor=INK, backColor=colors.HexColor("#fff4e5"),
                           borderColor=colors.HexColor("#f0c27a"), borderWidth=0.6, borderPadding=6, spaceBefore=4, spaceAfter=9),
}


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md(t):
    """**bold** and `code` -> reportlab markup."""
    t = esc(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"`(.+?)`", rf"<font name='{MONO}' size='8.3'>\1</font>", t)


class Doc:
    def __init__(self):
        self.story = []

    def P(self, t, st="p"):
        self.story.append(Paragraph(md(t), S[st]))

    def H(self, t, lvl=1):
        self.story.append(Paragraph(esc(t), S[f"h{lvl}"]))

    def B(self, items, numbered=False):
        for i, t in enumerate(items):
            lead = f"{i + 1}." if numbered else "&#8226;"
            self.story.append(Paragraph(f"{lead}&nbsp;&nbsp;{md(t)}", ParagraphStyle("li", parent=S["p"], leftIndent=12, firstLineIndent=-10)))

    def code(self, text, max_lines=60, width=112):
        lines = []
        for l in str(text).replace("\t", "    ").splitlines()[:max_lines]:
            while len(l) > width:
                lines.append(l[:width]); l = "    " + l[width:]
            lines.append(l)
        t = Table([[Preformatted("\n".join(lines) or " ", S["code"])]], colWidths=[174 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f5f8")), ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                               ("LEFTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        self.story.append(t)
        self.story.append(Spacer(1, 4))

    def table(self, rows, widths, mono=()):
        data = []
        for i, r in enumerate(rows):
            data.append([c if not isinstance(c, str) else Paragraph(md(c) if i else esc(c), S["cellb" if i == 0 else ("cellm" if j in mono else "cell")])
                         for j, c in enumerate(r)])
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        st = [("GRID", (0, 0), (-1, -1), 0.3, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaeef2")),
              ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        for i in range(2, len(data), 2):
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fbfcfd")))
        t.setStyle(TableStyle(st))
        self.story.append(t)
        self.story.append(Spacer(1, 5))

    def img(self, key, caption="", maxh=120):
        p = os.path.join(DIAG, f"{key}.png")
        if not os.path.exists(p):
            return
        from PIL import Image as PI
        w, h = PI.open(p).size
        W = 174 * mm
        H = W * h / w
        if H > maxh * mm:
            H = maxh * mm
            W = H * w / h
        self.story.append(Image(p, width=W, height=H))
        if caption:
            self.story.append(Paragraph(esc(caption), ParagraphStyle("cap", parent=S["small"], alignment=1)))

    def note(self, t, warn=False):
        self.story.append(Paragraph(md(t), S["warn" if warn else "note"]))

    def brk(self):
        self.story.append(PageBreak())

    def build(self, path, title):
        def page(c, d):
            c.saveState(); c.setFont(BODY, 7.5); c.setFillColor(MUTED)
            c.drawString(18 * mm, 10 * mm, title)
            c.drawRightString(192 * mm, 10 * mm, str(d.page))
            c.setStrokeColor(RULE); c.line(18 * mm, 13 * mm, 192 * mm, 13 * mm); c.restoreState()
        doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm, bottomMargin=18 * mm, title=title,
                                author="pytorch-spark-inference-platform")
        doc.build(self.story, onFirstPage=page, onLaterPages=page)
        print("wrote", path)


# ------------------------------------------------------------------ test evidence
def load_tests():
    """Latest result + log of every test id across all results/airgap_sim_* runs."""
    tests = {}
    for d in sorted(glob.glob(os.path.join(REPO, "results", "airgap_sim_*"))):
        sj = os.path.join(d, "summary.json")
        if not os.path.exists(sj):
            continue
        try:
            summ = json.load(open(sj, encoding="utf-8-sig"))
        except Exception:
            continue
        if isinstance(summ, dict):
            summ = [summ]
        for r in summ:
            log = os.path.join(d, f"{r['Test']}.log")
            tests[r["Test"]] = {**r, "log": open(log, encoding="utf-8", errors="replace").read() if os.path.exists(log) else "", "run": os.path.basename(d)}
    return tests


T = load_tests()


def ev(tid, patterns, n=12):
    """Lines of a test's log matching any pattern (the evidence shown in the runbook)."""
    log = T.get(tid, {}).get("log", "")
    out = list(dict.fromkeys(l.rstrip() for l in log.splitlines() if any(re.search(p, l) for p in patterns)))
    return "\n".join(out[:n]) if out else "(no output captured)"


def res(tid):
    t = T.get(tid)
    return f"{t['Result']} ({t['Seconds']} s)" if t else "not run"


from runbook_content import build_process_pdf, build_runbook_pdf  # noqa: E402

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    build_process_pdf(Doc, os.path.join(REPO, "docs", "NER_PIPELINE_END_TO_END_PROCESS.pdf"), T, ev, res)
    build_runbook_pdf(Doc, os.path.join(REPO, "docs", "CLUSTER_RUNBOOK_MODES_AND_TESTS.pdf"), T, ev, res)
