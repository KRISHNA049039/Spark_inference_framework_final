"""
What a client can select: the platform's pipelines (models/pipelines/manifest.json)
and tensor models (built-ins + models/plugins/manifest.json). Manifests are read
from the platform checkout through the runner transport and cached.
"""
import json

from django.core.cache import cache

from . import conf
from .transports import get_transport

_CACHE_KEY = "inference_gateway:catalog"


def _manifest(kind, rel_path, errors):
    try:
        return json.loads(get_transport(conf.runner_for(kind)).read_text(rel_path))
    except Exception as e:  # platform unreachable / file missing: report, keep the rest usable
        errors.append(f"{rel_path}: {e}")
        return {}


def get_catalog(refresh=False):
    data = None if refresh else cache.get(_CACHE_KEY)
    if data is not None:
        return data
    errors = []
    services = conf.get("SERVICE_URLS")
    pipelines = {
        name: {"description": entry.get("description", ""),
               "sync_predict": name in services,
               "input": "documents (upload files or input_path under the shared data folder)"}
        for name, entry in _manifest("pipeline", "models/pipelines/manifest.json", errors).items()
    }
    plugins = {name: {**info, "source": "built-in"} for name, info in conf.get("BUILTIN_MODELS").items()}
    for name, entry in _manifest("plugin", "models/plugins/manifest.json", errors).items():
        plugins[name] = {"input_shape": entry.get("input_shape"), "category": entry.get("category", "custom"),
                         "output": entry.get("output_desc", ""), "source": "plugin"}
    data = {"pipelines": pipelines, "plugins": plugins, "errors": errors}
    if not errors:
        cache.set(_CACHE_KEY, data, conf.get("CATALOG_CACHE_SECONDS"))
    return data
