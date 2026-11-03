#!/usr/bin/env python3
"""Smoke test an INSTALLED Prompt Vault (wheel in a venv, pipx, uv tool, uvx ...). Stdlib only.

    python tools/dist_smoke.py --bin PATH_TO_promptvault [--port N] [--data-dir DIR]
                               [--expect-xlsx 0|1] [--expect-seed 213] [--expect-version X]

Checks: `promptvault version`, serve on a spare port, health, `/` serves the UI, the seed library is
loaded, create + list through the API, `export json`, XLSX unavailable/available as expected, then
stops the server it started (whole process tree) and confirms the port is closed. A separate
command with spaces (for example a uvx call) can be passed as --bin "uvx --from X promptvault".
Only touches --data-dir (default: a fresh temporary folder, removed at the end) and the process
it starts.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

FAILED: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("ok:   " if cond else "FAIL: ") + msg, flush=True)
    if not cond:
        FAILED.append(msg)


def port_open(port: int) -> bool:
    for host in ("localhost",):
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            continue
    return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return int(s.getsockname()[1])


def get(url: str, timeout: float = 10) -> tuple[int, bytes, str]:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (localhost only)
        return r.status, r.read(), r.headers.get("content-type", "")


def stop_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True, help="the promptvault command (may contain spaces)")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--expect-xlsx", type=int, choices=[0, 1], default=0)
    ap.add_argument("--expect-seed", type=int, default=213)
    ap.add_argument("--expect-version", default="")
    ap.add_argument("--min-seed", action="store_true", help="seed count may be larger")
    args = ap.parse_args()

    cmd = shlex.split(args.bin, posix=(os.name != "nt")) if " " in args.bin else [args.bin]
    cmd = [c.strip('"') for c in cmd]
    port = args.port or free_port()
    own_dir = not args.data_dir
    data = args.data_dir or tempfile.mkdtemp(prefix="pv-dist-smoke-")
    work = tempfile.mkdtemp(prefix="pv-dist-cwd-")  # no stray .env from the caller's folder
    env = {k: v for k, v in os.environ.items() if not k.startswith("PV_")}
    env.update({"PV_DATA_DIR": data, "PV_PORT": str(port), "PYTHONUNBUFFERED": "1"})
    base = f"http://localhost:{port}"
    proc: subprocess.Popen[bytes] | None = None

    def run(*a: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*cmd, *a], env=env, cwd=work, capture_output=True, text=True, timeout=180, check=False
        )

    try:
        v = run("version")
        ok(v.returncode == 0 and bool(v.stdout.strip()), f"promptvault version -> {v.stdout.strip()}")
        if args.expect_version:
            ok(v.stdout.strip() == args.expect_version, f"version is {args.expect_version}")

        proc = subprocess.Popen(
            [*cmd, "serve", "--port", str(port)], env=env, cwd=work,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        healthy = False
        for _ in range(90):
            if proc.poll() is not None:
                break
            try:
                healthy = get(f"{base}/api/v1/health", 3)[0] == 200
                if healthy:
                    break
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        ok(healthy, f"health answers on port {port}")
        if not healthy:
            return 1

        code, body, ctype = get(base + "/")
        ok(code == 200 and "text/html" in ctype and b"<div id=\"root\"" in body, "/ serves the UI")
        code, body, _ = get(base + "/some/spa/route")
        ok(code == 200 and b"<div id=\"root\"" in body, "SPA fallback serves the UI")
        _, body, _ = get(f"{base}/api/v1/version")
        ok("version" in json.loads(body), f"/api/v1/version {body.decode()[:80]}")

        _, body, _ = get(f"{base}/api/v1/prompts?limit=1")
        total = json.loads(body)["total"]
        ok(total == args.expect_seed or (args.min_seed and total >= args.expect_seed),
           f"seed library loaded (total {total}, expected {args.expect_seed})")

        req = urllib.request.Request(
            f"{base}/api/v1/prompts",
            data=json.dumps({"title": "Dist smoke check", "body": "Created by dist_smoke."}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            ok(r.status in (200, 201), f"create via API ({r.status})")
        _, body, _ = get(f"{base}/api/v1/prompts?limit=1")
        ok(json.loads(body)["total"] == total + 1, "list shows the new prompt")
        ls = run("list", "--limit", "500")
        ok(ls.returncode == 0 and "Dist smoke check" in ls.stdout, "CLI list sees it")

        ex = run("export", "json", "-")
        ok(ex.returncode == 0 and "Dist smoke check" in ex.stdout, f"export json ({len(ex.stdout)} bytes)")
        xl = run("export", "xlsx", os.path.join(work, "out.xlsx"))
        if args.expect_xlsx:
            ok(xl.returncode == 0 and os.path.getsize(os.path.join(work, "out.xlsx")) > 1000,
               "export xlsx works (extra installed)")
        else:
            ok(xl.returncode != 0 and "prompt-vault[xlsx]" in (xl.stdout + xl.stderr),
               "export xlsx is unavailable and names the extra")
    finally:
        if proc is not None:
            stop_tree(proc)
            time.sleep(1)
            ok(not port_open(port), f"port {port} closed after stopping the server")
        shutil.rmtree(work, ignore_errors=True)
        if own_dir:
            shutil.rmtree(data, ignore_errors=True)

    if FAILED:
        print(f"{len(FAILED)} check(s) failed")
        return 1
    print("DIST SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
