#!/usr/bin/env bash
# =============================================================================
# LAB ONLY - run the 2-machine lab cluster (deploy/docker-compose.lab_lan.yml)
# in server mode and cluster mode with Ada's three images, and collect results.
# Run on the MASTER machine, from the repo root, in the WSL2 Ubuntu shell:
#
#   bash deploy/lab_lan_tests.sh                    # server, then cluster
#   bash deploy/lab_lan_tests.sh cluster            # one mode
#   LAB_GPU=1 bash deploy/lab_lan_tests.sh          # lab-only cu128 GPU run (not an Ada check)
#   LAB_EXPECT_WORKERS=1 bash deploy/lab_lan_tests.sh   # master machine only
#
# The remote machine is started by hand: the script prints the command and
# waits until the remote worker has registered.
# Output: results/lab_lan_<timestamp>/ (summary.txt, summary.json, per-mode logs + result JSON)
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

MODES=("$@"); [ ${#MODES[@]} -eq 0 ] && MODES=(server cluster)
ENV_FILE=deploy/lab_lan.env
set -a; . "$ENV_FILE"; set +a
EXPECT=${LAB_EXPECT_WORKERS:-2}
REMOTE_IP=${LAB_REMOTE_IP:-192.168.4.101}
INPUT=${LAB_INPUT:-/app/data/ner_samples}
NDOCS=$(ls data/ner_samples | wc -l)
EXPECTED_ENTITIES="8 27 33 6 29 39"      # docs/NER_CLUSTER_FROM_DEPS_IMAGE_WSL_20261005.md 10.7 (GPU run)
COMPOSE=(docker compose -f deploy/docker-compose.lab_lan.yml)
[ "${LAB_GPU:-0}" = 1 ] && COMPOSE+=(-f deploy/docker-compose.lab_lan.gpu.yml)
COMPOSE+=(--env-file "$ENV_FILE")
OUT=results/lab_lan_$(date +%Y%m%d_%H%M%S)$([ "${LAB_GPU:-0}" = 1 ] && echo _gpu)
mkdir -p "$OUT"
SUMMARY=()

say()  { echo "      $*" | tee -a "$OUT/$CUR.log"; }
pass() { SUMMARY+=("$1|PASS|$2"); echo -e "  => \e[32mPASS\e[0m $2"; }
fail() { SUMMARY+=("$1|FAIL|$2"); echo -e "  => \e[31mFAIL\e[0m $2"; }
alive_workers() { curl -s --max-time 5 "http://$LAB_MASTER_IP:8080/json/" | python3 -c "import json,sys; print(json.load(sys.stdin).get('aliveworkers',0))" 2>/dev/null || echo 0; }

# ------------------------------------------------------------------ L01
CUR=L01; echo; echo "[L01] Prerequisites (master machine)"
ok=1
docker info >/dev/null 2>&1 || { say "Docker engine not reachable"; ok=0; }
say "docker $(docker version -f '{{.Server.Version}}' 2>/dev/null) (28+ needed for the image mount)"
ip -4 addr | grep -q "inet $LAB_MASTER_IP/" && say "LAN IP $LAB_MASTER_IP present (mirrored networking ok)" \
    || { say "LAN IP $LAB_MASTER_IP NOT visible here - Docker Desktop or mirrored networking off?"; ok=0; }
if [ "${LAB_GPU:-0}" = 1 ]; then IMAGES="$LAB_MMI_GPU_IMAGE $LAB_LEAN_IMAGE $LAB_SERVER_GPU_IMAGE $NER_DEPS_IMAGE"
else IMAGES="$LAB_MMI_IMAGE $LAB_LEAN_IMAGE $LAB_SERVER_IMAGE"; fi
for img in $IMAGES; do
    id=$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null) \
        && say "image $img $id" || { say "MISSING image $img"; ok=0; }
done
say "compare the image ids above with: docker image inspect -f '{{.Id}}' <image>  on Ada"
for f in gliner-multi/gliner_config.json nllb-200-distilled-600M/config.json hf_cache; do
    [ -e "$MODEL_FS_DIR/$f" ] && say "weights ok: $f" || { say "MISSING weights: $MODEL_FS_DIR/$f"; ok=0; }
done
[ $ok = 1 ] && pass L01 "prerequisites" || { fail L01 "prerequisites - fix the above first"; MODES=(); }

# ------------------------------------------------------------------ per mode
run_mode() {
    local mode=$1 id=$2 master="lab-$1-master" worker="lab-$1-worker"
    CUR=$id; echo; echo "[$id] $mode mode across $EXPECT machine(s)"
    "${COMPOSE[@]}" --profile "$mode-master" --profile "$mode-worker" up -d >>"$OUT/$id.log" 2>&1
    if [ "$EXPECT" -gt 1 ]; then
        echo -e "      \e[33mOn the remote machine ($REMOTE_IP), from the repo root, run now:\e[0m"
        local rc_cmd="docker compose -f deploy/docker-compose.lab_lan.yml$([ "${LAB_GPU:-0}" = 1 ] && echo ' -f deploy/docker-compose.lab_lan.gpu.yml') --env-file deploy/lab_lan.env"
        echo "        $rc_cmd --profile server-worker --profile cluster-worker down"
        echo "        LAB_NODE_IP=$REMOTE_IP $rc_cmd --profile $mode-worker up -d"
    fi
    local t0=$SECONDS n=0
    while [ $((SECONDS - t0)) -lt ${LAB_WAIT_SEC:-900} ]; do
        n=$(alive_workers); [ "$n" -ge "$EXPECT" ] && break; sleep 10
    done
    say "alive workers: $n of $EXPECT (master UI http://$LAB_MASTER_IP:8080)"
    [ "$n" -ge "$EXPECT" ] || { docker logs "$master" >"$OUT/$id.$master.log" 2>&1; fail "$id" "$mode: workers did not register"; return; }

    if [ "$mode" = server ]; then
        local t1=$SECONDS
        until [ "$(docker inspect -f '{{.State.Health.Status}}' lab-kitchen 2>/dev/null)" = healthy ] || [ $((SECONDS - t1)) -gt 900 ]; do sleep 10; done
        say "kitchen: $(docker inspect -f '{{.State.Health.Status}}' lab-kitchen 2>/dev/null) (remote kitchen: check with docker ps there)"
    else
        docker logs "$master" 2>&1 | grep install_ner_deps | tee -a "$OUT/$id.log" | sed 's/^/      /'
    fi

    local partitions=$(( EXPECT > 2 ? EXPECT : 2 )) execmem=512m
    [ "$mode" = cluster ] && execmem=4g
    local t2=$SECONDS
    docker exec -w /app "$master" python submit_pipeline_job.py --pipeline ner_translate --input "$INPUT" \
        --execution-mode "$mode" --master "spark://$LAB_MASTER_IP:7077" --partitions $partitions \
        --driver-memory 2g --executor-memory $execmem >"$OUT/$id.submit.log" 2>&1
    local rc=$? secs=$((SECONDS - t2))
    grep -E "execution-mode=|Processed [0-9]+ document|lang=|ERROR|written to" "$OUT/$id.submit.log" | sed 's/^/      /'
    local rjson; rjson=$(grep -o "results/ner_translate_[0-9_]*\.json" "$OUT/$id.submit.log" | tail -1)
    [ -n "$rjson" ] && cp "$rjson" "$OUT/$id.$mode.result.json"

    # executor-side evidence from this node's worker
    docker exec "$worker" bash -c "grep -rh 'model source\|model_store\|GPU detected\|Error' /opt/spark/work 2>/dev/null | tail -20" >"$OUT/$id.executor.log" 2>&1
    docker logs lab-kitchen >"$OUT/$id.kitchen.log" 2>&1 || true
    for c in "$master" "$worker"; do docker logs "$c" >"$OUT/$id.$c.log" 2>&1; done

    local verdict
    verdict=$(python3 - "$OUT/$id.$mode.result.json" "$NDOCS" "$EXPECT" "$EXPECTED_ENTITIES" <<'PY'
import json, sys
path, ndocs, expect, want = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4].split()
try:
    r = json.load(open(path))
except Exception as e:
    print(f"FAIL|no result JSON ({e})"); sys.exit()
res = r.get("results", {})
errs = [k for k, v in res.items() if v.get("error")]
hosts = sorted({p.get("hostname") for p in r.get("partition_details", [])})
counts = [len(res[k].get("entities_unique", [])) for k in sorted(res) if not res[k].get("error")]
msg = (f"{len(res)}/{ndocs} docs, errors={len(errs)}, hosts={hosts}, "
       f"entities={counts}, elapsed={r.get('elapsed_time')}s")
ok = len(res) == ndocs and not errs and len(hosts) >= expect
if sorted(counts) != sorted(int(x) for x in want):
    msg += f" (differs from the GPU reference {want} - compare server vs cluster below)"
print(("PASS|" if ok else "FAIL|") + msg)
PY
)
    say "submit rc=$rc in ${secs}s: ${verdict#*|}"
    [ "${verdict%%|*}" = PASS ] && [ $rc -eq 0 ] && pass "$id" "$mode: ${verdict#*|}" || fail "$id" "$mode: ${verdict#*|}"

    "${COMPOSE[@]}" --profile "$mode-master" --profile "$mode-worker" down >>"$OUT/$id.log" 2>&1
    [ "$EXPECT" -gt 1 ] && say "master side stopped; the remote worker is stopped by the next mode's down command (or run it by hand)"
}

i=2
for m in "${MODES[@]}"; do
    case $m in server|cluster) run_mode "$m" "L0$i"; i=$((i+1));; *) echo "unknown mode $m";; esac
done

# ------------------------------------------------------------------ server vs cluster
CUR=summary
S=$(ls "$OUT"/*.server.result.json 2>/dev/null | head -1); C=$(ls "$OUT"/*.cluster.result.json 2>/dev/null | head -1)
if [ -n "$S" ] && [ -n "$C" ]; then
    echo; echo "[L9] server vs cluster: same entities per document?"
    v=$(python3 - "$S" "$C" <<'PY'
import json, sys
a, b = (json.load(open(p))["results"] for p in sys.argv[1:3])
diff = [k for k in sorted(set(a) | set(b))
        if sorted(map(str, a.get(k, {}).get("entities_unique", []))) != sorted(map(str, b.get(k, {}).get("entities_unique", [])))]
print(("PASS|identical for all %d documents" % len(a)) if not diff else ("FAIL|differ: " + ", ".join(diff)))
PY
)
    [ "${v%%|*}" = PASS ] && pass L9 "${v#*|}" || fail L9 "${v#*|}"
fi

echo
for l in "${SUMMARY[@]}"; do IFS='|' read -r t r d <<<"$l"; printf "%-4s %-5s %s\n" "$t" "$r" "$d"; done | tee "$OUT/summary.txt"
printf "%s\n" "${SUMMARY[@]}" | python3 -c "import json,sys; print(json.dumps([dict(zip(('test','result','detail'),l.rstrip('\n').split('|',2))) for l in sys.stdin], indent=2))" >"$OUT/summary.json"
echo "Logs and results: $OUT"
