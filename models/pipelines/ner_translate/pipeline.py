"""
Thin BYOM "pipeline" wrapper around mt_ner_all_formats.py.

Exposes the load()/run(loaded, paths) contract that
inference/text_pipeline_engine.py expects, without modifying the underlying
pipeline's own extraction/translation/NER logic at all.

Model location: by default the weights are read from models/weights/ next to
the code. When MODEL_STORE_URI is set (e.g. hdfs://hdfs-namenode:8020/models/weights
for an air-gapped HDFS cluster, or file:///mnt/models/weights for a file
system on the master shared with the nodes), load() first resolves the model
directories through models/model_store.py - HDFS downloads are cached per node.

Three artefacts make up the pipeline's models:
  gliner-multi/              GLiNER multi v2.1 weights + gliner_config.json
  nllb-200-distilled-600M/   NLLB translation model + tokenizer
  hf_cache/                  Hugging Face hub cache holding GLiNER's backbone
                             (microsoft/mdeberta-v3-base) config + tokenizer -
                             GLiNER resolves its encoder by that hub name, so
                             offline it must find it in the hub cache.
"""
import os
import shutil

from . import mt_ner_all_formats as _impl

GLINER_NAME = "gliner-multi"
NLLB_NAME = "nllb-200-distilled-600M"
HF_CACHE_NAME = "hf_cache"


def _install_hf_cache(src_dir):
    """Copy the models--* entries of an offline HF hub cache into this process's
    hub cache (huggingface_hub.constants.HF_HUB_CACHE), which transformers reads
    with HF_HUB_OFFLINE=1. Needed because the cache location is fixed when
    transformers is imported, before load() knows where the store put the files."""
    from huggingface_hub import constants
    dst_root = constants.HF_HUB_CACHE
    if not os.path.isdir(src_dir) or os.path.abspath(src_dir) == os.path.abspath(dst_root):
        return
    os.makedirs(dst_root, exist_ok=True)
    for name in sorted(os.listdir(src_dir)):
        dst = os.path.join(dst_root, name)
        if name.startswith("models--") and not os.path.exists(dst):
            shutil.copytree(os.path.join(src_dir, name), dst)          # follows symlinks -> plain files
            print(f"[ner_translate] offline HF cache: {name} -> {dst_root}")


def _resolve_models():
    uri = os.environ.get("MODEL_STORE_URI")
    if not uri:
        base = os.path.dirname(_impl.GLINER_DIR)
        print(f"[ner_translate] model source: local files {base}")
        _install_hf_cache(os.path.join(base, HF_CACHE_NAME))
        return
    from models import model_store
    print(f"[ner_translate] model source: model store {uri}")
    _impl.GLINER_DIR = model_store.resolve(model_store.location(GLINER_NAME))
    _impl.NLLB_DIR = model_store.resolve(model_store.location(NLLB_NAME))
    try:
        _install_hf_cache(model_store.resolve(model_store.location(HF_CACHE_NAME)))
    except FileNotFoundError:
        print(f"[ner_translate] WARNING: no {HF_CACHE_NAME}/ in the model store - GLiNER needs its "
              f"backbone (microsoft/mdeberta-v3-base) in the Hugging Face cache to load offline")


def load():
    """Load GLiNER + NLLB + language-id once per executor (or once per model server)."""
    _resolve_models()
    return _impl.load_models()


def run(loaded, paths, labels=None):
    """Run the full extract -> detect -> translate -> NER pipeline over `paths`.

    Returns {filename: {language, translated, entities_unique, ...}} —
    the same shape mt_ner_all_formats.py itself writes to ner_output.json.
    """
    return _impl.process_paths_batched(loaded, paths, labels or _impl.DEFAULT_LABELS)
