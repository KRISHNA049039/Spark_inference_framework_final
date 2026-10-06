"""
diagram_engine.py - one definition -> editable draw.io page + matching PNG.

Boxes and edges are declared once (absolute coordinates in draw.io pixels);
to_drawio() writes an <mxfile> with one page per diagram (open in
app.diagrams.net or draw.io desktop), render_png() draws the same geometry
with Pillow so the images embedded in documents match the .drawio pages.
"""
import html
import math
from xml.sax.saxutils import escape

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("diagram_engine.py needs Pillow to draw PNGs: pip install pillow")

STYLES = {
    #          fill        stroke     font
    "client":  ("#f5f5f5", "#666666", "#1b1f24"),
    "driver":  ("#dae8fc", "#6c8ebf", "#1b1f24"),
    "spark":   ("#ffe6cc", "#d79b00", "#1b1f24"),
    "python":  ("#d5e8d4", "#82b366", "#1b1f24"),
    "gpu":     ("#f8cecc", "#b85450", "#1b1f24"),
    "triton":  ("#e1d5e7", "#9673a6", "#1b1f24"),
    "storage": ("#fff2cc", "#d6b656", "#1b1f24"),
    "infra":   ("#e6f4f1", "#3f8f7f", "#1b1f24"),
    "note":    ("#fffbe6", "#d6b656", "#5c4a00"),
    "bad":     ("#fde2e2", "#c0392b", "#7a1a12"),
    "good":    ("#e3f5e1", "#2e8b3d", "#14501e"),
    "white":   ("#ffffff", "#9ca3af", "#1b1f24"),
}
FONT_DIR = "C:/Windows/Fonts/"


def _font(bold, size):
    try:
        return ImageFont.truetype(FONT_DIR + ("arialbd.ttf" if bold else "arial.ttf"), size)
    except Exception:
        return ImageFont.load_default()


class Diagram:
    def __init__(self, key, title, subtitle=""):
        self.key, self.title, self.subtitle = key, title, subtitle
        self.cells = []   # boxes in z-order
        self.edges = []

    # ---------------------------------------------------------------- declare
    def container(self, cid, x, y, w, h, label, style="white"):
        self.cells.append(dict(id=cid, x=x, y=y, w=w, h=h, label=label, style=style, kind="container"))
        return cid

    def box(self, cid, x, y, w, h, label, style="spark", shape="rect", font=12):
        self.cells.append(dict(id=cid, x=x, y=y, w=w, h=h, label=label, style=style, kind=shape, font=font))
        return cid

    def text(self, cid, x, y, w, h, label, font=12, color="#1b1f24", align="left"):
        self.cells.append(dict(id=cid, x=x, y=y, w=w, h=h, label=label, style="white", kind="text", font=font,
                               color=color, align=align))
        return cid

    def edge(self, src, dst, label="", dashed=False, color="#333333", exit=None, entry=None, points=(), both=False,
             width=1.5, label_seg=None):
        self.edges.append(dict(src=src, dst=dst, label=label, dashed=dashed, color=color, exit=exit, entry=entry,
                               points=list(points), both=both, width=width, label_seg=label_seg))

    # ---------------------------------------------------------------- geometry
    def _cell(self, cid):
        return next(c for c in self.cells if c["id"] == cid)

    def _anchors(self, e):
        a, b = self._cell(e["src"]), self._cell(e["dst"])
        if e["exit"] is None or e["entry"] is None:
            ax, ay = a["x"] + a["w"] / 2, a["y"] + a["h"] / 2
            bx, by = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
            tx, ty = (e["points"][0] if e["points"] else (bx, by))
            dx, dy = tx - ax, ty - ay
            x_overlap = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]) > 0
            y_overlap = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]) > 0
            if x_overlap and not y_overlap and not e["points"]:
                ex, en = ((0.5, 1), (0.5, 0)) if by > ay else ((0.5, 0), (0.5, 1))
            elif b["x"] >= a["x"] + a["w"] and not e["points"]:
                ex, en = (1, 0.5), (0, 0.5)
            elif b["x"] + b["w"] <= a["x"] and not e["points"]:
                ex, en = (0, 0.5), (1, 0.5)
            elif abs(dy) >= abs(dx):
                ex, en = ((0.5, 1), (0.5, 0)) if dy > 0 else ((0.5, 0), (0.5, 1))
            else:
                ex, en = ((1, 0.5), (0, 0.5)) if dx > 0 else ((0, 0.5), (1, 0.5))
            e["exit"] = e["exit"] or ex
            e["entry"] = e["entry"] or en
        p0 = (a["x"] + a["w"] * e["exit"][0], a["y"] + a["h"] * e["exit"][1])
        p1 = (b["x"] + b["w"] * e["entry"][0], b["y"] + b["h"] * e["entry"][1])
        return [p0] + [tuple(p) for p in e["points"]] + [p1]

    def bounds(self):
        xs = [c["x"] for c in self.cells] + [c["x"] + c["w"] for c in self.cells]
        ys = [c["y"] for c in self.cells] + [c["y"] + c["h"] for c in self.cells]
        return min(xs), min(ys), max(xs), max(ys)

    # ---------------------------------------------------------------- draw.io
    def _html(self, label):
        out = []
        for line in label.split("\n"):
            if line.startswith("*"):
                out.append(f"<b>{html.escape(line[1:])}</b>")
            else:
                out.append(html.escape(line))
        return "<br>".join(out)

    def to_drawio_page(self, page_id):
        x0, y0, x1, y1 = self.bounds()
        cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
        cells.append(f'<mxCell id="{self.key}_title" value="{escape(self._html("*" + self.title + (chr(10) + self.subtitle if self.subtitle else "")), {chr(34): "&quot;"})}" '
                     f'style="text;html=1;align=left;verticalAlign=top;fontSize=16;whiteSpace=wrap;" vertex="1" parent="1">'
                     f'<mxGeometry x="{x0}" y="{y0 - 60}" width="{max(600, x1 - x0)}" height="50" as="geometry"/></mxCell>')
        for c in self.cells:
            fill, stroke, fontc = STYLES[c["style"]]
            if c["kind"] == "container":
                st = (f"rounded=1;arcSize=3;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};dashed=1;"
                      f"verticalAlign=top;align=left;spacingLeft=8;spacingTop=2;fontSize=13;fontColor={fontc};")
            elif c["kind"] == "cyl":
                st = (f"shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=8;"
                      f"fillColor={fill};strokeColor={stroke};fontSize={c['font']};fontColor={fontc};")
            elif c["kind"] == "text":
                st = f"text;html=1;whiteSpace=wrap;align={c['align']};verticalAlign=top;fontSize={c['font']};fontColor={c['color']};"
            else:
                st = (f"rounded=1;arcSize=10;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
                      f"fontSize={c['font']};fontColor={fontc};" +
                      ("dashed=1;align=left;verticalAlign=top;spacingLeft=6;spacingTop=4;" if c["style"] == "note" else ""))
            val = escape(self._html(c["label"]), {'"': "&quot;"})
            cells.append(f'<mxCell id="{self.key}_{c["id"]}" value="{val}" style="{st}" vertex="1" parent="1">'
                         f'<mxGeometry x="{c["x"]}" y="{c["y"]}" width="{c["w"]}" height="{c["h"]}" as="geometry"/></mxCell>')
        for i, e in enumerate(self.edges):
            pts = self._anchors(e)
            st = (f"endArrow=block;endFill=1;html=1;rounded=0;strokeColor={e['color']};strokeWidth={e['width']};fontSize=11;"
                  f"exitX={e['exit'][0]};exitY={e['exit'][1]};exitDx=0;exitDy=0;"
                  f"entryX={e['entry'][0]};entryY={e['entry'][1]};entryDx=0;entryDy=0;labelBackgroundColor=#ffffff;")
            if e["dashed"]:
                st += "dashed=1;"
            if e["both"]:
                st += "startArrow=block;startFill=1;"
            wp = "".join(f'<mxPoint x="{p[0]}" y="{p[1]}"/>' for p in e["points"])
            wp = f'<Array as="points">{wp}</Array>' if wp else ""
            val = escape(self._html(e["label"]), {'"': "&quot;"})
            cells.append(f'<mxCell id="{self.key}_e{i}" value="{val}" style="{st}" edge="1" parent="1" '
                         f'source="{self.key}_{e["src"]}" target="{self.key}_{e["dst"]}">'
                         f'<mxGeometry relative="1" as="geometry">{wp}</mxGeometry></mxCell>')
        return (f'<diagram id="{page_id}" name="{escape(self.title[:60])}"><mxGraphModel dx="1400" dy="900" grid="1" '
                f'gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
                f'pageWidth="{int(x1 + 80)}" pageHeight="{int(y1 + 80)}" math="0" shadow="0"><root>'
                + "".join(cells) + "</root></mxGraphModel></diagram>")

    # ---------------------------------------------------------------- PNG
    def render_png(self, path, scale=2):
        x0, y0, x1, y1 = self.bounds()
        pad = 24
        top = 64 if self.subtitle else 44
        W, H = int((x1 - x0 + 2 * pad) * scale), int((y1 - y0 + 2 * pad + top) * scale)
        img = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(img)
        ox, oy = (pad - x0) * scale, (pad + top - y0) * scale
        S = lambda x, y: (x * scale + ox, y * scale + oy)
        d.text((pad * scale, 10 * scale), self.title, fill="#1b1f24", font=_font(True, 18 * scale))
        if self.subtitle:
            d.text((pad * scale, 36 * scale), self.subtitle, fill="#57606a", font=_font(False, 12 * scale))
        for c in self.cells:
            fill, stroke, fontc = STYLES[c["style"]]
            p0, p1 = S(c["x"], c["y"]), S(c["x"] + c["w"], c["y"] + c["h"])
            if c["kind"] == "container":
                d.rounded_rectangle([p0, p1], radius=6 * scale, fill=fill, outline=stroke, width=int(1.2 * scale))
                self._dash_rect(d, p0, p1, stroke, scale)
                d.text((p0[0] + 8 * scale, p0[1] + 5 * scale), c["label"].lstrip("*"), fill=fontc, font=_font(True, 13 * scale))
                continue
            if c["kind"] == "text":
                self._text_block(d, c, S, scale, align=c["align"], color=c["color"], valign="top")
                continue
            if c["kind"] == "cyl":
                e = 8 * scale
                d.rectangle([p0[0], p0[1] + e / 2, p1[0], p1[1] - e / 2], fill=fill)
                d.ellipse([p0[0], p1[1] - e, p1[0], p1[1]], fill=fill, outline=stroke, width=int(1.2 * scale))
                d.rectangle([p0[0] + 1, p0[1] + e / 2, p1[0] - 1, p1[1] - e / 2], fill=fill)
                d.line([p0[0], p0[1] + e / 2, p0[0], p1[1] - e / 2], fill=stroke, width=int(1.2 * scale))
                d.line([p1[0], p0[1] + e / 2, p1[0], p1[1] - e / 2], fill=stroke, width=int(1.2 * scale))
                d.ellipse([p0[0], p0[1], p1[0], p0[1] + e], fill=fill, outline=stroke, width=int(1.2 * scale))
            else:
                d.rounded_rectangle([p0, p1], radius=min(8 * scale, (p1[1] - p0[1]) / 4), fill=fill, outline=stroke,
                                    width=int(1.3 * scale))
                if c["style"] == "note":
                    self._dash_rect(d, p0, p1, stroke, scale)
            if c["style"] == "note":
                self._text_block(d, c, S, scale, align="left", color=fontc, valign="top")
            else:
                self._text_block(d, c, S, scale, color=fontc)
        for e in self.edges:
            pts = [S(*p) for p in self._anchors(e)]
            w = int(e["width"] * scale)
            for a, b in zip(pts, pts[1:]):
                if e["dashed"]:
                    self._dash_line(d, a, b, e["color"], w, scale)
                else:
                    d.line([a, b], fill=e["color"], width=w)
            self._arrow(d, pts[-2], pts[-1], e["color"], scale)
            if e["both"]:
                self._arrow(d, pts[1], pts[0], e["color"], scale)
            if e["label"]:
                segs = list(zip(pts, pts[1:]))
                seg = segs[e["label_seg"]] if e.get("label_seg") is not None else max(segs, key=lambda s: math.dist(*s))
                mx, my = (seg[0][0] + seg[1][0]) / 2, (seg[0][1] + seg[1][1]) / 2
                f = _font(False, 11 * scale)
                lines = e["label"].split("\n")
                tw = max(d.textlength(l.lstrip("*"), font=f) for l in lines)
                th = len(lines) * 13 * scale
                if abs(seg[0][1] - seg[1][1]) < 1 and tw > math.dist(*seg) - 30 * scale:
                    my -= th / 2 + 4 * scale  # label wider than a horizontal arrow: sit above it
                d.rectangle([mx - tw / 2 - 3 * scale, my - th / 2 - 1 * scale, mx + tw / 2 + 3 * scale, my + th / 2 + 1 * scale],
                            fill="white")
                for i, l in enumerate(lines):
                    ff = _font(l.startswith("*"), 11 * scale)
                    d.text((mx - d.textlength(l.lstrip("*"), font=ff) / 2, my - th / 2 + i * 13 * scale), l.lstrip("*"),
                           fill="#333333", font=ff)
        img.save(path)
        return path

    # ---------------------------------------------------------------- helpers
    def _wrap(self, d, text, font, width):
        out = []
        for para in text.split("\n"):
            bold = para.startswith("*")
            words, line = para.lstrip("*").split(" "), ""
            for w in words:
                t = (line + " " + w).strip()
                if d.textlength(t, font=font[bold]) <= width or not line:
                    line = t
                else:
                    out.append((bold, line))
                    line = w
            out.append((bold, line))
        return out

    def _text_block(self, d, c, S, scale, align="center", color="#1b1f24", valign="middle"):
        size = c.get("font", 12) * scale
        fonts = {False: _font(False, size), True: _font(True, size)}
        p0, p1 = S(c["x"], c["y"]), S(c["x"] + c["w"], c["y"] + c["h"])
        lines = self._wrap(d, c["label"], fonts, (p1[0] - p0[0]) - 10 * scale)
        lh = size * 1.22
        total = lh * len(lines)
        y = p0[1] + (4 * scale if valign == "top" else ((p1[1] - p0[1]) - total) / 2)
        for bold, l in lines:
            f = fonts[bold]
            tw = d.textlength(l, font=f)
            x = p0[0] + 5 * scale if align == "left" else (p0[0] + p1[0] - tw) / 2
            d.text((x, y), l, fill=color, font=f)
            y += lh

    def _arrow(self, d, a, b, color, scale):
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        L, Wd = 10 * scale, 4.5 * scale
        p1 = (b[0] - L * math.cos(ang) + Wd * math.sin(ang), b[1] - L * math.sin(ang) - Wd * math.cos(ang))
        p2 = (b[0] - L * math.cos(ang) - Wd * math.sin(ang), b[1] - L * math.sin(ang) + Wd * math.cos(ang))
        d.polygon([b, p1, p2], fill=color)

    def _dash_line(self, d, a, b, color, w, scale):
        L = math.dist(a, b)
        n = max(1, int(L / (8 * scale)))
        for i in range(0, n, 2):
            t0, t1 = i / n, min(1, (i + 1) / n)
            d.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                    (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)], fill=color, width=w)

    def _dash_rect(self, d, p0, p1, color, scale):
        # overlay white gaps on the border to fake a dashed outline
        step = 10 * scale
        for x in range(int(p0[0] + step), int(p1[0] - step), int(step)):
            if (x // step) % 2:
                d.line([x, p0[1], x + step / 2, p0[1]], fill="white", width=int(1.4 * scale))
                d.line([x, p1[1], x + step / 2, p1[1]], fill="white", width=int(1.4 * scale))
        for y in range(int(p0[1] + step), int(p1[1] - step), int(step)):
            if (y // step) % 2:
                d.line([p0[0], y, p0[0], y + step / 2], fill="white", width=int(1.4 * scale))
                d.line([p1[0], y, p1[0], y + step / 2], fill="white", width=int(1.4 * scale))


def write_drawio(diagrams, path):
    pages = "".join(dg.to_drawio_page(f"page{i}") for i, dg in enumerate(diagrams))
    xml = f'<mxfile host="app.diagrams.net" agent="build_diagrams.py" version="24.0.0" type="device">{pages}</mxfile>'
    open(path, "w", encoding="utf-8").write(xml)
    return path
