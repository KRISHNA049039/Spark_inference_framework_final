"""
Model store - where model weights live, independent of where code runs.

In an air-gapped deployment the weights (GLiNER, NLLB, plugin checkpoints)
are kept once in the cluster's HDFS (or on a file system of the master that
every node can read), not baked into images or copied onto every worker.
This module turns a model location into a local directory/file that
from_pretrained() / torch.load() can read:

    local_dir = resolve("hdfs://hdfs-namenode:8020/models/weights/gliner-multi")
    local_dir = resolve("file:///mnt/models/weights/gliner-multi")   # shared / master FS
    local_dir = resolve("/app/models/weights/gliner-multi")          # plain local path

HDFS is read through WebHDFS (the namenode's built-in HTTP REST API, port
9870 by default) using only the Python standard library - no hadoop CLI,
libhdfs, JVM or extra wheels needed on the executor or in the model server,
which keeps the air-gapped dependency list unchanged.

Downloads go to a per-node cache (MODEL_CACHE_DIR, default /tmp/model_cache)
and are atomic: a directory is fetched into a temporary sibling and renamed
into place, with a .complete marker, so concurrent Python workers on the same
node never read a half-written model and later tasks reuse the cache.

Environment:
    MODEL_STORE_URI         base location, e.g. hdfs://hdfs-namenode:8020/models/weights
                            or file:///mnt/models/weights (unset = use repo paths)
    MODEL_STORE_WEBHDFS     WebHDFS base URL override, e.g. http://hdfs-namenode:9870
                            (default: http://<hdfs host>:9870)
    MODEL_STORE_USER        HDFS user name for WebHDFS (default: root)
    MODEL_CACHE_DIR         local cache directory (default: /tmp/model_cache)
"""
import json
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_WEBHDFS_PORT = 9870


def store_uri():
    """Base model-store URI from the environment, or None (use local paths)."""
    return os.environ.get("MODEL_STORE_URI") or None


def location(name: str) -> str:
    """Location of a named model artefact under MODEL_STORE_URI (e.g. 'gliner-multi')."""
    base = store_uri()
    if not base:
        raise RuntimeError("MODEL_STORE_URI is not set")
    return base.rstrip("/") + "/" + name.lstrip("/")


def resolve(path_or_uri: str, log=print) -> str:
    """Return a local path for a local path, file:// URI or hdfs:// URI."""
    parsed = urllib.parse.urlparse(path_or_uri)
    if parsed.scheme in ("", "file"):
        local = parsed.path if parsed.scheme == "file" else path_or_uri
        if parsed.scheme == "file" and os.name == "nt" and local.startswith("/") and ":" in local[:4]:
            local = local[1:]  # file:///D:/x -> D:/x
        if not os.path.exists(local):
            raise FileNotFoundError(f"model store: {path_or_uri} does not exist on this node")
        return local
    if parsed.scheme in ("hdfs", "webhdfs"):
        return _fetch_hdfs(parsed, log)
    raise ValueError(f"model store: unsupported scheme in {path_or_uri!r}")


# ---------------------------------------------------------------- WebHDFS
def _webhdfs_base(parsed) -> str:
    override = os.environ.get("MODEL_STORE_WEBHDFS")
    if override:
        return override.rstrip("/")
    port = parsed.port if parsed.scheme == "webhdfs" and parsed.port else DEFAULT_WEBHDFS_PORT
    return f"http://{parsed.hostname}:{port}"


def _call(base, hdfs_path, op, timeout=60):
    user = os.environ.get("MODEL_STORE_USER", "root")
    url = f"{base}/webhdfs/v1{urllib.parse.quote(hdfs_path)}?op={op}&user.name={user}"
    return urllib.request.urlopen(url, timeout=timeout)   # follows the namenode -> datanode redirect


def _status(base, hdfs_path):
    with _call(base, hdfs_path, "GETFILESTATUS") as r:
        return json.load(r)["FileStatus"]


def _list(base, hdfs_path):
    with _call(base, hdfs_path, "LISTSTATUS") as r:
        return json.load(r)["FileStatuses"]["FileStatus"]


def _download_file(base, hdfs_path, dest, size):
    with _call(base, hdfs_path, "OPEN", timeout=600) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, length=8 * 1024 * 1024)
    got = os.path.getsize(dest)
    if got != size:
        raise IOError(f"model store: {hdfs_path} truncated ({got} of {size} bytes)")
    return got


def _download_tree(base, hdfs_path, dest):
    total = 0
    st = _status(base, hdfs_path)
    if st["type"] == "FILE":
        return _download_file(base, hdfs_path, dest, st["length"])
    os.makedirs(dest, exist_ok=True)
    for entry in _list(base, hdfs_path):
        child = hdfs_path.rstrip("/") + "/" + entry["pathSuffix"]
        target = os.path.join(dest, entry["pathSuffix"])
        if entry["type"] == "DIRECTORY":
            total += _download_tree(base, child, target)
        else:
            total += _download_file(base, child, target, entry["length"])
    return total


def _fetch_hdfs(parsed, log):
    base = _webhdfs_base(parsed)
    hdfs_path = parsed.path or "/"
    cache_root = os.environ.get("MODEL_CACHE_DIR", os.path.join(tempfile.gettempdir(), "model_cache"))
    local = os.path.join(cache_root, parsed.hostname or "hdfs", hdfs_path.strip("/"))
    marker = local + ".complete"
    if os.path.exists(marker) and os.path.exists(local):
        log(f"[model_store] cache hit {local}")
        return local
    os.makedirs(os.path.dirname(local), exist_ok=True)
    if os.path.exists(local):                    # left over from an interrupted fetch (no marker)
        shutil.rmtree(local, ignore_errors=True)
    t0 = time.time()
    try:
        _status(base, hdfs_path)
    except urllib.error.HTTPError as e:
        raise FileNotFoundError(f"model store: {hdfs_path} not found in HDFS at {base} (HTTP {e.code})") from e
    except urllib.error.URLError as e:
        raise ConnectionError(f"model store: cannot reach WebHDFS at {base}: {e.reason}") from e
    tmp = tempfile.mkdtemp(prefix=".partial-", dir=os.path.dirname(local))
    target = os.path.join(tmp, os.path.basename(local))
    try:
        nbytes = _download_tree(base, hdfs_path, target)
        try:
            os.replace(target, local)            # atomic publish
        except OSError:
            if not os.path.exists(marker):       # someone else published first? otherwise re-raise
                raise
        open(marker, "w").write(json.dumps({"source": f"{base}{hdfs_path}", "bytes": nbytes, "time": time.time()}))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    dt = time.time() - t0
    log(f"[model_store] fetched {base}{hdfs_path} -> {local}  {nbytes / 1e6:.1f} MB in {dt:.1f} s "
        f"({nbytes / 1e6 / max(dt, 1e-6):.0f} MB/s)")
    return local
