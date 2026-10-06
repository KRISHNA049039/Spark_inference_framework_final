"""
Selection -> platform CLI -> tracked job.

    pipeline  python submit_pipeline_job.py --pipeline <name> --input <dir> --partitions N
                     --execution-mode auto|service|cluster --driver-memory .. --executor-memory .. [--master URL]
    plugin    python submit_job.py --model <name> (--input <file.npy> | --samples N) --mode cpu_only|gpu_only|hybrid
                     --partitions N --batch-size B --engine rdd|udf [--master URL]

Both CLIs print "... written to results/<name>_<timestamp>.json"; that file (relative
to the runner workdir) is read back and summarised into the job row.
"""
import json
import re
import shlex
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import connections
from django.utils import timezone

from . import conf
from .models import InferenceJob
from .transports import get_transport

PIPELINE_SCRIPT = "submit_pipeline_job.py"
PLUGIN_SCRIPT = "submit_job.py"
_RESULT_RE = re.compile(r"written to (\S+\.json)")
_MEM_RE = re.compile(r"^\d+[mMgG]$")
_PROGRESS_RE = re.compile(r"\[Stage \d+:[^\n\r]*?\]")


class JobRequestError(ValueError):
    """Invalid selection or options (-> HTTP 400)."""


def _int(options, key, default, lo, hi):
    try:
        value = int(options.get(key, default))
    except (TypeError, ValueError):
        raise JobRequestError(f"{key} must be an integer")
    if not lo <= value <= hi:
        raise JobRequestError(f"{key} must be between {lo} and {hi}")
    return value


def _choice(options, key, default, allowed):
    value = options.get(key, default)
    if value not in allowed:
        raise JobRequestError(f"{key} must be one of {', '.join(allowed)}")
    return value


def _memory(options, key, default):
    value = str(options.get(key, default))
    if not _MEM_RE.match(value):
        raise JobRequestError(f"{key} must look like 512m or 4g")
    return value


PIPELINE_OPTIONS = {"partitions", "execution_mode", "driver_memory", "executor_memory"}
PLUGIN_OPTIONS = {"samples", "mode", "partitions", "batch_size", "engine"}


def clean_params(kind, name, options, cluster_input=None):
    """Validate client options against the runner defaults -> job params."""
    cfg = conf.runner_for(kind, name)
    allowed = PIPELINE_OPTIONS if kind == InferenceJob.Kind.PIPELINE else PLUGIN_OPTIONS
    unknown = set(options) - allowed
    if unknown:
        raise JobRequestError(f"unknown option(s) {', '.join(sorted(unknown))}; allowed: {', '.join(sorted(allowed))}")
    if kind == InferenceJob.Kind.PIPELINE:
        if not cluster_input:
            raise JobRequestError("a pipeline needs input: upload files or give input_path")
        params = {
            "input": cluster_input,
            "partitions": _int(options, "partitions", cfg.get("partitions", 2), 1, 256),
            "execution_mode": _choice(options, "execution_mode", cfg.get("execution_mode", "auto"), ["auto", "service", "cluster"]),
            "driver_memory": _memory(options, "driver_memory", cfg.get("driver_memory", "6g")),
            "executor_memory": _memory(options, "executor_memory", cfg.get("executor_memory", "4g")),
        }
    else:
        params = {
            "mode": _choice(options, "mode", cfg.get("mode", "hybrid"), ["cpu_only", "gpu_only", "hybrid"]),
            "partitions": _int(options, "partitions", cfg.get("partitions", 4), 1, 256),
            "batch_size": _int(options, "batch_size", cfg.get("batch_size", 256), 1, 65536),
            "engine": _choice(options, "engine", cfg.get("engine", "rdd"), ["rdd", "udf"]),
        }
        if cluster_input:
            params["input"] = cluster_input
        else:
            params["samples"] = _int(options, "samples", 512, 1, 10_000_000)
    if cfg.get("master"):
        params["master"] = cfg["master"]  # from settings only - clients cannot point jobs at other clusters
    return params


def build_args(job):
    p = job.params
    if job.kind == InferenceJob.Kind.PIPELINE:
        args = [PIPELINE_SCRIPT, "--pipeline", job.target, "--input", p["input"], "--partitions", str(p["partitions"]),
                "--execution-mode", p["execution_mode"], "--driver-memory", p["driver_memory"],
                "--executor-memory", p["executor_memory"]]
    else:
        args = [PLUGIN_SCRIPT, "--model", job.target, "--mode", p["mode"], "--partitions", str(p["partitions"]),
                "--batch-size", str(p["batch_size"]), "--engine", p["engine"]]
        args += ["--input", p["input"]] if p.get("input") else ["--samples", str(p["samples"])]
    if p.get("master"):
        args += ["--master", p["master"]]
    return args


def _summarise(data):
    summary = {k: v for k, v in data.items() if k != "results"}
    if isinstance(data.get("results"), dict):  # pipelines: one entry per document
        summary["documents"] = {
            name: {"error": r["error"]} if r.get("error") else
                  {"language": r.get("language"), "translated": r.get("translated"),
                   "entities": len(r.get("entities_unique", []))}
            for name, r in data["results"].items()}
    return summary


def run_job(job_id):
    """Run one queued job to completion (thread pool or Celery worker)."""
    try:
        job = InferenceJob.objects.get(pk=job_id)
        if job.status != InferenceJob.Status.QUEUED:
            return
        transport = get_transport(conf.runner_for(job.kind, job.target))
        timeout = conf.get("JOB_TIMEOUT_SECONDS")
        args = build_args(job)
        job.command = shlex.join(transport.argv(args, timeout))
        job.status, job.started_at = InferenceJob.Status.RUNNING, timezone.now()
        job.save(update_fields=["command", "status", "started_at"])
        try:
            _, code, output = transport.run(args, timeout)
            output = _PROGRESS_RE.sub("", output).replace("\r", "")
            job.exit_code = code
            job.log = output[-conf.get("LOG_TAIL_CHARS"):]
            found = _RESULT_RE.findall(output)
            if code == 0 and found:
                job.result_path = found[-1]
                job.summary = _summarise(json.loads(transport.read_text(job.result_path)))
                job.status = InferenceJob.Status.SUCCEEDED
            else:
                tail = [l for l in output.splitlines() if l.strip() and not l.startswith("SUCCESS: The process")][-15:]
                job.error = f"exit code {code}" + (": no results file reported" if code == 0 else "") + "\n" + "\n".join(tail)
                job.status = InferenceJob.Status.FAILED
        except subprocess.TimeoutExpired:
            job.status, job.error = InferenceJob.Status.FAILED, f"timed out after {timeout} s"
        except Exception as e:  # transport / results parsing: keep the job row truthful
            job.status, job.error = InferenceJob.Status.FAILED, f"{type(e).__name__}: {e}"
        job.finished_at = timezone.now()
        job.save()
    finally:
        connections.close_all()  # this thread's DB connections


def expire_stale(job):
    """A RUNNING job past its timeout was lost (e.g. the backend restarted mid-run)."""
    limit = timedelta(seconds=conf.get("JOB_TIMEOUT_SECONDS") + 600)
    if job.status == InferenceJob.Status.RUNNING and job.started_at and timezone.now() - job.started_at > limit:
        job.status, job.finished_at = InferenceJob.Status.FAILED, timezone.now()
        job.error = "no result within the timeout; the backend process running it may have restarted"
        job.save(update_fields=["status", "finished_at", "error"])
    return job


_pool = None
_pool_lock = threading.Lock()


def dispatch(job_id):
    if conf.get("EXECUTOR") == "celery":
        from .tasks import run_job_task
        run_job_task.delay(str(job_id))
        return
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=conf.get("MAX_CONCURRENT_JOBS"), thread_name_prefix="inference-job")
    _pool.submit(run_job, job_id)
