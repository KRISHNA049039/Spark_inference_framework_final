"""
Before / after check for token-bounded translation chunks (runs in the model-server image).

Runs process_paths_batched twice on the same documents with the models loaded once:
  before - the old behaviour: sentences split on . ! ? only, translation chunks
           bounded by MAX_CHARS characters (chunk_text)
  after  - the current code: danda-aware split, one translation unit per sentence /
           line, split further only if over the NLLB token budget (chunk_for_translation)
and records, per translated document, the tokens NLLB receives per chunk, the
translation, and the entities found.

    python verify_translate_chunking.py <out.json> <doc> [<doc> ...]
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, "/app")
from models.pipelines.ner_translate import pipeline  # noqa: E402
from models.pipelines.ner_translate import mt_ner_all_formats as M  # noqa: E402

OUT, DOCS = sys.argv[1], sys.argv[2:]
OLD_SPLIT = re.compile(r"(?<=[.!?。!?])\s+")
NEW_SPLIT = M._SENTENCE_SPLIT
new_chunker = M.chunk_for_translation


def old_chunker(text, tokenizer, max_tokens=M.TRANSLATE_MAX_TOKENS):
    return M.chunk_text(text)[0]


def use(old):
    M._SENTENCE_SPLIT = OLD_SPLIT if old else NEW_SPLIT
    M.chunk_for_translation = old_chunker if old else new_chunker


loaded = pipeline.load()
_, _, tok, lid, _ = loaded

report = {"max_tokens": M.TRANSLATE_MAX_TOKENS, "docs": {}}
for fp in DOCS:
    text = M.preprocess(M.extract_text(fp))
    lang = M.detect_language(lid, text)
    if lang in M.WELL_SUPPORTED or lang not in M.NLLB_LANG:
        continue
    tok.src_lang = M.NLLB_LANG[lang]
    entry = {"lang": lang, "chars": len(text)}
    for label, old in (("before", True), ("after", False)):
        use(old)
        chunks = M.chunk_for_translation(text, tok)
        entry[label] = {"chunk_chars": [len(c) for c in chunks],
                        "tokens_to_nllb": [len(tok(c)["input_ids"]) for c in chunks]}  # incl. language token + </s>
    report["docs"][os.path.basename(fp)] = entry

orig_translate = M.translate_chunks
spent = {"s": 0.0}


def timed_translate(*a, **k):
    t0 = time.time()
    out = orig_translate(*a, **k)
    spent["s"] += time.time() - t0
    return out


M.translate_chunks = timed_translate
M.process_paths_batched(loaded, DOCS, M.DEFAULT_LABELS)  # warm-up: CUDA kernels, allocator, OCR models
report["timing"] = {}
for label, old in (("before", True), ("after", False)):
    use(old)
    spent["s"] = 0.0
    t0 = time.time()
    res = M.process_paths_batched(loaded, DOCS, M.DEFAULT_LABELS)
    report["timing"][label] = {"total_s": round(time.time() - t0, 2), "translate_s": round(spent["s"], 2)}
    for name, r in res.items():
        d = report["docs"].setdefault(name, {"lang": r.get("language")})
        d.setdefault(label, {})
        d[label]["entities_unique"] = len(r.get("entities_unique", []))
        d[label]["entities"] = sorted(f"{e['type']}: {e['text']}" for e in r.get("entities_unique", []))
        if r.get("translated"):
            d[label]["translation"] = r["text_used"]
use(False)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=1, ensure_ascii=False)
print(json.dumps({n: {k: (v if not isinstance(v, dict) else {x: y for x, y in v.items() if x in ("tokens_to_nllb", "entities_unique")})
                      for k, v in d.items()} for n, d in report["docs"].items()}, indent=1, ensure_ascii=False))
