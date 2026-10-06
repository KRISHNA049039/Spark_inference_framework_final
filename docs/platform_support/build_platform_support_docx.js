// build_platform_support_docx.js - "Running the Cluster on Windows and Ubuntu" (Word, A4 portrait).
// What works on Windows (Docker Desktop + WSL2) and on Ubuntu (Docker Engine), what differs,
// how to set up each, and how to build multi-machine clusters. Needs the `docx` npm package.
//   node docs/platform_support/build_platform_support_docx.js [out.docx]
const path = require("path");
const kit = require("./docx_kit")();

const REPO = path.join(__dirname, "..", "..");
const OUT = process.argv[2] || path.join(REPO, "docs", "WINDOWS_AND_UBUNTU_SUPPORT.docx");
const { H1, H2, P, B, N, code, table } = kit;
const note = (t) => kit.note(t);
const warn = (t) => kit.warn(t);

// ================================================================== CONTENT
kit.title("Running the Cluster on Windows and Ubuntu", "What works on Windows (Docker Desktop + WSL2) and on Ubuntu (Docker Engine), what differs, how to set up each, and how to build clusters that span several machines.");
table([["item", "value"],
  ["System", "pytorch-spark-inference-platform - Spark 3.5.1 cluster, NER pipeline (service and cluster mode), tensor models, HDFS model store"],
  ["Based on", "Runs on a Windows 11 laptop (Docker Desktop 29.5.3, Compose 5.1.4, WSL2 kernel 6.18, NVIDIA GTX 1650, driver 610.62): NER in both modes and all 12 air-gap simulation tests passed. AWS runs on Ubuntu 22.04 (Deep Learning Base AMI). The two-machine Windows LAN test recorded in docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md"],
  ["Audience", "Engineers setting up the cluster on Windows or Ubuntu machines"],
  ["Related", "DOCKER_CONTAINERS_AND_COMPOSE.pdf (every image and compose file), CLUSTER_RUNBOOK_MODES_AND_TESTS.pdf (modes and tests), AIRGAP_DEPENDENCIES_AND_VERSIONS.pdf (what to carry)"]],
  [18, 82]);
kit.toc();

// ------------------------------------------------------------------ 1
H1("1. The short answer", true);
P("**Yes - the same images and compose files run on both.** Every container is a Linux image (linux/amd64), so inside the containers Windows and Ubuntu are identical: the same Python 3.11, Java 17, Spark 3.5.1, torch 2.6 and models. What differs is the Docker layer underneath: on Ubuntu the Docker daemon runs directly on the machine; on Windows, Docker Desktop runs it inside a hidden Linux VM (WSL2). That difference only matters for networking between machines, memory, disk speed and GPU setup.");
table([["setup", "Windows (Docker Desktop + WSL2)", "Ubuntu (Docker Engine)"],
  ["One machine, whole cluster", "Works - tested: NER in both modes, all 12 air-gap simulation tests", "Works - same compose files and commands"],
  ["GPU", "NVIDIA Windows driver only; Docker Desktop passes the GPU into containers", "NVIDIA driver + nvidia-container-toolkit"],
  ["Several machines in one cluster", "Not with Docker Desktop (Spark master fails with BindException). Workaround: Docker CE inside a WSL2 Ubuntu distro with mirrored networking - for testing, not production", "Works - `docker run --network host` on each machine (how the AWS runs were done)"],
  ["Mixed Windows + Ubuntu nodes", "Possible when the Windows nodes use the WSL2 Docker CE workaround", "Works"],
  ["Recommended for", "Development and tests on one machine", "Multi-machine clusters and production"]],
  [22, 40, 38]);

// ------------------------------------------------------------------ 2
H1("2. Why it works on both");
B(["**Linux containers everywhere.** Docker Desktop on Windows runs Linux containers in a WSL2 VM; Ubuntu runs them natively. The images are built once and run unchanged on both.",
   "**The GPU reaches the container differently.** On Windows the NVIDIA Windows driver exposes the GPU to WSL2 (GPU paravirtualisation) and Docker Desktop hands it to containers that request it. On Ubuntu the NVIDIA Container Toolkit injects the host driver into the container. In both cases the CUDA runtime libraries come from the image (torch cu126 wheels); only the driver comes from the host.",
   "**Networking is where they differ.** On Ubuntu `--network host` gives a container the machine's real network card. On Windows, Docker Desktop's \"host\" is the WSL2 VM, which sits behind NAT - containers cannot bind the machine's real LAN address. Inside one machine that does not matter (containers talk over Docker's own network); across machines it does, because Spark executors must connect back to the driver on its advertised address."]);

// ------------------------------------------------------------------ 3
H1("3. Compose files and scripts per operating system");
table([["file / script", "Windows", "Ubuntu", "notes"],
  ["docker-compose.laptop.yml", "yes", "yes", "tensor models, 1 GPU worker"],
  ["docker-compose.cluster.yml", "yes", "yes", "bridge network; its GPU worker has the GPU disabled"],
  ["docker-compose.ner_translate.yml", "yes", "yes", "NER in-process (Option A)"],
  ["docker-compose.ner_translate_server.yml", "yes", "yes", "NER waiter / kitchen (Option B); start with deploy/scripts/setup_ner_translate_server.sh (bash)"],
  ["docker-compose.airgap_sim.yml", "yes", "yes", "HDFS model store + both NER modes; tested on Windows"],
  ["docker-compose.cluster.linux.yml", "no", "yes", "network_mode: host - only meaningful on Linux"],
  ["docker-compose.yml", "no (as written)", "yes", "`runtime: nvidia` is not provided by Docker Desktop; on Windows use `--gpus all` / deploy.resources instead"],
  ["*.ps1 scripts (airgap_sim_tests.ps1, start_cluster.ps1, run_aws_*.ps1)", "yes", "with PowerShell 7 (pwsh)", "some defaults are Windows paths, e.g. airgap_sim_tests.ps1 -WeightsSrc"],
  ["*.sh scripts (setup_*.sh, modes_node.sh, build_*.sh)", "Git Bash or WSL", "yes", "host-network deployment scripts are meant for Linux hosts"]],
  [34, 14, 16, 36]);

// ------------------------------------------------------------------ 4
H1("4. Setting up Windows (one machine)");
H2("4.1 Requirements");
table([["component", "version / setting", "why"],
  ["Windows", "10 22H2 or 11, virtualisation enabled in the BIOS", "WSL2 needs it"],
  ["WSL2", "`wsl --update`; the kernel used here was 6.18", "Docker Desktop's backend"],
  ["Docker Desktop", "WSL2 backend (tested: 29.5.3, Compose 5.1.4)", "Linux containers + GPU support"],
  ["NVIDIA driver", "the normal Windows driver (tested: 610.62) - nothing to install inside WSL", "GPU paravirtualisation into WSL2"],
  ["Memory for the VM", "`%USERPROFILE%\\.wslconfig`: `[wsl2]` `memory=6GB` or more", "the NER model server needs ~4 GB while loading; the default limit is too small on an 8 GB machine"]],
  [22, 44, 34]);
H2("4.2 Start and check");
code(["# PowerShell, repository root",
  "wsl --shutdown                                   # after editing .wslconfig; then start Docker Desktop",
  "docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi   # GPU visible in containers?",
  "docker compose -f deploy/docker-compose.laptop.yml up -d                    # tensor-model cluster",
  "$env:MODEL_STORE_URI = \"hdfs://hdfs-namenode:8020/models/weights\"",
  "docker compose -f deploy/docker-compose.airgap_sim.yml --profile hdfs --profile service up -d",
  ".\\deploy\\airgap_sim_tests.ps1                                              # the 12 tests"].join("\n"));
H2("4.3 Tips specific to Windows");
B(["**Memory is capped by the WSL2 VM**, not by the machine: 6 GB was needed to run HDFS + the model server; other containers (e.g. a database) compete for the same 6 GB.",
   "**Bind mounts from Windows drives are slow.** Files under `D:\\...` reach the containers through the WSL2 file-sharing layer; model loads measured 20-60 MB/s. Keep large, hot data in Docker named volumes (the model caches already are) or inside the WSL filesystem.",
   "**Git line endings** - see section 8 before cloning the repository on another Windows machine.",
   "**Paths in environment variables** can be Windows paths (`$env:MODEL_FS_DIR = \"D:\\models\"`); Docker Desktop translates them for bind mounts."]);

// ------------------------------------------------------------------ 5
H1("5. Setting up Ubuntu (one machine or a cluster node)");
H2("5.1 Requirements");
table([["component", "version / setting", "why"],
  ["Ubuntu", "22.04 LTS (used on AWS; 24.04 should behave the same but was not tested here)", "host OS"],
  ["Docker Engine + compose plugin", "docker-ce, docker-ce-cli, containerd.io, docker-buildx-plugin, docker-compose-plugin (Compose v2)", "profiles and `name:` in the compose files need Compose v2"],
  ["NVIDIA driver", ">= 525.60.13 (CUDA 12 minor-version compatibility); >= 560.28 recommended (native CUDA 12.6)", "the images carry CUDA 12.6 runtime libraries"],
  ["NVIDIA Container Toolkit", "nvidia-container-toolkit, then `nvidia-ctk runtime configure --runtime=docker`", "gives containers the GPU (`--gpus all`)"],
  ["Air gap", "carry the .deb packages for all of the above (or install before the machine is isolated)", "no apt repositories inside the gap"]],
  [26, 46, 28]);
H2("5.2 Install and check");
code(["sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
  "sudo apt-get install -y nvidia-container-toolkit",
  "sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker",
  "sudo usermod -aG docker $USER                    # log out / in",
  "docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi",
  "docker compose -f deploy/docker-compose.laptop.yml up -d      # same files as on Windows"].join("\n"));
P("On a single Ubuntu machine the compose files behave exactly as on Windows, with no VM memory cap and native disk speed. `docker-compose.cluster.linux.yml` (host networking) and `docker-compose.yml` (`runtime: nvidia`) also work here.");

// ------------------------------------------------------------------ 6
H1("6. Clusters across several machines");
H2("6.1 Ubuntu nodes (recommended)");
P("Each machine runs its containers with `--network host`, so Spark daemons bind and advertise the machine's real IP. The repository's scripts do this: deploy/scripts/setup_master.sh and setup_gpu_worker.sh, and modes_node.sh (used for the AWS CPU + GPU node runs).");
code(["# master machine (IP 10.0.0.10)",
  "docker run -d --name spark-master --network host -e SPARK_LOCAL_IP=10.0.0.10 multi-model-inference:latest \\",
  "    bash -c \"start-master.sh -h 10.0.0.10 && tail -f /opt/spark/logs/*master*\"",
  "# each GPU worker machine (IP 10.0.0.11)",
  "docker run -d --name spark-gpu-worker --network host --gpus all --shm-size=4g -e SPARK_LOCAL_IP=10.0.0.11 \\",
  "    multi-model-inference:latest bash -c \"start-worker.sh spark://10.0.0.10:7077 -c 4 -m 12g && tail -f /opt/spark/logs/*worker*\""].join("\n"));
table([["open between the machines", "port(s)", "used by"],
  ["Spark master", "7077 (RPC), 8080 (UI)", "workers and drivers register; web UI"],
  ["Spark workers", "8081 (UI) + a random worker port", "master -> worker"],
  ["driver", "4040 (UI) + random RPC and BlockManager ports", "executors connect back to the driver - fix them with `spark.driver.port` / `spark.blockManager.port` if the firewall needs fixed ports"],
  ["model server (service mode)", "8000", "executors -> kitchen"],
  ["HDFS", "8020, 9870 (namenode), 9864, 9866 (datanodes)", "model store"]],
  [26, 34, 40]);
warn("Build the images with `--target final` (or load a saved image) on every node: deploy/Dockerfile's default build target is the torch-less `lean` stage, and setup_master.sh / setup_gpu_worker.sh build without a target. Every node must run the same image so Python and package versions match.");
H2("6.2 Windows nodes (testing only)");
P("Docker Desktop cannot take part in a multi-machine cluster: its containers never see the machine's real LAN address, so the Spark master fails with `java.net.BindException: Cannot assign requested address`. `--network host`, WSL2 mirrored networking alone, and Docker Desktop's host-networking toggle were all tried and did not fix it. What worked (docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md):");
N(["In `%USERPROFILE%\\.wslconfig`: `[wsl2]` `networkingMode=mirrored` and `vmIdleTimeout=-1`, then `wsl --shutdown`.",
   "Install a separate Ubuntu distro: `wsl --install -d Ubuntu-22.04` (not Docker Desktop's own distro).",
   "Inside it, install Docker CE and nvidia-container-toolkit the normal Linux way (section 5.2).",
   "Move the image across with `docker save` (Docker Desktop) / `docker load` (the WSL Docker CE engine).",
   "Run the containers with `--network host` inside that distro, exactly as on Ubuntu (6.1).",
   "Check the Windows network profile stays **Private** after every `wsl --shutdown`: `Get-NetConnectionProfile`; fix with `Set-NetConnectionProfile -InterfaceAlias \"Ethernet\" -NetworkCategory Private`.",
   "Keep one long-lived session open against the distro (`wsl -d Ubuntu-22.04 -- sleep 999999`) while it serves: short one-off `wsl` commands let the distro shut down and restart Docker with every container."]);
note("Verdict from that test: good for multi-node testing on Windows hardware, **not a production architecture** - the WSL VM stops when the laptop sleeps or updates, there is no real supervision, and the firewall changes are broad. Production clusters run on Linux hosts (section 6.1).");
H2("6.3 Mixed Windows and Ubuntu nodes");
P("Spark does not care about the host OS: all nodes run the same Linux image. A Windows machine can join an Ubuntu cluster as a worker (or run the master) when it uses the WSL2 Docker CE setup of 6.2, with the same image, reachable ports and the same shared data mount.");

// ------------------------------------------------------------------ 7
H1("7. Differences to expect");
table([["aspect", "Windows (Docker Desktop)", "Ubuntu"],
  ["memory for containers", "the WSL2 VM limit (.wslconfig memory=)", "the machine's RAM"],
  ["disk speed of bind mounts", "Windows drives via file sharing - slow (20-60 MB/s measured for model loads)", "native"],
  ["GPU plumbing", "Windows driver + WSL2 GPU paravirtualisation; GPU-to-host copies measured slow (0.06-0.3 GB/s) - small impact here", "driver + container toolkit; native PCIe speed"],
  ["networking between machines", "not possible with Docker Desktop; WSL2 Docker CE workaround", "`--network host`"],
  ["GPU syntax in compose", "`deploy.resources` / `--gpus all`", "same, plus legacy `runtime: nvidia`"],
  ["scripts", ".ps1 native; .sh via Git Bash / WSL", ".sh native; .ps1 via pwsh"],
  ["line endings", "risk of CRLF in a fresh clone (section 8)", "LF"],
  ["best use", "development, one-machine tests, demos", "multi-node clusters, production, air-gapped deployment"]],
  [24, 42, 34]);

// ------------------------------------------------------------------ 8
H1("8. Line endings - one thing to fix before sharing the repository");
P("The shell scripts are currently LF (checked byte by byte), which is what Linux needs. But this machine has `git config core.autocrlf true` and the repository has no `.gitattributes`, so a fresh `git clone` on another Windows machine may check the .sh files out with CRLF endings. Scripts copied into or mounted in the Linux containers then fail with `/bin/bash^M: bad interpreter`. A `.gitattributes` in the repository root prevents it:");
code(["*.sh   text eol=lf",
  "*.py   text eol=lf",
  "*.yml  text eol=lf",
  "*.ps1  text eol=crlf"].join("\n"));

// ------------------------------------------------------------------ 9
H1("9. Checklist");
table([["check", "command", "expected"],
  ["Docker and Compose", "`docker version` / `docker compose version`", "Compose v2 or newer"],
  ["GPU in containers", "`docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi`", "your GPU and driver listed"],
  ["memory available to Docker", "`docker info --format \"{{.MemTotal}}\"`", ">= 6 GB for the NER model server + HDFS"],
  ["images present", "`docker images`", "spark-lean, ner-translate-server (and the others you need)"],
  ["one-machine cluster", "`docker compose -f deploy/docker-compose.airgap_sim.yml --profile hdfs --profile service up -d`", "all services healthy"],
  ["multi-machine (Ubuntu / WSL Docker CE)", "open http://<master>:8080 from another machine", "every worker listed as ALIVE"],
  ["end to end", "`.\\deploy\\airgap_sim_tests.ps1` or one `submit_pipeline_job.py` run", "PASS / documents processed"]],
  [26, 50, 24]);

// ================================================================== DOCUMENT
kit.write(OUT, "Running the Cluster on Windows and Ubuntu");
