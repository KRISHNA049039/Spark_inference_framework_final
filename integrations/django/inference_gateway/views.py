"""
JSON endpoints (mounted under e.g. /api/inference/):

    GET  catalog/                       pipelines and models that can be selected
    POST jobs/                          start a Spark job for the selected pipeline / plugin -> 202 + job
    GET  jobs/                          recent jobs (?status=, ?kind=, ?limit=)
    GET  jobs/<id>/                     status + summary (?log=1 adds command and output tail)
    GET  jobs/<id>/results/             full results JSON of a finished job
    POST pipelines/<name>/predict/      synchronous call to the pipeline's model server (small requests)
    GET  pipelines/<name>/health/       model server status

POST jobs/ accepts multipart (fields kind, name, options=<JSON>, input_path, files=...) or
JSON {"kind", "name", "options": {...}, "input_path": "..."}.
"""
import json
import os
import posixpath
import urllib.error
import urllib.request
import uuid
from functools import wraps

from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils.module_loading import import_string
from django.utils.text import get_valid_filename
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import conf
from .catalog import get_catalog
from .models import InferenceJob
from .runner import JobRequestError, clean_params, dispatch, expire_stale
from .transports import get_transport


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def guarded(view):
    """Optional access check: INFERENCE_GATEWAY["AUTH_CHECK"] = callable or dotted path, (request) -> bool."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        check = conf.get("AUTH_CHECK")
        if check:
            check = import_string(check) if isinstance(check, str) else check
            if not check(request):
                return _error("not authorised", 403)
        try:
            return view(request, *args, **kwargs)
        except JobRequestError as e:
            return _error(str(e))
    return wrapper


def _payload(request):
    """-> (fields dict, uploaded files) from multipart or JSON bodies."""
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            raise JobRequestError("body is not valid JSON")
        if not isinstance(data, dict):
            raise JobRequestError("body must be a JSON object")
        return data, []
    data = {k: request.POST.get(k) for k in request.POST}
    for key in ("options", "labels", "input_paths"):
        if data.get(key):
            try:
                data[key] = json.loads(data[key])
            except json.JSONDecodeError:
                raise JobRequestError(f"{key} must be JSON")
    return data, request.FILES.getlist("files")


def _safe_rel(path):
    """A path inside the shared data folder, given relative or as the cluster's absolute path."""
    path = str(path).replace("\\", "/")
    cluster_root = conf.get("CLUSTER_DATA_DIR").rstrip("/") + "/"
    if path.startswith(cluster_root):
        path = path[len(cluster_root):]
    rel = posixpath.normpath(path).lstrip("/")
    if rel in ("", ".") or rel == ".." or rel.startswith("../"):
        raise JobRequestError("paths must point inside the shared data folder")
    root = conf.get("SHARED_DATA_DIR")
    if root and not os.path.exists(os.path.join(root, *rel.split("/"))):
        raise JobRequestError(f"{rel} does not exist in the shared data folder")
    return rel


def _cluster_path(rel):
    return posixpath.join(conf.get("CLUSTER_DATA_DIR"), rel)


def _plan_uploads(files, folder, allowed_ext):
    """Check uploads and pick their names -> (folder relative to the data root, file names). Writes nothing."""
    root = conf.get("SHARED_DATA_DIR")
    if not root:
        raise JobRequestError("file uploads need INFERENCE_GATEWAY['SHARED_DATA_DIR']")
    if len(files) > conf.get("MAX_UPLOAD_FILES"):
        raise JobRequestError(f"at most {conf.get('MAX_UPLOAD_FILES')} files per request")
    names, used = [], set()
    for f in files:
        name = get_valid_filename(os.path.basename(f.name)) or "file"
        stem, ext = os.path.splitext(name)
        if ext.lower() not in allowed_ext:
            raise JobRequestError(f"{f.name}: unsupported file type (allowed: {' '.join(allowed_ext)})")
        n = 1
        while name.lower() in used:  # results are keyed by file name - keep them unique
            name, n = f"{stem}_{n}{ext}", n + 1
        used.add(name.lower())
        names.append(name)
    return posixpath.join(conf.get("UPLOAD_SUBDIR"), folder), names


def _write_uploads(files, rel, names):
    dest = os.path.join(conf.get("SHARED_DATA_DIR"), *rel.split("/"))
    os.makedirs(dest, exist_ok=True)
    for f, name in zip(files, names):
        with open(os.path.join(dest, name), "wb") as out:
            for chunk in f.chunks():
                out.write(chunk)


@require_GET
@guarded
def catalog_view(request):
    return JsonResponse(get_catalog(refresh=request.GET.get("refresh") == "1"))


@csrf_exempt
@require_http_methods(["GET", "POST"])
@guarded
def jobs_view(request):
    if request.method == "GET":
        qs = InferenceJob.objects.all()
        for key in ("status", "kind"):
            if request.GET.get(key):
                qs = qs.filter(**{key: request.GET[key]})
        try:
            limit = min(int(request.GET.get("limit", 50)), 200)
        except ValueError:
            raise JobRequestError("limit must be an integer")
        return JsonResponse({"jobs": [expire_stale(j).to_dict() for j in qs[:limit]]})

    data, files = _payload(request)
    kind, name = data.get("kind"), data.get("name")
    catalog = get_catalog()
    if kind == InferenceJob.Kind.PIPELINE:
        known = catalog["pipelines"]
    elif kind == InferenceJob.Kind.PLUGIN:
        known = catalog["plugins"]
    else:
        raise JobRequestError('kind must be "pipeline" or "plugin"')
    if name not in known:
        raise JobRequestError(f"unknown {kind} {name!r}; available: {', '.join(sorted(known)) or 'none'}"
                              + (f" (catalog errors: {catalog['errors']})" if catalog.get("errors") else ""))
    options = data.get("options") or {}
    if not isinstance(options, dict):
        raise JobRequestError("options must be a JSON object")

    job = InferenceJob(kind=kind, target=name)
    cluster_input, upload = None, None
    if files:
        if kind == InferenceJob.Kind.PIPELINE:
            rel, names = _plan_uploads(files, str(job.id), conf.get("PIPELINE_EXTENSIONS"))
            cluster_input = _cluster_path(rel)                       # the job folder: all uploaded documents
        else:
            if len(files) != 1:
                raise JobRequestError("a plugin takes one .npy file (shape (N, *input_shape), float32)")
            rel, names = _plan_uploads(files, str(job.id), [".npy"])
            cluster_input = _cluster_path(posixpath.join(rel, names[0]))
        upload = (rel, names)
    elif data.get("input_path"):
        cluster_input = _cluster_path(_safe_rel(data["input_path"]))
    job.params = clean_params(kind, name, options, cluster_input)   # validate everything before writing files
    if upload:
        _write_uploads(files, *upload)
    user = getattr(request, "user", None)
    job.created_by = user.get_username() if user is not None and user.is_authenticated else ""
    job.save()
    transaction.on_commit(lambda: dispatch(job.id))
    response = JsonResponse(job.to_dict(), status=202)
    response["Location"] = reverse("inference_gateway:job-detail", args=[job.id])
    return response


@require_GET
@guarded
def job_detail_view(request, job_id):
    job = InferenceJob.objects.filter(pk=job_id).first()
    if job is None:
        return _error("job not found", 404)
    return JsonResponse(expire_stale(job).to_dict(include_log=request.GET.get("log") == "1"))


@require_GET
@guarded
def job_results_view(request, job_id):
    job = InferenceJob.objects.filter(pk=job_id).first()
    if job is None:
        return _error("job not found", 404)
    if job.status != InferenceJob.Status.SUCCEEDED:
        return JsonResponse({"error": f"job is {job.status}", "job": job.to_dict()}, status=409)
    try:
        data = json.loads(get_transport(conf.runner_for(job.kind, job.target)).read_text(job.result_path))
    except Exception as e:
        return _error(f"results file {job.result_path} not readable: {e}", 502)
    return JsonResponse(data)


def _service_call(name, path, body=None):
    base = conf.get("SERVICE_URLS").get(name)
    if not base:
        raise LookupError(name)
    req = urllib.request.Request(base.rstrip("/") + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=conf.get("PREDICT_TIMEOUT_SECONDS")) as resp:
        return json.loads(resp.read())


@csrf_exempt
@require_POST
@guarded
def predict_view(request, name):
    """Small, interactive requests straight to the pipeline's model server (no Spark job)."""
    if name not in conf.get("SERVICE_URLS"):
        return _error(f"no model server configured for {name!r} (INFERENCE_GATEWAY['SERVICE_URLS'])", 404)
    data, files = _payload(request)
    if files:
        rel, names = _plan_uploads(files, f"predict-{uuid.uuid4()}", conf.get("PIPELINE_EXTENSIONS"))
        _write_uploads(files, rel, names)
        paths = [_cluster_path(posixpath.join(rel, n)) for n in names]
    else:
        given = data.get("input_paths") or []
        if not isinstance(given, list) or not given:
            raise JobRequestError("upload files or give input_paths (a list of paths in the shared data folder)")
        paths = [_cluster_path(_safe_rel(p)) for p in given]
    labels = data.get("labels")
    if labels is not None and (not isinstance(labels, list) or not all(isinstance(x, str) for x in labels)):
        raise JobRequestError("labels must be a list of strings")
    try:
        results = _service_call(name, "/predict", {"paths": paths, "labels": labels})
    except (urllib.error.URLError, TimeoutError) as e:
        return _error(f"model server unreachable: {e}", 502)
    if isinstance(results, dict) and set(results) == {"error"}:  # e.g. "models still loading, retry shortly"
        return _error(results["error"], 503)
    return JsonResponse({"pipeline": name, "results": results})


@require_GET
@guarded
def health_view(request, name):
    try:
        return JsonResponse(_service_call(name, "/health"))
    except LookupError:
        return _error(f"no model server configured for {name!r}", 404)
    except (urllib.error.URLError, TimeoutError) as e:
        return _error(f"model server unreachable: {e}", 502)
