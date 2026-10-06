"""
modes_charts.py - bar charts for the execution-modes document, from
modes_summary.json (benchmark/analyze_modes_stats.py).

  python benchmark/modes_charts.py results/modes_20260926/aws_2node
Writes <dir>/charts/throughput_<model>.png, tasktime_<model>.png, loads.png
"""
import json
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("modes_charts.py needs Pillow to draw PNGs: pip install pillow")

ROOT = sys.argv[1] if len(sys.argv) > 1 else "results/modes_20260926/aws_2node"
FAMILY = {"rdd": "#d79b00", "udf": "#82b366", "native": "#6c8ebf", "triton": "#9673a6", "platform10": "#b85450"}
F = lambda b, s: ImageFont.truetype("C:/Windows/Fonts/" + ("arialbd.ttf" if b else "arial.ttf"), s)


def fam(mode):
    return next((v for k, v in FAMILY.items() if mode.startswith(k)), "#666666")


def hbar(rows, title, unit, path, fmt="{:,.0f}", note=""):
    """rows: [(label, value, color)]"""
    S = 2
    W, left, rh, top = 1100 * S, 230 * S, 34 * S, 70 * S
    H = top + rh * len(rows) + 50 * S
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((20 * S, 16 * S), title, fill="#1b1f24", font=F(True, 17 * S))
    if note:
        d.text((20 * S, 42 * S), note, fill="#57606a", font=F(False, 12 * S))
    vmax = max([v for _, v, _ in rows if v] + [1])
    span = W - left - 150 * S
    for i, (lab, v, col) in enumerate(rows):
        y = top + i * rh
        d.text((20 * S, y + 8 * S), lab, fill="#1b1f24", font=F(False, 13 * S))
        if v is None:
            d.text((left, y + 8 * S), "failed / not run", fill="#c0392b", font=F(False, 12 * S))
            continue
        w = max(2, span * v / vmax)
        d.rounded_rectangle([left, y + 5 * S, left + w, y + rh - 5 * S], radius=3 * S, fill=col)
        d.text((left + w + 8 * S, y + 8 * S), fmt.format(v) + unit, fill="#1b1f24", font=F(True, 12 * S))
    x = 20 * S
    for k, col in FAMILY.items():
        d.rectangle([x, H - 30 * S, x + 14 * S, H - 16 * S], fill=col)
        d.text((x + 20 * S, H - 32 * S), k, fill="#1b1f24", font=F(False, 12 * S))
        x += 150 * S
    img.save(path)


def main():
    summ = json.load(open(os.path.join(ROOT, "modes_summary.json")))
    out = os.path.join(ROOT, "charts")
    os.makedirs(out, exist_ok=True)
    for model in sorted({s["model"] for s in summ if s.get("model")}):
        rows = [(s["mode"], s.get("throughput") if not s.get("error") else None, fam(s["mode"]))
                for s in summ if s["model"] == model]
        hbar(rows, f"Throughput by execution mode - {model}", " /s", os.path.join(out, f"throughput_{model}.png"),
             note="samples per second, end-to-end wall time of the Spark job (higher is better)")
        rows = []
        for s in summ:
            if s["model"] != model:
                continue
            infer = [st for st in s["stages"] if "UDF" in st.get("kind", "") or "map (Python)" in st.get("kind", "")]
            med = infer[-1]["task_ms_median"] / 1000 if infer and infer[-1].get("task_ms_median") else None
            rows.append((s["mode"], med, fam(s["mode"])))
        hbar(rows, f"Median inference-task duration - {model}", " s", os.path.join(out, f"tasktime_{model}.png"),
             fmt="{:,.2f}", note="median over the tasks of the stage that runs the model (includes model load when done per task)")
    rows = [(f"{s['model'][:10]} {s['mode']}", len(s.get("model_loads", [])), fam(s["mode"])) for s in summ
            if s["mode"] and not s["mode"].startswith("udf")]
    hbar(rows, "Model loads per application", "", os.path.join(out, "loads.png"),
         note="RDD: one per task; native predict_batch_udf / Triton client: one per Python worker (pandas UDF not instrumented)")
    print("charts ->", out)


if __name__ == "__main__":
    main()
