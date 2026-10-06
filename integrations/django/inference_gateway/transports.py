"""
How the backend reaches the Spark driver host, where the platform code lives.

    local  - the backend runs on the driver host (platform checkout + pyspark installed)
    docker - the driver is a container on the backend's Docker host (docker exec)
    ssh    - the driver host is another machine (ssh, key-based, BatchMode)

Every transport runs `<python> <script> <args...>` in the platform's working
directory and can read a file relative to it (the results JSON). Arguments are
passed as an argv list (local / docker) or shell-quoted (ssh) - never through a
shell built from user input.

Runner config keys: transport, workdir, python, env (dict), container (docker),
host + ssh_options (ssh), master and default job options (see runner.py).
"""
import os
import posixpath
import shlex
import subprocess

# Extra seconds the outer process waits after the in-host `timeout` has fired.
_GRACE = 60


class Transport:
    def __init__(self, cfg):
        self.cfg = cfg
        self.workdir = cfg.get("workdir", "/app")
        self.python = cfg.get("python", "python")
        self.env = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}

    def argv(self, args, timeout):
        raise NotImplementedError

    def run(self, args, timeout):
        """-> (argv, exit code, combined stdout + stderr)."""
        argv = self.argv(args, timeout)
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout + _GRACE)
        return argv, proc.returncode, proc.stdout or ""

    def read_text(self, rel_path):
        raise NotImplementedError


class LocalTransport(Transport):
    def argv(self, args, timeout):
        return [self.python, *args]

    def run(self, args, timeout):
        argv = self.argv(args, timeout)
        # Killing the driver's Python on timeout also ends its Spark JVM (it exits when its stdin closes).
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, cwd=self.workdir,
                              env={**os.environ, **self.env})
        return argv, proc.returncode, proc.stdout or ""

    def read_text(self, rel_path):
        with open(os.path.join(self.workdir, rel_path), encoding="utf-8") as f:
            return f.read()


class DockerTransport(Transport):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.container = cfg["container"]
        self.docker = cfg.get("docker", "docker")

    def argv(self, args, timeout):
        env = [x for k, v in self.env.items() for x in ("-e", f"{k}={v}")]
        # `timeout` runs inside the container: killing the docker CLI alone would leave the job running there.
        return [self.docker, "exec", "-w", self.workdir, *env, self.container,
                "timeout", str(int(timeout)), self.python, *args]

    def read_text(self, rel_path):
        proc = subprocess.run([self.docker, "exec", self.container, "cat", posixpath.join(self.workdir, rel_path)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=120)
        if proc.returncode:
            raise FileNotFoundError(proc.stderr.strip() or rel_path)
        return proc.stdout


class SSHTransport(Transport):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.host = cfg["host"]
        self.ssh = [cfg.get("ssh", "ssh"), *cfg.get("ssh_options", ["-o", "BatchMode=yes"])]

    def _remote(self, words):
        env = " ".join(f"{k}={shlex.quote(v)}" for k, v in self.env.items())
        return f"cd {shlex.quote(self.workdir)} && {env + ' ' if env else ''}" + " ".join(shlex.quote(w) for w in words)

    def argv(self, args, timeout):
        return [*self.ssh, self.host, self._remote(["timeout", str(int(timeout)), self.python, *args])]

    def read_text(self, rel_path):
        proc = subprocess.run([*self.ssh, self.host, self._remote(["cat", rel_path])],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=120)
        if proc.returncode:
            raise FileNotFoundError(proc.stderr.strip() or rel_path)
        return proc.stdout


_TRANSPORTS = {"local": LocalTransport, "docker": DockerTransport, "ssh": SSHTransport}


def get_transport(cfg):
    try:
        return _TRANSPORTS[cfg.get("transport", "local")](cfg)
    except KeyError as e:
        raise ValueError(f"unknown transport {cfg.get('transport')!r} (use local, docker or ssh)") from e
