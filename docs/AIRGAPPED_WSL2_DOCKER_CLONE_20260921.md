# Air-Gapped WSL2 + Docker CE Setup — Clone Instead of Rebuild

How to get a fully working "Docker CE inside mirrored-networking WSL2 Ubuntu" environment (see `docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md`) onto a Windows machine with **no internet access at all**, by cloning an already-configured distro instead of reinstalling every package offline.

---

## The problem this solves

`wsl --install -d Ubuntu-22.04` and `apt-get install docker-ce ...` both need internet — they fetch from the Microsoft Store backend and Docker's/NVIDIA's apt repos respectively. An air-gapped machine can't do either. The repo's existing air-gapped docs (`AIRGAPPED_5NODE_DEPLOYMENT.md`, `AIRGAPPED_TROUBLESHOOTING.md`) solve this the traditional way: download every individual `.deb` package on an internet machine, transfer them, `dpkg -i` offline. That works, but it's a lot of small moving parts to get exactly right (dependency ordering, matching package versions, etc.).

## The shortcut: clone the whole distro

WSL2 has a built-in export/import mechanism that has nothing to do with the Microsoft Store — it just packages an entire Linux filesystem into a single `.tar` file, and rebuilds a distro from that tarball on any other machine. If distro A already has Docker CE, nvidia-container-toolkit, and even our application's Docker image all installed and working, exporting A and importing it as a new distro on machine B gives you an **exact clone** — no package installation step needed on B at all.

This is the same idea as shipping a pre-built VM image instead of an install script — you're moving finished state, not instructions for producing it.

## Steps

### 1. On an internet-connected machine, build the source distro once

(Already done for `192.168.4.104` in this session — see `WINDOWS_LAN_NETWORKING_FIX_20260921.md` for how that distro was built: mirrored networking enabled, Ubuntu-22.04 installed, Docker CE + nvidia-container-toolkit installed inside it.)

**Don't bundle the application image into this export if you already have it separately.** If you already have `multi-model-inference.tar` (or can get it to the air-gapped machine on its own, e.g. via the same LAN/USB transfer used earlier in this session), keep the distro export "bare" — Ubuntu + Docker CE + nvidia-container-toolkit only, no application image loaded — and `docker load` your own copy on the air-gapped side separately (step 8 below). Otherwise you're transferring the same multi-GB image twice for no reason. Remove any loaded images first:

```powershell
wsl -d Ubuntu-22.04 -- docker rm -f spark-master
wsl -d Ubuntu-22.04 -- docker rmi multi-model-inference:latest
wsl -d Ubuntu-22.04 -- docker system prune -af
```

### 2. Export it to a single (compressed) file

```powershell
wsl --shutdown
wsl --export Ubuntu-22.04 D:\ubuntu2204-docker-bare.tar.gz --format tar.gz
```

`wsl --shutdown` first ensures the distro isn't mid-write when exported. `--format tar.gz` compresses the export (default is an uncompressed plain `.tar` — the `--format` flag also supports `tar.xz` for smaller-but-slower compression). With the application image stripped out per step 1, this "bare" export is just the OS + Docker + toolkit — a small fraction of the size of a full export with a multi-GB image baked in.

### 3. Move that file to the air-gapped machine

Same offline-transfer problem as moving any large file to an air-gapped box — USB drive, write-once optical media, or whatever your organization's air-gap transfer process already requires (see `docs/internet_to_airgapped_transfer.md` for this repo's existing checksum/verification workflow, which applies here too — `sha256sum` the file before and after transfer).

### 4. Confirm the Windows features exist (should already, no internet needed)

WSL2 itself is a Windows OS feature, not a download — it ships in the Windows image. Air-gapped machines running a normal Windows 10/11 install already have the *capability*, just possibly not *enabled*:

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

Reboot if either line actually changed something (DISM says so).

**One real gap:** the WSL2 Linux kernel itself is normally fetched via Windows Update the first time WSL runs on a machine. If this air-gapped machine has *never* used WSL before, grab the standalone installer (`wsl_update_x64.msi` from `https://aka.ms/wsl2kernel`) on an internet machine and transfer it over too — install it once, offline, before continuing. If WSL already works there for anything else, this is a non-issue.

### 5. Import the cloned distro — no store, no internet, no package manager involved

```powershell
wsl --import Ubuntu-22.04 C:\WSL\Ubuntu-22.04 D:\ubuntu2204-docker-bare.tar.gz --version 2
```

`wsl --import <name> <install-location> <tarball> --version 2` unpacks the tarball (it auto-detects gzip/xz compression) as a brand-new WSL2 distro at the given install path. It's functionally identical to the original the moment this finishes — same Docker CE, same nvidia-container-toolkit, same everything except the application image (deliberately left out — see step 1).

### 5b. Load your own copy of the application image

Since the distro export was kept bare, load `multi-model-inference.tar` (the copy you already have on the air-gapped machine) into this newly-imported distro's Docker yourself:

```powershell
wsl -d Ubuntu-22.04 -- docker load -i /mnt/c/path/to/multi-model-inference.tar
```

(Adjust the path — anything under `C:\...` on Windows is reachable from inside WSL at `/mnt/c/...`.) Verify with `wsl -d Ubuntu-22.04 -- docker images`.

### 6. Enable mirrored networking on this machine too

This is a local Windows/WSL2 setting, not a download — it works offline exactly the same as it did on the source machine:

```powershell
@"
[wsl2]
networkingMode=mirrored
"@ | Set-Content -Path "$env:USERPROFILE\.wslconfig" -Encoding utf8
wsl --shutdown
```

### 7. Set the network adapter to Private and open the Spark ports — **do this every time, right after any `wsl --shutdown`**

Enabling mirrored networking (and any subsequent `wsl --shutdown`, including the one in step 6) can make Windows silently reclassify your Ethernet/Wi-Fi adapter from **Private** to **Public**. This happened on the master mid-session and broke cross-machine reachability even though every local/same-machine test still passed — `ping` worked, but `curl` from the other machine timed out, because Windows' far-stricter Public-profile firewall was silently blocking it. Ran into this after several `wsl --shutdown` cycles for exports, well after the initial setup — so **check this again any time you shut down and restart WSL**, not just once at the start.

```powershell
# Check current classification — run this after every wsl --shutdown
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory

# Fix it if it shows "Public" (adjust interface names to match your machine)
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
```

Then (one-time, persists across reboots — but re-run if you ever see the rules missing) open the ports the cluster actually needs, scoped to Private:

```powershell
New-NetFirewallRule -DisplayName "Spark Master" -Direction Inbound -LocalPort 7077,8080,4040 -Protocol TCP -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "Spark Worker" -Direction Inbound -LocalPort 8081 -Protocol TCP -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "Spark Executors" -Direction Inbound -LocalPort 30000-40000 -Protocol TCP -Action Allow -Profile Private
```

Both of these commands need an elevated (Administrator) PowerShell.

### 8. Verify

```powershell
wsl -d Ubuntu-22.04 -- docker --version
wsl -d Ubuntu-22.04 -- docker images
wsl -d Ubuntu-22.04 -- ip addr show
```

You should see Docker's version, the `multi-model-inference:latest` image (loaded separately in step 5b), and the machine's real IP addresses in the interface list (confirming mirrored networking took effect).

**Then verify reachability from a genuinely different machine on the LAN** (not from this machine talking to itself — same-machine tests can pass even when cross-machine access is actually blocked, exactly as happened in step 7's story):

```powershell
# Run this from the OTHER machine, not this one
curl.exe http://<this-machine's-IP>:8080/json/
```

---

## Concepts behind this

- **`wsl --export`/`--import` operate below the package-manager layer.** They don't care what's installed inside the distro or how it got there — they treat the whole Linux filesystem as one opaque blob. This is exactly why it sidesteps the air-gap problem: there's no `apt`/`dnf`/network call anywhere in the export or import path.
- **This layers on top of this repo's `docker save`/`docker load` pattern rather than replacing it**: `docker save`/`load` moves one container image (app + its dependencies); `wsl --export`/`import` moves the platform underneath it (OS + Docker engine + toolkit). Keeping the export "bare" and loading the application image separately (step 5b) means each tool handles the layer it's actually good at, instead of `wsl --export` re-packaging an image that `docker save` already packaged once.
- **`.wslconfig`'s `networkingMode=mirrored` is pure local configuration** — it changes how WSL2's virtual network adapter is set up on *this* machine, with no dependency on anything external. That's why it transfers cleanly to an air-gapped box: it's a setting, not a download.
- **The WSL2 kernel is the one piece that's genuinely separate from "the distro"** — it's shared infrastructure that every WSL2 distro on a machine runs on top of, updated independently of any individual distro's filesystem. That's why cloning a distro doesn't automatically bring the kernel with it, and why a never-before-used-WSL machine needs that one standalone installer.
- **Windows' network *category* (Private/Public/Domain) and the *firewall* are two separate layers that both have to agree.** The firewall rules only apply to whichever profile(s) you scoped them to; if Windows reclassifies the adapter into a different category — which mirrored networking's adapter churn can trigger — your existing rules silently stop applying, with no error anywhere. This is exactly the kind of failure that same-machine testing can't catch (loopback and same-host traffic don't go through this check the same way), which is why step 8 insists on testing from a second, physically different machine.
