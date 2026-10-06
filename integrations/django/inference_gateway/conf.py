"""Settings for the app: settings.INFERENCE_GATEWAY = {...}, merged over these defaults."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# File types the NER pipeline can read (mt_ner_all_formats.SUPPORTED_EXTS).
PIPELINE_EXTENSIONS = [
    ".txt", ".md", ".log", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".yaml", ".yml", ".ini", ".rst",
    ".html", ".htm", ".pdf", ".docx", ".odt", ".rtf", ".epub", ".pptx", ".xlsx", ".xlsm", ".xls", ".ods",
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif",
]

# Built-in tensor models (models/__init__.py get_default_registry); plugins come from
# models/plugins/manifest.json and are added to these at run time.
BUILTIN_MODELS = {
    "ew_classifier": {"input_shape": [128], "category": "signal", "output": "8-class logits (radar/jammer/comms)"},
    "signal_denoiser": {"input_shape": [128], "category": "signal", "output": "128-dim denoised signal"},
    "threat_prioritizer": {"input_shape": [128], "category": "signal", "output": "scalar priority score [0,1]"},
    "rf_fingerprinter": {"input_shape": [128], "category": "signal", "output": "32-dim emitter embedding"},
    "anomaly_detector": {"input_shape": [128], "category": "signal", "output": "scalar anomaly score"},
    "resnet18": {"input_shape": [3, 224, 224], "category": "image_classification", "output": "1000-class ImageNet logits"},
    "mobilenetv3": {"input_shape": [3, 224, 224], "category": "image_classification", "output": "1000-class ImageNet logits"},
    "efficientnet_b0": {"input_shape": [3, 224, 224], "category": "image_classification", "output": "1000-class ImageNet logits"},
    "yolov8_nano": {"input_shape": [3, 640, 640], "category": "object_detection", "output": "detection boxes (x,y,w,h,conf,cls)"},
    "yolov8_small": {"input_shape": [3, 640, 640], "category": "object_detection", "output": "detection boxes (x,y,w,h,conf,cls)"},
}

DEFAULTS = {
    # Folder the backend writes uploaded documents into (host path / NFS mount) ...
    "SHARED_DATA_DIR": None,
    # ... and the same folder as the Spark nodes and the model server see it.
    "CLUSTER_DATA_DIR": "/app/data",
    "UPLOAD_SUBDIR": "uploads",
    # Where and how the platform's CLIs run. Keys: "pipeline:<name>", "pipeline",
    # "plugin:<name>", "plugin", "default" (first match wins). See README.md.
    "RUNNERS": {"default": {"transport": "local", "workdir": ".", "python": "python"}},
    # Pipeline -> model-server URL reachable from the backend (sync predict endpoint).
    "SERVICE_URLS": {},
    "BUILTIN_MODELS": BUILTIN_MODELS,
    "PIPELINE_EXTENSIONS": PIPELINE_EXTENSIONS,
    "EXECUTOR": "thread",            # "thread" (in-process pool) or "celery"
    "MAX_CONCURRENT_JOBS": 1,        # per backend process with the thread executor
    "JOB_TIMEOUT_SECONDS": 3600,
    "PREDICT_TIMEOUT_SECONDS": 600,
    "MAX_UPLOAD_FILES": 200,
    "LOG_TAIL_CHARS": 20000,
    "CATALOG_CACHE_SECONDS": 300,
    # Optional access check: callable or dotted path, (request) -> bool. None = open (protect the URLs yourself).
    "AUTH_CHECK": None,
}


def get(key):
    return getattr(settings, "INFERENCE_GATEWAY", {}).get(key, DEFAULTS[key])


def runner_for(kind, name=None):
    """Runner config for a pipeline / plugin: most specific key wins."""
    runners = get("RUNNERS")
    for key in (f"{kind}:{name}" if name else None, kind, "default"):
        if key and key in runners:
            return runners[key]
    raise ImproperlyConfigured(f"INFERENCE_GATEWAY['RUNNERS'] has no entry for {kind}:{name}, {kind} or default")
