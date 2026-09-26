# Worker Machine Setup — Handoff Context

You are Claude Code running on the **GPU worker machine** (LAN IP `192.168.4.101`) for a 2-node Spark cluster test of this repo (`pytorch-spark-inference-platform`). A separate Claude Code session already did the equivalent setup on the **master machine** (LAN IP `192.168.4.104`) in a long troubleshooting session — this doc is everything you need to replicate that here and register this machine as the cluster's GPU worker. Read this fully before doing anything; it explains *why* each step exists, not just what to type.

## Where things stand

- Master machine (`192.168.4.104`) has a Spark master container running and confirmed reachable from this worker machine over the LAN — a `curl http://192.168.4.104:8080/json/` from this machine already returned `"status": "ALIVE"` earlier.
- This worker machine already has the `multi-model-inference:latest` Docker image built (via Docker Desktop) — confirm with `docker images` in a normal PowerShell.
- Full narrative of what was tried and why: `docs/LIVE_CLUSTER_TEST_20260921.md` (chronological log), `docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md` (the core networking problem and fix — **read this one, it's essential context**), `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md` (offline-cloning approach, not needed here since this machine has internet).

## The core problem you're solving (read `WINDOWS_LAN_NETWORKING_FIX_20260921.md` for full detail)

Docker Desktop for Windows runs containers inside a hidden, NAT'd WSL2 VM — containers **cannot bind to the machine's real LAN IP**, no matter what Docker Desktop settings you toggle (bridge network, `--network host`, "Enable host networking" — all tested, all failed). Spark's standalone worker daemon needs to advertise this machine's real IP (`192.168.4.101`) to the master, and Spark literally tries to *bind* a socket to whatever address it advertises — so under Docker Desktop, that bind fails immediately.

**The fix, proven working on the master**: install a real, separate Docker Engine (Docker CE) directly inside a WSL2 Ubuntu distro (not Docker Desktop's own reserved `docker-desktop` distro), with WSL2's "mirrored networking" mode enabled. That combination gives the distro genuine access to the physical network interface, so `--network host` there behaves exactly like real Linux.

## Steps to run on this worker machine

### 1. Enable WSL2 mirrored networking

```powershell
@"
[wsl2]
networkingMode=mirrored
"@ | Set-Content -Path "$env:USERPROFILE\.wslconfig" -Encoding utf8
wsl --shutdown
```

### 2. Install a fresh Ubuntu-22.04 WSL distro

```powershell
wsl --install -d Ubuntu-22.04 --no-launch
wsl -d Ubuntu-22.04
```

The second command's first run will prompt you to create a Linux username/password interactively — do that once, then you're in a bash prompt inside the distro.

### 3. Verify mirrored networking actually works before going further

From inside that Ubuntu prompt:

```bash
ip addr show | grep 192.168.4
```

You must see `192.168.4.101` in the output. If you don't, stop here — mirrored networking didn't take effect (double check `.wslconfig` path and that `wsl --shutdown` actually ran before reopening the distro), and nothing past this point will work correctly.

### 4. Install Docker CE inside this Ubuntu distro

Run each of these as a normal (non-root doesn't matter, WSL Ubuntu's default user usually has sudo) command inside the WSL Ubuntu prompt — prefix with `sudo` if not running as root:

```bash
sudo apt-get update -qq
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update -qq
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
docker --version
```

Confirm the daemon is active: `sudo systemctl status docker` (WSL2 Ubuntu images from the Store have systemd enabled by default — if `systemctl` isn't available, that's a different problem to flag before continuing).

### 5. Install nvidia-container-toolkit (for `--gpus all` GPU passthrough)

```bash
sudo curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update -qq
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

You don't need a separate NVIDIA Linux driver install — WSL2's GPU passthrough uses the Windows host's driver directly; this toolkit just bridges Docker to it.

### 5b. Set the network adapter to Private and open the needed ports

This bit independently caused a real outage on the master mid-session: enabling mirrored networking (and any subsequent `wsl --shutdown`) can silently reclassify your Ethernet/Wi-Fi adapter from **Private** to **Public** in Windows. When that happens, Windows' much stricter Public-profile firewall blocks inbound connections even though everything *looks* fine — `ping` still works, same-machine tests still pass, only genuine cross-machine TCP connections silently time out. Check and fix this now, and **re-check it after every `wsl --shutdown` you do from here on**, not just once:

```powershell
# Elevated (Administrator) PowerShell required for both blocks below
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory
# If either shows "Public", fix it (adjust interface names to match this machine):
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private

New-NetFirewallRule -DisplayName "Spark Worker" -Direction Inbound -LocalPort 8081 -Protocol TCP -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "Spark Executors" -Direction Inbound -LocalPort 30000-40000 -Protocol TCP -Action Allow -Profile Private
```

(The master side needs its own equivalent rules for ports 7077/8080/4040 — already done on `192.168.4.104` as of this handoff, but if the master session tells you it's having connectivity trouble later, this is the first thing to ask them to re-check.)

### 5c. Critical: hold a persistent WSL session open if you're running commands via an external tool

If you (Claude, or whatever is driving this) issue many separate one-off `wsl -d Ubuntu-22.04 -- <command>` invocations back-to-back — which is exactly what happens during normal debugging (one command to check `docker ps`, another for `docker logs`, another for `curl`, etc.) — the distro's entire userspace can start repeatedly tearing down and restarting every ~20 seconds, taking Docker and every container down with it. This isn't a `vmIdleTimeout=-1` failure; it's a *separate*, per-instance idle/session-teardown path that setting doesn't fully cover, and it happened on the master mid-session, producing exactly the symptom you might see here: a container that looks like it's crash-looping with zero errors in its own logs, or (as actually happened) a worker registering successfully with the master and then disassociating ~18 seconds later.

**Before doing any real diagnostic work, start one long-lived background session and leave it running for the rest of the setup:**

```powershell
Start-Process powershell -ArgumentList '-NoProfile','-Command','wsl -d Ubuntu-22.04 -- sleep 999999' -WindowStyle Hidden
```

This holds the distro "attached" continuously so subsequent one-off `wsl -d Ubuntu-22.04 -- <command>` calls don't each re-arm an idle timer. Verify it's working by checking `docker ps` twice, 20+ seconds apart, without this session running — if the container's uptime resets between the two checks, that confirms this exact problem, and the fix above resolves it immediately.

### 6. Prove the actual thing that matters: can this engine bind to the real IP?

Don't just trust `ip addr` — directly test the bind, exactly like was done on the master:

```bash
docker run --rm --network host python:3.11-slim python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(('192.168.4.101', 9999))
    print('BIND SUCCEEDED')
except Exception as e:
    print('BIND FAILED:', e)
"
```

Must print `BIND SUCCEEDED`. If it doesn't, do not proceed to starting the worker container — something about the mirrored networking setup didn't take, and Spark will fail exactly the same way it did on the master before this was fixed.

### 7. Get the application image into this new Docker engine

This machine already has `multi-model-inference:latest` in Docker Desktop's engine. Move it into the new WSL Ubuntu Docker engine (both are on the same physical machine, so this is a local transfer, no network needed):

```powershell
# In a normal Windows PowerShell (not inside WSL)
docker save multi-model-inference:latest -o C:\spark-inference\multi-model-inference.tar
```

```bash
# Inside the WSL Ubuntu distro
docker load -i /mnt/c/spark-inference/multi-model-inference.tar
docker images   # confirm multi-model-inference:latest is now listed
```

### 8. Start the GPU worker container, registering with the master

```bash
docker run -d --name spark-gpu-worker --network host --gpus all --shm-size=4g \
  multi-model-inference:latest \
  bash -c "start-worker.sh spark://192.168.4.104:7077 -c 4 -m 12g && tail -f /opt/spark/logs/*worker*"
```

Note: unlike the earlier Docker-Desktop-based docs (`docs/WINDOWS_CLUSTER_SETUP.md`), you do **not** need `-e SPARK_WORKER_HOST=...` / `SPARK_LOCAL_IP=...` env var tricks or port-mapping flags (`-p 8081:8081`) here — `--network host` on this real Docker Engine already gives the container the machine's actual IP directly, so Spark's default hostname resolution inside the container will correctly resolve to `192.168.4.101` on its own.

### 9. Verify registration

```bash
docker logs spark-gpu-worker
```

Look for a line like `Successfully registered with master spark://192.168.4.104:7077`. Then confirm from the master's side (or just curl it from here too):

```bash
curl -s http://192.168.4.104:8080/json/
```

`"aliveworkers"` should now be `1` (or more), with an entry under `"workers"` showing this machine's host and core/memory offer.

## If something fails

- **Worker registers with master successfully, then disconnects/disassociates shortly after** (or anything looks like it's crash-looping with no error in its logs): almost certainly the per-instance idle-teardown issue from step 5c — make sure the persistent `sleep 999999` keep-alive session is actually running before doing anything else.
- **Bind test in step 6 fails**: mirrored networking isn't actually active. Re-check `.wslconfig` content and location (`%USERPROFILE%\.wslconfig`, note the leading dot), and that `wsl --shutdown` fully tore down WSL before you reopened the distro (check `wsl -l -v` shows all distros as `Stopped` right after shutdown).
- **`docker` command not found after step 4**: the apt install likely failed partway — re-run step 4's commands one at a time and check for errors, don't skip straight to step 5.
- **Worker container starts but doesn't register, or `curl http://192.168.4.104:8080/json/` from this machine times out** (while `ping 192.168.4.104` works fine): this is almost certainly the Private/Public network-category issue from step 5b — but on the **master's** side this time. Ask whoever/whatever is running the master session to re-run `Get-NetConnectionProfile` there and fix it if it shows Public. Don't skip this just because "it worked before" — it can regress after any `wsl --shutdown` on either machine. If that's not it, check the master container is actually running at all (`docker ps` on the master).
- **GPU not detected inside container** (`nvidia-smi` fails inside a test container): confirm Windows' own NVIDIA driver supports WSL2 CUDA passthrough (`nvidia-smi` should work directly in a plain `wsl -d Ubuntu-22.04` prompt, no Docker involved, before troubleshooting the container layer).

## After this works

Once `aliveworkers` shows this machine registered, the next step (coordinated from the master side) is running the full benchmark suite:

```bash
# From the master's spark-master container
docker exec -it spark-master bash -c "SPARK_MASTER_URL=spark://192.168.4.104:7077 python benchmark/cluster_benchmark.py --incremental"
```

This runs all 3 device modes (`cpu_only`, `gpu_only`, `hybrid`) × 3 load levels = 9 runs, using this worker's GPU. See `docs/BENCHMARK_TESTS.md` for what each phase measures.
