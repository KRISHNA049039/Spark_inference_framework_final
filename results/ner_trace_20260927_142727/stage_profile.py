"""
Stage profiler for the ner_translate pipeline - runs inside the model-server image
(GPU, models in the node cache) and measures every step the kitchen / executor
performs: model bytes on disk -> CPU RAM -> GPU, per-document extraction and
language id, the real tensor shapes NLLB and GLiNER see, GPU memory, PCIe copy
rates. Uses the pipeline's own functions; only wraps them with timers.

    python stage_profile.py <out.json> <doc> [<doc> ...]
"""
import json
import os
import sys
import time

sys.path.insert(0, "/app")
from models.pipelines.ner_translate import pipeline  # noqa: E402  (imports pyarrow before torch)
from models.pipelines.ner_translate import mt_ner_all_formats as M  # noqa: E402
import torch  # noqa: E402

OUT, DOCS = sys.argv[1], sys.argv[2:]
R = {"docs": {}, "runs": []}
dev = "cuda" if torch.cuda.is_available() else "cpu"


def sync():
    if dev == "cuda":
        torch.cuda.synchronize()


def mem():
    return {"allocated_mb": round(torch.cuda.memory_allocated() / 2**20, 1),
            "reserved_mb": round(torch.cuda.memory_reserved() / 2**20, 1)} if dev == "cuda" else {}


def tensor_bytes(m):
    ps = list(m.parameters())
    bs = list(m.buffers())
    return {"params": sum(p.numel() for p in ps),
            "bytes": sum(p.numel() * p.element_size() for p in ps) + sum(b.numel() * b.element_size() for b in bs),
            "dtypes": sorted({str(p.dtype) for p in ps})}


def folder(path):
    files, total = [], 0
    for root, _, names in os.walk(path):
        for n in names:
            fp = os.path.join(root, n)
            sz = os.path.getsize(fp)
            total += sz
            if sz > 1_000_000:
                files.append([os.path.relpath(fp, path), sz])
    return {"path": path, "bytes": total, "big_files": sorted(files, key=lambda x: -x[1])}


def vm():
    """VM-wide memory / paging counters (the container shares the WSL2 / host kernel)."""
    out = {}
    try:
        for line in open("/proc/meminfo"):
            k, v = line.split(":")
            if k in ("MemAvailable", "Cached", "SwapFree"):
                out[k + "_mb"] = int(v.split()[0]) // 1024
        for line in open("/proc/vmstat"):
            k, v = line.split()
            if k in ("pswpin", "pswpout", "pgmajfault", "pgpgin"):
                out[k] = int(v)
    except OSError:
        pass
    return out


def vdelta(a, b):
    return {k: b[k] - a[k] for k in a if k in b and not k.endswith("_mb")} | {k: b[k] for k in b if k.endswith("_mb")}


def shapes(obj):
    if torch.is_tensor(obj):
        return [list(obj.shape), str(obj.dtype).replace("torch.", "")]
    if isinstance(obj, dict):
        return {k: shapes(v) for k, v in obj.items() if torch.is_tensor(v)}
    if isinstance(obj, (list, tuple)):
        return [shapes(v) for v in obj if torch.is_tensor(v)]
    return None


# ------------------------------------------------------------------ environment
R["env"] = {"torch": torch.__version__, "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
            "device": dev, "MODEL_STORE_URI": os.environ.get("MODEL_STORE_URI"), "cpu_count": os.cpu_count()}
if dev == "cuda":
    p = torch.cuda.get_device_properties(0)
    R["env"]["gpu"] = {"name": p.name, "sm_count": p.multi_processor_count, "cc": f"{p.major}.{p.minor}",
                       "total_mb": round(p.total_memory / 2**20)}

# ------------------------------------------------------------------ PCIe copy rate
if dev == "cuda":
    pc = {}
    for pinned in (False, True):
        x = torch.empty(256 * 2**20, dtype=torch.uint8, pin_memory=pinned)
        y = x.to(dev); sync()
        t = time.time(); y = x.to(dev, non_blocking=pinned); sync(); h2d = time.time() - t
        t = time.time(); _ = y.to("cpu"); sync(); d2h = time.time() - t
        gb = x.numel() / 1e9
        pc["pinned" if pinned else "pageable"] = {"h2d_gb_s": round(gb / h2d, 2), "d2h_gb_s": round(gb / d2h, 2)}
        del x, y
    torch.cuda.empty_cache()
    R["pcie_256MB_copy"] = pc

# ------------------------------------------------------------------ model load, step by step
L = {}
t = time.time(); pipeline._resolve_models(); L["resolve_and_hf_cache_s"] = round(time.time() - t, 2)
L["gliner_dir"] = folder(M.GLINER_DIR)
L["nllb_dir"] = folder(M.NLLB_DIR)

from gliner import GLiNER  # noqa: E402
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # noqa: E402

L["vm_start"] = vm()
v0 = vm(); t = time.time(); g = GLiNER.from_pretrained(M.GLINER_DIR, local_files_only=True); L["gliner_disk_to_ram_s"] = round(time.time() - t, 2)
L["vm_gliner_disk_to_ram"] = vdelta(v0, vm())
L["gliner_fp32"] = tensor_bytes(g)
v0 = vm(); sync(); t = time.time(); g = g.to(dev); sync(); L["gliner_to_gpu_s"] = round(time.time() - t, 2)
L["vm_gliner_to_gpu"] = vdelta(v0, vm())
g.eval()
t = time.time(); g = g.half(); sync(); L["gliner_half_s"] = round(time.time() - t, 2)
L["gliner_fp16"] = tensor_bytes(g)
L["gpu_after_gliner"] = mem()

t = time.time(); tok = AutoTokenizer.from_pretrained(M.NLLB_DIR, local_files_only=True); L["nllb_tokenizer_s"] = round(time.time() - t, 2)
v0 = vm(); t = time.time(); nllb = AutoModelForSeq2SeqLM.from_pretrained(M.NLLB_DIR, local_files_only=True); L["nllb_disk_to_ram_s"] = round(time.time() - t, 2)
L["vm_nllb_disk_to_ram"] = vdelta(v0, vm())
L["nllb"] = tensor_bytes(nllb)
v0 = vm(); sync(); t = time.time(); nllb = nllb.to(dev); sync(); L["nllb_to_gpu_s"] = round(time.time() - t, 2)
L["vm_nllb_to_gpu"] = vdelta(v0, vm())
nllb.eval()
L["gpu_after_nllb"] = mem()
L["gliner_class"] = f"{type(g).__module__}.{type(g).__name__} / inner {type(g.model).__name__}"
L["nllb_class"] = type(nllb).__name__
R["load"] = L
models = (g, nllb, tok, M.langid, dev)

# ------------------------------------------------------------------ per-document front end
M._resolve_ocr_lang()
R["ocr_langs"] = M._OCR_LANG_CACHE
for fp in DOCS:
    d = {"bytes": os.path.getsize(fp)}
    t = time.time(); raw = M.extract_text(fp); d["extract_s"] = round(time.time() - t, 3)
    d["extractor"] = "tesseract OCR" if os.path.splitext(fp)[1].lower() in M.IMAGE_EXTS else "plain text read"
    if d["extractor"] == "tesseract OCR":
        from PIL import Image
        im = Image.open(fp)
        d["image"] = f"{im.size[0]}x{im.size[1]} {im.mode}"
    txt = M.preprocess(raw)
    d["chars"] = len(txt)
    d["utf8_bytes"] = len(txt.encode("utf-8"))
    t = time.time(); lang = M.detect_language(M.langid, txt); d["lid_s"] = round(time.time() - t, 4)
    d["lang"] = lang
    d["route"] = "translate" if (lang not in M.WELL_SUPPORTED and lang in M.NLLB_LANG) else "direct"
    d["nllb_src"] = M.NLLB_LANG.get(lang) if d["route"] == "translate" else None
    chunks, _ = M.chunk_text(txt)
    d["chunks"] = len(chunks)
    d["chunk_chars"] = [len(c) for c in chunks]
    if d["route"] == "translate":
        tok.src_lang = d["nllb_src"]
        d["nllb_tokens_untruncated"] = [len(tok(c)["input_ids"]) for c in chunks]
    R["docs"][os.path.basename(fp)] = d

# ------------------------------------------------------------------ instrumented batched runs
log = []
orig_generate = nllb.generate
orig_gl = g.batch_predict_entities


def generate(**kw):
    sync(); t0 = time.time()
    out = orig_generate(**kw)
    sync()
    log.append({"op": "nllb.generate", "src_lang": tok.src_lang, "input_ids": list(kw["input_ids"].shape),
                "output_ids": list(out.shape), "input_tokens_real": int(kw["attention_mask"].sum()),
                "s": round(time.time() - t0, 3)})
    return out


def batch_predict(texts, labels, **kw):
    sync(); t0 = time.time()
    out = orig_gl(texts, labels, **kw)
    sync()
    log.append({"op": "gliner.batch_predict_entities", "batch": len(texts), "chars": [len(x) for x in texts],
                "entities": [len(e) for e in out], "s": round(time.time() - t0, 3)})
    return out


nllb.generate = generate
g.batch_predict_entities = batch_predict

counts = {"enc": 0, "dec": 0}
hooks = [nllb.model.encoder.register_forward_pre_hook(lambda m, a: counts.__setitem__("enc", counts["enc"] + 1)),
         nllb.model.decoder.register_forward_pre_hook(lambda m, a: counts.__setitem__("dec", counts["dec"] + 1))]
gl_shapes = []
try:
    hooks.append(g.model.register_forward_pre_hook(
        lambda m, a, k: gl_shapes.append({**{f"arg{i}": shapes(x) for i, x in enumerate(a) if torch.is_tensor(x)},
                                          **(shapes(k) or {})}), with_kwargs=True))
except Exception as e:  # older torch / different GLiNER layout
    gl_shapes.append({"hook_error": str(e)})

stage_t = {}
for fn in ("extract_text", "detect_language", "translate_chunks", "predict_chunks"):
    orig = getattr(M, fn)

    def wrap(*a, _o=orig, _n=fn, **k):
        sync(); t0 = time.time()
        r = _o(*a, **k)
        sync()
        stage_t[_n] = stage_t.get(_n, 0) + time.time() - t0
        return r
    setattr(M, fn, wrap)

for run in ("cold (first call)", "warm (second call)"):
    log.clear(); gl_shapes.clear(); stage_t.clear(); counts.update(enc=0, dec=0)
    if dev == "cuda":
        torch.cuda.reset_peak_memory_stats()
    base = torch.cuda.memory_allocated() if dev == "cuda" else 0
    sync(); t0 = time.time()
    res = M.process_paths_batched(models, DOCS, M.DEFAULT_LABELS)
    sync(); total = time.time() - t0
    R["runs"].append({
        "run": run, "total_s": round(total, 2),
        "stage_s": {k: round(v, 3) for k, v in stage_t.items()},
        "calls": list(log), "nllb_encoder_calls": counts["enc"], "nllb_decoder_steps": counts["dec"],
        "gliner_forward_inputs": gl_shapes[:4],
        "peak_activation_mb": round((torch.cuda.max_memory_allocated() - base) / 2**20, 1) if dev == "cuda" else None,
        "entities_unique": {k: len(v.get("entities_unique", [])) for k, v in res.items()},
        "result_json_bytes": len(json.dumps(res, ensure_ascii=False).encode("utf-8")),
    })
for h in hooks:
    h.remove()
R["labels"] = M.DEFAULT_LABELS
R["settings"] = {"MAX_CHARS": M.MAX_CHARS, "BATCH_SIZE": M.BATCH_SIZE, "TRANSLATE_BATCH_SIZE": M.TRANSLATE_BATCH_SIZE,
                 "TRANSLATE_MAX_TOKENS": M.TRANSLATE_MAX_TOKENS, "SCORE_THRESHOLD": M.SCORE_THRESHOLD, "USE_FP16": M.USE_FP16}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
print(json.dumps({k: R[k] for k in ("env", "load")}, indent=1)[:3000])
for r in R["runs"]:
    print(r["run"], r["total_s"], r["stage_s"], r["nllb_decoder_steps"], r["peak_activation_mb"])
