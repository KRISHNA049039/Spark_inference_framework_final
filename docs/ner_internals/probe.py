"""
Container probe - samples what is running and who talks to whom, from /proc only
(stdlib; works in every image of the simulation).

Each sample (one JSON line) holds:
  procs : pid -> ppid, command line, RSS, threads, number of open sockets
  conns : TCP sockets (local, remote, state) with the pids that own them
  net   : per-interface rx/tx byte counters

    python probe.py <out.jsonl> <seconds> <interval>
"""
import json
import os
import socket
import struct
import sys
import time

STATES = {"01": "ESTABLISHED", "02": "SYN_SENT", "03": "SYN_RECV", "04": "FIN_WAIT1", "05": "FIN_WAIT2",
          "06": "TIME_WAIT", "07": "CLOSE", "08": "CLOSE_WAIT", "09": "LAST_ACK", "0A": "LISTEN", "0B": "CLOSING"}


def procs():
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/stat") as f:
                st = f.read()
            fields = st[st.rfind(")") + 2:].split()
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
            if not cmd:
                continue  # kernel thread / zombie
            rss = thr = 0
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1])
                    elif line.startswith("Threads:"):
                        thr = int(line.split()[1])
            socks = []
            try:
                for fd in os.listdir(f"/proc/{pid}/fd"):
                    try:
                        link = os.readlink(f"/proc/{pid}/fd/{fd}")
                    except OSError:
                        continue
                    if link.startswith("socket:["):
                        socks.append(link[8:-1])
            except OSError:
                pass
            out[int(pid)] = {"ppid": int(fields[1]), "cmd": cmd[:600], "rss_kb": rss, "threads": thr, "socks": socks}
        except (OSError, IndexError, ValueError):
            continue
    return out


def _addr(s, v6):
    ip, port = s.split(":")
    if v6:
        b = bytes.fromhex(ip)
        b = b"".join(b[i:i + 4][::-1] for i in range(0, 16, 4))
        ip = socket.inet_ntop(socket.AF_INET6, b)
        if ip.startswith("::ffff:"):
            ip = ip[7:]
    else:
        ip = socket.inet_ntop(socket.AF_INET, struct.pack("<I", int(ip, 16)))
    return f"{ip}:{int(port, 16)}"


def conns():
    res = []
    for fn, v6 in (("/proc/net/tcp", False), ("/proc/net/tcp6", True)):
        try:
            with open(fn) as f:
                lines = f.read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            p = line.split()
            res.append({"local": _addr(p[1], v6), "remote": _addr(p[2], v6),
                        "state": STATES.get(p[3], p[3]), "inode": p[9]})
    return res


def netdev():
    d = {}
    with open("/proc/net/dev") as f:
        for line in f.read().splitlines()[2:]:
            name, rest = line.split(":", 1)
            v = rest.split()
            d[name.strip()] = {"rx": int(v[0]), "tx": int(v[8])}
    return d


def snap():
    ps, cs = procs(), conns()
    owner = {}
    for pid, p in ps.items():
        for s in p["socks"]:
            owner.setdefault(s, []).append(pid)
    for c in cs:
        c["pids"] = owner.get(c.pop("inode"), [])
    for p in ps.values():
        p["socks"] = len(p["socks"])
    return {"t": time.time(), "host": socket.gethostname(), "procs": ps, "conns": cs, "net": netdev()}


if __name__ == "__main__":
    out, dur, every = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    end = time.time() + dur
    with open(out, "a") as f:
        while True:
            f.write(json.dumps(snap()) + "\n")
            f.flush()
            if time.time() >= end:
                break
            time.sleep(every)
