#!/usr/bin/env bash
# Install the ner_translate dependencies at container start from a dependency
# image mounted at /deps, so the Spark cluster can run on the plain
# multi-model-inference image (deploy/docker-compose.ner_deps.yml).
#
# Works with any layout of the dependency image:
#   A. .whl files anywhere in it        -> installed from there
#      (or exactly from $NER_WHEELS_DIR when that is set)
#   B. no .whl files, but the packages already pip-installed in it (e.g. a
#      python image) -> wheels are rebuilt offline from those installed
#      packages (their RECORD + WHEEL metadata), skipping torch / CUDA so the
#      base image's torch 2.6.0+cu126 is never replaced, then installed
# Pinned by /deps/requirements.txt, else the repo's requirements file.
# OCR .debs from /deps/debs, else /deps-debs (the repo's debs/ner_translate).
#
# Offline only (pip --no-index): a missing or incompatible package (wrong
# Python version, wrong pinned version) stops the container with pip's message
# instead of installing something untested. Skips everything when the packages
# are already present (a restarted container keeps them).
set -euo pipefail

DEPS=${NER_DEPS_DIR:-/deps}
REQ=$DEPS/requirements.txt
[ -f "$REQ" ] || REQ=/app/models/pipelines/ner_translate/requirements.txt
DEBS=$DEPS/debs
[ -d "$DEBS" ] || DEBS=/deps-debs
REBUILT=/tmp/ner_wheels_rebuilt
log() { echo "[install_ner_deps] $*"; }

if python -c "import gliner, transformers, pytesseract" 2>/dev/null && command -v tesseract >/dev/null; then
    log "already installed in this container - skipping"
    exit 0
fi
if [ ! -d "$DEPS" ]; then
    log "ERROR: nothing mounted at $DEPS - is the dependency image mounted?" >&2
    exit 1
fi

# ---------------------------------------------------------------- OCR packages
if ! command -v tesseract >/dev/null; then
    if ls "$DEBS"/*.deb >/dev/null 2>&1; then
        log "OCR packages from $DEBS"
        # first pass unpacks everything, second configures what waited on a dependency
        dpkg -i "$DEBS"/*.deb >/dev/null 2>&1 || true
        dpkg -i "$DEBS"/*.deb >/dev/null
    else
        log "WARNING: no .deb packages found - OCR of images and scanned PDFs will not work"
    fi
fi

# ---------------------------------------------------------------- find the wheels
WHEEL_DIRS=()
if [ -n "${NER_WHEELS_DIR:-}" ]; then
    [ -d "$NER_WHEELS_DIR" ] || { log "ERROR: NER_WHEELS_DIR=$NER_WHEELS_DIR does not exist" >&2; exit 1; }
    WHEEL_DIRS=("$NER_WHEELS_DIR")
else
    # folders holding .whl files; Python's own bundled installers (ensurepip) do not count
    mapfile -t WHEEL_DIRS < <(find "$DEPS" -xdev -name '*.whl' -not -path '*/ensurepip/*' -printf '%h\n' 2>/dev/null | sort -u)
    # a wheel folder only counts as the NER bundle if it actually holds gliner
    HAS_GLINER=no
    for d in "${WHEEL_DIRS[@]}"; do ls "$d"/gliner-*.whl >/dev/null 2>&1 && HAS_GLINER=yes; done
    [ "$HAS_GLINER" = yes ] || WHEEL_DIRS=()
fi

if [ ${#WHEEL_DIRS[@]} -eq 0 ]; then
    SITE=$(find "$DEPS" -xdev -type d -iname 'gliner-*.dist-info' -printf '%h\n' 2>/dev/null | head -1)
    if [ -z "$SITE" ]; then
        log "ERROR: no .whl files and no installed gliner package found in the dependency image at $DEPS" >&2
        exit 1
    fi
    log "no .whl files; rebuilding wheels from the packages installed in $SITE"
    rm -rf "$REBUILT"
    python - "$SITE" "$REBUILT" <<'PY'
import base64, csv, hashlib, os, re, sys, zipfile

src, out = sys.argv[1], sys.argv[2]
# provided by the base image - never taken from the dependency image
SKIP = re.compile(r"^(torch|torchvision|torchaudio|triton|nvidia[-_.].*)$", re.I)
os.makedirs(out, exist_ok=True)
made, skipped = 0, []
for entry in sorted(os.listdir(src)):
    if not entry.endswith(".dist-info"):
        continue
    di = os.path.join(src, entry)
    meta = {}
    try:
        with open(os.path.join(di, "METADATA"), encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    break
                k, _, v = line.partition(":")
                meta.setdefault(k.strip(), v.strip())
    except OSError:
        skipped.append(entry); continue
    name, ver = meta.get("Name"), meta.get("Version")
    rec = os.path.join(di, "RECORD")
    if not name or not ver or SKIP.match(name) or not os.path.isfile(rec):
        skipped.append(name or entry); continue
    tags = []
    if os.path.isfile(os.path.join(di, "WHEEL")):
        tags = [l.split(":", 1)[1].strip() for l in open(os.path.join(di, "WHEEL")) if l.startswith("Tag:")]
    tags = tags or ["py3-none-any"]
    tag = "-".join(".".join(sorted({t.split("-")[i] for t in tags})) for i in range(3))
    whl = os.path.join(out, f"{re.sub(r'[-_.]+', '_', name)}-{ver.replace('-', '_')}-{tag}.whl")
    rows = []
    with zipfile.ZipFile(whl, "w", zipfile.ZIP_DEFLATED) as z:
        for row in csv.reader(open(rec, encoding="utf-8")):
            if not row:
                continue
            p = row[0]
            # scripts outside site-packages are regenerated by pip; bytecode is rebuilt
            if p.startswith(("..", "/")) or p.endswith(".pyc") or p == f"{entry}/RECORD":
                continue
            full = os.path.join(src, p)
            if not os.path.isfile(full):
                continue
            data = open(full, "rb").read()
            z.writestr(p, data)
            h = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            rows.append(f"{p},sha256={h},{len(data)}")
        rows.append(f"{entry}/RECORD,,")
        z.writestr(f"{entry}/RECORD", "\n".join(rows) + "\n")
    made += 1
print(f"[install_ner_deps] rebuilt {made} wheels; not taken: {', '.join(sorted(skipped)) or 'none'}")
PY
    WHEEL_DIRS=("$REBUILT")
fi

# ---------------------------------------------------------------- install
FIND_LINKS=()
for d in "${WHEEL_DIRS[@]}"; do FIND_LINKS+=("--find-links=$d"); done
log "Python packages from ${WHEEL_DIRS[*]} (pinned by $REQ)"
PIP_ROOT_USER_ACTION=ignore pip install --no-cache-dir --no-index "${FIND_LINKS[@]}" -r "$REQ" -q
python -c "import torch, transformers, gliner; print('[install_ner_deps] OK torch', torch.__version__, '| transformers', transformers.__version__, '| gliner', gliner.__version__)"
