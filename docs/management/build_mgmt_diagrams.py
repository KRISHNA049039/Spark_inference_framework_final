"""
build_mgmt_diagrams.py - architecture diagrams for the management report.

  python docs/management/build_mgmt_diagrams.py
Writes docs/management/platform_architecture.drawio (editable in draw.io /
app.diagrams.net, one page per diagram) and docs/management/png/<key>.png,
drawn from the same definitions with docs/diagrams/diagram_engine.py.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "diagrams"))
from diagram_engine import Diagram, write_drawio  # noqa: E402

D = []


def d_platform():
    g = Diagram("mgmt_platform_architecture", "1. Platform architecture: multilingual NER on a Spark cluster",
                "Spark sends file names, not documents; each worker loads the models once and runs the whole pipeline")
    # master node
    g.container("mn", 0, 0, 360, 330, "*Master node")
    g.box("drv", 20, 40, 320, 90, "*Driver (submit_pipeline_job.py)\nlists the documents, splits them\ninto partitions, collects the results", "driver", font=11)
    g.box("sm", 20, 160, 320, 60, "*Spark master :7077\nassigns tasks to workers", "spark", font=11)
    g.box("res", 20, 250, 320, 60, "*Results (JSON per job)\nlanguage, translation, entities", "storage", shape="cyl", font=11)
    # worker nodes
    g.container("wn", 420, 0, 560, 330, "*Worker nodes (GPU), one or more")
    g.box("ex", 440, 40, 520, 60, "*Spark executor: runs one task = a batch of file paths", "spark", font=11)
    g.box("p1", 440, 130, 120, 90, "*1 Extract text\nPDF, Office,\nimages (OCR)", "python", font=10)
    g.box("p2", 573, 130, 120, 90, "*2 Detect\nlanguage", "python", font=10)
    g.box("p3", 706, 130, 120, 90, "*3 Translate\nto English\n(NLLB-200)", "gpu", font=10)
    g.box("p4", 840, 130, 120, 90, "*4 Find\nentities\n(GLiNER)", "gpu", font=10)
    g.box("docs", 440, 250, 520, 60, "*Input documents: same folder path on every node\n200 languages; text, PDF, Word, Excel, PowerPoint, images", "storage", shape="cyl", font=10)
    # model store
    g.container("ms", 1040, 0, 300, 330, "*Model store (one setting)")
    g.box("hdfs", 1060, 40, 260, 90, "*HDFS (production)\nmodels kept once; each node\ndownloads and caches them", "storage", font=11)
    g.box("lfs", 1060, 150, 260, 90, "*Local folder (dev / air-gap)\nE:\\ner\\models, read in place\nno HDFS needed", "storage", font=11)
    g.box("mdl", 1060, 260, 260, 50, "*GLiNER + NLLB-200 + backbone\n~4.6 GB", "note", font=10)
    # infrastructure
    g.container("inf", 0, 370, 1340, 120, "*Runs on (each machine)")
    g.box("i1", 20, 410, 240, 60, "*Windows 11 host\nNVIDIA driver", "infra", font=11)
    g.box("i2", 300, 410, 240, 60, "*WSL2 (Linux VM)\nmirrored networking", "infra", font=11)
    g.box("i3", 580, 410, 330, 60, "*Docker\nDesktop (1 machine) or CE in Ubuntu (LAN)", "infra", font=11)
    g.box("i4", 950, 410, 370, 60, "*Images: multi-model-inference (Spark 3.5.1,\nPyTorch 2.6, Java 17) + ner-translate-worker", "infra", font=10)
    # flows
    g.edge("drv", "sm", "register job")
    g.edge("sm", "ex", "launch tasks", exit=(1, 0.5), entry=(0, 0.6), points=[(378, 190), (378, 76)])
    g.edge("drv", "ex", "file paths", exit=(1, 0.3), entry=(0, 0.3), color="#6c8ebf")
    g.edge("p1", "p2", "")
    g.edge("p2", "p3", "")
    g.edge("p3", "p4", "")
    g.edge("ex", "p1", "", exit=(0.115, 1), entry=(0.5, 0))
    g.edge("p1", "docs", "open files", dashed=True, exit=(0.5, 1), entry=(0.115, 0))
    g.edge("ex", "hdfs", "load models", exit=(1, 0.5), entry=(0, 0.5), color="#b85450")
    g.edge("ex", "lfs", "or", dashed=True, exit=(1, 0.8), entry=(0, 0.3), color="#b85450")
    g.edge("ex", "res", "results", exit=(0, 0.9), entry=(1, 0.5), points=[(402, 94), (402, 280)], color="#6c8ebf")
    g.edge("i1", "i2", "")
    g.edge("i2", "i3", "")
    g.edge("i3", "i4", "")
    D.append(g)


def d_deploy():
    g = Diagram("mgmt_deployment_options", "2. Deployment options: where the cluster runs",
                "Same images and code in all three; only the start method and the model store change")
    cols = [
        ("a", 0, "*A. One machine", "good",
         "*Docker Desktop\none compose file\n(docker-compose.airgap_sim.yml,\nprofile cluster)",
         "*Models: local folder (dev.env)\nMaster + 1 worker on one PC",
         "*Use for: development, testing,\nsingle air-gapped workstation\n\nStatus: validated 27 and 30 Sep 2026"),
        ("b", 450, "*B. LAN cluster (Windows)", "white",
         "*Docker CE inside WSL2 Ubuntu\nhost networking,\none container per machine",
         "*Models: same folder on every node\nor HDFS\nMaster PC + worker PCs",
         "*Use for: multi-machine lab tests\n\nFragile: WSL idle shutdowns,\nfirewall resets after restarts\nStatus: validated 21 and 25 Sep 2026"),
        ("c", 900, "*C. Production (recommended)", "good",
         "*Linux servers or Kubernetes\nnative host networking,\nno WSL layer",
         "*Models: HDFS (download once,\ncache per node)",
         "*Use for: production and\nlarge air-gapped deployments\n\nStatus: design ready,\nnot yet built"),
    ]
    for key, x, head, style, run, models, use in cols:
        g.container(f"{key}c", x, 0, 420, 400, head)
        g.box(f"{key}1", x + 20, 40, 380, 100, run, "infra", font=11)
        g.box(f"{key}2", x + 20, 160, 380, 80, models, "storage", font=11)
        g.box(f"{key}3", x + 20, 260, 380, 120, use, style, font=11)
        g.edge(f"{key}1", f"{key}2", "")
        g.edge(f"{key}2", f"{key}3", "")
    g.edge("ac", "bc", "scale out", exit=(1, 0.2), entry=(0, 0.2), color="#3f8f7f")
    g.edge("bc", "cc", "harden", exit=(1, 0.2), entry=(0, 0.2), color="#3f8f7f")
    D.append(g)


d_platform()
d_deploy()

if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "png"), exist_ok=True)
    for dg in D:
        dg.render_png(os.path.join(HERE, "png", f"{dg.key}.png"))
    print(write_drawio(D, os.path.join(HERE, "platform_architecture.drawio")))
