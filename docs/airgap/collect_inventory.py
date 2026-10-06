"""
collect_inventory.py - exact inventory of what has to cross the air gap.

Reads the truth from the built images themselves (not from requirement files):
OS, Python, Java, Spark, torch / CUDA / cuDNN, every pip package with its version,
tesseract languages, image IDs and digests; plus the model weights on disk with
SHA-256 checksums and the host's Docker / NVIDIA versions.

Writes docs/airgap/inventory.json and docs/airgap/AIRGAP_BILL_OF_MATERIALS.csv.

    python docs/airgap/collect_inventory.py [--weights <dir with gliner-multi, nllb-..., hf_cache>] [--no-hash]
"""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES = ["multi-model-inference:latest", "spark-lean:latest", "ner-translate-worker:latest", "ner-translate-server:latest",
          "apache/hadoop:3.4.1"]

# Printed inside each image; sections separated by markers, every command optional.
PROBE = r"""
echo '@@os'; . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"
echo '@@python'; (python3 --version || python --version) 2>&1
echo '@@java'; java -version 2>&1 | head -1
echo '@@spark'; cat /opt/spark/RELEASE 2>/dev/null | head -1
echo '@@hadoop'; (hadoop version 2>/dev/null | head -1) || true
echo '@@tesseract'; (tesseract --version 2>&1 | head -1) || true
echo '@@tesslangs'; (tesseract --list-langs 2>/dev/null | tail -n +2 | tr '\n' ' '; echo) || true
echo '@@dpkg'; (dpkg-query -W -f='${Package}=${Version}\n' 2>/dev/null | wc -l) || true
echo '@@torch'; (python3 -c "import torch;print(torch.__version__, torch.version.cuda, torch.backends.cudnn.version())" 2>/dev/null) || true
echo '@@pip'; (python3 -m pip list --format=json 2>/dev/null || python -m pip list --format=json 2>/dev/null) || echo '[]'
echo '@@end'
"""


def run(cmd, timeout=600):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout


def probe_image(image):
    code, out = run(["docker", "image", "inspect", image, "--format", "{{json .}}"])
    if code:
        return {"image": image, "present": False}
    meta = json.loads(out)
    info = {"image": image, "present": True, "id": meta["Id"], "digests": meta.get("RepoDigests") or [],
            "created": meta.get("Created", "")[:19], "size_bytes": meta.get("Size"), "arch": f"{meta.get('Os')}/{meta.get('Architecture')}"}
    code, out = run(["docker", "run", "--rm", "--entrypoint", "sh", image, "-c", PROBE])
    sections, cur = {}, None
    for line in out.splitlines():
        if line.startswith("@@"):
            cur = line[2:]
            sections[cur] = []
        elif cur:
            sections[cur].append(line)
    for key in ("os", "python", "java", "spark", "hadoop", "tesseract", "tesslangs", "dpkg", "torch"):
        info[key] = " ".join(x.strip() for x in sections.get(key, []) if x.strip())
    try:
        info["pip"] = {p["name"].lower(): p["version"] for p in json.loads(" ".join(sections.get("pip", ["[]"])))}
    except ValueError:
        info["pip"] = {}
    return info


def sha256(path, bufsize=8 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def weights(root, do_hash):
    out = []
    for folder in ("gliner-multi", "nllb-200-distilled-600M", "hf_cache"):
        base = os.path.join(root, folder)
        for dirpath, _, files in os.walk(base):
            for f in sorted(files):
                p = os.path.join(dirpath, f)
                rel = os.path.relpath(p, root).replace("\\", "/")
                try:
                    size = os.path.getsize(p)
                except OSError:  # HF cache snapshots/* are Linux symlinks to blobs/*; Windows cannot open them
                    out.append({"file": rel, "bytes": 0, "sha256": "", "symlink": True})
                    continue
                out.append({"file": rel, "bytes": size, "sha256": sha256(p) if do_hash else ""})
    return out


def host():
    h = {}
    for key, cmd in (("docker", ["docker", "version", "--format", "client {{.Client.Version}} / server {{.Server.Version}} ({{.Server.Os}})"]),
                     ("compose", ["docker", "compose", "version", "--short"]),
                     ("nvidia", ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])):
        try:
            h[key] = run(cmd, timeout=60)[1].strip()
        except (OSError, subprocess.TimeoutExpired):
            h[key] = ""
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=r"D:\pytorch-spark-inference-platform_20260921\models\weights")
    ap.add_argument("--no-hash", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    inv = {"collected": time.strftime("%Y-%m-%d %H:%M"), "host": host(), "images": {}}
    for image in IMAGES:
        print("probing", image, flush=True)
        inv["images"][image] = probe_image(image)
    print("hashing weights in", a.weights, flush=True)
    inv["weights_root"] = a.weights
    inv["weights"] = weights(a.weights, not a.no_hash) if os.path.isdir(a.weights) else []
    debs = os.path.join(os.path.dirname(os.path.dirname(HERE)), "debs", "ner_translate")
    inv["debs"] = sorted(os.listdir(debs)) if os.path.isdir(debs) else []
    with open(os.path.join(HERE, "inventory.json"), "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=1)

    # Bill of materials: one row per shipped component
    rows = [["category", "component", "version", "shipped in", "needed by"]]
    for image, i in inv["images"].items():
        if not i.get("present"):
            continue
        rows.append(["container image", image, i["id"][7:19], "docker save tar", image])
        for k in ("os", "python", "java", "spark", "hadoop", "tesseract"):
            if i.get(k):
                rows.append(["runtime", k, i[k], image, image])
        for name, ver in sorted(i["pip"].items()):
            rows.append(["python package", name, ver, image, image])
    for w in inv["weights"]:
        rows.append(["model weights", w["file"], w["sha256"][:16] or f"{w['bytes']} bytes", "HDFS /models/weights or master FS", "ner_translate"])
    for deb in inv["debs"]:
        name, ver = deb.split("_")[0], deb.split("_")[1].replace("%3a", ":")
        rows.append(["system package (.deb)", name, ver, "debs/ner_translate", "offline build of ner-translate-worker"])
    with open(os.path.join(HERE, "AIRGAP_BILL_OF_MATERIALS.csv"), "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    print(f"done in {time.time() - t0:.0f} s: {len(rows) - 1} BOM rows")


if __name__ == "__main__":
    sys.exit(main())
