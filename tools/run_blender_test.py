"""Run one Blender test with captured output and a bounded execution time."""

import math
import subprocess
import sys
import time
from pathlib import Path


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: run_blender_test.py BLENDER SCRIPT TIMEOUT_SECONDS")
    blender, script, timeout_text = sys.argv[1:]
    timeout = float(timeout_text)
    if not math.isfinite(timeout) or timeout <= 0:
        raise SystemExit("timeout must be positive")
    cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", script]
    started = time.monotonic()
    folder = Path("dist") / "blender-test-logs"
    folder.mkdir(parents=True, exist_ok=True)
    stem = Path(script).stem
    stdout_path, stderr_path = folder / f"{stem}.stdout.log", folder / f"{stem}.stderr.log"
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            result = subprocess.run(cmd, stdout=stdout, stderr=stderr, timeout=timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
            print(f"TIMEOUT: {script} exceeded {timeout:g}s; Blender process terminated", flush=True)
    print(f"Full stdout: {stdout_path}; stderr: {stderr_path}", flush=True)
    cycle_count = 0
    in_cycle = False
    with stdout_path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if "depsgraph" in line and "WARNING Dependency cycle detected:" in line:
                cycle_count += 1
                in_cycle = True
                if cycle_count == 1:
                    print(line.rstrip(), flush=True)
            elif in_cycle and line.lstrip().startswith("|"):
                continue
            else:
                in_cycle = False
                print(line.rstrip(), flush=True)
    if cycle_count:
        print(f"Dependency cycle warnings: {cycle_count}; complete details in {stdout_path}", flush=True)
    with stderr_path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            print(line.rstrip(), flush=True)
    print(f"== {script}: exit={code}, elapsed={time.monotonic() - started:.1f}s", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
