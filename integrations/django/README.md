# inference_gateway — Django endpoints for the Spark inference platform

A drop-in Django app. The client picks a **pipeline** (file pipelines such as `ner_translate`) or a **plugin** (tensor models: the 10 built-ins plus BYOM plugins). The app then:

1. turns that choice into the platform's own command (`submit_pipeline_job.py` or `submit_job.py`);
2. runs it on the Spark driver host;
3. tracks it as a job and returns the results.

A pipeline that has a model server can also be called synchronously for small requests.

```
client ──HTTP──> Django (inference_gateway)
                   ├─ POST jobs/  ─> [local | docker exec | ssh] python submit_pipeline_job.py / submit_job.py ─> Spark cluster
                   │                 └─ reads results/<name>_<ts>.json back -> job summary + full results
                   └─ POST pipelines/<name>/predict/ ─HTTP─> model server /predict (no Spark job)
uploads ─> SHARED_DATA_DIR/uploads/<job id>/   ==  CLUSTER_DATA_DIR/uploads/<job id>/ on every Spark node
```

Requirements: Django 4.2 or newer, Python 3.10 or newer. Celery is optional. There are no other dependencies.

## 1. Add it to the backend

1. Copy `inference_gateway/` into the backend repository, next to your other apps.
2. Add it to `settings.py`:
   ```python
   INSTALLED_APPS += ["inference_gateway"]
   ```
3. Mount its URLs in `urls.py`:
   ```python
   path("api/inference/", include("inference_gateway.urls"))
   ```
4. Create the job table:
   ```
   python manage.py migrate inference_gateway
   ```
5. Configure `INFERENCE_GATEWAY` (section 2) and check the connection:
   ```
   curl http://<backend>/api/inference/catalog/
   ```
   If `errors` is empty, the backend can reach the platform.

## 2. Settings

The backend needs to reach three things:

| what | setting | notes |
|---|---|---|
| the Spark driver host, where the platform code lives | `RUNNERS` | `local`, `docker` or `ssh` |
| a folder shared with every Spark node and the model server | `SHARED_DATA_DIR` (as the backend sees it) + `CLUSTER_DATA_DIR` (as the nodes see it) | only file *paths* travel through Spark; each node opens the files itself |
| the model server, for synchronous predictions (optional) | `SERVICE_URLS` | a URL the backend can reach |

### Example: the air-gapped simulation on the laptop (`deploy/docker-compose.airgap_sim.yml`)

```python
INFERENCE_GATEWAY = {
    "SHARED_DATA_DIR": r"D:\pytorch-spark-inference-platform 1\data",   # the repo's data/ = /app/data in every container
    "CLUSTER_DATA_DIR": "/app/data",
    "RUNNERS": {
        # NER in service mode: lean driver + worker, the model server does the work
        "pipeline:ner_translate": {"transport": "docker", "container": "sim-spark-master", "workdir": "/app",
                                   "master": "spark://ner-translate-master:7077", "execution_mode": "service",
                                   "partitions": 2, "driver_memory": "1g", "executor_memory": "512m"},
        # tensor models need torch on the driver: the laptop cluster (deploy/docker-compose.laptop.yml)
        "plugin": {"transport": "docker", "container": "spark-master", "workdir": "/app",
                   "master": "spark://spark-master:7077"},
    },
    "SERVICE_URLS": {"ner_translate": "http://localhost:8001"},          # model server port published by the compose file
}
```

### Example: backend on its own host, air-gapped cluster

```python
INFERENCE_GATEWAY = {
    "SHARED_DATA_DIR": "/mnt/inference-data",        # NFS share, mounted at /app/data on every Spark node and the model server
    "CLUSTER_DATA_DIR": "/app/data",
    "RUNNERS": {
        "pipeline": {"transport": "ssh", "host": "spark@spark-master.internal", "workdir": "/opt/platform",
                     "python": "/opt/platform/.venv/bin/python", "master": "spark://spark-master.internal:7077",
                     "execution_mode": "service", "driver_memory": "4g", "executor_memory": "2g"},
        "plugin":   {"transport": "ssh", "host": "spark@spark-master.internal", "workdir": "/opt/platform",
                     "python": "/opt/platform/.venv/bin/python", "master": "spark://spark-master.internal:7077"},
    },
    "SERVICE_URLS": {"ner_translate": "http://ner-translate-server.internal:8000"},
    "EXECUTOR": "celery",                            # see section 5
    "MAX_CONCURRENT_JOBS": 2,
    "AUTH_CHECK": "accounts.permissions.can_run_inference",   # your function: (request) -> bool
}
```

### Runner keys

A runner is looked up by `"pipeline:<name>"`, then `"pipeline"`, then `"default"`. Plugins use `"plugin:<name>"`, then `"plugin"`, then `"default"`.

| key | used by | meaning |
|---|---|---|
| `transport` | all | `local` (the backend runs on the driver host), `docker` (`docker exec` into the driver container), `ssh` (key-based, BatchMode) |
| `workdir` | all | the platform checkout on the driver host (`/app` in the images) |
| `python` | all | the Python interpreter that has pyspark and the platform's requirements |
| `container` | docker | driver container name |
| `host`, `ssh_options` | ssh | `user@host`; extra ssh flags (default `-o BatchMode=yes`) |
| `env` | all | extra environment variables for the CLI, e.g. `{"MODEL_STORE_URI": "hdfs://..."}` |
| `master` | all | Spark master URL passed as `--master`. Taken from settings only; clients cannot choose it |
| `partitions`, `execution_mode`, `driver_memory`, `executor_memory` | pipelines | defaults for the job options |
| `mode`, `partitions`, `batch_size`, `engine` | plugins | defaults for the job options |

### Other settings (defaults shown)

| setting | default | meaning |
|---|---|---|
| `EXECUTOR` | `"thread"` | `thread`: an in-process pool; `celery`: `inference_gateway.tasks.run_job_task` |
| `MAX_CONCURRENT_JOBS` | `1` | pool size, per backend process |
| `JOB_TIMEOUT_SECONDS` | `3600` | enforced with `timeout` on the driver host, so the job really stops |
| `PREDICT_TIMEOUT_SECONDS` | `600` | synchronous model-server calls |
| `MAX_UPLOAD_FILES` | `200` | files per request |
| `UPLOAD_SUBDIR` | `"uploads"` | under the shared folder |
| `CATALOG_CACHE_SECONDS` | `300` | how long the manifests stay cached |
| `AUTH_CHECK` | `None` | callable or dotted path `(request) -> bool`; `None` means the endpoints are open, so protect them yourself |

## 3. Endpoints

All endpoints are relative to where you mounted the URLs (`/api/inference/` here), and all responses are JSON.

| method | path | what it does |
|---|---|---|
| GET | `catalog/` | pipelines and models that can be selected (`?refresh=1` re-reads the manifests) |
| POST | `jobs/` | start a Spark job for the selected pipeline or plugin. Returns `202` with the job and a `Location` header |
| GET | `jobs/` | recent jobs (`?status=`, `?kind=`, `?limit=` up to 200) |
| GET | `jobs/<id>/` | status and summary (`?log=1` adds the command and the output tail) |
| GET | `jobs/<id>/results/` | the full results of a succeeded job (`409` while it is queued, running or failed) |
| POST | `pipelines/<name>/predict/` | synchronous call to the pipeline's model server, for a few documents |
| GET | `pipelines/<name>/health/` | model server status: `ok` or `loading` |

### Start a pipeline job with uploaded documents

```bash
curl -X POST http://localhost:8000/api/inference/jobs/ \
  -F kind=pipeline -F name=ner_translate \
  -F 'options={"partitions": 2, "execution_mode": "service"}' \
  -F files=@report_hi.txt -F files=@scan.png -F files=@brief.pdf
```

```json
{"id": "6f0c...", "kind": "pipeline", "target": "ner_translate", "status": "queued",
 "params": {"input": "/app/data/uploads/6f0c...", "partitions": 2, "execution_mode": "service",
            "driver_memory": "1g", "executor_memory": "512m", "master": "spark://ner-translate-master:7077"}, ...}
```

### Start a pipeline job on documents already in the shared folder

```bash
curl -X POST http://localhost:8000/api/inference/jobs/ -H 'Content-Type: application/json' \
  -d '{"kind": "pipeline", "name": "ner_translate", "input_path": "ner_samples", "options": {"partitions": 2}}'
```

`input_path` is relative to the shared folder. A cluster path such as `/app/data/ner_samples` is also accepted. It can be a folder or a single file, and paths outside the shared folder are rejected.

### Start a plugin (tensor model) job

```bash
# random input with the model's input shape
curl -X POST http://localhost:8000/api/inference/jobs/ -H 'Content-Type: application/json' \
  -d '{"kind": "plugin", "name": "resnet18", "options": {"samples": 2000, "mode": "gpu_only", "partitions": 4}}'

# your data: one .npy file, shape (N, *input_shape), float32
curl -X POST http://localhost:8000/api/inference/jobs/ -F kind=plugin -F name=ew_classifier -F files=@iq_batch.npy
```

### Follow the job and fetch the results

```bash
curl http://localhost:8000/api/inference/jobs/6f0c.../            # queued -> running -> succeeded | failed
curl http://localhost:8000/api/inference/jobs/6f0c.../results/    # the full results file
```

For a succeeded pipeline job, `summary` holds the Spark totals plus one line per document:

```json
"summary": {"elapsed_time": 32.8, "num_files": 3, "num_partitions": 2,
            "partition_details": [{"hostname": "ner-translate-worker", "num_paths": 2, "run_time_sec": 14.1}, ...],
            "documents": {"report_hi.txt": {"language": "hi", "translated": true, "entities": 29},
                          "scan.png": {"language": "en", "translated": false, "entities": 8}}}
```

For a failed job, `error` holds the exit code and the last lines of the output. `?log=1` returns the full output tail.

### Synchronous prediction (no Spark job)

```bash
curl -X POST http://localhost:8000/api/inference/pipelines/ner_translate/predict/ \
  -F files=@report_hi.txt -F 'labels=["person", "location", "weapon system"]'

curl -X POST http://localhost:8000/api/inference/pipelines/ner_translate/predict/ -H 'Content-Type: application/json' \
  -d '{"input_paths": ["ner_samples/sample_text3.txt"]}'
```

This returns `{"pipeline": "ner_translate", "results": {"<file>": {"language", "translated", "entities_unique", ...}}}`. If the model server is still loading its models it returns `503`, and if it can't be reached it returns `502`.

Custom `labels` work only on this synchronous endpoint. `submit_pipeline_job.py` has no labels option, so Spark jobs always use the pipeline's 19 default labels.

### Options and their limits

| kind | option | allowed values | default |
|---|---|---|---|
| pipeline | `partitions` | 1–256 (the parallel Spark tasks) | runner `partitions`, or 2 |
| pipeline | `execution_mode` | `auto`, `service`, `cluster` | runner, or `auto` |
| pipeline | `driver_memory`, `executor_memory` | e.g. `512m`, `4g` | runner, or `6g` / `4g` |
| plugin | `samples` | 1–10,000,000 (random input, used when no `.npy` is uploaded) | 512 |
| plugin | `mode` | `cpu_only`, `gpu_only`, `hybrid` | runner, or `hybrid` |
| plugin | `partitions` | 1–256 | runner, or 4 |
| plugin | `batch_size` | 1–65,536 | runner, or 256 |
| plugin | `engine` | `rdd`, `udf` | runner, or `rdd` |

Unknown options are rejected with `400`, so a typo can't silently fall back to a default. Pipeline and model names are checked against the catalog. The CLI is always called with a fixed list of arguments; no shell is built from the client's input.

## 4. What happens on `POST jobs/`

1. The kind, name, options and input path are validated. Nothing has been written yet.
2. Uploads are saved to `SHARED_DATA_DIR/uploads/<job id>/`. Every Spark node sees that folder as `CLUSTER_DATA_DIR/uploads/<job id>/`.
3. An `InferenceJob` row is saved with status `queued`. After the transaction commits, the job is handed to the executor.
4. The runner builds the CLI command, marks the job `running`, and runs it through the transport with a hard time limit.
5. The CLI prints `... written to results/<name>_<timestamp>.json`. The runner reads that file back through the same transport, stores a summary, and marks the job `succeeded`. Otherwise it stores the error and marks it `failed`.

## 5. Production notes

- **Executor.** The `thread` executor runs jobs inside the web process. That's fine for one process. With several gunicorn workers, each worker gets its own pool, and a restart loses running jobs: they are marked `failed` once past their timeout. Use `EXECUTOR: "celery"` and run a worker with `celery -A <project> worker -Q celery`.
- **Concurrency.** Keep `MAX_CONCURRENT_JOBS` low. Every job shares the same GPU or model server. Also, the CLIs name their results file by the second, so two jobs of the same pipeline that finish in the same second would share a file name.
- **Authentication.** The views are CSRF-exempt, because this is a JSON API. Protect them with `AUTH_CHECK`, or mount the URLs behind your own authentication middleware or gateway.
- **Uploads are not deleted.** They stay in `uploads/<job id>/`, so a job can be re-run and audited. Add a periodic cleanup if disk space matters.
- **Code on the cluster.** The CLIs run whatever platform code is on the driver host or in the driver image. After changing the pipeline, update that code or rebuild the images: `ner-translate-server`, `ner-translate-worker`, `spark-lean`.
- **`local` transport on Windows.** Spark workers must use the same Python version as the driver. Set `PYSPARK_PYTHON` in the runner's `env` if several Pythons are installed.
