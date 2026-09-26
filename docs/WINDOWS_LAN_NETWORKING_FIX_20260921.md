# Windows LAN Cluster Networking — Problem, Fix, and Production Notes

Session log: why the standard `docs/WINDOWS_CLUSTER_SETUP.md` approach failed on real Windows machines, what actually fixed it, the concepts behind the fix, and whether to use this in production.

---

## The problem

Goal: run this framework's Spark cluster across two real Windows machines on the same LAN — this machine as master (`192.168.4.104`), a second machine as GPU worker (`192.168.4.101`) — using Docker Desktop, exactly as `docs/WINDOWS_CLUSTER_SETUP.md` describes.

Following that doc exactly, the Spark master container crashed on startup:

```
java.net.BindException: Cannot assign requested address: Service 'sparkMaster' failed after 16 retries (starting from 7077)!
```

## Root cause

Two facts combine to cause this:

1. **Spark's standalone master/worker daemons don't separate "bind address" from "advertised address."** Whatever host you tell Spark to advertise (`-h <ip>`, `SPARK_LOCAL_IP`, `SPARK_WORKER_HOST` — they all feed the same internal variable), it tries to **literally open a listening socket on that exact address**. There's no standalone-Spark config that says "tell everyone I'm at X, but just bind to whatever's available." This is a known, long-standing limitation — not a bug in this repo.

2. **Docker Desktop for Windows doesn't give containers your real network card.** Docker Desktop runs everything inside a hidden WSL2 virtual machine. By default that VM sits behind NAT — it has its own private, fake IP addresses, and neither the container's default bridge network nor even `--network host` can see or bind to your actual Ethernet/Wi-Fi adapter (`192.168.4.104`). We verified this directly: even with `--network host`, a container only saw `192.168.65.x` / `172.x` addresses, never the real one.

Put together: we told Spark to bind to an address that, from inside any Docker Desktop container, simply doesn't exist. Every retry failed the same way.

This is exactly why `docs/CLUSTER_SETUP_GUIDE.md` (the AWS/Linux version) works fine with `--network host` — on real Linux, `--network host` genuinely shares the physical host's network stack. Windows' Docker Desktop only *simulates* that inside its own VM.

## What we tried that didn't work (and why)

| Attempt | Result | Why |
|---|---|---|
| `docker run --network host` | Still fake addresses | Docker Desktop's "host" network is the VM's own network, not Windows' |
| Enable WSL2 "mirrored networking" (`.wslconfig`) | WSL2 itself now saw the real IP (`wsl -d docker-desktop -- ip addr` proved it) | But Docker Desktop's *own* container engine sits in a further-nested network layer that mirroring alone doesn't reach |
| Docker Desktop's "Enable host networking" GUI toggle | Setting saved, but a container still failed to bind | Needed a full backend restart to activate — after forcing that, it *still* failed a direct bind test. Docker Desktop's container network stack on Windows just doesn't expose the physical NIC to containers, full stop |

We only trusted the final verdict after directly testing the actual operation we needed (`socket.bind(('192.168.4.104', 9999))` inside a container), not just eyeballing `ip addr` output — that direct test is what proved each attempt had failed.

## What actually fixed it

Skip Docker Desktop's engine entirely. Run a **real, plain Docker Engine (Docker CE) directly inside a WSL2 Ubuntu distro**, with WSL2's mirrored networking mode on:

1. **`.wslconfig`** (`C:\Users\<user>\.wslconfig`):
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
   This makes the *entire* WSL2 subsystem present your real network interfaces to every distro — no more fake NAT'd network at the OS level.

2. **Install a fresh Ubuntu-22.04 WSL distro** (`wsl --install -d Ubuntu-22.04`) — deliberately *not* Docker Desktop's own reserved `docker-desktop` distro, which stays sealed off regardless of the mirroring setting.

3. **Install Docker CE inside that distro** the normal Linux way (`apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin`, from Docker's official apt repo) — a completely independent Docker daemon from Docker Desktop's.

4. **Install `nvidia-container-toolkit`** inside the same distro for GPU passthrough — this bridges Docker's `--gpus all` flag to the NVIDIA driver that's still doing the actual work on the Windows side (WSL2 GPU passthrough doesn't need a separate Linux driver install).

5. Verified with a direct bind test — **this is the one that matters**:
   ```python
   import socket
   s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   s.bind(('192.168.4.104', 9999))   # succeeded
   ```
   Because this Ubuntu distro is a normal Linux system (just running under WSL2's hypervisor) with mirrored networking, its `--network host` behaves exactly like real Linux `--network host` — it has genuine access to the physical NIC.

6. Transferred the already-built image into this new engine locally (`docker save` from Docker Desktop's engine → `docker load` into the WSL Ubuntu engine) rather than rebuilding from scratch.

## A second, separate gotcha found afterward: Windows silently blocked it anyway

Getting the bind to succeed wasn't the end of it. After several more `wsl --shutdown` cycles later in the session (for unrelated distro-export work), the master became unreachable from the worker machine again — `ping` worked, but `curl http://192.168.4.104:8080/json/` from the worker timed out, and everything *on* the master (same-machine tests) still looked fine.

Root cause: Windows had silently reclassified the Ethernet/Wi-Fi adapters from **Private** to **Public** network category — almost certainly triggered by the network stack churn from enabling mirrored networking and repeated `wsl --shutdown`s. The firewall rules opened earlier in this session were scoped to the Private profile only, so once the adapter flipped to Public, Windows' far stricter default Public-profile firewall silently started blocking the exact same ports again, with zero visible error.

Fix:
```powershell
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
```

The lesson that generalizes: **same-machine connectivity tests cannot catch this class of bug.** Loopback and self-directed traffic don't necessarily traverse the same firewall/profile logic as traffic arriving from a genuinely different machine — every reachability check in this whole exercise that actually mattered had to be run from the *other* physical machine, not from the one being configured. This is now baked into the setup docs (`docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md`, `docs/WORKER_MACHINE_HANDOFF_20260921.md`) as a check to repeat after every `wsl --shutdown`, not a one-time setup step.

## A third gotcha: the whole WSL2 VM was silently power-cycling, not just the container

After the above two fixes, the master container was still dying every 20-30 seconds — sometimes exit code 255 with zero log output, once exit code 0. `docker logs` showed nothing useful either time, which was the first clue this wasn't really a container-level problem at all.

`dmesg` inside the WSL distro told the real story:

```
WSL ERROR: InitTerminateInstanceInternal: systemctl poweroff did not terminate the instance in 10000 ms, calling reboot(RB_POWER_OFF)
EXT4-fs: unmounting filesystem...
EXT4-fs: mounted filesystem... (fresh remount moments later)
```

**The entire WSL2 VM was being powered off and rebooted**, taking Docker and every container with it, then coming back up fresh each time — which is exactly why the container looked like it was "crash-looping" with no consistent error: it wasn't crashing, it was being reborn from scratch, repeatedly.

Root cause: WSL2 has a default idle-timeout that powers off a distro's lightweight VM once nothing is actively "attached" to it. This session had been driving that distro through many separate one-off `wsl -d Ubuntu-22.04 -- <command>` invocations (from an orchestrating process outside the distro) — each one attaches briefly, runs, and detaches, which is exactly the pattern that repeatedly re-arms the idle timer, even with `dockerd` running as a real background systemd service inside. Fix:

```ini
[wsl2]
networkingMode=mirrored
vmIdleTimeout=-1
```

(`wsl --shutdown` to apply, then re-check the network category from the previous gotcha, since that's another thing every `wsl --shutdown` can quietly break.)

**Generalizable lesson**: when a containerized service is "crash-looping" with no error message at all in its own logs, check the layer *below* the container before debugging the application — `dmesg`/kernel logs, the VM/host lifecycle, not just `docker logs`. An empty error message is itself informative: real application crashes almost always log *something* on the way down; a silent restart with nothing logged is a strong hint that something outside the process's own control killed it.

## A fourth gotcha, and the real final root cause: driving WSL through many separate one-off commands

Even after `vmIdleTimeout=-1`, the master kept restarting — every ~20 seconds, dockerd itself (not just the container) was being cleanly stopped and restarted by systemd, taking down unrelated services (`motd`, `systemd-tmpfiles-clean.timer`, `apport`) at the same moment. That pattern — an entire userspace teardown-and-restart cycle, not a single service crashing — was the same signature as the original whole-VM power-cycling problem, just one layer more targeted.

The actual trigger: the debugging process itself. Every `wsl -d Ubuntu-22.04 -- <command>` invocation from an external orchestrating process attaches to the distro, runs, and detaches — and it turns out there's a per-instance idle/session-teardown path distinct from (and not fully covered by) the VM-level `vmIdleTimeout` setting. Driving a distro through dozens of rapid, separate one-off commands (exactly what a debugging session tends to do — one `docker ps`, then a `docker logs`, then a `curl`, each as its own invocation) re-arms that per-instance idle trigger over and over, so the distro's whole userspace never gets to stay "attached" long enough to be considered non-idle.

**Fix**: hold one long-lived dummy session open against the distro for the duration of any real work — e.g. `wsl -d Ubuntu-22.04 -- sleep 999999` launched once in the background — so the instance always has an attached client, and run actual commands through separate calls as needed without that gap ever being read as "idle." Confirmed directly: zero `Stopping Docker` events in a 90-second window with one persistent session held open, versus one roughly every 20 seconds beforehand with no persistent session and only separate one-off commands.

**This was the true root cause of every restart symptom in this document from the second gotcha onward** — not a container config issue, not a Spark issue, not even something `vmIdleTimeout` alone could fully fix. If you're scripting/automating anything against a WSL2 distro (not just this Spark setup) via repeated separate `wsl -d <distro> -- ...` calls, hold a persistent session open for the duration, or you may see the exact same inexplicable service-restart symptoms.

## The concepts behind this

- **Docker networking modes**: `bridge` (default — an isolated virtual network NAT'd through the host), `host` (share the host's actual network namespace — no isolation, but real interface access), `none`. `host` mode is only as good as what "the host" actually is from Docker's point of view.
- **Docker Desktop's architecture on Windows/Mac**: unlike native Linux Docker (daemon runs directly on the OS), Docker Desktop always runs its daemon inside a lightweight VM (WSL2 on Windows, a similar hypervisor on Mac). "The host" as far as that daemon is concerned is the VM, not your actual laptop — this is *the* fundamental reason Docker behaves differently on Windows/Mac for anything network-adjacent.
- **WSL2 networking modes**: historically WSL2 (all of it, Docker Desktop or not) ran its own NAT'd virtual network. Mirrored networking mode (a newer WSL2 feature) changes this so WSL2 shares the Windows host's real interfaces directly — closing that gap for anything running *directly* in WSL2. It does **not** automatically extend into Docker Desktop's own nested engine, which is a separate, further-sandboxed thing living inside its own special `docker-desktop` distro.
- **Spark standalone cluster addressing**: Master and Worker daemons each take a single `host` value (via CLI `-h`/`--host` or env vars like `SPARK_LOCAL_IP`/`SPARK_WORKER_HOST`) that becomes both their bind address and the address they advertise to every other node for the lifetime of the cluster. There's no "advertise A, bind to B" split — which is precisely why containerized multi-host Spark clusters need real host networking, and why this is a recurring pain point anyone running standalone Spark in Docker eventually hits.

## Can this go into production as-is?

**No — treat this as a way to unblock local Windows-laptop testing, not a production architecture.** Reasons:

1. **It's a workaround for a client-OS limitation, not a deployment pattern.** Production inference infrastructure runs on real Linux servers/VMs/cloud instances (exactly what `docs/CLUSTER_SETUP_GUIDE.md`'s AWS EC2 approach already does) — there, `--network host` works natively with zero WSL2/mirroring/Docker-Desktop games. None of today's networking fight would exist on a Linux box.
2. **Running Docker CE inside WSL2 on someone's Windows workstation isn't durable infrastructure**: no real process supervision beyond `systemctl` inside a VM that stops when the laptop sleeps/reboots/updates, no real HA, and it depends on a specific Windows feature (WSL2 mirrored networking) that's still relatively new and has had rough edges across Windows versions.
3. **Standalone Spark itself is what most people graduate away from for production anyway** — see this repo's own comparison table in `docs/WINDOWS_CLUSTER_SETUP.md` ("Industry Approaches Comparison"): Kubernetes + Spark Operator or a managed service (EMR/Databricks) is the recommended production path, specifically because they handle node discovery/addressing/HA properly instead of relying on standalone Spark's simple (and, as we found, networking-fragile) master/worker model.
4. **Security posture**: we opened broad firewall ports on the Private profile and stood up ad-hoc unauthenticated HTTP file servers to move files around — completely reasonable for a one-off LAN test between two machines you own, but not something to carry into any shared or production network as-is.

**Where this pattern *is* legitimately useful:** local multi-"node" development/testing on Windows hardware before deploying to real Linux infrastructure — e.g., validating that this framework's distributed logic (partitioning, device-mode placement, executor scaling) behaves correctly across genuinely separate processes/machines, without needing cloud spend for every iteration. That's exactly the situation we were in this session.

**For actual production**, follow `docs/CLUSTER_SETUP_GUIDE.md` (real Linux hosts, native `--network host`) or move to Kubernetes + Spark Operator / a managed Spark service, as the repo's own docs already recommend.
