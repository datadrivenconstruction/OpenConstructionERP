"""Cross-platform serve lifecycle for the published-wheel check (Linux, macOS, Windows).

  life.py start <venv> <data> <log>   start serve in its own process group, pid -> <data>.pid
  life.py stop  <venv> <data>         stop serve (graceful, then by pid tree), stop the
                                      embedded postmaster, assert port 8080 is free
"""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

WIN = os.name == "nt"
PORT = 8080


def exe(venv, name):
    return str(Path(venv) / ("Scripts" if WIN else "bin") / (name + (".exe" if WIN else "")))


def port_free():
    # Ask whether anything accepts on the port. A bind test reads a socket in
    # TIME_WAIT as busy on Linux and macOS, which is not a live server.
    with socket.socket() as s:
        s.settimeout(2)
        return s.connect_ex(("127.0.0.1", PORT)) != 0


def alive(pid):
    if WIN:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start(venv, data, log):
    if not port_free():
        sys.exit("FAIL: port 8080 busy before start")
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WIN else {"start_new_session": True}
    fh = open(log, "wb")
    p = subprocess.Popen(
        [exe(venv, "openconstructionerp"), "serve", "--host", "127.0.0.1", "--port", str(PORT), "--data-dir", data, "--demo"],
        stdin=subprocess.DEVNULL,
        stdout=fh,
        stderr=subprocess.STDOUT,
        **kw,
    )
    Path(data + ".pid").write_text(str(p.pid))
    print(f"started serve pid {p.pid} -> {log}")


def stop(venv, data):
    pid = int(Path(data + ".pid").read_text())
    if alive(pid):
        if WIN:
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(pid, signal.SIGTERM)
        for _ in range(60):
            if not alive(pid):
                break
            time.sleep(1)
        if alive(pid):
            print("NOTE: serve still alive 60 s after the graceful signal, killing its tree by pid")
            if WIN:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"])
            else:
                os.killpg(pid, signal.SIGKILL)
    pgdata = Path(data) / "pgdata"
    if (pgdata / "postmaster.pid").exists():
        binpath = subprocess.run(
            [exe(venv, "python"), "-c", "from pixeltable_pgserver.utils import POSTGRES_BIN_PATH as p; print(p)"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        pg_ctl = str(Path(binpath) / ("pg_ctl.exe" if WIN else "pg_ctl"))
        subprocess.run([pg_ctl, "-D", str(pgdata), "-m", "fast", "-w", "-t", "60", "stop"])
    time.sleep(3)
    rc = 0
    if (pgdata / "postmaster.pid").exists():
        print("FAIL: postmaster.pid still present after pg_ctl stop")
        rc = 1
    if not port_free():
        print("FAIL: port 8080 still held after stop")
        rc = 1
    if rc == 0:
        print("stopped cleanly")
    sys.exit(rc)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "start":
        start(*sys.argv[2:5])
    elif cmd == "stop":
        stop(*sys.argv[2:4])
    else:
        sys.exit(f"unknown command {cmd}")
