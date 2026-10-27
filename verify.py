"""Quick repo check: runs EVERYTHING in demo mode and reports what works.

Run:  python verify.py

Use it before presenting and before publishing. It costs nothing: demo mode is
forced, so no API key is needed. Each step runs as its own process with output
captured, which also catches Windows console-encoding problems.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
STEPS = [
    ("build the database", ["data/seed.py"]),
    ("lesson 2: what Claude sees (stdio)", ["lessons/02_what_claude_sees.py"]),
    ("lesson 3: attack the guard", ["lessons/03_attack_the_guard.py"]),
    ("lesson 4: Bella tour (3 roles)", ["lessons/04_bella_tour.py"]),
    ("mint a JWT", ["scripts/mint_token.py", "viewer", "--hours", "0.1"]),
    ("test suite (guard, tools, auth over HTTP + stdio)", ["-m", "pytest", "-q", "-p", "no:cacheprovider"]),
]
TIMEOUT_S = 300


def run(args: list[str]) -> tuple[bool, str, float]:
    started = time.perf_counter()
    try:
        r = subprocess.run([sys.executable, *args], cwd=ROOT, env={**os.environ, "MOCK": "1"},
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"hung (over {TIMEOUT_S}s)", time.perf_counter() - started
    took = time.perf_counter() - started
    if r.returncode == 0:
        return True, "", took
    lines = [line for line in (r.stdout + r.stderr).splitlines() if line.strip()]
    return False, lines[-1][:140] if lines else f"exit code {r.returncode}", took


def main() -> int:
    print(f"Checking {len(STEPS)} steps in demo mode (no API key, no cost)\n")
    failures = []
    for label, args in STEPS:
        print(f"  {label:<52}", end="", flush=True)
        ok, reason, took = run(args)
        print(f"{'OK   ' if ok else 'FAIL '} {took:5.1f}s")
        if not ok:
            print(f"      -> {reason}")
            failures.append(label)
    print()
    if failures:
        print(f"{len(failures)} of {len(STEPS)} failed: {', '.join(failures)}")
        return 1
    print("All green. Bella is ready: python -m bella_mcp  (or: python -m bella_mcp http)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
