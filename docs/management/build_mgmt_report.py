"""
build_mgmt_report.py - management report (Word) for the Spark inference platform:
architecture first, then timeline, challenges, open gaps, results with charts,
and recommendations.

  python docs/management/build_mgmt_diagrams.py   # architecture (draw.io + PNG)
  python docs/management/build_mgmt_report.py     # charts + .docx

Figures come from docs/ (CHALLENGES_AND_LESSONS, WINDOWS_LAN_NETWORKING_FIX,
SESSION_SUMMARY_*, TEST_RESULTS_AND_TRADEOFFS, LEADERSHIP_BENCHMARK_DASHBOARD,
EXECUTION_MODE_SELECTOR_*, ner_internals) and results/ (campaign_20260926,
ner_translate_20260930_174126.json, airgap_sim_*).
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from docx import Document  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PNG = os.path.join(HERE, "png")
OUT = os.path.join(HERE, "Spark_Inference_Platform_Management_Report_20260930.docx")
os.makedirs(PNG, exist_ok=True)

ACCENT, GREY, DARK, MUTED = "#2F6FB5", "#B8BEC6", "#1B1F24", "#5B636E"
GOOD, BAD = "#4E9A5B", "#C0504D"
plt.rcParams.update({"font.family": "Arial", "font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": "#9AA1AA"})


# ------------------------------------------------------------------ charts
def _finish(fig, ax, title, subtitle, name):
    h = fig.get_figheight()
    fig.text(0.01, 1 - 0.12 / h, title, ha="left", va="top", fontsize=13, fontweight="bold", color=DARK)
    fig.text(0.01, 1 - 0.42 / h, subtitle, ha="left", va="top", fontsize=9.5, color=MUTED)
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.68 / h))
    path = os.path.join(PNG, name)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def chart_challenges():
    rows = [("Spark configuration", 15), ("Docker images", 15), ("Windows networking", 13), ("AWS cloud setup", 10),
            ("GPU support", 9), ("Python libraries", 7), ("WSL2 stability", 6), ("Offline delivery", 5),
            ("NER pipeline", 4), ("File transfer and admin", 4)]
    total, top3 = sum(v for _, v in rows), sum(v for _, v in rows[:3])
    fig, ax = plt.subplots(figsize=(8, 4.2))
    names, vals = [r[0] for r in rows][::-1], [r[1] for r in rows][::-1]
    colors = [ACCENT if i >= len(rows) - 3 else GREY for i in range(len(rows))]
    ax.barh(names, vals, color=colors, height=0.65)
    for i, v in enumerate(vals):
        ax.text(v + 0.2, i, str(v), va="center", fontsize=9.5, color=DARK)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    return _finish(fig, ax, "Three areas caused nearly half of all problems",
                   f"{top3} of {total} recorded problems ({round(top3 / total * 100)}%) came from the top three areas",
                   "chart_challenges.png")


def chart_ner_gpu():
    fig, ax = plt.subplots(figsize=(7, 3))
    labels, vals = ["CPU", "GPU"], [45.36, 5.86]
    ax.barh(labels[::-1], vals[::-1], color=[ACCENT, GREY], height=0.55)
    for i, v in enumerate(vals[::-1]):
        ax.text(v + 0.6, i, f"{v:.1f} s", va="center", fontsize=10, color=DARK)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    return _finish(fig, ax, f"GPU runs the NER pipeline {45.36 / 5.86:.1f}x faster than CPU",
                   "Same 6 documents, identical output; NER model server, 21 Sep 2026",
                   "chart_ner_gpu.png")


def chart_translation_fix():
    fig, ax = plt.subplots(figsize=(7, 3.2))
    langs, before, after = ["Hindi", "Marathi"], [14, 24], [29, 39]
    y = range(len(langs))
    ax.barh([i + 0.2 for i in y], before, height=0.38, color=GREY, label="Before fix")
    ax.barh([i - 0.2 for i in y], after, height=0.38, color=ACCENT, label="After fix")
    for i in y:
        ax.text(before[i] + 0.4, i + 0.2, str(before[i]), va="center", fontsize=9.5, color=DARK)
        ax.text(after[i] + 0.4, i - 0.2, str(after[i]), va="center", fontsize=9.5, color=DARK)
    ax.set_yticks(list(y), langs)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    return _finish(fig, ax, "Translation fix found 68 entities instead of 38 in Hindi and Marathi",
                   "Unique entities per document; long text was being cut at NLLB's 400-token limit (fixed 27 Sep 2026)",
                   "chart_translation_fix.png")


def chart_time_split():
    fig, ax = plt.subplots(figsize=(7, 2.4))
    load, run = 203.2, 29.5
    ax.barh([0], [load], color=ACCENT, height=0.5)
    ax.barh([0], [run], left=[load], color=GREY, height=0.5)
    ax.text(load / 2, 0, f"Loading models  {load:.0f} s", ha="center", va="center", color="white", fontsize=10,
            fontweight="bold")
    ax.text(load + run + 3, 0, f"Processing 6 documents  {run:.0f} s", va="center", fontsize=10, color=DARK)
    ax.set_xlim(0, 330)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    return _finish(fig, ax, f"Model loading took {round(load / (load + run) * 100)}% of the job time",
                   "Local-folder model store, one PC, GTX 1650, Docker Desktop reading models from D: (30 Sep 2026)",
                   "chart_time_split.png")


def chart_device_modes():
    fig, ax = plt.subplots(figsize=(7, 3))
    modes, vals = ["CPU only", "GPU only", "Hybrid"], [922, 2083, 2002]
    colors = [GREY, ACCENT, GREY]
    ax.bar(modes, vals, color=colors, width=0.55)
    for i, v in enumerate(vals):
        ax.text(i, v + 40, f"{v:,}/s", ha="center", fontsize=10, color=DARK)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    return _finish(fig, ax, "GPU gives 2.3x the throughput of CPU across the 10 tensor models",
                   "Samples per second, 25,700 samples, AWS g4dn (NVIDIA T4); image and detection models gain most",
                   "chart_device_modes.png")


def chart_image_size():
    fig, ax = plt.subplots(figsize=(7, 2.6))
    labels, vals = ["After fixes", "Before"], [3.82, 11.9]
    ax.barh(labels, vals, color=[ACCENT, GREY], height=0.55)
    for i, v in enumerate(vals):
        ax.text(v + 0.15, i, f"{v} GB", va="center", fontsize=10, color=DARK)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    return _finish(fig, ax, "Image clean-up cut the NER delivery size by 68%",
                   "Combined size of the Spark-lean and model-server images (three packaging bugs fixed)",
                   "chart_image_size.png")


# ------------------------------------------------------------------ docx helpers
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2)
sec.top_margin = sec.bottom_margin = Cm(1.8)
st = doc.styles["Normal"]
st.font.name, st.font.size = "Calibri", Pt(10.5)
for lvl, size in ((1, 16), (2, 12.5)):
    h = doc.styles[f"Heading {lvl}"]
    h.font.size, h.font.color.rgb = Pt(size), RGBColor(0x1F, 0x4E, 0x8C)
CONTENT_W = Cm(17)


def shade(cell, fill):
    pr = cell._tc.get_or_add_tcPr()
    s = OxmlElement("w:shd")
    s.set(qn("w:val"), "clear")
    s.set(qn("w:color"), "auto")
    s.set(qn("w:fill"), fill)
    pr.append(s)


def para(text, bold_lead=None, size=None, space_after=6, italic=False, color=None):
    p = doc.add_paragraph()
    if bold_lead:
        r = p.add_run(bold_lead)
        r.bold = True
        if size:
            r.font.size = size
    r = p.add_run(text)
    r.italic = italic
    if size:
        r.font.size = size
    if color:
        r.font.color.rgb = color
    p.paragraph_format.space_after = Pt(space_after)
    return p


def bullet(text, bold_lead=None):
    p = doc.add_paragraph(style="List Bullet")
    if bold_lead:
        p.add_run(bold_lead).bold = True
    p.add_run(text)
    p.paragraph_format.space_after = Pt(2)
    return p


def numbered(n, text, bold_lead=None):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.7)
    p.paragraph_format.first_line_indent = Cm(-0.7)
    p.paragraph_format.space_after = Pt(4)
    p.add_run(f"{n}.\t").bold = True
    if bold_lead:
        p.add_run(bold_lead).bold = True
    p.add_run(text)
    return p


def table(rows, widths, font=9.5):
    t = doc.add_table(rows=0, cols=len(rows[0]))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for ci, val in enumerate(row):
            c = cells[ci]
            c.width = widths[ci]
            c.text = ""
            p = c.paragraphs[0]
            bold = ri == 0
            text = val
            if isinstance(val, tuple):
                text, bold = val[0], True
            r = p.add_run(text)
            r.font.size = Pt(font)
            r.bold = bold
            if ri == 0:
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                shade(c, "1F4E8C")
            elif ri % 2 == 0:
                shade(c, "F2F5F9")
    tr = t.rows[0]._tr.get_or_add_trPr()
    h = OxmlElement("w:tblHeader")
    h.set(qn("w:val"), "true")
    tr.append(h)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def figure(path, caption, width=CONTENT_W):
    doc.add_picture(path, width=width)
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph()
    r = p.add_run(caption)
    r.italic, r.font.size, r.font.color.rgb = True, Pt(9), RGBColor(0x5B, 0x63, 0x6E)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(10)


def page_break():
    doc.add_paragraph().add_run().add_break(__import__("docx").enum.text.WD_BREAK.PAGE)


# ------------------------------------------------------------------ content
charts = dict(challenges=chart_challenges(), gpu=chart_ner_gpu(), tfix=chart_translation_fix(),
              split=chart_time_split(), modes=chart_device_modes(), size=chart_image_size())

t = doc.add_heading(level=0)
r = t.add_run("Spark Inference Platform")
r.font.color.rgb = RGBColor(0x1F, 0x4E, 0x8C)
para("Architecture, challenges, results and recommendations", size=Pt(13), color=RGBColor(0x5B, 0x63, 0x6E),
     space_after=2)
para("Status as of 30 September 2026", size=Pt(10), color=RGBColor(0x5B, 0x63, 0x6E), space_after=14)

doc.add_heading("Summary", level=1)
para("The platform runs multilingual entity extraction (NER) and 10 tensor models on a Spark cluster, and is "
     "validated on one machine, on a real 2-machine GPU cluster, and in an air-gap rehearsal. Getting there took "
     "88 recorded problems across 10 areas; three gaps remain before it is safe to rebuild and ship.")
bullet(" all execution modes passed on the 2-machine cluster (25 Sep); the air-gap rehearsal passed with models "
       "from HDFS and from a local folder (27 and 30 Sep).", "Working:")
bullet(" GPU runs the NER pipeline 7.7x faster than CPU; a translation fix raised entities found in Hindi and "
       "Marathi from 38 to 68; delivery images shrank 68%.", "Results:")
bullet(" GPU fix not in the build files, images older than the code, and the Windows multi-PC setup is a lab "
       "workaround.", "Open gaps:")
bullet(" deliver the air-gapped NER cluster now with the local-folder model store; move production to Linux "
       "servers with HDFS.", "Recommendation:")

# ---- 1 architecture
page_break()
doc.add_heading("1. Architecture", level=1)
para("The driver on the master node lists the documents and sends only their file names to the workers. Each "
     "worker loads the models once per task and runs the whole pipeline: extract text, detect the language, "
     "translate to English, find entities. Where the models come from is one setting: HDFS in production, a "
     "local folder on a development PC or a single air-gapped workstation.")
figure(os.path.join(PNG, "mgmt_platform_architecture.png"), "Figure 1. Platform architecture (editable: "
       "docs/management/platform_architecture.drawio, page 1)")
table([["Layer", "Technology", "Role"],
       ["Orchestration", "Apache Spark 3.5.1 (standalone)", "Splits work into tasks, runs them on workers, retries failures"],
       ["Models", "GLiNER multi v2.1, NLLB-200 (600M), 10 tensor models", "Entity extraction, translation (200 languages), signal/image/detection inference"],
       ["Compute", "PyTorch 2.6 (CUDA 12.6), NVIDIA GPUs", "Runs the models; CPU fallback when no GPU"],
       ["Packaging", "Docker images, offline package bundles", "Same software on every node; installable without internet"],
       ["Model store", "HDFS or a local folder", "Models kept once, not inside the images"],
       ["Host", "Windows 11 + WSL2, or Linux", "Runs Docker; Linux recommended for production"]],
      [Cm(3), Cm(6), Cm(8)])
figure(os.path.join(PNG, "mgmt_deployment_options.png"), "Figure 2. Deployment options (editable: "
       "docs/management/platform_architecture.drawio, page 2)")

# ---- 2 timeline
doc.add_heading("2. How we got here", level=1)
para("The work ran in six stages over about ten weeks; each stage fixed the blockers found in the one before it.")
table([["When", "Stage", "Outcome"],
       ["27–30 Sep 2026", "Air-gap rehearsal: HDFS and local-folder model stores", "12 rehearsal tests passed; NER job validated with models from a local folder"],
       ["25 Sep 2026", "Full validation on the real 2-machine cluster", "All modes passed; GPU work confirmed on the worker machine"],
       ["21 Sep 2026", "Two Windows PCs joined into one LAN cluster", "Worked only after moving to Docker inside WSL2"],
       ["13–17 Sep 2026", "NER pipeline packaged for offline use", "Own image and offline bundles; GPU 7.7x faster than CPU"],
       ["20–24 Jul 2026", "Single-PC Windows lab cluster", "Ran on Docker Desktop; multi-PC attempts failed on networking"],
       ["17–18 Jul 2026", "First cluster on AWS", "Worked after 17 cloud, driver and Spark fixes"]],
      [Cm(3), Cm(6.5), Cm(7.5)])

# ---- 3 challenges
page_break()
doc.add_heading("3. Challenges", level=1)
para("Most problems were not in our code. They came from how Windows, Docker and Spark behave together, and they "
     "often failed without an error message. Windows-only issues (networking plus WSL2) total 19 when combined, the "
     "largest single root cause; Linux servers would not have them.")
figure(charts["challenges"], "Figure 3. Recorded problems by area (from the project's problem logs, Jul–Sep 2026)")
doc.add_heading("What went wrong, by area", level=2)
table([["Area", "What went wrong", "How we fixed it"],
       ["Windows networking", "Docker Desktop hides containers behind a private network, so the other PC could not reach them; Windows also silently switched the network to Public and re-blocked the firewall.", "Docker inside WSL2 (Linux on Windows), which can use the real network card; a check after every restart."],
       ["WSL2 stability", "Containers restarted every 20–30 s with empty logs: Windows was shutting the Linux VM down as idle.", "Disabled the idle shutdown; one session kept open permanently."],
       ["Spark configuration", "Jobs hung when requested memory or CPU did not fit a worker; workers could not find the code or the driver's address.", "Right-sized memory and cores; explicit code paths and host addresses."],
       ["GPU support", "The RTX 5060 was listed as supported but failed on real hardware; one GPU service silently ran on CPU.", "Found a PyTorch build that works (proven with a real calculation); added the missing GPU setting."],
       ["Docker images", "Images 3x larger than needed; some builds produced the wrong image or old code.", "Changed how files enter the build (11.9 GB to 3.8 GB); always build the named target."],
       ["Python libraries", "Installing one library silently downgraded PyTorch or changed libraries for every model.", "Pinned versions; the NER pipeline got its own isolated image."],
       ["NER pipeline", "Could not load offline; Hindi and Marathi translations dropped text.", "Shipped the missing model files; translate one sentence at a time."],
       ["Offline delivery", "Offline system packages clashed with the base image; the build contacted Docker Hub; HDFS needed extra ports.", "Bundles built from the exact base image; build works without Docker Hub; ports documented."],
       ["File transfer and admin", "Windows file sharing refused logins; firewall changes needed admin rights.", "Large files moved over plain HTTP on the LAN."],
       ["AWS cloud setup", "Old tools, missing permissions, no GPU quota or capacity, non-ASCII text rejected.", "Upgraded tools, switched region, spread across zones."]],
      [Cm(3.2), Cm(7.4), Cm(6.4)], font=9)
doc.add_heading("The five problems that cost the most time", level=2)
numbered(1, " Three settings changes failed; only Docker inside WSL2 worked. Linux servers do not have this limit.",
         "Docker Desktop cannot run a multi-PC cluster.")
numbered(2, " The real cause was Windows powering off the Linux VM underneath; it took three separate fixes.",
         "Containers seemed to crash with no error.")
numbered(3, " The installed PyTorch lacks code for RTX 50-series cards; proven by running a real calculation.",
         "The new GPU looked supported but was not.")
numbered(4, " A 1-second limit set for a quick name check leaked into Spark's own connection.",
         "A connection timeout that looked unrelated.")
numbered(5, " Spark gives no error when a job asks for more memory or CPU than a worker offers.",
         "Jobs that waited forever.")

# ---- 4 open gaps
doc.add_heading("4. Open gaps", level=1)
para("None of these affect today's results, but each will break the next rebuild or delivery if left open.")
table([["#", "Gap", "Risk if left open", "Next step"],
       ["1", "The GPU fix is not in the build files: images still install a PyTorch build without RTX 50-series support.", "Fresh builds fail on RTX 50-series GPUs. The Ada GPU of the air-gapped system is not affected (verified 30 Sep).", "Update PyTorch in the two image recipes, rebuild, rerun GPU tests."],
       ["2", "Shipped images are older than the code; current features were copied into running containers by hand.", "Recreating a container loses the patches; an air-gap delivery could ship old code.", "Rebuild all images from current code, check sizes, re-export the delivery bundle."],
       ["3", "The multi-PC Windows setup is a lab workaround (WSL settings, held-open session, firewall checks).", "Restarts or Windows updates can silently drop a worker; not supportable in production.", "Keep Windows for development; run production on Linux servers or Kubernetes."]],
      [Cm(0.8), Cm(5.4), Cm(5.4), Cm(5.4)], font=9)
para("Confirmed to work but not yet measured as faster: GPU sharing between processes (MPS), parallel GPU streams "
     "and Spark's GPU-aware scheduling. Treat speed claims for them as unproven until benchmarked.", italic=True,
     size=Pt(9.5))

# ---- 5 results
page_break()
doc.add_heading("5. Results", level=1)
para("Functional results are solid across all three environments; performance results show where the GPU pays off "
     "and where time is lost.")
doc.add_heading("Validation", level=2)
table([["Test", "Environment", "Result"],
       ["Execution modes (RDD, pandas UDF, distributed GPU, NER in-process)", "Real 2-machine GPU cluster, 25 Sep", "All passed; work confirmed on the GPU worker"],
       ["Benchmark campaign: 28 tests x 3 environments", "AWS g4dn, Windows, WSL2 Docker, 26 Sep", "80 passed, 3 partial, 1 failed (Windows memory limits only)"],
       ["Air-gap rehearsal: 12 tests (HDFS, local folder, model server, cluster)", "One PC, no internet dependencies, 27 Sep", "All 12 passed"],
       ["NER job, models from a local folder", "One PC, Docker Desktop, 30 Sep", "6 of 6 documents processed; Hindi and Marathi translated"],
       ["Offline build of the NER image from bundles", "Dev PC, 30 Sep", "Built from local packages only"]],
      [Cm(6.5), Cm(5), Cm(5.5)], font=9)
doc.add_heading("NER pipeline", level=2)
figure(charts["gpu"], "Figure 4. NER pipeline: CPU vs GPU run time")
figure(charts["tfix"], "Figure 5. Entities found before and after the translation fix")
figure(charts["split"], "Figure 6. Where the time goes in a NER job (30 Sep run)")
doc.add_heading("Tensor models and delivery", level=2)
figure(charts["modes"], "Figure 7. Throughput by device mode, 10 tensor models")
figure(charts["size"], "Figure 8. Delivery image size before and after clean-up")
table([["Finding", "Evidence"],
       ["Spark adds overhead for small, fast models", "On one AWS GPU, a single process with parallel GPU streams reached 58,842 samples/s against 4,494/s for the best Spark run: Spark pays off only when volume or fault tolerance needs several machines."],
       ["Best Spark settings", "6–8 partitions (matching the core count), batch size 256, 3 workers for a 5,000-signal workload."],
       ["Model loading is a fixed cost", "About 1.2 s per executor for the tensor models; 203 s for the NER models read over the Windows file bridge."]],
      [Cm(5), Cm(12)], font=9)

# ---- 6 recommendations
doc.add_heading("6. Recommendations", level=1)
table([["#", "Recommendation", "Why", "When"],
       ["1", "Deliver the air-gapped NER cluster on one workstation with the local-folder model store (runbook ready).", "Validated 30 Sep; no HDFS to operate; the Ada GPU needs no changes.", "Now"],
       ["2", "Rebuild all images from current code; remove the Docker Hub line from the NER build; add an image-size check.", "Closes gap 2 and makes offline builds repeatable.", "Now"],
       ["3", "Keep models on a fast local disk and load them once per worker, not per task.", "Model loading is 87% of a NER job today (Figure 6).", "Now"],
       ["4", "Put the RTX 50-series PyTorch fix into the image recipes.", "Closes gap 1 for newer GPUs; the air-gapped Ada system is unaffected.", "Next"],
       ["5", "Fix the known NER limitations: same-named files overwrite each other; an unused 1.2 GB file is stored and fetched.", "Correctness for real corpora; faster first load.", "Next"],
       ["6", "Benchmark MPS, parallel GPU streams and GPU-aware scheduling before relying on them.", "Currently confirmed only as working, not as faster.", "Next"],
       ["7", "Use Spark where volume or fault tolerance needs it; use a single GPU process for small batches.", "Single process was 13x faster for small tensor models (section 5).", "Guidance"],
       ["8", "Run production on Linux servers (or Kubernetes) with HDFS as the model store; keep Windows/WSL for development.", "Removes the 19 Windows-only failure modes and gap 3.", "Plan"]],
      [Cm(0.8), Cm(7), Cm(7), Cm(2.2)], font=9)

doc.add_heading("Sources", level=2)
para("Project documents in docs/: CHALLENGES_AND_LESSONS, WINDOWS_LAN_NETWORKING_FIX_20260921, "
     "SESSION_SUMMARY_AND_AIRGAPPED_UPDATE_GUIDE_20260921, EXECUTION_MODE_SELECTOR_AND_CLUSTER_VALIDATION_20260925, "
     "TEST_RESULTS_AND_TRADEOFFS, LEADERSHIP_BENCHMARK_DASHBOARD, SPARK_VS_SINGLE_GPU_ANALYSIS, CHANGELOG_2026*, "
     "ner_internals, AIRGAP_NER_LOCAL_FS_CHANGES_20260930. Measurements in results/: campaign_20260926, "
     "modes_20260926, airgap_sim_20260927_*, ner_translate_20260930_174126.json.", size=Pt(9),
     color=RGBColor(0x5B, 0x63, 0x6E))

# footer page numbers
fp = sec.footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = fp.add_run()
for tag, txt in (("begin", None), (None, "PAGE"), ("end", None)):
    el = OxmlElement("w:fldChar" if tag else "w:instrText")
    if tag:
        el.set(qn("w:fldCharType"), tag)
    else:
        el.set(qn("xml:space"), "preserve")
        el.text = txt
    run._r.append(el)

doc.core_properties.title = "Spark Inference Platform - Architecture, Challenges, Results and Recommendations"
doc.save(OUT)
print(OUT)
