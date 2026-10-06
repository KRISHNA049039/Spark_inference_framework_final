"""
charts.py - small vector charts (reportlab graphics) for the NER internals PDF:
timelines of processes / tasks and line charts of GPU or memory samples.
"""
from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm

INK, MUTED, GRID = colors.HexColor("#1b1f24"), colors.HexColor("#57606a"), colors.HexColor("#d0d7de")
C = {"driver": colors.HexColor("#6c8ebf"), "spark": colors.HexColor("#d79b00"), "python": colors.HexColor("#82b366"),
     "gpu": colors.HexColor("#b85450"), "kitchen": colors.HexColor("#9673a6"), "io": colors.HexColor("#d6b656"),
     "wait": colors.HexColor("#c9d1d9"), "boot": colors.HexColor("#a5d6a7"), "load": colors.HexColor("#e57373")}


def _step(span):
    for s in (0.5, 1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600):
        if span / s <= 10:
            return s
    return 1200


def timeline(lanes, t0, t1, width=174 * mm, lane_h=13, label_w=118, font="Helvetica", unit="s"):
    """lanes: [(label, [(start, end, color, text), ...])], times in seconds relative to anything (t0..t1)."""
    gap = 5
    h = len(lanes) * (lane_h + gap) + 24
    d = Drawing(width, h)
    x0, W = label_w, width - label_w - 4
    span = max(t1 - t0, 1e-6)

    def sx(t):
        return x0 + (min(max(t, t0), t1) - t0) / span * W

    step = _step(span)
    t = 0.0
    while t <= span + 1e-9:
        x = sx(t0 + t)
        d.add(Line(x, 12, x, h - 4, strokeColor=GRID, strokeWidth=0.3))
        d.add(String(x, 3, f"{t:g}{unit}", fontName=font, fontSize=6, fillColor=MUTED, textAnchor="middle"))
        t += step
    for i, (label, bars) in enumerate(lanes):
        y = h - 6 - (i + 1) * (lane_h + gap) + gap
        d.add(String(2, y + lane_h / 2 - 2.5, label, fontName=font, fontSize=6.8, fillColor=INK))
        for s, e, col, txt in bars:
            xa, xb = sx(s), sx(e)
            w = max(xb - xa, 1.0)
            d.add(Rect(xa, y, w, lane_h, fillColor=col, strokeColor=None))
            if txt:
                tw = len(txt) * 3.3
                if tw < w - 2:
                    d.add(String(xa + w / 2, y + lane_h / 2 - 2.3, txt, fontName=font, fontSize=6, fillColor=INK, textAnchor="middle"))
                else:
                    d.add(String(min(xa + w + 2, x0 + W - tw), y + lane_h / 2 - 2.3, txt, fontName=font, fontSize=6, fillColor=INK))
    return d


def linechart(series, t0, t1, ymax, width=174 * mm, height=40 * mm, label_w=118, font="Helvetica", ylabel="", yfmt="{:g}"):
    """series: [(name, color, [(t, v), ...])]"""
    d = Drawing(width, height)
    x0, W, y0, H = label_w, width - label_w - 4, 14, height - 22
    span = max(t1 - t0, 1e-6)
    for k in range(5):
        y = y0 + H * k / 4
        d.add(Line(x0, y, x0 + W, y, strokeColor=GRID, strokeWidth=0.3))
        d.add(String(x0 - 3, y - 2, yfmt.format(ymax * k / 4), fontName=font, fontSize=6, fillColor=MUTED, textAnchor="end"))
    step = _step(span)
    t = 0.0
    while t <= span + 1e-9:
        x = x0 + t / span * W
        d.add(String(x, 3, f"{t:g}s", fontName=font, fontSize=6, fillColor=MUTED, textAnchor="middle"))
        t += step
    d.add(String(2, y0 + H / 2, ylabel, fontName=font, fontSize=6.8, fillColor=INK))
    for i, (name, col, pts) in enumerate(series):
        pp = []
        for t, v in pts:
            if t0 <= t <= t1:
                pp += [x0 + (t - t0) / span * W, y0 + min(v, ymax) / ymax * H]
        if len(pp) >= 4:
            d.add(PolyLine(pp, strokeColor=col, strokeWidth=0.9))
        d.add(Rect(2, y0 + H / 2 - 12 - i * 9, 6, 4, fillColor=col, strokeColor=None))
        d.add(String(10, y0 + H / 2 - 12 - i * 9, name, fontName=font, fontSize=6, fillColor=INK))
    return d
